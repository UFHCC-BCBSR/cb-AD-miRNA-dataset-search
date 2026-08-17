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

form.addEventListener('submit', e => {
    e.preventDefault();
    logEl.textContent = `BASE URL: ${BASE}\n`;
    downloadDiv.classList.add('hidden');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Running…';

    const data = {
        srcLit: document.getElementById('srcLit').checked,
        srcSra: document.getElementById('srcSra').checked,
        tissueSyn: document.getElementById('tissueSyn').value,
        libFilter: document.querySelector('input[name="libFilter"]:checked').value,
        caseCtrl: document.getElementById('caseCtrl').value,
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
        const streamUrl = BASE + 'stream/' + res.run_id;
        logEl.textContent += `stream URL: ${streamUrl}\n`;

        const eventSource = new EventSource(streamUrl);

        eventSource.onmessage = ev => {
            if (ev.data === '__DONE__') {
                eventSource.close();
                downloadLink.href = BASE + 'download/' + res.run_id;
                downloadDiv.classList.remove('hidden');
                submitBtn.disabled = false;
                submitBtn.textContent = 'Run Search';
            } else {
                logEl.textContent += ev.data + '\n';
                logEl.scrollTop = logEl.scrollHeight;
            }
        };

        eventSource.onerror = () => {
            const state = eventSource.readyState;
            const stateLabel = state === 0 ? 'CONNECTING' : state === 1 ? 'OPEN' : 'CLOSED';
            logEl.textContent += `\n[ERROR] EventSource error — readyState: ${state} (${stateLabel}), url: ${eventSource.url}\n`;
            eventSource.close();
            if (state === 2) {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Run Search';
            }
        };
    })
    .catch(err => {
        logEl.textContent += `\n[ERROR] ${err.message}\n`;
        submitBtn.disabled = false;
        submitBtn.textContent = 'Run Search';
    });
});
