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
