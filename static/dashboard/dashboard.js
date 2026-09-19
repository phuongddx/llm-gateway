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
