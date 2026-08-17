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

/* ---- Tissue resolution (OLS4) ---- */
const tissueInput = document.getElementById('tissueInput');
const tissueChips = document.getElementById('tissueChips');
const tissueCount = document.getElementById('tissueCount');
const tissueError = document.getElementById('tissueError');
const tissueAdd = document.getElementById('tissueAdd');
const tissueAddInput = document.getElementById('tissueAddInput');
const tissueAddBtn = document.getElementById('tissueAddBtn');
let tissueTerms = [];  // source of truth — displayed chips
let tissueResolving = false;

function renderChips() {
    tissueChips.innerHTML = '';
    tissueTerms.forEach((term, i) => {
        const badge = document.createElement('span');
        badge.className = 'badge bg-secondary me-1 mb-1 tissue-chip';
        badge.textContent = term + ' ';
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn-close btn-close-sm';
        btn.setAttribute('aria-label', 'Remove');
        btn.style.fontSize = '0.6em';
        btn.addEventListener('click', () => {
            tissueTerms.splice(i, 1);
            renderChips();
        });
        badge.appendChild(btn);
        tissueChips.appendChild(badge);
    });
    if (tissueTerms.length > 0) {
        tissueCount.textContent = tissueTerms.length + ' terms';
        tissueCount.style.display = '';
        tissueAdd.style.display = '';
    } else {
        tissueCount.style.display = 'none';
        tissueAdd.style.display = 'none';
    }
}

function resolveTissue(query) {
    if (!query.trim()) {
        tissueTerms = [];
        renderChips();
        tissueError.style.display = 'none';
        return;
    }
    tissueResolving = true;
    tissueError.style.display = 'none';
    tissueCount.textContent = 'Resolving\u2026';
    tissueCount.style.display = '';
    fetch(BASE + 'resolve_tissue?q=' + encodeURIComponent(query))
    .then(r => r.json())
    .then(data => {
        if (data.error) {
            tissueTerms = data.fallback || [query.trim().toLowerCase()];
            tissueError.textContent = 'Could not reach ontology service. Using raw input as fallback.';
            tissueError.style.display = '';
        } else if (!data.terms || data.terms.length === 0) {
            tissueTerms = [query.trim().toLowerCase()];
            tissueError.textContent = 'No terms found. Using raw input.';
            tissueError.style.display = '';
        } else {
            tissueTerms = data.terms;
        }
        renderChips();
        tissueResolving = false;
    })
    .catch(() => {
        tissueTerms = [query.trim().toLowerCase()];
        tissueError.textContent = 'Could not reach ontology service. Using raw input as fallback.';
        tissueError.style.display = '';
        renderChips();
        tissueResolving = false;
    });
}

tissueInput.addEventListener('blur', () => resolveTissue(tissueInput.value));
tissueInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); resolveTissue(tissueInput.value); }
});

tissueAddBtn.addEventListener('click', addCustomTerm);
tissueAddInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); addCustomTerm(); }
});

function addCustomTerm() {
    const val = tissueAddInput.value.trim().toLowerCase();
    if (val && !tissueTerms.includes(val)) {
        tissueTerms.push(val);
        renderChips();
    }
    tissueAddInput.value = '';
}

/* ---- Pattern preview ---- */
const conditionEl = document.getElementById('condition');
const previewEl = document.getElementById('patternPreview');
let previewTimer = null;

function refreshPreview() {
    const cond = conditionEl.value.trim();
    if (!cond) { previewEl.style.display = 'none'; return; }
    const tissue = tissueTerms.length > 0 ? tissueTerms.join(',') : tissueInput.value;
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

/* ---- Metrics parsing ---- */
function parseMetrics(line) {
    const panel = document.getElementById('summaryMetrics');
    if (!panel) return;

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

    // Tissue metadata breakdown
    const tissueMeta = line.match(/no_metadata_runs=(\d+)\s*\|\s*matched_runs=(\d+)\s*\|\s*no_match_runs=(\d+)/);
    if (tissueMeta) {
        panel.innerHTML += '<div class="col-md-4 py-2">'
            + '<div class="metric-val">' + tissueMeta[1] + '</div>'
            + '<div class="metric-label">Runs with no tissue metadata</div></div>'
            + '<div class="col-md-4 py-2">'
            + '<div class="metric-val">' + tissueMeta[2] + '</div>'
            + '<div class="metric-label">Runs matched by tissue</div></div>'
            + '<div class="col-md-4 py-2">'
            + '<div class="metric-val">' + tissueMeta[3] + '</div>'
            + '<div class="metric-label">Runs with no tissue match</div></div>';
    }

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
    if (tissueResolving) {
        tissueError.textContent = 'Please wait for tissue resolution to finish.';
        tissueError.style.display = '';
        return;
    }
    if (tissueTerms.length === 0) {
        tissueError.textContent = 'No tissue terms to match against. Enter a tissue name first.';
        tissueError.style.display = '';
        return;
    }
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
        tissueTerms: tissueTerms,
        libStrategy: checkedValues('libStrategy'),
        libSelection: checkedValues('libSelection'),
        condition: conditionEl.value,
        minTotal: document.getElementById('minTotal').value,
        maxParallel: 2,
        includeNoMetadata: document.getElementById('includeNoMetadata').checked
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

/* ---- Initial resolution on page load ---- */
resolveTissue(tissueInput.value);
