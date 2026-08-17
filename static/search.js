const form = document.getElementById('searchForm');
const logEl = document.getElementById('log');
const downloadDiv = document.getElementById('downloadArea');
const downloadLink = document.getElementById('downloadLink');
const maxParallel = document.getElementById('maxParallel');
const parallelVal = document.getElementById('parallelVal');
const submitBtn = form.querySelector('button[type="submit"]');

const cfgEl = document.getElementById('appConfig');
let cfgBase = '';
try { cfgBase = (JSON.parse(cfgEl.textContent).scriptRoot || ''); } catch (e) {}
const BASE = cfgBase
    ? new URL(cfgBase.replace(/\/?$/, '/'), window.location.origin).href
    : new URL('.', window.location.href).href;

maxParallel.addEventListener('input', () => {
    parallelVal.textContent = maxParallel.value;
});

function poll(runId) {
    fetch(BASE + 'poll/' + runId)
    .then(r => {
        if (!r.ok) {
            throw new Error(`Poll failed (${r.status}): ${r.statusText}`);
        }
        return r.json();
    })
    .then(res => {
        for (const line of res.lines) {
            if (line === '__DONE__') {
                downloadLink.href = BASE + 'download/' + runId;
                downloadDiv.classList.remove('hidden');
                submitBtn.disabled = false;
                submitBtn.textContent = 'Run Search';
                return;
            }
            logEl.textContent += line + '\n';
            logEl.scrollTop = logEl.scrollHeight;
        }
        if (!res.done) {
            setTimeout(() => poll(runId), 1000);
        }
    })
    .catch(err => {
        logEl.textContent += `\n[ERROR] ${err.message}\n`;
        submitBtn.disabled = false;
        submitBtn.textContent = 'Run Search';
    });
}

form.addEventListener('submit', e => {
    e.preventDefault();
    logEl.textContent = `BASE URL: ${BASE}\n`;
    downloadDiv.classList.add('hidden');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Running…';

    const data = {
        srcLit: document.getElementById('srcLit').checked,
        srcSra: document.getElementById('srcSra').checked,
        humanOnly: document.getElementById('humanOnly').checked,
        tissueSyn: document.getElementById('tissueSyn').value,
        libFilter: document.querySelector('input[name="libFilter"]:checked').value,
        condition: document.getElementById('condition').value,
        minTotal: document.getElementById('minTotal').value,
        minCases: document.getElementById('minCases').value,
        minControls: document.getElementById('minControls').value,
        maxParallel: maxParallel.value
    };

    fetch(BASE + 'run', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
    })
    .then(r => {
        if (!r.ok) {
            return r.text().then(body => {
                throw new Error(`POST run failed (${r.status}): ${body.slice(0, 500)}`);
            });
        }
        return r.json();
    })
    .then(res => {
        logEl.textContent += `run_id: ${res.run_id}\n`;
        logEl.textContent += `poll URL: ${BASE}poll/${res.run_id}\n`;
        poll(res.run_id);
    })
    .catch(err => {
        logEl.textContent += `\n[ERROR] ${err.message}\n`;
        submitBtn.disabled = false;
        submitBtn.textContent = 'Run Search';
    });
});
