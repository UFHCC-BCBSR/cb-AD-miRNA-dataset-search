#!/usr/bin/env python3
'''Flask app that runs the AD vs control RNA‑seq candidate pipeline with user‑adjustable parameters.
Features:
* UI (templates/index.html) lets the user set tissue synonyms, library‑prep filter, case/control regex, sample‑size thresholds, and which data sources to use.
* When the user clicks Run, a background thread runs the three pipeline scripts (literature_first_search.py, ad_pfc_dataset_search.py, fetch_geo_metadata.py) inside a temporary folder.
* Output is streamed back via Server‑Sent Events (SSE).
* When finished, a download link for verified_candidates_full.csv appears.
''' 

import os, uuid, shutil, threading, queue, subprocess
from flask import Flask, request, jsonify, send_from_directory, Response, render_template

app = Flask(__name__)
RUNS = {}

def start_pipeline(run_id, params):
    q = queue.Queue()
    temp_dir = os.path.join('/tmp', f'ad_search_{run_id}')
    os.makedirs(temp_dir, exist_ok=True)
    # copy repo files into temp_dir
    repo_root = os.path.abspath(os.path.dirname(__file__))
    for item in os.listdir(repo_root):
        if item.startswith('.'):
            continue
        src = os.path.join(repo_root, item)
        dst = os.path.join(temp_dir, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
    commands = []
    if params.get('srcLit'):
        commands.append([
            'python', 'literature_first_search.py',
            f"--tissue-synonyms={params['tissueSyn']}",
            f"--case-control-regex={params['caseCtrl']}",
            f"--library-filter-mode={params['libFilter']}"
        ])
    if params.get('srcSra'):
        commands.append([
            'python', 'ad_pfc_dataset_search.py',
            f"--tissue-synonyms={params['tissueSyn']}",
            f"--case-control-regex={params['caseCtrl']}",
            f"--library-filter-mode={params['libFilter']}"
        ])
    commands.append([
        'python', 'fetch_geo_metadata.py',
        f"--min-total={params['minTotal']}",
        f"--min-cases={params['minCases']}",
        f"--min-controls={params['minControls']}",
        f"--library-filter-mode={params['libFilter']}",
        f"--max-parallel={params['maxParallel']}"
    ])
    def worker():
        try:
            for cmd in commands:
                proc = subprocess.Popen(
                    cmd, cwd=temp_dir, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, env=os.environ
                )
                for line in proc.stdout:
                    q.put(line.rstrip())
                proc.wait()
                if proc.returncode != 0:
                    q.put(f"[ERROR] Command {' '.join(cmd)} exited with code {proc.returncode}")
                    break
            q.put('__DONE__')
        except Exception as e:
            q.put(f"[EXCEPTION] {e}")
            q.put('__DONE__')
    threading.Thread(target=worker, daemon=True).start()
    RUNS[run_id] = {'queue': q, 'temp_dir': temp_dir}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/run', methods=['POST'])
def run():
    data = request.get_json()
    params = {
        'srcLit': bool(data.get('srcLit', True)),
        'srcSra': bool(data.get('srcSra', True)),
        'tissueSyn': data.get('tissueSyn', ''),
        'libFilter': data.get('libFilter', 'no-polyA'),
        'caseCtrl': data.get('caseCtrl', ''),
        'minTotal': int(data.get('minTotal', 30)),
        'minCases': int(data.get('minCases', 30)),
        'minControls': int(data.get('minControls', 30)),
        'maxParallel': int(data.get('maxParallel', 2)),
    }
    run_id = str(uuid.uuid4())
    start_pipeline(run_id, params)
    return jsonify({'run_id': run_id})

@app.route('/stream/<run_id>')
def stream(run_id):
    if run_id not in RUNS:
        return 'Invalid run id', 404
    q = RUNS[run_id]['queue']
    def generate():
        while True:
            line = q.get()
            yield f'data: {line}\n\n'
            if line == '__DONE__':
                break
    return Response(generate(), mimetype='text/event-stream')

@app.route('/poll/<run_id>')
def poll(run_id):
    if run_id not in RUNS:
        return jsonify({'error': 'Invalid run id'}), 404
    q = RUNS[run_id]['queue']
    lines = []
    while not q.empty():
        try:
            line = q.get_nowait()
            lines.append(line)
            if line == '__DONE__':
                break
        except queue.Empty:
            break
    return jsonify({'lines': lines, 'done': lines[-1] == '__DONE__' if lines else False})

@app.route('/download/<run_id>')
def download(run_id):
    info = RUNS.get(run_id)
    if not info:
        return 'Invalid run id', 404
    directory = info['temp_dir']
    filename = 'verified_candidates_full.csv'
    if not os.path.exists(os.path.join(directory, filename)):
        return 'Result not available', 404
    return send_from_directory(directory, filename, as_attachment=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3838, debug=False)
