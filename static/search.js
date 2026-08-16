const form = document.getElementById('searchForm');
const logEl = document.getElementById('log');
const downloadDiv = document.getElementById('downloadArea');
const downloadLink = document.getElementById('downloadLink');
const maxParallel = document.getElementById('maxParallel');
const parallelVal = document.getElementById('parallelVal');

maxParallel.addEventListener('input', () => {
    parallelVal.textContent = maxParallel.value;
});

form.addEventListener('submit', e => {
    e.preventDefault();
    logEl.textContent = '';
    downloadDiv.classList.add('hidden');
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
    fetch('run', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
    })
    .then(r => r.json())
    .then(res => {
        const eventSource = new EventSource(`stream/${res.run_id}`);
        eventSource.onmessage = ev => {
            if (ev.data === '__DONE__') {
                eventSource.close();
                downloadLink.href = `download/${res.run_id}`;
                downloadDiv.classList.remove('hidden');
            } else {
                logEl.textContent += ev.data + '\n';
                logEl.scrollTop = logEl.scrollHeight;
            }
        };
    });
});
