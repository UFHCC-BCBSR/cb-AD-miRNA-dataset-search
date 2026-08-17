const form = document.getElementById('searchForm');
const logEl = document.getElementById('log');
const downloadDiv = document.getElementById('downloadArea');
const downloadLink = document.getElementById('downloadLink');
const submitBtn = form.querySelector('button[type="submit"]');

const cfgEl = document.getElementById('appConfig');
let cfgBase = '';
try { cfgBase = (JSON.parse(cfgEl.textContent).scriptRoot || ''); } catch (e) {}
const BASE = cfgBase
    ? new URL(cfgBase.replace(/\/?$/, '/'), window.location.origin).href
    : new URL('.', window.location.href).href;

/* ---- Pattern preview (Task 4) ---- */
const conditionEl = document.getElementById('condition');
const tissueEl = document.getElementById('tissueSyn');
const previewEl = document.getElementById('patternPreview');
let previewTimer = null;

function refreshPreview() {
    const cond = conditionEl.value.trim();
    if (!cond) { previewEl.style.display = 'none'; return; }
    const tissue = tissueEl.value;
    clearTimeout(previewTimer);
    previewTimer = setTimeout(() => {
        fetch(BASE + 'preview_patterns?condition=' + encodeURIComponent(cond)
              + '&tissue=' + encodeURIComponent(tissue))
        .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(data => {
            document.getElementById('prevSra').textContent = data.sra_queries.join(' | ');
            document.getElementById('prevCase').textContent = data.case_patterns.join(' | ');
            document.getElementById('prevPubMed').textContent = data.pubmed_query;
            previewEl.style.display = '';
        })
        .catch(() => { previewEl.style.display = 'none'; });
    }, 300);
}

conditionEl.addEventListener('blur', refreshPreview);
conditionEl.addEventListener('change', refreshPreview);
tissueEl.addEventListener('blur', refreshPreview);
tissueEl.addEventListener('change', refreshPreview);

/* ---- Metrics parsing (Task 5) ---- */
function parseMetrics(line) {
    const panel = document.getElementById('summaryMetrics');
    if (!panel) return;

    // SRA: runs_deduped=N | after_human_rnaseq=N | after_tissue=N | final_datasets=N
    const sraMatch = line.match(
        /SRA:\s*runs_deduped=(\d+)\s*\|\s*after_human_rnaseq=(\d+)\s*\|\s*after_tissue=(\d+)\s*\|\s*final_datasets=(\d+)/
    );
    if (sraMatch) {
        panel.innerHTML += '<div class="col-md-3 py-2">'
            + '<div class="metric-val">' + sraMatch[1] + '</div>'
            + '<div class="metric-label">Runs found</div></div>'
            + '<div class="col-md-3 py-2">'
            + '<div class="metric-val">' + sraMatch[2] + '</div>'
            + '<div class="metric-label">After organism/strategy/selection</div></div>'
            + '<div class="col-md-3 py-2">'
            + '<div class="metric-val">' + sraMatch[3] + '</div>'
            + '<div class="metric-label">After tissue match</div></div>'
            + '<div class="col-md-3 py-2">'
            + '<div class="metric-val">' + sraMatch[4] + '</div>'
            + '<div class="metric-label">Final studies</div></div>';
        document.getElementById('summaryPanel').style.display = '';
    }

    // SRA tissue blank fields
    const tissueBlank = line.match(/tissue_blank_fields=(\d+)\s*\|\s*tissue_from_metadata=(\d+)/);
    if (tissueBlank) {
        panel.innerHTML += '<div class="col-md-6 py-2">'
            + '<div class="metric-val">' + tissueBlank[1] + '</div>'
            + '<div class="metric-label">Runs with blank tissue metadata</div></div>'
            + '<div class="col-md-6 py-2">'
            + '<div class="metric-val">' + tissueBlank[2] + '</div>'
            + '<div class="metric-label">Runs with tissue from BioSample</div></div>';
    }

    // PubMed: papers_found=N | promising=N | ... | total_resolved=N/N (X%)
    const pubMatch = line.match(
        /PubMed:\s*papers_found=(\d+)\s*\|\s*promising=(\d+)\s*\|\s*elink_resolved=(\d+)\s*\|\s*fallback_resolved=(\d+)\s*\|\s*total_resolved=(\S+)/
    );
    if (pubMatch) {
        panel.innerHTML += '<div class="col-md-2 py-2">'
            + '<div class="metric-val">' + pubMatch[1] + '</div>'
            + '<div class="metric-label">Papers found</div></div>'
            + '<div class="col-md-2 py-2">'
            + '<div class="metric-val">' + pubMatch[2] + '</div>'
            + '<div class="metric-label">Promising</div></div>'
            + '<div class="col-md-2 py-2">'
            + '<div class="metric-val">' + pubMatch[3] + '</div>'
            + '<div class="metric-label">Elink resolved</div></div>'
            + '<div class="col-md-2 py-2">'
            + '<div class="metric-val">' + pubMatch[4] + '</div>'
            + '<div class="metric-label">Fallback resolved</div></div>'
            + '<div class="col-md-4 py-2">'
            + '<div class="metric-val">' + pubMatch[5] + '</div>'
            + '<div class="metric-label">Total GEO resolved</div></div>';
        document.getElementById('summaryPanel').style.display = '';
    }
}

/* ---- Polling ---- */
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
            parseMetrics(line);
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

/* ---- Submit ---- */
form.addEventListener('submit', e => {
    e.preventDefault();
    logEl.textContent = `BASE URL: ${BASE}\n`;
    downloadDiv.classList.add('hidden');
    document.getElementById('summaryMetrics').innerHTML = '';
    document.getElementById('summaryPanel').style.display = 'none';
    submitBtn.disabled = true;
    submitBtn.textContent = 'Running\u2026';

    function checkedValues(name) {
        return [...document.querySelectorAll(`input[name="${name}"]:checked`)].map(el => el.value);
    }

    const data = {
        srcLit: document.getElementById('srcLit').checked,
        srcSra: document.getElementById('srcSra').checked,
        humanOnly: document.getElementById('humanOnly').checked,
        tissueSyn: tissueEl.value,
        libStrategy: checkedValues('libStrategy'),
        libSelection: checkedValues('libSelection'),
        condition: conditionEl.value,
        minTotal: document.getElementById('minTotal').value,
        maxParallel: 2
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
