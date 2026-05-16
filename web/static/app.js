// Avinya Web — Frontend

let sessionId = generateId();
let isStreaming = false;
let currentStreamText = "";
let theme = localStorage.getItem("avinya-theme") || "dark";
let authenticated = false;

document.documentElement.setAttribute("data-theme", theme);

// Init
document.addEventListener("DOMContentLoaded", () => {
  checkAuth();
  setupInput();
  setupDragDrop();
});

function generateId() {
  return Math.random().toString(36).substring(2, 10);
}

// Auth
async function checkAuth() {
  try {
    const res = await fetch("/api/auth/check", { method: "POST" });
    const data = await res.json();
    if (data.authenticated) {
      authenticated = true;
      document.getElementById("auth-screen").style.display = "none";
      document.getElementById("app").style.display = "flex";
      initApp();
    }
  } catch {
    // Not authenticated, show auth screen
  }
}

async function handleAuth(event) {
  event.preventDefault();
  const pin = document.getElementById("auth-pin").value;
  const errorEl = document.getElementById("auth-error");
  const btn = document.getElementById("auth-btn");

  btn.textContent = "...";
  btn.disabled = true;
  errorEl.style.display = "none";

  try {
    const res = await fetch("/api/auth", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin }),
    });

    if (res.ok) {
      authenticated = true;
      document.getElementById("auth-screen").style.display = "none";
      document.getElementById("app").style.display = "flex";
      initApp();
    } else {
      errorEl.style.display = "block";
      document.getElementById("auth-pin").value = "";
      document.getElementById("auth-pin").focus();
    }
  } catch {
    errorEl.textContent = "Connection error";
    errorEl.style.display = "block";
  }

  btn.textContent = "Enter";
  btn.disabled = false;
  return false;
}

async function handleLogout() {
  await fetch("/api/auth/logout", { method: "POST" });
  authenticated = false;
  document.getElementById("auth-screen").style.display = "flex";
  document.getElementById("app").style.display = "none";
  document.getElementById("auth-pin").value = "";
  document.getElementById("auth-pin").focus();
  closeSidebar();
}

function initApp() {
  checkHealth();
  loadSessions();
  loadKnowledge();
  showWelcome();
  registerSW();
}

// PWA
function registerSW() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/static/sw.js").catch(() => {});
  }
}

// Health check
async function checkHealth() {
  if (!authenticated) return;
  const indicator = document.getElementById("status-indicator");
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    if (data.status === "ok") {
      indicator.className = "status-chip ready";
      indicator.textContent = "Ready";
    } else {
      indicator.className = "status-chip error";
      indicator.textContent = "Degraded";
    }
  } catch {
    indicator.className = "status-chip error";
    indicator.textContent = "Offline";
  }
}

// Search
async function searchDocs() {
  if (!authenticated) return;
  const input = document.getElementById("search-input");
  const query = input.value.trim();
  if (!query) return;

  const resultsEl = document.getElementById("search-results");
  resultsEl.innerHTML = '<p class="muted">Searching...</p>';

  try {
    const res = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, limit: 10 }),
    });
    const data = await res.json();

    if (!data.results || !data.results.length) {
      resultsEl.innerHTML = '<p class="muted">No results found</p>';
      return;
    }

    resultsEl.innerHTML = data.results.map(r => `
      <div class="search-result-item">
        <span class="sr-score">${r.score.toFixed(2)}</span>
        <div class="sr-source">${escapeHtml(r.source)}</div>
        <div class="sr-content">${escapeHtml(r.content)}</div>
        <div style="margin-top:4px;display:flex;gap:4px;">
          <button class="search-action-btn" onclick="viewDocument('${escapeHtml(r.metadata.path || r.source)}')">View</button>
          <button class="search-action-btn" onclick="useSearchResult('${escapeHtml(r.source)}', '${escapeHtml(r.content.substring(0, 100))}')">Ask</button>
        </div>
      </div>
    `).join("");
  } catch {
    resultsEl.innerHTML = '<p class="muted">Search failed</p>';
  }
}

function useSearchResult(source, snippet) {
  document.getElementById("input-box").value = `What does ${source} say about this: ${snippet}`;
  document.getElementById("input-box").focus();
  closeSidebar();
}

function viewDocument(path) {
  fetch(`/api/documents/${path}`)
    .then(r => r.text())
    .then(content => {
      document.getElementById("doc-viewer-title").textContent = path.split("/").pop();
      document.getElementById("doc-viewer-source").textContent = path;
      document.getElementById("doc-viewer-content").textContent = content;
      document.getElementById("doc-viewer-modal").classList.add("active");
    })
    .catch(() => {
      window.open(`/api/documents/${path}`, "_blank");
    });
}

function closeDocViewer() {
  document.getElementById("doc-viewer-modal").classList.remove("active");
}

function exportCurrentChat() {
  if (!sessionId) return;
  window.open(`/api/sessions/${sessionId}/export`, "_blank");
  closeSidebar();
}

function uploadAudio() {
  document.getElementById("audio-modal").classList.add("active");
  closeSidebar();
}

function closeAudioModal() {
  document.getElementById("audio-modal").classList.remove("active");
}

function handleAudioSelect(event) {
  const files = event.target.files;
  if (files.length) uploadAudioFiles(files);
}

async function uploadAudioFiles(files) {
  const progress = document.getElementById("audio-progress");
  const status = document.getElementById("audio-status");
  const fill = progress.querySelector(".progress-fill");
  progress.style.display = "block";
  fill.style.width = "0%";

  for (const file of files) {
    status.textContent = `Uploading ${file.name}...`;
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch("/api/upload/audio", { method: "POST", body: formData });
      const result = await res.json();
      if (result.status === "uploaded") {
        status.textContent = `Saved: ${file.name}`;
        fill.style.width = "100%";
      } else {
        status.textContent = `Error: ${result.error || "Failed"}`;
        fill.style.width = "0%";
      }
    } catch (err) {
      status.textContent = `Error: ${err.message}`;
      fill.style.width = "0%";
    }
  }

  setTimeout(() => { progress.style.display = "none"; }, 3000);
}

// Sessions
async function loadSessions() {
  try {
    const res = await fetch("/api/sessions");
    const sessions = await res.json();
    renderSessions(sessions);
  } catch {
    // No server sessions yet
  }
}

function renderSessions(sessions) {
  const list = document.getElementById("session-list");
  if (!sessions.length) {
    list.innerHTML = '<p class="muted">No conversations yet</p>';
    return;
  }
  list.innerHTML = sessions.slice(0, 10).map(s => `
    <div class="session-item ${s.id === sessionId ? 'active' : ''}" onclick="switchSession('${s.id}')">
      <span class="title">${escapeHtml(s.title)}</span>
      <button class="delete-btn" onclick="event.stopPropagation(); deleteSession('${s.id}')" title="Delete">&times;</button>
    </div>
  `).join("");
}

async function switchSession(id) {
  sessionId = id;
  currentStreamText = "";
  isStreaming = false;
  const messages = document.getElementById("chat-messages");
  messages.innerHTML = "";

  try {
    const res = await fetch(`/api/sessions/${id}`);
    const data = await res.json();
    if (data.messages && data.messages.length) {
      data.messages.forEach(m => appendMessage(m.role, m.content, false));
    }
    document.getElementById("chat-title").textContent = data.title || "Avinya";
  } catch {
    appendMessage("assistant", "Ready when you are.", false);
  }

  loadSessions();
  closeSidebar();
}

async function deleteSession(id) {
  if (id === sessionId) {
    newChat();
    return;
  }
  await fetch(`/api/sessions/${id}`, { method: "DELETE" });
  loadSessions();
}

function newChat() {
  sessionId = generateId();
  currentStreamText = "";
  isStreaming = false;
  document.getElementById("chat-messages").innerHTML = "";
  document.getElementById("chat-title").textContent = "Avinya";
  document.getElementById("chat-subtitle").textContent = "Ask me anything about the club";
  showWelcome();
  loadSessions();
  closeSidebar();
}

// Knowledge
async function loadKnowledge() {
  const list = document.getElementById("knowledge-list");
  try {
    const res = await fetch("/api/knowledge");
    const files = await res.json();
    if (!files.length) {
      list.innerHTML = '<p class="muted">No documents indexed yet</p>';
      return;
    }
    list.innerHTML = files.slice(0, 10).map(f => `
      <div class="knowledge-item">
        <div class="name">${escapeHtml(f.name)}</div>
        <div class="meta">${formatSize(f.size)} · ${formatDate(f.modified)}</div>
      </div>
    `).join("");
  } catch {
    list.innerHTML = '<p class="muted">Unable to load</p>';
  }
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString();
}

// Welcome screen
function showWelcome() {
  const messages = document.getElementById("chat-messages");
  if (messages.children.length > 0) return;
  messages.innerHTML = `
    <div class="welcome">
      <h2>Welcome to Avinya</h2>
      <p>I'm the permanent member of Vihang Drone Club. I know about our projects, rules, history, and everything in between. Ask me anything.</p>
      <div class="welcome-features">
        <div class="feature-card">
          <div class="icon">📚</div>
          <h4>Club Knowledge</h4>
          <p>Access all indexed documents and club information</p>
        </div>
        <div class="feature-card">
          <div class="icon">🎯</div>
          <h4>Project History</h4>
          <p>Learn about past and current drone projects</p>
        </div>
        <div class="feature-card">
          <div class="icon">👋</div>
          <h4>New Member Guide</h4>
          <p>Get started with club rules and traditions</p>
        </div>
      </div>
    </div>
  `;
}

// Chat
async function sendMessage() {
  const input = document.getElementById("input-box");
  const text = input.value.trim();
  if (!text || isStreaming) return;

  input.value = "";
  input.style.height = "auto";
  removeWelcome();

  appendMessage("user", text);
  isStreaming = true;
  currentStreamText = "";
  document.getElementById("send-btn").disabled = true;

  const assistantEl = appendMessage("assistant", "", true, true);
  const bodyEl = assistantEl.querySelector(".message-body");

  try {
    const res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, session_id: sessionId }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: "Server error" }));
      bodyEl.textContent = "Error: " + (err.error || "Failed to get response");
      isStreaming = false;
      document.getElementById("send-btn").disabled = false;
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        try {
          const data = JSON.parse(line.slice(6));
          if (data.type === "meta") {
            document.getElementById("model-chip").textContent = data.model;
            if (data.sources && data.sources.length) {
              appendSources(assistantEl, data.sources);
            }
          } else if (data.type === "token") {
            currentStreamText += data.text;
            bodyEl.innerHTML = renderMarkdown(currentStreamText);
            bodyEl.classList.add("streaming-cursor");
            scrollToBottom();
          } else if (data.type === "error") {
            bodyEl.textContent = "Error: " + data.message;
            bodyEl.classList.remove("streaming-cursor");
          } else if (data.type === "done") {
            bodyEl.classList.remove("streaming-cursor");
            bodyEl.innerHTML = renderMarkdown(currentStreamText);
            appendCopyButton(assistantEl, currentStreamText);
            appendMeta(assistantEl, data.elapsed);
            isStreaming = false;
            document.getElementById("send-btn").disabled = false;
            loadSessions();
          }
        } catch {
          // Skip malformed SSE data
        }
      }
    }
  } catch (err) {
    bodyEl.textContent = "Connection error. Please try again.";
    bodyEl.classList.remove("streaming-cursor");
    isStreaming = false;
    document.getElementById("send-btn").disabled = false;
  }
}

function sendQuick(text) {
  document.getElementById("input-box").value = text;
  sendMessage();
}

function removeWelcome() {
  const welcome = document.querySelector(".welcome");
  if (welcome) welcome.remove();
}

function appendMessage(role, content, streaming = false, returnEl = false) {
  const messages = document.getElementById("chat-messages");
  const div = document.createElement("div");
  div.className = "message";

  const isUser = role === "user";
  div.innerHTML = `
    <div class="message-header">
      <div class="message-avatar ${role}">${isUser ? "Y" : "A"}</div>
      <span class="message-role">${isUser ? "You" : "Avinya"}</span>
    </div>
    <div class="message-body">${content ? renderMarkdown(content) : (streaming ? '<span class="streaming-cursor"></span>' : "")}</div>
  `;

  messages.appendChild(div);
  scrollToBottom();

  if (returnEl) return div;
}

function appendSources(messageEl, sources) {
  const footer = messageEl.querySelector(".message-footer") || createMessageFooter(messageEl);
  const sourcesHtml = sources.slice(0, 3).map(s =>
    `<span class="message-meta">${escapeHtml(s.file)} (${s.score.toFixed(2)})</span>`
  ).join("");
  footer.innerHTML = sourcesHtml + footer.innerHTML;
}

function appendCopyButton(messageEl, text) {
  const footer = createMessageFooter(messageEl);
  const btn = document.createElement("button");
  btn.className = "copy-btn";
  btn.textContent = "Copy";
  btn.onclick = () => {
    navigator.clipboard.writeText(text);
    btn.textContent = "Copied!";
    setTimeout(() => btn.textContent = "Copy", 1500);
  };
  footer.appendChild(btn);
}

function appendMeta(messageEl, elapsed) {
  const footer = createMessageFooter(messageEl);
  if (elapsed) {
    const span = document.createElement("span");
    span.className = "message-meta";
    span.textContent = `${elapsed}s`;
    footer.appendChild(span);
  }
}

function createMessageFooter(messageEl) {
  let footer = messageEl.querySelector(".message-footer");
  if (!footer) {
    footer = document.createElement("div");
    footer.className = "message-footer";
    messageEl.appendChild(footer);
  }
  return footer;
}

// Markdown rendering
function renderMarkdown(text) {
  if (!text) return "";

  let html = text;

  // Code blocks
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
    const highlighted = highlightCode(escapeHtml(code.trim()), lang);
    return `<pre><code>${highlighted}</code></pre>`;
  });

  // Inline code
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");

  // Bold
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

  // Italic
  html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");

  // Headings
  html = html.replace(/^### (.+)$/gm, "<h3>$1</h3>");
  html = html.replace(/^## (.+)$/gm, "<h2>$1</h2>");
  html = html.replace(/^# (.+)$/gm, "<h1>$1</h1>");

  // Blockquotes
  html = html.replace(/^> (.+)$/gm, "<blockquote>$1</blockquote>");

  // Unordered lists
  html = html.replace(/^[\-\*] (.+)$/gm, "<li>$1</li>");
  html = html.replace(/(<li>.*<\/li>\n?)+/g, "<ul>$&</ul>");

  // Ordered lists
  html = html.replace(/^\d+\. (.+)$/gm, "<li>$1</li>");

  // Horizontal rules
  html = html.replace(/^---$/gm, "<hr>");

  // Links
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

  // Paragraphs
  html = html.replace(/\n\n/g, "</p><p>");
  html = html.replace(/\n/g, "<br>");

  // Wrap in paragraph if not already wrapped
  if (!html.startsWith("<")) {
    html = "<p>" + html + "</p>";
  }

  return html;
}

function highlightCode(code, lang) {
  if (!lang) return code;

  const langLower = lang.toLowerCase();
  const keywords = {
    python: /\b(def|class|import|from|return|if|else|elif|for|while|try|except|with|as|in|not|and|or|is|None|True|False|self|lambda|yield|raise|pass|break|continue|async|await)\b/g,
    javascript: /\b(const|let|var|function|return|if|else|for|while|class|import|from|export|default|async|await|new|this|true|false|null|undefined|try|catch|throw)\b/g,
    js: /\b(const|let|var|function|return|if|else|for|while|class|import|from|export|default|async|await|new|this|true|false|null|undefined)\b/g,
    typescript: /\b(const|let|var|function|return|if|else|for|while|class|import|from|export|default|async|await|new|this|true|false|null|undefined|type|interface|enum)\b/g,
    ts: /\b(const|let|var|function|return|if|else|for|while|class|import|from|export|default|async|await|new|this|true|false|null|undefined|type|interface)\b/g,
    bash: /\b(if|then|else|fi|for|while|do|done|case|esac|function|return|exit|echo|export|source|cd|ls|mkdir|rm|cp|mv|cat|grep|sed|awk)\b/g,
    sh: /\b(if|then|else|fi|for|while|do|done|echo|export|cd|ls|mkdir|rm|cp|mv|cat|grep)\b/g,
  };

  const patterns = keywords[langLower] || keywords.javascript;
  if (patterns) {
    code = code.replace(patterns, '<span class="code-keyword">$1</span>');
  }

  // Strings
  code = code.replace(/(&quot;[^&]*&quot;|"[^"]*"|'[^']*')/g, '<span class="code-string">$1</span>');
  // Comments
  code = code.replace(/(\/\/.*|#.*)/g, '<span class="code-comment">$1</span>');
  // Numbers
  code = code.replace(/\b(\d+\.?\d*)\b/g, '<span class="code-number">$1</span>');
  // Function calls
  code = code.replace(/\b([a-zA-Z_]\w*)\s*(?=\()/g, '<span class="code-function">$1</span>');

  return code;
}

// Input handling
function setupInput() {
  const input = document.getElementById("input-box");

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 120) + "px";
  });
}

// Drag & drop
function setupDragDrop() {
  const dropZone = document.getElementById("drop-zone");
  if (!dropZone) return;

  ["dragenter", "dragover"].forEach(evt => {
    dropZone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropZone.classList.add("dragover");
    });
  });

  ["dragleave", "drop"].forEach(evt => {
    dropZone.addEventListener(evt, () => {
      dropZone.classList.remove("dragover");
    });
  });

  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    const files = e.dataTransfer.files;
    if (files.length) uploadFiles(files);
  });
}

function handleFileSelect(event) {
  const files = event.target.files;
  if (files.length) uploadFiles(files);
}

async function uploadFiles(files) {
  const progress = document.getElementById("upload-progress");
  const status = document.getElementById("upload-status");
  const fill = progress.querySelector(".progress-fill");
  progress.style.display = "block";
  fill.style.width = "0%";

  for (const file of files) {
    status.textContent = `Uploading ${file.name}...`;
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch("/api/upload", { method: "POST", body: formData });
      const result = await res.json();
      if (result.status === "uploaded") {
        status.textContent = `Indexed: ${result.indexed} files, ${result.chunks} chunks`;
        fill.style.width = "100%";
        loadKnowledge();
      } else {
        status.textContent = `Error: ${result.error || "Failed"}`;
        fill.style.width = "0%";
      }
    } catch (err) {
      status.textContent = `Error: ${err.message}`;
      fill.style.width = "0%";
    }
  }

  setTimeout(() => {
    progress.style.display = "none";
  }, 3000);
}

function uploadKnowledge() {
  document.getElementById("upload-modal").classList.add("active");
  closeSidebar();
}

function closeUploadModal() {
  document.getElementById("upload-modal").classList.remove("active");
}

async function reindexKnowledge() {
  const status = document.getElementById("status-indicator");
  status.textContent = "Reindexing...";
  try {
    const res = await fetch("/api/reindex", { method: "POST" });
    const result = await res.json();
    status.textContent = `Indexed ${result.files_indexed} files`;
    loadKnowledge();
  } catch {
    status.textContent = "Reindex failed";
  }
  setTimeout(() => checkHealth(), 2000);
  closeSidebar();
}

// Sidebar
document.getElementById("menu-btn").addEventListener("click", () => {
  document.getElementById("sidebar").classList.add("open");
  document.getElementById("sidebar-overlay").classList.add("active");
});

document.getElementById("close-sidebar").addEventListener("click", closeSidebar);
document.getElementById("sidebar-overlay").addEventListener("click", closeSidebar);

function closeSidebar() {
  document.getElementById("sidebar").classList.remove("open");
  document.getElementById("sidebar-overlay").classList.remove("active");
}

document.getElementById("new-chat-btn").addEventListener("click", newChat);

// Theme toggle
document.getElementById("theme-toggle").addEventListener("click", () => {
  theme = theme === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("avinya-theme", theme);
});

// Utilities
function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function scrollToBottom() {
  const container = document.getElementById("chat-container");
  container.scrollTop = container.scrollHeight;
}
