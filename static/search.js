const form = document.getElementById('searchForm');
const logEl = document.getElementById('log');
const downloadDiv = document.getElementById('downloadArea');
const downloadLink = document.getElementById('downloadLink');
form.addEventListener('submit', e => {
    e.preventDefault();
    logEl.textContent = '';
    downloadDiv.style.display = 'none';
    const data = {
        srcLit: document.getElementById('srcLit').checked,
        srcSra: document.getElementById('srcSra').checked,
        tissueSyn: document.getElementById('tissueSyn').value,
        libFilter: document.querySelector('input[name="libFilter"]:checked').value,
        caseCtrl: document.getElementById('caseCtrl').value,
        minTotal: document.getElementById('minTotal').value,
        minCases: document.getElementById('minCases').value,
        minControls: document.getElementById('minControls').value,
        maxParallel: document.getElementById('maxParallel').value
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
                downloadLink.href = `/download/${res.run_id}`;
                downloadDiv.style.display = 'block';
            } else {
                logEl.textContent += ev.data + '\n';
                logEl.scrollTop = logEl.scrollHeight;
            }
        };
    });
});
