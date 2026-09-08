/* LLM Gateway Playground — main logic */

// === State ===
const state = {
  apiKey: null,
  currentModel: null,
  conversations: [],
  activeConversationId: null,
  isStreaming: false,
  abortController: null,
};

// === DOM refs ===
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

const dom = {
  loginOverlay: $('#login-overlay'),
  loginForm: $('#login-form'),
  apiKeyInput: $('#api-key-input'),
  loginBtn: $('#login-btn'),
  loginError: $('#login-error'),
  app: $('#app'),
  sidebar: $('#sidebar'),
  sidebarToggle: $('#sidebar-toggle'),
  sidebarClose: $('#sidebar-close'),
  modelSelect: $('#model-select'),
  systemPrompt: $('#system-prompt'),
  temperature: $('#temperature'),
  tempVal: $('#temp-val'),
  maxTokens: $('#max-tokens'),
  maxTokensVal: $('#max-tokens-val'),
  topP: $('#top-p'),
  topPVal: $('#top-p-val'),
  convList: $('#conversation-list'),
  newChatBtn: $('#new-chat-btn'),
  chatTitle: $('#chat-title'),
  messages: $('#messages'),
  userInput: $('#user-input'),
  sendBtn: $('#send-btn'),
  stopBtn: $('#stop-btn'),
};

// === Auth + Init ===
dom.loginForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const key = dom.apiKeyInput.value.trim();
  if (!key) return;
  dom.loginBtn.disabled = true;
  dom.loginError.hidden = true;
  try {
    state.apiKey = key;
    await fetchModels();
    dom.loginOverlay.hidden = true;
    dom.app.hidden = false;
    loadConversations();
    if (state.conversations.length === 0) newConversation();
    else switchConversation(state.conversations[0].id);
  } catch (err) {
    state.apiKey = null;
    dom.loginError.textContent = err.message || 'Connection failed';
    dom.loginError.hidden = false;
    dom.loginBtn.disabled = false;
  }
});

// === API ===
async function fetchModels() {
  const res = await fetch('/v1/models', {
    headers: { 'Authorization': `Bearer ${state.apiKey}` },
  });
  if (!res.ok) throw new Error(`Auth failed (${res.status})`);
  const data = await res.json();
  dom.modelSelect.innerHTML = '';
  data.data.forEach((m) => {
    const opt = document.createElement('option');
    opt.value = m.id;
    opt.textContent = m.id;
    dom.modelSelect.appendChild(opt);
  });
  if (data.data.length > 0) state.currentModel = data.data[0].id;
}

async function* streamChat(messages, model, systemPrompt, params) {
  state.abortController = new AbortController();
  const res = await fetch('/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${state.apiKey}`,
    },
    body: JSON.stringify({
      model,
      messages,
      system_prompt: systemPrompt,
      stream: true,
      temperature: params.temperature,
      max_tokens: params.maxTokens,
      top_p: params.topP,
    }),
    signal: state.abortController.signal,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const frames = buffer.split('\n\n');
    buffer = frames.pop();

    for (const frame of frames) {
      for (const line of frame.split('\n')) {
        if (!line.startsWith('data: ')) continue;
        const data = line.slice(6);
        if (data === '[DONE]') return;
        let parsed;
        try {
          parsed = JSON.parse(data);
        } catch {
          continue; // malformed frame — skip, never a gateway error
        }
        if (parsed.error) throw new Error(parsed.error?.message || 'Unknown gateway error');
        if (parsed.token) yield parsed.token;
      }
    }
  }

  // H4: Check remaining buffer for [DONE] that split across chunks
  if (buffer.trim()) {
    for (const line of buffer.split('\n')) {
      if (!line.startsWith('data: ')) continue;
      const data = line.slice(6).trim();
      if (data === '[DONE]') return;
      let parsed;
      try {
        parsed = JSON.parse(data);
      } catch {
        continue; // malformed frame — skip, never a gateway error
      }
      if (parsed.error) throw new Error(parsed.error?.message || 'Unknown gateway error');
      if (parsed.token) yield parsed.token;
    }
  }
}

// === Chat UI ===
function getActiveConv() {
  return state.conversations.find((c) => c.id === state.activeConversationId);
}

function renderMessage(role, content, isStreaming) {
  const div = document.createElement('div');
  div.className = `message ${role}${isStreaming ? ' streaming' : ''}`;
  const label = document.createElement('div');
  label.className = 'role-label';
  label.textContent = role;
  const body = document.createElement('div');
  body.className = 'content';
  body.innerHTML = role === 'assistant' ? renderMarkdown(content) : escapeHtml(content);
  div.appendChild(label);
  div.appendChild(body);
  dom.messages.appendChild(div);
  return div;
}

// H2: Restrictive DOMPurify — block form/input to prevent phishing
const PURIFY_CONFIG = {
  ALLOWED_TAGS: [
    'p', 'br', 'strong', 'em', 'b', 'i', 'u', 's', 'code', 'pre',
    'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'a', 'blockquote', 'hr', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'span', 'del', 'sup', 'sub',
  ],
  ALLOWED_ATTR: ['href', 'target', 'rel', 'class'],
};

function renderMarkdown(text) {
  const fenceCount = (text.match(/```/g) || []).length;
  let safe = fenceCount % 2 !== 0 ? text + '\n```' : text;
  return DOMPurify.sanitize(marked.parse(safe), PURIFY_CONFIG);
}

function escapeHtml(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

let renderTimer = null;
let currentAssistantDiv = null;

function appendToken(token) {
  const conv = getActiveConv();
  if (!conv) return;
  const lastMsg = conv.messages[conv.messages.length - 1];
  if (!lastMsg || lastMsg.role !== 'assistant') return;
  lastMsg.content += token;

  if (renderTimer) {
    return;
  }
  renderTimer = setTimeout(() => {
    const el = currentAssistantDiv?.querySelector('.content');
    renderTimer = null;
    scrollToBottom();
  }, 50);
}

function scrollToBottom() {
  dom.messages.scrollTop = dom.messages.scrollHeight;
}

async function sendMessage() {
  const text = dom.userInput.value.trim();
  if (!text || state.isStreaming) return;

  const conv = getActiveConv();
  if (!conv) return;

  // Update model/params
  state.currentModel = dom.modelSelect.value;
  conv.model = state.currentModel;
  conv.systemPrompt = dom.systemPrompt.value;
  conv.params = getParams();

  // Add user message
  conv.messages.push({ role: 'user', content: text });
  renderMessage('user', text, false);
  dom.userInput.value = '';
  autoResizeInput();

  // Add assistant placeholder
  conv.messages.push({ role: 'assistant', content: '' });
  currentAssistantDiv = renderMessage('assistant', '', true);

  // Build messages array (exclude empty assistant)
  const apiMessages = conv.messages
    .filter((m) => m.content || m.role === 'user')
    .slice(0, -1); // remove empty assistant

  setStreaming(true);
  scrollToBottom();

  try {
    for await (const token of streamChat(apiMessages, conv.model, conv.systemPrompt, conv.params)) {
      appendToken(token);
    }
  } catch (err) {
    if (err.name === 'AbortError') {
      // User cancelled — keep partial
    } else {
      const lastMsg = conv.messages[conv.messages.length - 1];
      if (lastMsg && lastMsg.role === 'assistant' && !lastMsg.content) {
        lastMsg.content = `Error: ${err.message}`;
      }
      renderMessage('error', `Error: ${err.message}`, false);
    }
  } finally {
    setStreaming(false);
    // Final render
    if (currentAssistantDiv) {
      const lastMsg = conv.messages[conv.messages.length - 1];
      if (lastMsg) {
        const el = currentAssistantDiv.querySelector('.content');
        if (el) el.innerHTML = renderMarkdown(lastMsg.content);
        currentAssistantDiv.classList.remove('streaming');
        // H3: Scope hljs to just this message, not the entire page
        el.querySelectorAll('pre code').forEach((block) => hljs.highlightElement(block));
      }
    }
    saveConversation();
    updateConvTitle(conv);
    renderConvList();
  }
}

function setStreaming(on) {
  state.isStreaming = on;
  dom.sendBtn.hidden = on;
  dom.stopBtn.hidden = !on;
  dom.userInput.disabled = on;
}

function getParams() {
  return {
    temperature: parseFloat(dom.temperature.value),
    maxTokens: parseInt(dom.maxTokens.value, 10),
    topP: parseFloat(dom.topP.value),
  };
}

// === Conversation Management ===
const STORAGE_KEY = 'llm_playground_conversations';

function loadConversations() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    state.conversations = raw ? JSON.parse(raw) : [];
  } catch { state.conversations = []; }
}

function saveConversation() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.conversations));
}

function newConversation() {
  const conv = {
    id: crypto.randomUUID(),
    title: 'New Conversation',
    model: state.currentModel || dom.modelSelect.value,
    systemPrompt: dom.systemPrompt.value,
    params: getParams(),
    messages: [],
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
  state.conversations.unshift(conv);
  saveConversation();
  switchConversation(conv.id);
  renderConvList();
}

function switchConversation(id) {
  state.activeConversationId = id;
  const conv = getActiveConv();
  if (!conv) return;

  // Restore UI state
  dom.modelSelect.value = conv.model;
  state.currentModel = conv.model;
  dom.systemPrompt.value = conv.systemPrompt || '';
  if (conv.params) {
    dom.temperature.value = conv.params.temperature;
    dom.tempVal.textContent = conv.params.temperature;
    dom.maxTokens.value = conv.params.maxTokens;
    dom.maxTokensVal.textContent = conv.params.maxTokens;
    dom.topP.value = conv.params.topP;
    dom.topPVal.textContent = conv.params.topP;
  }
  dom.chatTitle.textContent = conv.title;

  // Render messages
  dom.messages.innerHTML = '';
  conv.messages.forEach((m) => renderMessage(m.role, m.content, false));
  dom.messages.querySelectorAll('pre code').forEach((block) => hljs.highlightElement(block));
  scrollToBottom();
  renderConvList();
}

function deleteConversation(id) {
  state.conversations = state.conversations.filter((c) => c.id !== id);
  saveConversation();
  if (state.activeConversationId === id) {
    if (state.conversations.length > 0) switchConversation(state.conversations[0].id);
    else newConversation();
  }
  renderConvList();
}

function updateConvTitle(conv) {
  const firstUser = conv.messages.find((m) => m.role === 'user');
  if (firstUser) conv.title = firstUser.content.slice(0, 40) + (firstUser.content.length > 40 ? '...' : '');
  conv.updatedAt = new Date().toISOString();
}

function renderConvList() {
  dom.convList.innerHTML = '';
  state.conversations.forEach((c) => {
    const div = document.createElement('div');
    div.className = `conv-item${c.id === state.activeConversationId ? ' active' : ''}`;
    div.innerHTML = `
      <span class="conv-title">${escapeHtml(c.title)}</span>
      <span class="conv-delete" title="Delete">&times;</span>
    `;
    div.querySelector('.conv-title').addEventListener('click', () => switchConversation(c.id));
    div.querySelector('.conv-delete').addEventListener('click', (e) => {
      e.stopPropagation();
      deleteConversation(c.id);
    });
    dom.convList.appendChild(div);
  });
}

// === Event Listeners ===

// Model select (single listener, not stacked)
dom.modelSelect.addEventListener('change', () => { state.currentModel = dom.modelSelect.value; });

// Send message
dom.sendBtn.addEventListener('click', sendMessage);
dom.userInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

// Stop streaming
dom.stopBtn.addEventListener('click', () => {
  if (state.abortController) state.abortController.abort();
});

// Sidebar toggle
dom.sidebarToggle.addEventListener('click', () => dom.sidebar.classList.toggle('collapsed'));
dom.sidebarClose.addEventListener('click', () => dom.sidebar.classList.add('collapsed'));

// New chat
dom.newChatBtn.addEventListener('click', newConversation);

// Param sliders
dom.temperature.addEventListener('input', () => { dom.tempVal.textContent = dom.temperature.value; });
dom.maxTokens.addEventListener('input', () => { dom.maxTokensVal.textContent = dom.maxTokens.value; });
dom.topP.addEventListener('input', () => { dom.topPVal.textContent = dom.topP.value; });

// Auto-resize textarea
dom.userInput.addEventListener('input', autoResizeInput);
function autoResizeInput() {
  dom.userInput.style.height = 'auto';
  dom.userInput.style.height = Math.min(dom.userInput.scrollHeight, 200) + 'px';
}

// Configure marked
marked.setOptions({ breaks: true, gfm: true });
