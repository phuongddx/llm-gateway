'use strict';

const REFRESH_MS = 15000;
const KEY_STORAGE = 'llm_dashboard_key';
const state = { key: null, since: null, timer: null, lastRequests: [], feedSeenIds: null };
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
  if (gauges[elId]) { gauges[elId].$gauge = { used, quota }; gauges[elId].data.datasets[0].data = data; gauges[elId].update(); return; }
  const canvas = document.createElement('canvas');
  document.getElementById(elId).replaceChildren(canvas);
  gauges[elId] = new Chart(canvas, {
    type: 'doughnut',
    data: { labels: ['used', 'remaining'], datasets: [{ data, backgroundColor: ['#ff6b6b', '#2a2f3d'], borderWidth: 0 }] },
    options: { cutout: '72%', plugins: { legend: { display: false }, tooltip: { enabled: false } } },
    plugins: [{ id: 'centerText', afterDraw(c) {
      const gauge = c.$gauge || { used, quota };
      const { ctx, chartArea } = c; const x = (chartArea.left + chartArea.right) / 2, y = (chartArea.top + chartArea.bottom) / 2;
      const pct = gauge.quota ? Math.round((gauge.used / gauge.quota) * 100) : (gauge.used > 0 ? 100 : 0);
      ctx.save(); ctx.textAlign = 'center'; ctx.fillStyle = pct >= 90 ? '#ff6b6b' : '#e6e8ef';
      ctx.font = 'bold 22px sans-serif'; ctx.fillText(pct + '%', x, y);
      ctx.font = '11px sans-serif'; ctx.fillStyle = '#8b90a0';
      ctx.fillText(`${Math.round(gauge.used)} / ${gauge.quota}`, x, y + 18); ctx.restore();
    } }],
  });
  gauges[elId].$gauge = { used, quota };
}

renderers.push(async () => {
  const c = await api('/v1/analytics/credits');
  renderGauge('gauge-5h', c.window_5h.credits_used, c.window_5h.quota);
  renderGauge('gauge-7d', c.window_7d_rolling.credits_used, c.window_7d_rolling.quota);
});

// --- latency/ttft line chart ---
let latencyChart = null;

// Bucket by hour (24h/7d) or day (30d).
function bucketRequests(reqs) {
  const dayBuckets = dom.timeFilter.value === '30d';
  const buckets = {};
  for (const r of reqs) {
    const d = new Date(r.created_at);
    const key = dayBuckets ? d.toISOString().slice(0, 10) : d.toISOString().slice(0, 13);
    (buckets[key] ??= { latency: [], ttft: [] }).latency.push(r.latency_ms || 0);
    buckets[key].ttft.push(r.ttft_ms || 0);
  }
  const keys = Object.keys(buckets).sort();
  const avg = (values) => values.length
    ? Math.round(values.reduce((sum, value) => sum + value, 0) / values.length)
    : 0;
  return {
    keys,
    latency: keys.map((key) => avg(buckets[key].latency)),
    ttft: keys.map((key) => avg(buckets[key].ttft)),
  };
}

function renderLatencyChart(reqs) {
  const { keys, latency, ttft } = bucketRequests(reqs);
  latencyChart?.destroy();
  const canvas = document.createElement('canvas');
  $('#chart-latency').replaceChildren(canvas);
  latencyChart = new Chart(canvas, {
    type: 'line',
    data: {
      labels: keys,
      datasets: [
        { label: 'Latency ms', data: latency, borderColor: '#7c8cff', tension: 0.3, pointRadius: 2 },
        { label: 'TTFT ms', data: ttft, borderColor: '#3dd68c', tension: 0.3, pointRadius: 2 },
      ],
    },
    options: { maintainAspectRatio: false, scales: { y: { beginAtZero: true } } },
  });
}

// --- tokens by model bar chart, model table, and drilldown ---
let modelsChart = null;

function renderModels(models) {
  const top = models.slice(0, 10);
  modelsChart?.destroy();
  const canvas = document.createElement('canvas');
  $('#chart-models').replaceChildren(canvas);
  modelsChart = new Chart(canvas, {
    type: 'bar',
    data: {
      labels: top.map((model) => model.model),
      datasets: [{
        label: 'Tokens',
        data: top.map((model) => model.total_tokens),
        backgroundColor: '#7c8cff',
      }],
    },
    options: { maintainAspectRatio: false, scales: { y: { beginAtZero: true } } },
  });

  $('#model-table-body').innerHTML = models.map((model, index) => `
    <tr class="clickable" data-i="${index}">
      <td>${model.model}</td><td>${model.provider}</td><td>${model.request_count}</td>
      <td>${model.total_tokens.toLocaleString()}</td><td>${model.cost_usd.toFixed(4)}</td>
      <td>${Math.round(model.avg_latency_ms)} ms</td><td>${Math.round(model.avg_ttft_ms)} ms</td>
    </tr>`).join('');
}

function renderDrilldown(model) {
  const requests = state.lastRequests.filter((request) => request.model === model);
  $('#drilldown-title').textContent = `${model} — ${requests.length} recent requests`;
  $('#drilldown-body').innerHTML = requests.map((request) => `
    <tr>
      <td>${new Date(request.created_at).toLocaleString()}</td>
      <td class="${request.status === 'error' ? 'err' : 'ok'}">${request.status}</td>
      <td>${request.total_tokens.toLocaleString()}</td>
      <td>${Math.round(request.latency_ms)} ms</td>
      <td>${Math.round(request.ttft_ms)} ms</td>
      <td class="err">${request.error_message || ''}</td>
    </tr>`).join('');
  $('#drilldown').classList.remove('hidden');
}

renderers.push(async () => {
  const query = state.since ? `?since=${encodeURIComponent(state.since)}` : '';
  const [modelsResponse, requestsResponse] = await Promise.all([
    api(`/v1/analytics/models${query}`),
    api(`/v1/analytics/requests${query}${query ? '&' : '?'}limit=200`),
  ]);
  state.lastRequests = requestsResponse.requests;
  state.lastModels = modelsResponse.models;
  renderLatencyChart(state.lastRequests);
  renderModels(state.lastModels);
});

// --- live feed (new rows flash) ---
renderers.push(async () => {
  const first = state.feedSeenIds === null;
  const seen = state.feedSeenIds || new Set();
  $('#feed-body').innerHTML = state.lastRequests.slice(0, 50).map((request) => `
    <tr class="${!first && !seen.has(request.id) ? 'new-row' : ''}">
      <td>${new Date(request.created_at).toLocaleTimeString()}</td>
      <td>${request.model}</td><td>${request.provider}</td>
      <td>${request.total_tokens.toLocaleString()}</td>
      <td>${Math.round(request.latency_ms)} ms</td>
      <td class="${request.status === 'error' ? 'err' : 'ok'}">${request.status}</td>
    </tr>`).join('');
  state.feedSeenIds = new Set(state.lastRequests.slice(0, 50).map((request) => request.id));
});

document.addEventListener('DOMContentLoaded', () => {
  $('#model-table-body').addEventListener('click', (event) => {
    const row = event.target.closest('tr.clickable');
    if (!row) return;
    renderDrilldown(state.lastModels[Number(row.dataset.i)].model);
  });
  $('#drilldown-close').addEventListener('click', () => {
    $('#drilldown').classList.add('hidden');
  });
});
