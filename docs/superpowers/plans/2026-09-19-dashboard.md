# Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Full ops console at `/dashboard` — overview cards, GLM credit gauges, latency/TTFT charts, per-model table with drilldown, live request feed.

**Architecture:** Zero-build static page (vanilla JS + Chart.js 4 CDN) following the existing `/playground` pattern. No backend changes — consumes existing `/v1/analytics/*` endpoints.

**Tech Stack:** FastAPI static serving, vanilla JS, Chart.js 4.4.x (CDN, pinned), localStorage auth.

**Spec:** Approved design in chat (2026-09-19, session `vps192`): Option C full ops console + Chart.js CDN.

## Global Constraints

- No backend API changes; dashboard only reads `/v1/analytics/summary|models|requests|credits`.
- Auth: Bearer `APP_API_KEY`; key input persisted in localStorage key `llm_dashboard_key` (playground does not persist keys — dashboard owns its own).
- Zero-build: no bundler, no npm. Chart.js via `<script src>` pinned to `4.4.1` from jsdelivr.
- Dark theme matching `static/playground/playground.css` variables.
- Time filters: 24h / 7d / 30d → `since` query param (ISO 8601).
- Auto-refresh: 15s interval, toggleable, default OFF.
- Kebab-case filenames; files stay focused (HTML shell / CSS / JS logic).

## Existing API response shapes (verified in `analytics/db.py`, `routes/analytics.py`)

- `GET /v1/analytics/summary?since=` → `{total_requests, total_prompt_tokens, total_completion_tokens, total_tokens, total_cost_usd, avg_latency_ms, avg_ttft_ms, error_rate, since}`
- `GET /v1/analytics/models?since=` → `{models: [{model, provider, request_count, prompt_tokens, completion_tokens, total_tokens, cost_usd, avg_latency_ms, avg_ttft_ms}]}`
- `GET /v1/analytics/requests?since=&limit=&offset=` → `{requests: [{id, provider, model, prompt_tokens, completion_tokens, total_tokens, latency_ms, ttft_ms, cost_usd, status, error_message, created_at}], total, limit, offset}` (max limit 200)
- `GET /v1/analytics/credits` → `{window_5h: {credits_used, quota}, window_7d_rolling: {credits_used, quota, note}, by_model, off_peak_share}`

---

### Task 1: `/dashboard` route + tests

**Files:**
- Modify: `main.py` (after the `/playground` route, ~line 136)
- Test: `tests/test_dashboard.py` (new)

**Interfaces:**
- Consumes: existing `FileResponse`, `app` in `main.py`
- Produces: `GET /dashboard` → 200 HTML; static assets under existing `/static` mount

- [ ] **Step 1: Write failing tests**

```python
"""Tests for dashboard route and static file serving."""

import pytest


@pytest.mark.asyncio
async def test_dashboard_route_returns_html(client):
    """GET /dashboard returns 200 with HTML content type."""
    res = await client.get("/dashboard")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "dashboard" in res.text.lower()


@pytest.mark.asyncio
async def test_dashboard_no_auth_required(client):
    """Dashboard route does NOT require Bearer auth (assets do; data endpoints do)."""
    res = await client.get("/dashboard")
    assert res.status_code == 200
```

- [ ] **Step 2: Run tests, verify failure**

Run: `cd /Users/ddphuong/Projects/next-labs/llm-gateway && .venv/bin/python -m pytest tests/test_dashboard.py -v`
Expected: FAIL (404, route missing)

- [ ] **Step 3: Add route in `main.py` after the `/playground` route**

```python
@app.get("/dashboard")
async def dashboard():
    return FileResponse("static/dashboard/index.html")
```

(Also create an empty placeholder `static/dashboard/index.html` containing only `<!doctype html><title>dashboard</title>` so FileResponse does not 500.)

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/python -m pytest tests/test_dashboard.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_dashboard.py static/dashboard/index.html
git commit -m "feat(dashboard): add /dashboard route"
```

---

### Task 2: HTML shell + CSS theme

**Files:**
- Create: `static/dashboard/index.html` (full shell)
- Create: `static/dashboard/dashboard.css`

**Interfaces:**
- Produces DOM ids used by Task 3-6 JS: `api-key-input`, `key-save-btn`, `key-clear-btn`, `time-filter` (select), `refresh-toggle` (checkbox), `refresh-now-btn`, `error-banner`, `cards` (container), `gauge-5h`, `gauge-7d`, `chart-latency`, `chart-models`, `model-table-body`, `drilldown`, `feed-body`, plus chart canvases inside `chart-latency` / `chart-models` wrappers.

- [ ] **Step 1: Write `index.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>LLM Gateway — Dashboard</title>
  <link rel="stylesheet" href="/static/dashboard/dashboard.css" />
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
</head>
<body>
  <header class="topbar">
    <h1>LLM Gateway <span class="muted">dashboard</span></h1>
    <div class="controls">
      <input type="password" id="api-key-input" placeholder="API Key" autocomplete="off" />
      <button id="key-save-btn" class="btn">Save</button>
      <button id="key-clear-btn" class="btn ghost">Clear</button>
      <select id="time-filter">
        <option value="24h">24h</option>
        <option value="7d">7d</option>
        <option value="30d">30d</option>
      </select>
      <label class="toggle"><input type="checkbox" id="refresh-toggle" /> auto 15s</label>
      <button id="refresh-now-btn" class="btn">Refresh</button>
    </div>
  </header>
  <div id="error-banner" class="banner hidden"></div>

  <main>
    <section id="cards" class="cards"></section>

    <section class="row">
      <div class="panel"><h2>GLM credits — 5h</h2><div id="gauge-5h" class="gauge"></div></div>
      <div class="panel"><h2>GLM credits — 7d rolling</h2><div id="gauge-7d" class="gauge"></div></div>
    </section>

    <section class="panel">
      <h2>Latency / TTFT</h2>
      <div id="chart-latency" class="chart"></div>
    </section>

    <section class="panel">
      <h2>Tokens by model</h2>
      <div id="chart-models" class="chart"></div>
    </section>

    <section class="panel">
      <h2>Models</h2>
      <table class="table">
        <thead><tr><th>Model</th><th>Provider</th><th>Reqs</th><th>Tokens</th><th>Cost $</th><th>Latency</th><th>TTFT</th></tr></thead>
        <tbody id="model-table-body"></tbody>
      </table>
    </section>

    <section id="drilldown" class="panel hidden">
      <h2 id="drilldown-title"></h2>
      <button id="drilldown-close" class="btn ghost">Close</button>
      <table class="table">
        <thead><tr><th>Time</th><th>Status</th><th>Tokens</th><th>Latency</th><th>TTFT</th><th>Error</th></tr></thead>
        <tbody id="drilldown-body"></tbody>
      </table>
    </section>

    <section class="panel">
      <h2>Live feed</h2>
      <table class="table">
        <thead><tr><th>Time</th><th>Model</th><th>Provider</th><th>Tokens</th><th>Latency</th><th>Status</th></tr></thead>
        <tbody id="feed-body"></tbody>
      </table>
    </section>
  </main>

  <script src="/static/dashboard/dashboard.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `dashboard.css`** — dark theme (reuse playground palette: bg `#0f1117`, panel `#161a23`, text `#e6e8ef`, accent `#7c8cff`, ok `#3dd68c`, err `#ff6b6b`, muted `#8b90a0`). Cards = CSS grid `repeat(auto-fit, minmax(150px, 1fr))`; `.chart` fixed height `260px`; `.gauge` canvas `180×180`; `.table` full-width with subtle row borders; `.banner` red background; `.hidden{display:none}`; `.new-row` flash animation for live feed; responsive single column under 720px.

- [ ] **Step 3: Verify route test still passes + page loads**

Run: `.venv/bin/python -m pytest tests/test_dashboard.py -v` → PASS
Manual: `.venv/bin/python -m uvicorn main:app --port 8001 &` then `curl -s localhost:8001/dashboard | grep -c chart.umd` → `1`; kill server.

- [ ] **Step 4: Commit**

```bash
git add static/dashboard/index.html static/dashboard/dashboard.css
git commit -m "feat(dashboard): html shell and dark theme css"
```

---

### Task 3: JS core — state, auth, API client, refresh loop

**Files:**
- Create: `static/dashboard/dashboard.js`

**Interfaces:**
- Produces (used by Tasks 4-6): `state` object `{key, since, timer}`, `api(path)` fetch wrapper returning parsed JSON (throws `{status,message}`), `showError(msg)` / `hideError()`, `REFRESH_MS = 15000`, `refreshAll()` orchestrator calling registered renderers array `renderers` (push pattern: `renderers.push(async () => {...})`).
- `sinceForFilter()` maps `24h|7d|30d` → ISO string via `new Date(Date.now() - {24h:864e5, 7d:6048e5, 30d:2592e6}[f]).toISOString()`.

- [ ] **Step 1: Write core JS**

```javascript
'use strict';

const REFRESH_MS = 15000;
const KEY_STORAGE = 'llm_dashboard_key';
const state = { key: null, since: null, timer: null, lastRequests: [] };
const renderers = []; // async fns, called by refreshAll()

const $ = (sel) => document.querySelector(sel);
const dom = {
  keyInput: $('#api-key-input'), saveKey: $('#key-save-btn'), clearKey: $('#key-clear-btn'),
  timeFilter: $('#time-filter'), refreshToggle: $('#refresh-toggle'), refreshNow: $('#refresh-now-btn'),
  error: $('#error-banner'),
};

function sinceForFilter(f) {
  const spans = { '24h': 864e5, '7d': 6048e5, '30d': 2592e6 };
  return new Date(Date.now() - spans[f]).toISOString();
}

async function api(path) {
  const res = await fetch(path, { headers: { Authorization: `Bearer ${state.key}` } });
  if (res.status === 401) throw { status: 401, message: 'Invalid or missing API key' };
  if (!res.ok) throw { status: res.status, message: `HTTP ${res.status}` };
  return res.json();
}

function showError(msg) { dom.error.textContent = msg; dom.error.classList.remove('hidden'); }
function hideError() { dom.error.classList.add('hidden'); }

async function refreshAll() {
  if (!state.key) { showError('Enter API key to load data'); return; }
  hideError();
  try {
    for (const fn of renderers) await fn();
  } catch (e) {
    showError(e.message || String(e));
  }
}

function startLoop() {
  if (state.timer) clearInterval(state.timer);
  if (dom.refreshToggle.checked) state.timer = setInterval(refreshAll, REFRESH_MS);
}

function initAuth() {
  state.key = localStorage.getItem(KEY_STORAGE) || null;
  if (state.key) dom.keyInput.value = state.key;
  dom.saveKey.addEventListener('click', () => {
    state.key = dom.keyInput.value.trim() || null;
    if (state.key) localStorage.setItem(KEY_STORAGE, state.key);
    else localStorage.removeItem(KEY_STORAGE);
    refreshAll();
  });
  dom.clearKey.addEventListener('click', () => {
    state.key = null; localStorage.removeItem(KEY_STORAGE); dom.keyInput.value = '';
  });
}

function initControls() {
  dom.timeFilter.addEventListener('change', () => { state.since = sinceForFilter(dom.timeFilter.value); refreshAll(); });
  dom.refreshToggle.addEventListener('change', startLoop);
  dom.refreshNow.addEventListener('click', refreshAll);
}

document.addEventListener('DOMContentLoaded', () => {
  initAuth();
  initControls();
  state.since = sinceForFilter(dom.timeFilter.value);
  refreshAll();
});
```

- [ ] **Step 2: Manual smoke** — start uvicorn on 8001, open `http://localhost:8001/dashboard`: no key → red banner "Enter API key". Console clean.

- [ ] **Step 3: Commit**

```bash
git add static/dashboard/dashboard.js
git commit -m "feat(dashboard): state, auth and api client core"
```

---

### Task 4: Summary cards + credit gauges

**Files:**
- Modify: `static/dashboard/dashboard.js` (append)

**Interfaces:**
- Consumes: `api()`, `state.since`, `renderers` from Task 3
- Produces: none (renders DOM); gauge helper `renderGauge(el, used, quota)` reused by both gauges

- [ ] **Step 1: Append cards + gauges code**

```javascript
// --- summary cards ---
const CARD_DEFS = [
  ['Requests', (s) => s.total_requests],
  ['Tokens', (s) => s.total_tokens?.toLocaleString()],
  ['Cost $', (s) => s.total_cost_usd?.toFixed(4)],
  ['Error rate', (s) => (s.error_rate * 100).toFixed(1) + '%'],
  ['Avg latency', (s) => Math.round(s.avg_latency_ms) + ' ms'],
  ['Avg TTFT', (s) => Math.round(s.avg_ttft_ms) + ' ms'],
];

renderers.push(async () => {
  const s = await api(`/v1/analytics/summary${state.since ? `?since=${encodeURIComponent(state.since)}` : ''}`);
  $('#cards').innerHTML = CARD_DEFS.map(([label, val]) =>
    `<div class="card"><div class="card-label">${label}</div><div class="card-value">${val(s)}</div></div>`).join('');
});

// --- credit gauges (Chart.js doughnut) ---
const gauges = {};

function renderGauge(elId, used, quota) {
  const remain = Math.max(quota - used, 0);
  const data = [used, remain];
  if (gauges[elId]) { gauges[elId].data.datasets[0].data = data; gauges[elId].update(); return; }
  const canvas = document.createElement('canvas');
  document.getElementById(elId).replaceChildren(canvas);
  gauges[elId] = new Chart(canvas, {
    type: 'doughnut',
    data: { labels: ['used', 'remaining'], datasets: [{ data, backgroundColor: ['#ff6b6b', '#2a2f3d'], borderWidth: 0 }] },
    options: { cutout: '72%', plugins: { legend: { display: false }, tooltip: { enabled: false } } },
    plugins: [{ id: 'centerText', afterDraw(c) {
      const { ctx, chartArea } = c; const x = (chartArea.left + chartArea.right) / 2, y = (chartArea.top + chartArea.bottom) / 2;
      const pct = quota ? Math.round((used / quota) * 100) : 0;
      ctx.save(); ctx.textAlign = 'center'; ctx.fillStyle = pct >= 90 ? '#ff6b6b' : '#e6e8ef';
      ctx.font = 'bold 22px sans-serif'; ctx.fillText(pct + '%', x, y);
      ctx.font = '11px sans-serif'; ctx.fillStyle = '#8b90a0';
      ctx.fillText(`${Math.round(used)} / ${quota}`, x, y + 18); ctx.restore();
    } }],
  });
}

renderers.push(async () => {
  const c = await api('/v1/analytics/credits');
  renderGauge('gauge-5h', c.window_5h.credits_used, c.window_5h.quota);
  renderGauge('gauge-7d', c.window_7d_rolling.credits_used, c.window_7d_rolling.quota);
});
```

- [ ] **Step 2: Manual verify** — with valid key: 6 cards show numbers, two doughnut gauges render with center %.

- [ ] **Step 3: Commit**

```bash
git add static/dashboard/dashboard.js
git commit -m "feat(dashboard): summary cards and credit gauges"
```

---

### Task 5: Charts, model table, drilldown

**Files:**
- Modify: `static/dashboard/dashboard.js` (append)

**Interfaces:**
- Consumes: `api()`, `state.since`, `state.lastRequests` (set by Task 6 — code must tolerate `[]`)
- Produces: line chart `latencyChart`, bar chart `modelsChart`; `bucketRequests(reqs)` helper reused by Task 6

- [ ] **Step 1: Append chart/table/drilldown code**

```javascript
// --- latency/ttft line chart ---
let latencyChart = null;

// bucket by hour (24h/7d) or day (30d)
function bucketRequests(reqs) {
  const dayBuckets = dom.timeFilter.value === '30d';
  const buckets = {};
  for (const r of reqs) {
    const d = new Date(r.created_at);
    const k = dayBuckets ? d.toISOString().slice(0, 10) : d.toISOString().slice(0, 13);
    (buckets[k] ??= { lat: [], ttft: [] }).lat.push(r.latency_ms || 0);
    buckets[k].ttft.push(r.ttft_ms || 0);
  }
  const keys = Object.keys(buckets).sort();
  const avg = (a) => a.length ? Math.round(a.reduce((x, y) => x + y, 0) / a.length) : 0;
  return { keys, latency: keys.map((k) => avg(buckets[k].lat)), ttft: keys.map((k) => avg(buckets[k].ttft)) };
}

function renderLatencyChart(reqs) {
  const { keys, latency, ttft } = bucketRequests(reqs);
  const el = document.createElement('canvas');
  $('#chart-latency').replaceChildren(el);
  if (latencyChart) latencyChart.destroy();
  latencyChart = new Chart(el, {
    type: 'line',
    data: { labels: keys, datasets: [
      { label: 'Latency ms', data: latency, borderColor: '#7c8cff', tension: 0.3, pointRadius: 2 },
      { label: 'TTFT ms', data: ttft, borderColor: '#3dd68c', tension: 0.3, pointRadius: 2 },
    ] },
    options: { maintainAspectRatio: false, scales: { y: { beginAtZero: true } } },
  });
}

// --- tokens by model bar + table + drilldown ---
let modelsChart = null;

function renderModels(models) {
  const top = models.slice(0, 10);
  const el = document.createElement('canvas');
  $('#chart-models').replaceChildren(el);
  if (modelsChart) modelsChart.destroy();
  modelsChart = new Chart(el, {
    type: 'bar',
    data: { labels: top.map((m) => m.model), datasets: [{ label: 'Tokens', data: top.map((m) => m.total_tokens), backgroundColor: '#7c8cff' }] },
    options: { maintainAspectRatio: false, scales: { y: { beginAtZero: true } } },
  });

  $('#model-table-body').innerHTML = models.map((m, i) =>
    `<tr class="clickable" data-i="${i}"><td>${m.model}</td><td>${m.provider}</td><td>${m.request_count}</td>
     <td>${m.total_tokens.toLocaleString()}</td><td>${m.cost_usd.toFixed(4)}</td>
     <td>${Math.round(m.avg_latency_ms)} ms</td><td>${Math.round(m.avg_ttft_ms)} ms</td></tr>`).join('');
}

function renderDrilldown(model) {
  const reqs = state.lastRequests.filter((r) => r.model === model);
  $('#drilldown-title').textContent = `${model} — ${reqs.length} recent requests`;
  $('#drilldown-body').innerHTML = reqs.map((r) =>
    `<tr><td>${new Date(r.created_at).toLocaleString()}</td><td class="${r.status === 'error' ? 'err' : 'ok'}">${r.status}</td>
     <td>${r.total_tokens.toLocaleString()}</td><td>${Math.round(r.latency_ms)} ms</td><td>${Math.round(r.ttft_ms)} ms</td>
     <td class="err">${r.error_message || ''}</td></tr>`).join('');
  $('#drilldown').classList.remove('hidden');
}

renderers.push(async () => {
  const q = state.since ? `?since=${encodeURIComponent(state.since)}` : '';
  const [modelsRes, reqsRes] = await Promise.all([
    api(`/v1/analytics/models${q}`), api(`/v1/analytics/requests${q}${q ? '&' : '?'}limit=200`),
  ]);
  state.lastRequests = reqsRes.requests;
  state.lastModels = modelsRes.models;
  renderLatencyChart(state.lastRequests);
  renderModels(state.lastModels);
  $('#model-table-body').addEventListener('click', (e) => {
    const tr = e.target.closest('tr.clickable'); if (!tr) return;
    renderDrilldown(state.lastModels[Number(tr.dataset.i)].model);
  });
  $('#drilldown-close').addEventListener('click', () => $('#drilldown').classList.add('hidden'));
});
```

- [ ] **Step 2: Manual verify** — line chart shows points after ≥2 requests in window; bar chart + table populated; clicking model row opens drilldown filtered to that model.

- [ ] **Step 3: Commit**

```bash
git add static/dashboard/dashboard.js
git commit -m "feat(dashboard): latency chart, model chart and drilldown"
```

---

### Task 6: Live feed + auto-refresh wiring

**Files:**
- Modify: `static/dashboard/dashboard.js` (append)

**Interfaces:**
- Consumes: `state.lastRequests` (from Task 5), `refreshAll()` (Task 3)

- [ ] **Step 1: Append live feed renderer**

```javascript
// --- live feed (new rows flash) ---
renderers.push(async () => {
  const prevIds = new Set(state.lastRequests.map((r) => r.id));
  $('#feed-body').innerHTML = state.lastRequests.slice(0, 50).map((r) =>
    `<tr class="${prevIds.has(r.id) ? 'new-row' : ''}">
     <td>${new Date(r.created_at).toLocaleTimeString()}</td><td>${r.model}</td><td>${r.provider}</td>
     <td>${r.total_tokens.toLocaleString()}</td><td>${Math.round(r.latency_ms)} ms</td>
     <td class="${r.status === 'error' ? 'err' : 'ok'}">${r.status}</td></tr>`).join('');
});
```

Note: this renderer MUST run before Task 5's renderer resets `state.lastRequests` — move this `renderers.push` ABOVE the Task 5 push in file order (capture old ids before fetch). Final file order: Task 3 core → Task 4 → Task 6 feed push → Task 5 fetch push.

- [ ] **Step 2: Manual verify** — enable auto-refresh, send a chat request via curl/playground: within 15s a flashing row appears at top of feed; summary cards update.

- [ ] **Step 3: Full test suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass (2 new dashboard tests + existing suite green)

- [ ] **Step 4: Commit**

```bash
git add static/dashboard/dashboard.js
git commit -m "feat(dashboard): live feed with new-row flash"
```

---

### Task 7: README + final checks

**Files:**
- Modify: `README.md` (features list + endpoint section)

- [ ] **Step 1: Add to features list**

```markdown
- **Dashboard UI** -- full ops console at `/dashboard`: overview cards, GLM credit gauges, latency/TTFT charts, per-model drilldown, live request feed (Chart.js via CDN)
```

- [ ] **Step 2: Add section after Playground section**

```markdown
### Dashboard

Full ops console served at `/dashboard` (same Bearer key as the API, stored in localStorage).

- Overview cards: requests, tokens, cost, error rate, avg latency, avg TTFT
- GLM credit gauges: 5h + 7d rolling windows vs quota
- Charts: latency/TTFT over time, tokens by model (Chart.js 4 via CDN)
- Per-model table with click-through drilldown
- Live request feed with 15s auto-refresh toggle
```

- [ ] **Step 3: Lint + tests**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m ruff check main.py routes analytics`
Expected: pass / clean

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs(dashboard): document /dashboard console"
```

---

### Task 8: Deploy to VPS + live verify

**Files:** none in repo (VPS operations)

- [ ] **Step 1: Push branch commits to origin**

```bash
cd /Users/ddphuong/Projects/next-labs/llm-gateway && git push origin main
```

- [ ] **Step 2: Build image on VPS**

```bash
rsync -az --delete -e "ssh -i ~/.ssh/id_ed25519_stressvps -o IdentitiesOnly=yes" \
  --exclude .git --exclude .venv --exclude __pycache__ --exclude .pytest_cache --exclude .ruff_cache \
  --exclude repomix-\* --exclude data --exclude .env --exclude .env.apple-container --exclude .DS_Store \
  --exclude server.log --exclude .ngrok --exclude .omx --exclude .superpowers --exclude .claude \
  --exclude .planning --exclude plans --exclude .github \
  ./ root@187.77.158.9:/opt/llm-gateway/
ssh -i ~/.ssh/id_ed25519_stressvps root@187.77.158.9 \
  'cd /opt/llm-gateway && docker build -t llm-gateway:20260919b .'
```

- [ ] **Step 3: Update Dokploy compose image + deploy**

```bash
# update composeFile content replacing image tag llm-gateway:20260919 → llm-gateway:20260919b, then:
dokploy compose update --composeId 7LUC6yZGi2mh8CsRHfyvu --composeFile "<updated content>"
dokploy compose deploy --composeId 7LUC6yZGi2mh8CsRHfyvu
```

- [ ] **Step 4: Live verify**

```bash
curl -s https://llm-gateway.dropitx.site/dashboard | grep -c "chart.umd"   # → 1
curl -s -o /dev/null -w "%{http_code}\n" https://llm-gateway.dropitx.site/dashboard  # → 200
# Browser: open https://llm-gateway.dropitx.site/dashboard, enter APP_API_KEY, confirm cards+gauges+feed
```

- [ ] **Step 5: Update dokploy-deploy skill note** (image tag + dashboard endpoint line).

---

## Self-Review

- Spec coverage: cards ✓ gauges ✓ latency/TTFT chart ✓ tokens-by-model bar ✓ model table+drilldown ✓ live feed ✓ time filters ✓ auto-refresh 15s ✓ Chart.js CDN ✓ auth localStorage ✓ dark theme ✓ tests ✓ README ✓ deploy ✓
- No placeholders; all code blocks concrete.
- Type consistency: `state.lastRequests` written by Task 5, read by Task 6 (ordering note included); `renderGauge`/`bucketRequests` defined before use; DOM ids match Task 2 shell.
