// Avinya Web — Frontend

let sessionId = generateId();
let isStreaming = false;
let currentStreamText = "";
let theme = localStorage.getItem("avinya-theme") || "dark";
let authenticated = false;
let bulkFiles = [];
let pendingUploadFile = null;
let graphData = null;

let voiceRecognition = null;
let isVoiceActive = false;
let voiceSynth = window.speechSynthesis;

document.documentElement.setAttribute("data-theme", theme);

document.addEventListener("DOMContentLoaded", () => {
  checkAuth();
  setupInput();
  setupDragDrop();
  initVoice();
});

function generateId() {
  return Math.random().toString(36).substring(2, 10);
}

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
  } catch {}
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

function registerSW() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/static/sw.js").catch(() => {});
  }
}

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

async function loadSessions() {
  try {
    const res = await fetch("/api/sessions");
    const sessions = await res.json();
    renderSessions(sessions);
  } catch {}
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
        ${f.tags && f.tags.length ? `<div class="tags">${f.tags.map(t => `<span class="tag">${t}</span>`).join("")}</div>` : ""}
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

function showWelcome() {
  const messages = document.getElementById("chat-messages");
  if (messages.children.length > 0) return;
  messages.innerHTML = `
    <div class="welcome">
      <h2>Welcome to Avinya</h2>
      <p>I'm the permanent member of Vihang Drone Club. I know about our projects, rules, history, and everything in between. Ask me anything.</p>
      <div class="welcome-features">
        <div class="feature-card"><div class="icon">📚</div><h4>Club Knowledge</h4><p>Access all indexed documents and club information</p></div>
        <div class="feature-card"><div class="icon">🎯</div><h4>Project History</h4><p>Learn about past and current drone projects</p></div>
        <div class="feature-card"><div class="icon">👋</div><h4>New Member Guide</h4><p>Get started with club rules and traditions</p></div>
      </div>
    </div>
  `;
}

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
            if (data.related && data.related.length) {
              appendRelated(assistantEl, data.related);
            }
            if (data.confidence) {
              const chip = document.getElementById("confidence-chip");
              chip.style.display = "inline-block";
              chip.textContent = data.confidence;
              chip.className = "chip confidence-" + data.confidence;
            }
            if (data.gap) {
              appendGapAlert(assistantEl, data.gap);
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
            if (currentStreamText) {
              speakText(currentStreamText);
            }
          }
        } catch {}
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

function appendRelated(messageEl, related) {
  const footer = createMessageFooter(messageEl);
  const html = `<span class="message-meta" style="color:var(--accent)">Related: ${related.map(r => escapeHtml(r.file)).join(", ")}</span>`;
  footer.innerHTML += html;
}

function appendGapAlert(messageEl, gap) {
  const footer = createMessageFooter(messageEl);
  footer.innerHTML += `<span class="message-meta" style="color:var(--warning)">⚠ No docs on this topic yet — gap recorded</span>`;
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

function renderMarkdown(text) {
  if (!text) return "";
  let html = text;
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => `<pre><code>${highlightCode(escapeHtml(code.trim()), lang)}</code></pre>`);
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");
  html = html.replace(/^### (.+)$/gm, "<h3>$1</h3>");
  html = html.replace(/^## (.+)$/gm, "<h2>$1</h2>");
  html = html.replace(/^# (.+)$/gm, "<h1>$1</h1>");
  html = html.replace(/^> (.+)$/gm, "<blockquote>$1</blockquote>");
  html = html.replace(/^[\-\*] (.+)$/gm, "<li>$1</li>");
  html = html.replace(/(<li>.*<\/li>\n?)+/g, "<ul>$&</ul>");
  html = html.replace(/^\d+\. (.+)$/gm, "<li>$1</li>");
  html = html.replace(/^---$/gm, "<hr>");
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  html = html.replace(/\|(.+)\|/g, (match) => {
    const cells = match.split("|").filter(c => c.trim());
    if (cells.every(c => /^[\s\-:]+$/.test(c))) return "";
    return "<table><tr>" + cells.map(c => `<td>${c.trim()}</td>`).join("") + "</tr></table>";
  });
  html = html.replace(/\n\n/g, "</p><p>");
  html = html.replace(/\n/g, "<br>");
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
    bash: /\b(if|then|else|fi|for|while|do|done|echo|export|cd|ls|mkdir|rm|cp|mv|cat|grep)\b/g,
  };
  const patterns = keywords[langLower] || keywords.javascript;
  if (patterns) code = code.replace(patterns, '<span class="code-keyword">$1</span>');
  code = code.replace(/(&quot;[^&]*&quot;|"[^"]*"|'[^']*')/g, '<span class="code-string">$1</span>');
  code = code.replace(/(\/\/.*|#.*)/g, '<span class="code-comment">$1</span>');
  code = code.replace(/\b(\d+\.?\d*)\b/g, '<span class="code-number">$1</span>');
  code = code.replace(/\b([a-zA-Z_]\w*)\s*(?=\()/g, '<span class="code-function">$1</span>');
  return code;
}

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

function setupDragDrop() {
  const dropZone = document.getElementById("drop-zone");
  if (!dropZone) return;
  ["dragenter", "dragover"].forEach(evt => {
    dropZone.addEventListener(evt, (e) => { e.preventDefault(); dropZone.classList.add("dragover"); });
  });
  ["dragleave", "drop"].forEach(evt => {
    dropZone.addEventListener(evt, () => { dropZone.classList.remove("dragover"); });
  });
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    const files = e.dataTransfer.files;
    if (files.length) previewFile(files[0]);
  });
}

async function previewFile(file) {
  pendingUploadFile = file;
  const progress = document.getElementById("upload-progress");
  const preview = document.getElementById("upload-preview");
  progress.style.display = "none";
  preview.style.display = "block";
  try {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch("/api/upload/preview", { method: "POST", body: formData });
    const data = await res.json();
    document.getElementById("preview-content").textContent = data.preview.substring(0, 1000);
    const tagsEl = document.getElementById("suggested-tags");
    tagsEl.innerHTML = (data.suggested_tags || []).map(t =>
      `<label class="tag-check"><input type="checkbox" value="${t}" checked> ${t}</label>`
    ).join("");
  } catch {
    document.getElementById("preview-content").textContent = "Could not preview file";
  }
}

async function confirmUpload() {
  if (!pendingUploadFile) return;
  const tags = Array.from(document.querySelectorAll("#suggested-tags input:checked")).map(i => i.value);
  const contextNote = document.getElementById("context-note").value;
  const progress = document.getElementById("upload-progress");
  const status = document.getElementById("upload-status");
  const fill = progress.querySelector(".progress-fill");
  progress.style.display = "block";
  fill.style.width = "0%";
  status.textContent = `Uploading ${pendingUploadFile.name}...`;
  try {
    const formData = new FormData();
    formData.append("file", pendingUploadFile);
    formData.append("tags", tags.join(","));
    if (contextNote) formData.append("context_note", contextNote);
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
  setTimeout(() => {
    progress.style.display = "none";
    document.getElementById("upload-preview").style.display = "none";
    pendingUploadFile = null;
  }, 3000);
}

function handleFileSelect(event) {
  const files = event.target.files;
  if (files.length) previewFile(files[0]);
}

function uploadKnowledge() {
  document.getElementById("upload-preview").style.display = "none";
  document.getElementById("upload-progress").style.display = "none";
  document.getElementById("context-note").value = "";
  document.getElementById("upload-modal").classList.add("active");
  closeSidebar();
}

function closeUploadModal() {
  document.getElementById("upload-modal").classList.remove("active");
}

function uploadBulk() {
  bulkFiles = [];
  document.getElementById("bulk-queue").style.display = "none";
  document.getElementById("bulk-progress").style.display = "none";
  document.getElementById("bulk-modal").classList.add("active");
  closeSidebar();
  setupBulkDragDrop();
}

function closeBulkModal() {
  document.getElementById("bulk-modal").classList.remove("active");
}

function setupBulkDragDrop() {
  const dropZone = document.getElementById("bulk-drop-zone");
  if (!dropZone) return;
  ["dragenter", "dragover"].forEach(evt => {
    dropZone.addEventListener(evt, (e) => { e.preventDefault(); dropZone.classList.add("dragover"); });
  });
  ["dragleave", "drop"].forEach(evt => {
    dropZone.addEventListener(evt, () => { dropZone.classList.remove("dragover"); });
  });
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    const items = e.dataTransfer.items;
    if (items) {
      const filePromises = [];
      for (let i = 0; i < items.length; i++) {
        const entry = items[i].webkitGetAsEntry?.();
        if (entry) filePromises.push(readEntry(entry));
      }
      Promise.all(filePromises).then(results => {
        bulkFiles = results.flat();
        if (bulkFiles.length) {
          document.getElementById("bulk-queue-count").textContent = `${bulkFiles.length} files queued`;
          document.getElementById("bulk-queue").style.display = "block";
        }
      });
    } else if (e.dataTransfer.files.length) {
      bulkFiles = Array.from(e.dataTransfer.files);
      document.getElementById("bulk-queue-count").textContent = `${bulkFiles.length} files queued`;
      document.getElementById("bulk-queue").style.display = "block";
    }
  });
}

function readEntry(entry) {
  return new Promise((resolve) => {
    if (entry.isFile) {
      entry.file(file => resolve([file]));
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      const allFiles = [];
      const readBatch = () => {
        reader.readEntries(entries => {
          if (entries.length === 0) { Promise.all(allFiles).then(resolve); }
          else { for (const e of entries) allFiles.push(readEntry(e)); readBatch(); }
        });
      };
      readBatch();
    } else { resolve([]); }
  });
}

function handleBulkFileSelect(event) {
  bulkFiles = Array.from(event.target.files);
  if (bulkFiles.length) {
    document.getElementById("bulk-queue-count").textContent = `${bulkFiles.length} files queued`;
    document.getElementById("bulk-queue").style.display = "block";
  }
}

async function startBulkUpload() {
  const progress = document.getElementById("bulk-progress");
  const status = document.getElementById("bulk-status");
  const fill = progress.querySelector(".progress-fill");
  progress.style.display = "block";
  document.getElementById("bulk-queue").style.display = "none";
  fill.style.width = "0%";
  const formData = new FormData();
  for (const file of bulkFiles) formData.append("files", file);
  status.textContent = `Uploading ${bulkFiles.length} files...`;
  try {
    const res = await fetch("/api/upload/bulk", { method: "POST", body: formData });
    const result = await res.json();
    status.textContent = `Done: ${result.success} succeeded, ${result.failed} failed`;
    fill.style.width = "100%";
    loadKnowledge();
  } catch (err) {
    status.textContent = `Error: ${err.message}`;
    fill.style.width = "0%";
  }
  setTimeout(() => { progress.style.display = "none"; }, 3000);
}

function uploadImage() {
  document.getElementById("image-description").value = "";
  document.getElementById("image-progress").style.display = "none";
  document.getElementById("image-modal").classList.add("active");
  closeSidebar();
  setupImageDragDrop();
}

function closeImageModal() {
  document.getElementById("image-modal").classList.remove("active");
}

function setupImageDragDrop() {
  const dropZone = document.getElementById("image-drop-zone");
  if (!dropZone) return;
  ["dragenter", "dragover"].forEach(evt => {
    dropZone.addEventListener(evt, (e) => { e.preventDefault(); dropZone.classList.add("dragover"); });
  });
  ["dragleave", "drop"].forEach(evt => {
    dropZone.addEventListener(evt, () => { dropZone.classList.remove("dragover"); });
  });
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    if (e.dataTransfer.files.length) uploadImageFiles(e.dataTransfer.files);
  });
}

function handleImageSelect(event) {
  if (event.target.files.length) uploadImageFiles(event.target.files);
}

async function uploadImageFiles(files) {
  const progress = document.getElementById("image-progress");
  const status = document.getElementById("image-status");
  const fill = progress.querySelector(".progress-fill");
  const description = document.getElementById("image-description").value;
  progress.style.display = "block";
  fill.style.width = "0%";
  for (const file of files) {
    status.textContent = `Uploading ${file.name}...`;
    try {
      const formData = new FormData();
      formData.append("file", file);
      if (description) formData.append("description", description);
      const res = await fetch("/api/upload/image", { method: "POST", body: formData });
      const result = await res.json();
      if (result.status === "uploaded") {
        status.textContent = `Saved: ${file.name}`;
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
  setTimeout(() => { progress.style.display = "none"; }, 3000);
}

function uploadPhoto() {
  document.getElementById("photo-question").value = "";
  document.getElementById("photo-progress").style.display = "none";
  document.getElementById("photo-modal").classList.add("active");
  closeSidebar();
}

function closePhotoModal() {
  document.getElementById("photo-modal").classList.remove("active");
}

function handlePhotoSelect(event) {
  if (event.target.files.length) uploadPhotoFile(event.target.files[0]);
}

async function uploadPhotoFile(file) {
  const progress = document.getElementById("photo-progress");
  const status = document.getElementById("photo-status");
  const fill = progress.querySelector(".progress-fill");
  const question = document.getElementById("photo-question").value;
  progress.style.display = "block";
  fill.style.width = "0%";
  status.textContent = `Uploading ${file.name}...`;
  try {
    const formData = new FormData();
    formData.append("file", file);
    if (question) formData.append("question", question);
    const res = await fetch("/api/upload/photo", { method: "POST", body: formData });
    const result = await res.json();
    if (result.status === "uploaded") {
      status.textContent = result.analysis ? `Saved. Analysis: ${result.analysis.substring(0, 200)}` : `Saved: ${file.name}`;
      fill.style.width = "100%";
    } else {
      status.textContent = `Error: ${result.error || "Failed"}`;
      fill.style.width = "0%";
    }
  } catch (err) {
    status.textContent = `Error: ${err.message}`;
    fill.style.width = "0%";
  }
  setTimeout(() => { progress.style.display = "none"; }, 3000);
}

function uploadVideo() {
  document.getElementById("video-progress").style.display = "none";
  document.getElementById("video-modal").classList.add("active");
  closeSidebar();
}

function closeVideoModal() {
  document.getElementById("video-modal").classList.remove("active");
}

function handleVideoSelect(event) {
  if (event.target.files.length) uploadVideoFile(event.target.files[0]);
}

async function uploadVideoFile(file) {
  const progress = document.getElementById("video-progress");
  const status = document.getElementById("video-status");
  const fill = progress.querySelector(".progress-fill");
  progress.style.display = "block";
  fill.style.width = "0%";
  status.textContent = `Uploading ${file.name}...`;
  try {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch("/api/upload/video", { method: "POST", body: formData });
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
  setTimeout(() => { progress.style.display = "none"; }, 3000);
}

function captureMeeting() {
  document.getElementById("meeting-title").value = "";
  document.getElementById("meeting-attendees").value = "";
  document.getElementById("meeting-notes").value = "";
  document.getElementById("meeting-result").style.display = "none";
  document.getElementById("meeting-modal").classList.add("active");
  closeSidebar();
}

function closeMeetingModal() {
  document.getElementById("meeting-modal").classList.remove("active");
}

async function submitMeeting() {
  const title = document.getElementById("meeting-title").value.trim() || "Untitled Meeting";
  const attendeesRaw = document.getElementById("meeting-attendees").value.trim();
  const notes = document.getElementById("meeting-notes").value.trim();
  const attendees = attendeesRaw ? attendeesRaw.split(",").map(a => a.trim()).filter(Boolean) : [];
  if (!notes) { alert("Please enter meeting notes"); return; }
  const resultDiv = document.getElementById("meeting-result");
  const summaryDiv = document.getElementById("meeting-summary");
  resultDiv.style.display = "block";
  summaryDiv.innerHTML = '<p class="muted">Processing meeting notes...</p>';
  try {
    const res = await fetch("/api/meeting", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, attendees, notes }),
    });
    const data = await res.json();
    if (data.status === "captured") {
      summaryDiv.innerHTML = `<div style="margin-bottom:8px"><strong>Saved as:</strong> ${escapeHtml(data.filename)}</div><div style="white-space:pre-wrap">${renderMarkdown(data.summary)}</div>`;
    } else {
      summaryDiv.innerHTML = `<p style="color:var(--danger)">Error: ${escapeHtml(data.error || "Failed")}</p>`;
    }
  } catch (err) {
    summaryDiv.innerHTML = `<p style="color:var(--danger)">Connection error: ${escapeHtml(err.message)}</p>`;
  }
}

function showGraph() {
  document.getElementById("graph-modal").classList.add("active");
  closeSidebar();
  loadGraph();
}

function closeGraph() {
  document.getElementById("graph-modal").classList.remove("active");
}

async function loadGraph() {
  try {
    const res = await fetch("/api/graph");
    const data = await res.json();
    graphData = data;
    const emptyEl = document.getElementById("graph-empty");
    const reportEl = document.getElementById("graph-report");
    if (data.nodes && data.nodes.length > 0) {
      emptyEl.style.display = "none";
      drawGraph(data.nodes, data.edges || []);
      if (data.report) {
        reportEl.style.display = "block";
        reportEl.innerHTML = renderMarkdown(data.report);
      } else { reportEl.style.display = "none"; }
    } else { emptyEl.style.display = "block"; reportEl.style.display = "none"; }
  } catch { document.getElementById("graph-empty").style.display = "block"; }
}

function drawGraph(nodes, edges) {
  const canvas = document.getElementById("graph-canvas");
  const container = document.getElementById("graph-canvas-container");
  canvas.width = container.clientWidth;
  canvas.height = container.clientHeight;
  const ctx = canvas.getContext("2d");
  const nodeMap = {};
  const centerX = canvas.width / 2;
  const centerY = canvas.height / 2;
  const radius = Math.min(canvas.width, canvas.height) * 0.35;
  nodes.forEach((node, i) => {
    const angle = (2 * Math.PI * i) / nodes.length;
    node.x = centerX + radius * Math.cos(angle);
    node.y = centerY + radius * Math.sin(angle);
    nodeMap[node.id || node.label] = node;
  });
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  edges.forEach(edge => {
    const source = nodeMap[edge.source];
    const target = nodeMap[edge.target];
    if (source && target) {
      ctx.beginPath(); ctx.moveTo(source.x, source.y); ctx.lineTo(target.x, target.y);
      ctx.strokeStyle = "rgba(255, 122, 26, 0.3)"; ctx.lineWidth = 1; ctx.stroke();
    }
  });
  nodes.forEach(node => {
    ctx.beginPath(); ctx.arc(node.x, node.y, 6, 0, 2 * Math.PI);
    ctx.fillStyle = "#ff7a1a"; ctx.fill();
    ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--text").trim() || "#f0f0f0";
    ctx.font = "11px sans-serif"; ctx.textAlign = "center";
    ctx.fillText(node.label || node.id, node.x, node.y - 12);
  });
}

async function generateGraph() {
  const btn = document.getElementById("generate-graph-btn");
  btn.textContent = "Generating..."; btn.disabled = true;
  try {
    const res = await fetch("/api/graph/generate", { method: "POST" });
    const data = await res.json();
    if (data.status === "completed") await loadGraph();
    else alert("Graph generation failed: " + (data.error || data.stderr?.slice(-200)));
  } catch (err) { alert("Error: " + err.message); }
  btn.textContent = "Generate"; btn.disabled = false;
}

async function showProjects() {
  document.getElementById("projects-modal").classList.add("active");
  closeSidebar();
  loadProjects();
}

function closeProjects() { document.getElementById("projects-modal").classList.remove("active"); }

function showNewProjectForm() { document.getElementById("new-project-form").style.display = "block"; }

async function loadProjects() {
  const res = await fetch("/api/projects");
  const projects = await res.json();
  const list = document.getElementById("projects-list");
  if (!projects.length) { list.innerHTML = '<p class="muted">No projects tracked yet</p>'; return; }
  list.innerHTML = projects.map(p => `
    <div class="data-card">
      <div class="data-card-header">
        <span class="data-card-title">${escapeHtml(p.name)}</span>
        <span class="status-badge status-${p.status}">${p.status}</span>
      </div>
      <p class="muted">${escapeHtml(p.description || "")}</p>
      ${p.blockers && p.blockers.length ? `<p style="color:var(--danger)">Blockers: ${p.blockers.join(", ")}</p>` : ""}
      <div class="data-card-actions">
        <button class="btn-small" onclick="deleteProject('${p.id}')">Delete</button>
      </div>
    </div>
  `).join("");
}

async function createProject() {
  const name = document.getElementById("project-name").value.trim();
  const description = document.getElementById("project-desc").value.trim();
  const status = document.getElementById("project-status").value;
  if (!name) return;
  await fetch("/api/projects", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, description, status }),
  });
  document.getElementById("new-project-form").style.display = "none";
  loadProjects();
}

async function deleteProject(id) {
  await fetch(`/api/projects/${id}`, { method: "DELETE" });
  loadProjects();
}

async function showInventory() {
  document.getElementById("inventory-modal").classList.add("active");
  closeSidebar();
  loadInventory();
}

function closeInventory() { document.getElementById("inventory-modal").classList.remove("active"); }
function showNewItemForm() { document.getElementById("new-item-form").style.display = "block"; }

async function loadInventory() {
  const res = await fetch("/api/inventory");
  const items = await res.json();
  const list = document.getElementById("inventory-list");
  if (!items.length) { list.innerHTML = '<p class="muted">No inventory items</p>'; return; }
  list.innerHTML = items.map(i => `
    <div class="data-card">
      <div class="data-card-header">
        <span class="data-card-title">${escapeHtml(i.name)}</span>
        <span class="status-badge">Qty: ${i.quantity}</span>
      </div>
      <p class="muted">${escapeHtml(i.category || "")} · ${escapeHtml(i.location || "")} · ${escapeHtml(i.condition || "")}</p>
      <div class="data-card-actions">
        <button class="btn-small" onclick="deleteInventoryItem('${i.id}')">Delete</button>
      </div>
    </div>
  `).join("");
}

async function addItem() {
  const body = {
    name: document.getElementById("item-name").value.trim(),
    category: document.getElementById("item-category").value.trim(),
    quantity: parseInt(document.getElementById("item-qty").value) || 1,
    location: document.getElementById("item-location").value.trim(),
  };
  if (!body.name) return;
  await fetch("/api/inventory", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  document.getElementById("new-item-form").style.display = "none";
  loadInventory();
}

async function deleteInventoryItem(id) {
  await fetch(`/api/inventory/${id}`, { method: "DELETE" });
  loadInventory();
}

async function showCalendar() {
  document.getElementById("calendar-modal").classList.add("active");
  closeSidebar();
  loadCalendar();
}

function closeCalendar() { document.getElementById("calendar-modal").classList.remove("active"); }
function showNewEventForm() { document.getElementById("new-event-form").style.display = "block"; }

async function loadCalendar() {
  const res = await fetch("/api/calendar");
  const events = await res.json();
  const list = document.getElementById("calendar-list");
  if (!events.length) { list.innerHTML = '<p class="muted">No events scheduled</p>'; return; }
  list.innerHTML = events.map(e => `
    <div class="data-card">
      <div class="data-card-header">
        <span class="data-card-title">${escapeHtml(e.title)}</span>
        <span class="status-badge">${e.date || "No date"}</span>
      </div>
      <p class="muted">${escapeHtml(e.type || "")} · ${escapeHtml(e.location || "")}</p>
      <div class="data-card-actions">
        <button class="btn-small" onclick="deleteEvent('${e.id}')">Delete</button>
      </div>
    </div>
  `).join("");
}

async function createEvent() {
  const body = {
    title: document.getElementById("event-title").value.trim(),
    date: document.getElementById("event-date").value,
    location: document.getElementById("event-location").value.trim(),
    type: document.getElementById("event-type").value,
  };
  if (!body.title) return;
  await fetch("/api/calendar", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  document.getElementById("new-event-form").style.display = "none";
  loadCalendar();
}

async function deleteEvent(id) {
  await fetch(`/api/calendar/${id}`, { method: "DELETE" });
  loadCalendar();
}

async function showMembers() {
  document.getElementById("members-modal").classList.add("active");
  closeSidebar();
  loadMembers();
}

function closeMembers() { document.getElementById("members-modal").classList.remove("active"); }
function showNewMemberForm() { document.getElementById("new-member-form").style.display = "block"; }

async function loadMembers() {
  const res = await fetch("/api/members");
  const members = await res.json();
  const list = document.getElementById("members-list");
  if (!members.length) { list.innerHTML = '<p class="muted">No members registered</p>'; return; }
  list.innerHTML = members.map(m => `
    <div class="data-card">
      <div class="data-card-header">
        <span class="data-card-title">${escapeHtml(m.name)}</span>
        <span class="status-badge">${escapeHtml(m.role || "")}</span>
      </div>
      <p class="muted">${(m.expertise || []).map(e => `<span class="tag">${escapeHtml(e)}</span>`).join(" ")}</p>
      ${m.contact ? `<p class="muted">${escapeHtml(m.contact)}</p>` : ""}
      <div class="data-card-actions">
        <button class="btn-small" onclick="deleteMember('${m.id}')">Delete</button>
      </div>
    </div>
  `).join("");
}

async function addMember() {
  const body = {
    name: document.getElementById("member-name").value.trim(),
    role: document.getElementById("member-role").value.trim(),
    expertise: document.getElementById("member-expertise").value.split(",").map(e => e.trim()).filter(Boolean),
    contact: document.getElementById("member-contact").value.trim(),
  };
  if (!body.name) return;
  await fetch("/api/members", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  document.getElementById("new-member-form").style.display = "none";
  loadMembers();
}

async function deleteMember(id) {
  await fetch(`/api/members/${id}`, { method: "DELETE" });
  loadMembers();
}

async function showQA() {
  document.getElementById("qa-modal").classList.add("active");
  closeSidebar();
  loadQA();
}

function closeQA() { document.getElementById("qa-modal").classList.remove("active"); }
function showNewQuestionForm() { document.getElementById("new-question-form").style.display = "block"; }

async function loadQA() {
  const res = await fetch("/api/qa");
  const qa = await res.json();
  const list = document.getElementById("qa-list");
  if (!qa.length) { list.innerHTML = '<p class="muted">No questions yet</p>'; return; }
  list.innerHTML = qa.map(q => `
    <div class="data-card">
      <div class="data-card-header">
        <span class="data-card-title">${escapeHtml(q.question)}</span>
        <span class="status-badge status-${q.status}">${q.status}</span>
      </div>
      ${q.answer ? `<div style="white-space:pre-wrap;margin:8px 0">${renderMarkdown(q.answer)}</div>` : '<p class="muted">No answer yet</p>'}
      ${q.senior_correction ? `<div style="color:var(--warning);margin:8px 0"><strong>Senior correction:</strong> ${escapeHtml(q.senior_correction)}</div>` : ""}
      <p class="muted">Asked by ${escapeHtml(q.asked_by)} · ${formatDate(q.created)}</p>
    </div>
  `).join("");
}

async function postQuestion() {
  const body = {
    question: document.getElementById("qa-question").value.trim(),
    asked_by: document.getElementById("qa-asked-by").value.trim() || "anonymous",
  };
  if (!body.question) return;
  await fetch("/api/qa", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  document.getElementById("new-question-form").style.display = "none";
  loadQA();
}

async function showAnalytics() {
  document.getElementById("analytics-modal").classList.add("active");
  closeSidebar();
  loadAnalytics();
}

function closeAnalytics() { document.getElementById("analytics-modal").classList.remove("active"); }

async function loadAnalytics() {
  const res = await fetch("/api/analytics");
  const data = await res.json();
  const content = document.getElementById("analytics-content");
  content.innerHTML = `
    <div class="stats-grid">
      <div class="stat-card"><div class="stat-value">${data.total_queries}</div><div class="stat-label">Total Queries</div></div>
      <div class="stat-card"><div class="stat-value">${data.success_rate}%</div><div class="stat-label">Success Rate</div></div>
      <div class="stat-card"><div class="stat-value">${data.knowledge_gaps.length}</div><div class="stat-label">Knowledge Gaps</div></div>
    </div>
    ${data.alerts && data.alerts.length ? `<div style="margin:16px 0;padding:12px;background:rgba(251,191,36,0.1);border-radius:var(--radius-sm);border:1px solid var(--warning)"><h4 style="color:var(--warning)">⚠ Alerts</h4>${data.alerts.map(a => `<p>${escapeHtml(a)}</p>`).join("")}</div>` : ""}
    <h4 style="margin:16px 0 8px">Top Topics</h4>
    <div class="tag-cloud">${data.top_topics.map(t => `<span class="tag">${escapeHtml(t.topic)} (${t.count})</span>`).join("")}</div>
    <h4 style="margin:16px 0 8px">Recent Queries</h4>
    <div>${data.top_queries.map(q => `<p class="muted">${escapeHtml(q.query)} <span style="color:var(--text-muted);font-size:11px">${new Date(q.timestamp).toLocaleDateString()}</span></p>`).join("")}</div>
  `;
}

async function showGaps() {
  document.getElementById("gaps-modal").classList.add("active");
  closeSidebar();
  loadGaps();
}

function closeGaps() { document.getElementById("gaps-modal").classList.remove("active"); }

async function loadGaps() {
  const res = await fetch("/api/gaps");
  const gaps = await res.json();
  const content = document.getElementById("gaps-content");
  if (!gaps.length) { content.innerHTML = '<p class="muted">No knowledge gaps detected</p>'; return; }
  content.innerHTML = gaps.sort((a, b) => (b.count || 1) - (a.count || 1)).map(g => `
    <div class="data-card">
      <div class="data-card-header">
        <span class="data-card-title">${escapeHtml(g.query)}</span>
        <span class="status-badge">${g.count || 1} asks</span>
      </div>
      <p class="muted">First asked: ${formatDate(g.first_asked)} · Last asked: ${formatDate(g.last_asked)}</p>
    </div>
  `).join("");
}

async function showFreshness() {
  document.getElementById("freshness-modal").classList.add("active");
  closeSidebar();
  loadFreshness();
}

function closeFreshness() { document.getElementById("freshness-modal").classList.remove("active"); }

async function loadFreshness() {
  const res = await fetch("/api/knowledge/freshness", { method: "POST" });
  const data = await res.json();
  const content = document.getElementById("freshness-content");
  content.innerHTML = `
    <div class="stats-grid">
      <div class="stat-card"><div class="stat-value" style="color:var(--success)">${data.fresh.length}</div><div class="stat-label">Fresh (< 90 days)</div></div>
      <div class="stat-card"><div class="stat-value" style="color:var(--warning)">${data.stale.length}</div><div class="stat-label">Stale (90-180 days)</div></div>
      <div class="stat-card"><div class="stat-value" style="color:var(--danger)">${data.outdated.length}</div><div class="stat-label">Outdated (> 180 days)</div></div>
    </div>
    ${data.outdated.length ? `<h4 style="margin:16px 0 8px;color:var(--danger)">Outdated Documents</h4>${data.outdated.map(f => `<p class="muted">${escapeHtml(f.path)} — ${f.age_days} days old</p>`).join("")}` : ""}
    ${data.stale.length ? `<h4 style="margin:16px 0 8px;color:var(--warning)">Stale Documents</h4>${data.stale.map(f => `<p class="muted">${escapeHtml(f.path)} — ${f.age_days} days old</p>`).join("")}` : ""}
  `;
}

async function showAudit() {
  document.getElementById("audit-modal").classList.add("active");
  closeSidebar();
  loadAudit();
}

function closeAudit() { document.getElementById("audit-modal").classList.remove("active"); }

async function loadAudit() {
  const res = await fetch("/api/audit");
  const data = await res.json();
  const content = document.getElementById("audit-content");
  content.innerHTML = `
    <div class="stats-grid">
      <div class="stat-card"><div class="stat-value">${data.total_documents}</div><div class="stat-label">Total Documents</div></div>
      <div class="stat-card"><div class="stat-value" style="color:var(--warning)">${data.stale_documents.length}</div><div class="stat-label">Stale Documents</div></div>
      <div class="stat-card"><div class="stat-value" style="color:var(--danger)">${data.knowledge_gaps.length}</div><div class="stat-label">Knowledge Gaps</div></div>
    </div>
    ${data.high_demand_gaps.length ? `<h4 style="margin:16px 0 8px;color:var(--danger)">High-Demand Gaps</h4>${data.high_demand_gaps.map(g => `<p class="muted">${escapeHtml(g.query)} — asked ${g.count} times</p>`).join("")}` : ""}
    <p class="muted" style="margin-top:16px">Audit completed: ${formatDate(data.audit_date)}</p>
  `;
}

async function showStateReport() {
  document.getElementById("state-report-modal").classList.add("active");
  closeSidebar();
  loadStateReport();
}

function closeStateReport() { document.getElementById("state-report-modal").classList.remove("active"); }

async function loadStateReport() {
  const content = document.getElementById("state-report-content");
  content.innerHTML = '<p class="muted">Generating report...</p>';
  try {
    const res = await fetch("/api/reports/state");
    const data = await res.json();
    content.innerHTML = `
      <div class="stats-grid">
        <div class="stat-card"><div class="stat-value">${data.stats.documents}</div><div class="stat-label">Documents</div></div>
        <div class="stat-card"><div class="stat-value">${data.stats.projects}</div><div class="stat-label">Projects</div></div>
        <div class="stat-card"><div class="stat-value">${data.stats.members}</div><div class="stat-label">Members</div></div>
        <div class="stat-card"><div class="stat-value">${data.stats.queries}</div><div class="stat-label">Queries</div></div>
      </div>
      <div style="white-space:pre-wrap;margin-top:16px">${renderMarkdown(data.report)}</div>
      <p class="muted" style="margin-top:16px">Generated: ${formatDate(data.generated)}</p>
    `;
  } catch (err) {
    content.innerHTML = `<p style="color:var(--danger)">Error: ${escapeHtml(err.message)}</p>`;
  }
}

async function exportKB() {
  try {
    const res = await fetch("/api/knowledge/export", { method: "POST" });
    const data = await res.json();
    alert(`Knowledge base exported. ID: ${data.export_id}`);
  } catch (err) { alert("Export failed: " + err.message); }
}

async function showTemplates() {
  document.getElementById("templates-modal").classList.add("active");
  closeSidebar();
  loadTemplates();
}

function closeTemplates() { document.getElementById("templates-modal").classList.remove("active"); }
function showNewTemplateForm() { document.getElementById("new-template-form").style.display = "block"; }

async function loadTemplates() {
  const res = await fetch("/api/templates");
  const templates = await res.json();
  const list = document.getElementById("templates-list");
  if (!templates.length) { list.innerHTML = '<p class="muted">No templates yet</p>'; return; }
  list.innerHTML = templates.map(t => `
    <div class="data-card">
      <div class="data-card-header"><span class="data-card-title">${escapeHtml(t.name)}</span></div>
      <pre style="white-space:pre-wrap;font-size:12px;color:var(--text-secondary)">${escapeHtml(t.content)}</pre>
    </div>
  `).join("");
}

async function createTemplate() {
  const body = {
    name: document.getElementById("template-name").value.trim(),
    content: document.getElementById("template-content").value.trim(),
  };
  if (!body.name) return;
  await fetch("/api/templates", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  document.getElementById("new-template-form").style.display = "none";
  loadTemplates();
}

async function reindexKnowledge() {
  const status = document.getElementById("status-indicator");
  status.textContent = "Reindexing...";
  try {
    const res = await fetch("/api/reindex", { method: "POST" });
    const result = await res.json();
    status.textContent = `Indexed ${result.files_indexed} files`;
    loadKnowledge();
  } catch { status.textContent = "Reindex failed"; }
  setTimeout(() => checkHealth(), 2000);
  closeSidebar();
}

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

document.getElementById("theme-toggle").addEventListener("click", () => {
  theme = theme === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("avinya-theme", theme);
});

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function scrollToBottom() {
  const container = document.getElementById("chat-container");
  container.scrollTop = container.scrollHeight;
}

function initVoice() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) return;

  voiceRecognition = new SpeechRecognition();
  voiceRecognition.continuous = false;
  voiceRecognition.interimResults = true;
  voiceRecognition.lang = "en-IN";

  voiceRecognition.onresult = (event) => {
    let finalTranscript = "";
    let interimTranscript = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const transcript = event.results[i][0].transcript;
      if (event.results[i].isFinal) {
        finalTranscript += transcript;
      } else {
        interimTranscript += transcript;
      }
    }
    const statusText = document.getElementById("voice-status-text");
    if (interimTranscript) {
      statusText.textContent = interimTranscript;
    }
    if (finalTranscript.trim()) {
      document.getElementById("input-box").value = finalTranscript.trim();
      stopVoice();
      sendMessage();
    }
  };

  voiceRecognition.onerror = () => stopVoice();
  voiceRecognition.onend = () => { if (isVoiceActive) stopVoice(); };
}

function toggleVoice() {
  if (isVoiceActive) {
    stopVoice();
  } else {
    startVoice();
  }
}

function startVoice() {
  if (!voiceRecognition || isVoiceActive) return;
  voiceSynth?.cancel();
  isVoiceActive = true;
  const statusEl = document.getElementById("voice-status");
  const statusText = document.getElementById("voice-status-text");
  const voiceBtn = document.getElementById("voice-btn");
  statusEl.style.display = "flex";
  statusText.textContent = "Listening...";
  voiceBtn.classList.add("listening");
  try { voiceRecognition.start(); } catch (e) { stopVoice(); }
}

function stopVoice() {
  isVoiceActive = false;
  const statusEl = document.getElementById("voice-status");
  const voiceBtn = document.getElementById("voice-btn");
  statusEl.style.display = "none";
  voiceBtn.classList.remove("listening");
  try { voiceRecognition?.stop(); } catch {}
}

function speakText(text) {
  if (!voiceSynth) return;
  voiceSynth.cancel();
  const clean = text
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/#{1,6}\s*/g, "")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/\n{2,}/g, ". ")
    .replace(/\n/g, ". ")
    .replace(/e\.g\.,/g, "for example,")
    .replace(/i\.e\.,/g, "that is,")
    .replace(/etc\./g, "and so on.")
    .replace(/vs\./g, "versus")
    .replace(/(\d+)%/g, "$1 percent")
    .replace(/\s+/g, " ")
    .trim();
  if (!clean) return;
  const utterance = new SpeechSynthesisUtterance(clean);
  utterance.lang = "en-IN";
  utterance.rate = 1.0;
  voiceSynth.speak(utterance);
}
