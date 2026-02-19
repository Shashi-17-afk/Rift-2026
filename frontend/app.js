/**
 * PharmaGuard — Frontend Application Logic
 * Communicates with the FastAPI backend
 */

// Resolve API base dynamically (priority):
// 1) ?api=https://... in URL query param (overrides everything; also saved to localStorage)
// 2) <meta name="pg-api-base" content="..."> in index.html
// 3) localhost / 127.0.0.1  →  http://localhost:8000  (local dev)
// 4) file:// protocol       →  http://localhost:8000  (opened directly from disk)
// 5) PRODUCTION_API_BASE    →  hardcoded Render URL   (deployed on Vercel or any CDN)
// 6) localStorage.PG_API_BASE
// 7) Relative '' (Docker / Nginx reverse-proxy)

// ── The deployed Render backend URL ──────────────────────────────────────────
const PRODUCTION_API_BASE = 'https://pharmaguard-api-5zx9.onrender.com';

(function setupApiBase() {
  const params = new URLSearchParams(window.location.search);
  const apiFromQuery = params.get('api');
  if (apiFromQuery) {
    try { localStorage.setItem('PG_API_BASE', apiFromQuery); } catch { }
  }
})();

function inferApiBase() {
  // 1. Explicit override via ?api= query param
  const fromQuery = new URLSearchParams(window.location.search).get('api');
  if (fromQuery && fromQuery.trim()) {
    return fromQuery.trim().replace(/\/$/, '');
  }

  // 2. Meta tag (useful for whitelabel / self-hosted deployments)
  const meta = document.querySelector('meta[name="pg-api-base"]');
  const fromMeta = meta && meta.content && meta.content.trim();
  if (fromMeta) return fromMeta.replace(/\/$/, '');

  // 3. Local dev (file:// or localhost)
  if (window.location.protocol === 'file:') {
    return 'http://localhost:8000';
  }
  const host = window.location.hostname;
  if (host === 'localhost' || host === '127.0.0.1') {
    return 'http://localhost:8000';
  }

  // 4. Any production/CDN deployment → use the known Render backend directly
  if (window.location.hostname !== '') {
    return PRODUCTION_API_BASE;
  }

  // 5. localStorage override
  try {
    const fromStorage = localStorage.getItem('PG_API_BASE');
    if (fromStorage && fromStorage.trim()) return fromStorage.trim().replace(/\/$/, '');
  } catch { }

  // 6. Docker/Nginx reverse-proxy (same origin)
  return '';
}

const API_BASE = inferApiBase();

/* ── DOM refs ─────────────────────────────────────────────────── */
const form = document.getElementById('analyze-form');
const patientInput = document.getElementById('patient-id');
const drugSelect = document.getElementById('drug-select');
const fileInput = document.getElementById('vcf-file');
const dropZone = document.getElementById('drop-zone');
const fileChosen = document.getElementById('file-chosen');
const submitBtn = document.getElementById('submit-btn');
const btnText = submitBtn.querySelector('.btn-text');
const btnIcon = submitBtn.querySelector('.btn-icon');
const btnSpinner = submitBtn.querySelector('.btn-spinner');
const formError = document.getElementById('form-error');
const loadDemoBtn = document.getElementById('load-demo-btn');

const emptyState = document.getElementById('empty-state');
const loadingState = document.getElementById('loading-state');
const resultCards = document.getElementById('result-cards');

const statusBadge = document.getElementById('api-status-badge');
const statusLabel = statusBadge.querySelector('.status-label');

/* ── Loading steps ────────────────────────────────────────────── */
const lsSteps = {
  parse: document.getElementById('ls-parse'),
  extract: document.getElementById('ls-extract'),
  risk: document.getElementById('ls-risk'),
  explain: document.getElementById('ls-explain'),
};

/* ══════════════════════════════════════════════════════════════
   API STATUS CHECK
══════════════════════════════════════════════════════════════ */
async function checkApiStatus() {
  try {
    const res = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(5000) });
    if (res.ok) {
      setStatusOnline();
    } else {
      setStatusOffline();
    }
  } catch {
    setStatusOffline();
  }
}

function setStatusOnline() {
  statusBadge.className = 'status-badge status-online';
  statusLabel.textContent = 'API Online';
}

function setStatusOffline() {
  statusBadge.className = 'status-badge status-offline';
  statusLabel.textContent = 'API Offline';
}

/* ══════════════════════════════════════════════════════════════
   FILE DROP ZONE
══════════════════════════════════════════════════════════════ */
dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); }
});

['dragenter', 'dragover'].forEach(evt =>
  dropZone.addEventListener(evt, (e) => { e.preventDefault(); dropZone.classList.add('drag-over'); })
);
['dragleave', 'drop'].forEach(evt =>
  dropZone.addEventListener(evt, (e) => { e.preventDefault(); dropZone.classList.remove('drag-over'); })
);
dropZone.addEventListener('drop', (e) => {
  const file = e.dataTransfer?.files?.[0];
  if (file) setFile(file);
});
fileInput.addEventListener('change', () => {
  if (fileInput.files?.[0]) setFile(fileInput.files[0]);
});

function setFile(file) {
  // Transfer to the real input via DataTransfer
  const dt = new DataTransfer();
  dt.items.add(file);
  fileInput.files = dt.files;

  dropZone.classList.add('has-file');
  fileChosen.textContent = file.name;
  fileChosen.classList.remove('hidden');
}

/* ══════════════════════════════════════════════════════════════
   FORM VALIDATION
══════════════════════════════════════════════════════════════ */
function validateForm() {
  let ok = true;
  hideError();

  if (!patientInput.value.trim()) {
    patientInput.classList.add('invalid');
    showError('Patient ID is required.');
    ok = false;
  } else {
    patientInput.classList.remove('invalid');
  }

  if (!drugSelect.value) {
    showError('Please select a drug.');
    ok = false;
  }

  if (!fileInput.files?.length) {
    showError('Please upload a VCF file.');
    ok = false;
  }

  return ok;
}

function showError(msg) {
  formError.textContent = msg;
  formError.classList.remove('hidden');
}

function hideError() {
  formError.textContent = '';
  formError.classList.add('hidden');
}

/* ══════════════════════════════════════════════════════════════
   LOADING STATE HELPERS
══════════════════════════════════════════════════════════════ */
function showLoading() {
  emptyState.classList.add('hidden');
  resultCards.classList.add('hidden');
  loadingState.classList.remove('hidden');
  // Reset step states
  Object.values(lsSteps).forEach(el => { el.classList.remove('active', 'done'); });
  lsSteps.parse.classList.add('active');
}

function advanceStep(done, next) {
  if (done) lsSteps[done].classList.replace('active', 'done');
  if (next && lsSteps[next]) lsSteps[next].classList.add('active');
}

function showResults() {
  loadingState.classList.add('hidden');
  resultCards.classList.remove('hidden');
}

/* Submit button state */
function setSubmitting(on) {
  submitBtn.disabled = on;
  btnText.classList.toggle('hidden', on);
  btnIcon.classList.toggle('hidden', on);
  btnSpinner.classList.toggle('hidden', !on);
}

/* ══════════════════════════════════════════════════════════════
   RENDER RESULT
══════════════════════════════════════════════════════════════ */
// Module-level store so Copy/Download buttons can access latest data
let _lastResultData = null;

function riskClass(label) {
  const l = (label || '').toLowerCase();
  if (l === 'toxic' || l === 'ineffective') return 'high';
  if (l === 'adjust dosage') return 'medium';
  return 'low'; // 'safe' | 'unknown'
}

function riskEmoji(cls) {
  return cls === 'high' ? '⚠️' : cls === 'medium' ? '🟠' : '✅';
}

function formatLabel(label) {
  return (label || '').replace(/_/g, ' ');
}

function formatTimestamp(ts) {
  try {
    return new Date(ts).toLocaleString(undefined, {
      dateStyle: 'medium', timeStyle: 'short'
    });
  } catch { return ts; }
}

function renderVariants(variants) {
  if (!variants?.length) {
    return `<p class="no-variants">No pharmacogenomic variants detected by rsID lookup — coordinate-based defaults applied.</p>`;
  }
  return `<div class="variants-list">
    ${variants.map(v => `
      <div class="variant-item">
        <span class="variant-rsid">${v.rsid || '—'}</span>
        <span class="variant-pos">chr${v.chromosome}:${v.position.toLocaleString()}</span>
        <span class="variant-alleles">${v.ref} → ${v.alt}</span>
      </div>
    `).join('')}
  </div>`;
}

function renderResult(data) {
  const pgx = data.pharmacogenomic_profile;
  const risk = data.risk_assessment;
  const rec = data.clinical_recommendation;
  const llm = data.llm_generated_explanation;
  const qm = data.quality_metrics;

  const rc = riskClass(risk.risk_label);
  const pct = Math.round((risk.confidence_score || 0) * 100);
  // Build friendly phenotype display: "PM — Poor Metabolizer"
  const phenoFull = rec.phenotype_full || '';
  const phenoDisplay = phenoFull
    ? `${escHtml(pgx.phenotype)} — ${escHtml(phenoFull)}`
    : escHtml(pgx.phenotype);

  resultCards.innerHTML = `

    <!-- Patient header -->
    <div class="glass-card rc-header">
      <div class="rc-patient">
        <span class="rc-patient-id">👤 ${escHtml(data.patient_id)}</span>
        <span class="rc-timestamp">🕒 ${formatTimestamp(data.timestamp)}</span>
      </div>
      <span class="rc-drug-chip">💊 ${escHtml(data.drug)}</span>
    </div>

    <!-- Risk banner -->
    <div class="glass-card rc-risk-banner ${rc}">
      <div class="risk-icon-wrap">${riskEmoji(rc)}</div>
      <div class="risk-info">
        <div class="risk-label-text">${formatLabel(risk.risk_label)}</div>
        <div class="risk-meta">
          <span>🧬 ${escHtml(pgx.primary_gene)}</span>
          <span>⚗️ ${escHtml(pgx.diplotype)}</span>
          <span>📊 ${phenoDisplay}</span>
          <span>⚡ ${escHtml(risk.severity)} Severity</span>
        </div>
      </div>
      <div class="conf-bar-wrap">
        <div class="conf-label">Confidence</div>
        <div class="conf-bar"><div class="conf-fill" style="width:0%" data-pct="${pct}"></div></div>
        <div class="conf-pct">${pct}%</div>
      </div>
    </div>

    <!-- Info grid -->
    <div class="rc-grid">

      <!-- Pharmacogenomic Profile -->
      <div class="rc-card">
        <div class="rc-card-title">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/></svg>
          Genomic Profile
        </div>
        <div class="kv-row"><span class="kv-key">Primary Gene</span><span class="kv-val">${escHtml(pgx.primary_gene)}</span></div>
        <div class="kv-row"><span class="kv-key">Diplotype</span><span class="kv-val">${escHtml(pgx.diplotype)}</span></div>
        <div class="kv-row"><span class="kv-key">Phenotype</span><span class="kv-val">${phenoDisplay}</span></div>
        <div class="kv-row"><span class="kv-key">Variants Found</span><span class="kv-val">${pgx.detected_variants?.length ?? 0}</span></div>
      </div>

      <!-- Detected Variants -->
      <div class="rc-card">
        <div class="rc-card-title">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>
          Detected Variants
        </div>
        ${renderVariants(pgx.detected_variants)}
      </div>

      <!-- Dose Recommendation (full width) -->
      <div class="rc-card rc-full">
        <div class="rc-card-title">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 3H5a2 2 0 0 0-2 2v4m6-6h10a2 2 0 0 1 2 2v4M9 3v18m0 0h10a2 2 0 0 0 2-2v-4M9 21H5a2 2 0 0 1-2-2v-4m0 0h18"/></svg>
          Clinical Recommendation
        </div>
        <p class="dose-rec-text"><strong>Dose:</strong> ${escHtml(rec.dose_recommendation || 'See summary below.')}</p>
        ${rec.monitoring ? `<div class="monitoring-badge"> ${escHtml(rec.monitoring)}</div>` : ''}
      </div>

      <!-- AI Explanation (full width) -->
      <div class="rc-card rc-full">
        <div class="rc-card-title">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          AI Clinical Explanation
        </div>
        <p class="explanation-text">${escHtml(llm.summary)}</p>
      </div>

      <!-- Quality Metrics -->
      <div class="rc-card rc-full">
        <div class="rc-card-title">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
          Quality Metrics
        </div>
        <div class="quality-row">
          VCF Parsing:
          ${qm.vcf_parsing_success
      ? '<span class="quality-ok">✓ Success</span>'
      : '<span class="quality-fail">✗ Failed</span>'}
        </div>
      </div>

      <!-- Export Actions -->
      <div class="rc-card rc-full export-actions-card">
        <div class="rc-card-title">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          Export Results
        </div>
        <div class="export-btn-row">
          <button id="copy-json-btn" class="export-btn copy-btn">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
            Copy JSON
          </button>
          <button id="download-json-btn" class="export-btn download-btn">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            Download JSON
          </button>
        </div>
      </div>

    </div>
  `;

  // Store data for export
  _lastResultData = data;

  // Animate confidence bar after render
  requestAnimationFrame(() => {
    const fill = resultCards.querySelector('.conf-fill');
    if (fill) {
      setTimeout(() => { fill.style.width = fill.dataset.pct + '%'; }, 80);
    }

    // Wire up export buttons
    const copyBtn = document.getElementById('copy-json-btn');
    const dlBtn = document.getElementById('download-json-btn');

    if (copyBtn) {
      copyBtn.addEventListener('click', async () => {
        try {
          await navigator.clipboard.writeText(JSON.stringify(_lastResultData, null, 2));
          const orig = copyBtn.innerHTML;
          copyBtn.innerHTML = '✓ Copied!';
          copyBtn.classList.add('copied');
          setTimeout(() => { copyBtn.innerHTML = orig; copyBtn.classList.remove('copied'); }, 2000);
        } catch {
          alert('Copy failed — please use the Download button instead.');
        }
      });
    }

    if (dlBtn) {
      dlBtn.addEventListener('click', () => {
        const json = JSON.stringify(_lastResultData, null, 2);
        const blob = new Blob([json], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `pharmaguard-${_lastResultData.patient_id}-${_lastResultData.drug}.json`;
        a.click();
        URL.revokeObjectURL(url);
      });
    }
  });
}

/* ── XSS helper ─────────────────────────────────────────────── */
function escHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/* ══════════════════════════════════════════════════════════════
   FORM SUBMIT — REAL ANALYSIS
══════════════════════════════════════════════════════════════ */
form.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!validateForm()) return;

  setSubmitting(true);
  showLoading();

  const fd = new FormData();
  fd.append('patient_id', patientInput.value.trim());
  fd.append('drug', drugSelect.value);
  fd.append('file', fileInput.files[0]);

  try {
    // Simulate step transitions while fetch is in-flight
    const stepTimer1 = setTimeout(() => advanceStep('parse', 'extract'), 600);
    const stepTimer2 = setTimeout(() => advanceStep('extract', 'risk'), 1400);
    const stepTimer3 = setTimeout(() => advanceStep('risk', 'explain'), 2400);

    const res = await fetch(`${API_BASE}/api/analyze`, {
      method: 'POST',
      body: fd,
    });

    clearTimeout(stepTimer1);
    clearTimeout(stepTimer2);
    clearTimeout(stepTimer3);

    // Mark all steps done
    Object.keys(lsSteps).forEach(k => {
      lsSteps[k].classList.remove('active');
      lsSteps[k].classList.add('done');
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }

    const data = await res.json();

    setTimeout(() => {
      showResults();
      renderResult(data);
      setStatusOnline();
    }, 300);

  } catch (err) {
    loadingState.classList.add('hidden');
    emptyState.classList.remove('hidden');
    showError(err.message || 'Analysis failed. Is the backend running on port 8000?');
    setStatusOffline();
  } finally {
    setSubmitting(false);
  }
});

/* ══════════════════════════════════════════════════════════════
   DEMO MODE — load /api/test response
══════════════════════════════════════════════════════════════ */
loadDemoBtn.addEventListener('click', async () => {
  hideError();
  showLoading();
  loadDemoBtn.disabled = true;

  try {
    // Step animations
    const t1 = setTimeout(() => advanceStep('parse', 'extract'), 500);
    const t2 = setTimeout(() => advanceStep('extract', 'risk'), 1100);
    const t3 = setTimeout(() => advanceStep('risk', 'explain'), 1800);

    const res = await fetch(`${API_BASE}/api/test`);
    clearTimeout(t1); clearTimeout(t2); clearTimeout(t3);

    Object.keys(lsSteps).forEach(k => {
      lsSteps[k].classList.remove('active');
      lsSteps[k].classList.add('done');
    });

    if (!res.ok) throw new Error(`Demo endpoint returned ${res.status}`);
    const data = await res.json();

    setTimeout(() => {
      showResults();
      renderResult(data);
      setStatusOnline();
    }, 300);

  } catch (err) {
    loadingState.classList.add('hidden');
    emptyState.classList.remove('hidden');
    showError('Could not load demo — is the backend running on port 8000?');
    setStatusOffline();
  } finally {
    loadDemoBtn.disabled = false;
  }
});

/* ══════════════════════════════════════════════════════════════
   INIT
══════════════════════════════════════════════════════════════ */
checkApiStatus();
// Re-check every 30 seconds
setInterval(checkApiStatus, 30_000);

// Clear validation state on input
patientInput.addEventListener('input', () => {
  patientInput.classList.remove('invalid');
  hideError();
});
drugSelect.addEventListener('change', hideError);
