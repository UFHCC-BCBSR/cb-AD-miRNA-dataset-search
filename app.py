#!/usr/bin/env python3
'''Flask app that runs the AD vs control RNA‑seq candidate pipeline with user‑adjustable parameters.
Features:
* UI (templates/index.html) lets the user set tissue synonyms, library‑prep filter, case/control regex, sample‑size thresholds, and which data sources to use.
* When the user clicks Run, a background thread runs the three pipeline scripts (literature_first_search.py, ad_pfc_dataset_search.py, fetch_geo_metadata.py) inside a temporary folder.
* Output is streamed back via Server‑Sent Events (SSE).
* When finished, a download link for verified_candidates_full.csv appears.
''' 

import os, uuid, shutil, threading, queue, subprocess, shlex, zipfile, io
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
    sources = []
    if params.get('srcLit'):
        sources.append('Literature to GEO')
        lit_cmd = [
            'python', 'literature_first_search.py',
            f"--condition={params['condition']}",
            f"--tissue-synonyms={params['tissueSyn']}",
        ]
        if params.get('humanOnly'):
            lit_cmd.append('--human-only')
        else:
            lit_cmd.append('--no-human-filter')
        commands.append(lit_cmd)
    if params.get('srcSra'):
        sources.append('SRA search')
        sra_cmd = [
            'python', 'ad_pfc_dataset_search.py',
            f"--condition={params['condition']}",
            f"--tissue-synonyms={params['tissueSyn']}",
            f"--min-total={params['minTotal']}"
        ]
        if params.get('includeNoMetadata'):
            sra_cmd.append('--include-no-metadata')
        for strat in params.get('libStrategy', []):
            sra_cmd.append(f"--lib-strategy={strat}")
        for sel in params.get('libSelection', []):
            sra_cmd.append(f"--lib-selection={sel}")
        commands.append(sra_cmd)
    if params.get('srcLit'):
        sources.append('Literature to GEO')
        commands.append([
            'python', 'fetch_geo_metadata.py',
            f"--min-total={params['minTotal']}",
            f"--tissue-synonyms={params['tissueSyn']}",
            f"--max-parallel={params['maxParallel']}"
        ])
    q.put(f"[INFO] Sources: {' + '.join(sources) if sources else 'none'}")
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
                    q.put(f"[ERROR] Command {shlex.join(cmd)} exited with code {proc.returncode}")
                    break
            csvs = [f for f in os.listdir(temp_dir) if f.endswith('.csv')]
            if not csvs:
                q.put("[INFO] No downloadable CSV produced for this run.")
            q.put('__DONE__')
        except Exception as e:
            q.put(f"[EXCEPTION] {e}")
            q.put('__DONE__')
    threading.Thread(target=worker, daemon=True).start()
    RUNS[run_id] = {'queue': q, 'temp_dir': temp_dir}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/resolve_tissue')
def resolve_tissue():
    from tissue_ontology import resolve_tissue as _resolve
    q = request.args.get('q', '')
    result = _resolve(q)
    if result is None:
        return jsonify({'error': 'OLS unreachable', 'fallback': [q.strip().lower()]})
    return jsonify(result)

@app.route('/preview_patterns')
def preview_patterns():
    condition = request.args.get('condition', '')
    tissue = request.args.get('tissue', '')
    tissue_terms = [s.strip() for s in tissue.split(',') if s.strip()]
    try:
        import sys as _sys
        _sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
        from ad_pfc_dataset_search import (
            condition_to_sra_queries, condition_to_case_patterns)
        from literature_first_search import condition_to_pubmed_query
        return jsonify({
            'sra_queries': condition_to_sra_queries(condition),
            'case_patterns': condition_to_case_patterns(condition),
            'pubmed_query': condition_to_pubmed_query(condition, tissue_terms),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/run', methods=['POST'])
def run():
    data = request.get_json()
    tissue_terms = data.get('tissueTerms', [])
    params = {
        'srcLit': bool(data.get('srcLit', True)),
        'srcSra': bool(data.get('srcSra', True)),
        'tissueSyn': ','.join(tissue_terms) if tissue_terms else '',
        'libStrategy': data.get('libStrategy', []),
        'libSelection': data.get('libSelection', []),
        'condition': data.get('condition', ''),
        'minTotal': int(data.get('minTotal', 30)),
        'maxParallel': int(data.get('maxParallel', 2)),
        'humanOnly': bool(data.get('humanOnly', True)),
        'includeNoMetadata': bool(data.get('includeNoMetadata', True)),
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
    csvs = sorted(f for f in os.listdir(directory) if f.endswith('.csv'))
    if not csvs:
        return 'No output files produced for this run.', 404
    if len(csvs) == 1:
        return send_from_directory(directory, csvs[0], as_attachment=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in csvs:
            zf.write(os.path.join(directory, f), f)
    buf.seek(0)
    from flask import send_file
    return send_file(buf, mimetype='application/zip',
                     as_attachment=True, download_name='search_results.zip')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3838, debug=False)
