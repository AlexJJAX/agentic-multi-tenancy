const loginShell = document.querySelector("#login-shell");
const workspace = document.querySelector("#workspace");
const loginForm = document.querySelector("#login-form");
const chatForm = document.querySelector("#chat-form");
const messages = document.querySelector("#messages");
const sessionsNode = document.querySelector("#sessions");
const statusNode = document.querySelector("#chat-status");
const sendButton = document.querySelector("#send");
const usernameSelect = document.querySelector("#username");
const passwordInput = document.querySelector("#password");
const initialStatus = "Tenant scope comes from your signed session—not this message.";
const initialMessage =
  "Ask about your tenant’s policy, an order record, or a visible property. Your verified account sets the data boundary.";
const tenantPlaceholderMessages = Object.freeze({
  "tenant-A":
    "Hi there! I’m your payment and product support assistant. Ask me a payment- or product-related question to get started, for example: ‘Can I pay with PayPal?’ or ‘What is your return policy?’",
  "tenant-B":
    "Hi there! I’m your device support assistant. Ask me a device-related question to get started, for example: ‘How do I perform a soft reset on my device?’",
});
const demoPasswords = Object.freeze({
  "alice@tenant-a.demo": "alice-demo",
  "carol@tenant-a.demo": "carol-demo",
  "bob@tenant-b.demo": "bob-demo",
  "jake@tenant-b.demo": "jake-demo",
});
let currentSession = null;
let pendingDeleteSession = null;
let deleteConfirmationTimer = null;
let currentIdentity = null;

function resetTrustRail() {
  document
    .querySelectorAll("#trust-rail li")
    .forEach((node) => node.classList.remove("active"));
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  if (response.status === 204) return null;
  return response.json();
}

function scopeView(identity = currentIdentity) {
  if (!identity) {
    return {
      badge: "Scope pending",
      detail: "Session scope is established by verified identity.",
    };
  }
  const shortUser = identity.username.split("@")[0];
  return {
    badge: `${identity.tenant_id} · ${shortUser}`,
    detail: `Scoped to ${identity.tenant_id} / ${identity.username} — no other user or tenant can read this.`,
  };
}

function setIdentity(identity) {
  currentIdentity = identity;
  const scope = scopeView(identity);
  document.querySelector("#identity-name").textContent = identity.username;
  document.querySelector("#identity-tenant").textContent = identity.tenant_id;
  const activeScope = document.querySelector("#active-session-scope");
  activeScope.textContent = scope.badge;
  activeScope.title = scope.detail;
  activeScope.setAttribute("aria-label", `Active session. ${scope.detail}`);
  loginShell.hidden = true;
  workspace.hidden = false;
  if (!currentSession) showTenantPlaceholder();
}

function resetWorkspaceState() {
  clearDeleteConfirmation();
  currentSession = null;
  currentIdentity = null;
  messages.replaceChildren();
  sessionsNode.replaceChildren();
  addMessage("assistant", initialMessage);
  document.querySelector("#conversation-title").textContent = "New conversation";
  document.querySelector("#identity-name").textContent = "";
  document.querySelector("#identity-tenant").textContent = "";
  const activeScope = document.querySelector("#active-session-scope");
  activeScope.textContent = "Scope pending";
  activeScope.removeAttribute("title");
  activeScope.removeAttribute("aria-label");
  document.querySelector("#message-input").value = "";
  document.querySelector("#trace-request").textContent = "—";
  document.querySelector("#trace-tools").textContent = "None";
  document.querySelector("#trace-sources").textContent = "None";
  resetTrustRail();
  sendButton.disabled = false;
  statusNode.textContent = initialStatus;
}

function sourceView(source, index) {
  if (source.type === "document") {
    const context = [];
    if (typeof source.section === "string" && source.section) {
      context.push(source.section);
    }
    if (Number.isInteger(source.chunk_index)) {
      context.push(`Chunk ${source.chunk_index + 1}`);
    }
    return {
      kind: "document",
      label: "Tenant document",
      title: typeof source.source === "string" ? source.source : `Document ${index + 1}`,
      context: context.join(" · "),
      excerpt: typeof source.excerpt === "string" ? source.excerpt : "",
    };
  }

  if (source.type === "tool") {
    const recordIds = Array.isArray(source.record_ids)
      ? source.record_ids.filter((recordId) => typeof recordId === "string")
      : [];
    return {
      kind: "tool",
      label: "MCP tool result",
      title: typeof source.name === "string" ? source.name : `Tool result ${index + 1}`,
      context: recordIds.length
        ? `Records ${recordIds.join(", ")}`
        : "Tenant-scoped tool response",
      excerpt: "",
    };
  }

  return {
    kind: "other",
    label: "Supporting source",
    title: `Source ${index + 1}`,
    context: "",
    excerpt: "",
  };
}

function renderSources(article, sources) {
  article.querySelector(".message-sources")?.remove();
  const safeSources = Array.isArray(sources)
    ? sources.filter((source) => source && typeof source === "object")
    : [];
  if (!safeSources.length) return;

  const panel = document.createElement("details");
  panel.className = "message-sources";
  panel.open = true;

  const summary = document.createElement("summary");
  summary.className = "sources-summary";
  const summaryCopy = document.createElement("span");
  summaryCopy.className = "sources-summary-copy";
  const title = document.createElement("span");
  title.className = "sources-title";
  title.textContent = "Sources";
  const count = document.createElement("span");
  count.className = "sources-count";
  count.textContent = `${safeSources.length} ${safeSources.length === 1 ? "reference" : "references"}`;
  const action = document.createElement("span");
  action.className = "sources-action";
  action.setAttribute("aria-hidden", "true");
  summaryCopy.append(title, count);
  summary.append(summaryCopy, action);

  const list = document.createElement("div");
  list.className = "sources-list";
  safeSources.forEach((source, index) => {
    const view = sourceView(source, index);
    const reference = document.createElement("div");
    reference.className = `source-reference source-${view.kind}`;
    const kind = document.createElement("span");
    kind.className = "source-kind";
    kind.textContent = view.label;
    const name = document.createElement("strong");
    name.className = "source-name";
    name.textContent = view.title;
    reference.append(kind, name);
    if (view.context) {
      const context = document.createElement("span");
      context.className = "source-context";
      context.textContent = view.context;
      reference.append(context);
    }
    if (view.excerpt) {
      const excerpt = document.createElement("p");
      excerpt.className = "source-excerpt";
      excerpt.textContent = view.excerpt;
      reference.append(excerpt);
    }
    list.append(reference);
  });

  panel.append(summary, list);
  article.append(panel);
}

function historySources(item) {
  if (item.role !== "assistant" || typeof item.metadata_json !== "string") return [];
  try {
    const metadata = JSON.parse(item.metadata_json);
    return Array.isArray(metadata.sources) ? metadata.sources : [];
  } catch (_) {
    return [];
  }
}

function addMessage(role, text, sources = []) {
  const article = document.createElement("article");
  article.className = `message ${role}`;
  const speaker = document.createElement("span");
  speaker.className = "speaker";
  speaker.textContent = role === "user" ? "You" : "Assistant";
  const content = document.createElement("p");
  content.textContent = text;
  article.append(speaker, content);
  renderSources(article, sources);
  messages.append(article);
  article.scrollIntoView({ behavior: "smooth", block: "end" });
  return content;
}

function showTenantPlaceholder() {
  messages.replaceChildren();
  addMessage(
    "assistant",
    tenantPlaceholderMessages[currentIdentity?.tenant_id] || initialMessage,
  );
}

async function streamChat(payload, onEvent) {
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() || "";
    for (const frame of frames) {
      let eventName = "message";
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (data) onEvent(eventName, JSON.parse(data));
    }
    if (done) break;
  }
}

async function createSession() {
  const session = await api("/api/sessions", { method: "POST", body: "{}" });
  currentSession = session.session_id;
  document.querySelector("#conversation-title").textContent = "New conversation";
  await loadSessions();
  showTenantPlaceholder();
}

async function loadSessions() {
  const sessions = await api("/api/sessions");
  const scope = scopeView();
  sessionsNode.replaceChildren();
  if (!sessions.length) {
    const emptyState = document.createElement("p");
    emptyState.className = "session-empty";
    emptyState.textContent = "No saved sessions.";
    sessionsNode.append(emptyState);
    return;
  }
  for (const session of sessions) {
    const item = document.createElement("div");
    item.className = "session-item";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "session-link";
    button.textContent = session.title || "New conversation";
    if (session.session_id === currentSession) {
      button.setAttribute("aria-current", "page");
      item.classList.add("current");
    }
    button.addEventListener("click", () => openSession(session));

    const scopeBadge = document.createElement("span");
    scopeBadge.className = "scope-envelope session-scope";
    scopeBadge.textContent = scope.badge;
    scopeBadge.title = scope.detail;
    scopeBadge.setAttribute("aria-label", scope.detail);
    item.title = scope.detail;

    const deleteButton = document.createElement("button");
    const title = session.title || "New conversation";
    const isConfirming = pendingDeleteSession === session.session_id;
    deleteButton.type = "button";
    deleteButton.className = `session-delete${isConfirming ? " confirming" : ""}`;
    deleteButton.textContent = isConfirming ? "Confirm" : "Delete";
    deleteButton.setAttribute(
      "aria-label",
      isConfirming ? `Confirm deletion of ${title}` : `Delete ${title}`,
    );
    deleteButton.addEventListener("click", () => {
      void handleSessionDelete(session, deleteButton);
    });
    item.append(button, scopeBadge, deleteButton);
    sessionsNode.append(item);
  }
}

async function openSession(session) {
  clearDeleteConfirmation();
  currentSession = session.session_id;
  document.querySelector("#conversation-title").textContent = session.title || "Conversation";
  const history = await api(`/api/sessions/${session.session_id}/messages`);
  messages.replaceChildren();
  for (const item of history) {
    addMessage(item.role, item.content, historySources(item));
  }
  await loadSessions();
}

function clearDeleteConfirmation() {
  if (deleteConfirmationTimer) clearTimeout(deleteConfirmationTimer);
  pendingDeleteSession = null;
  deleteConfirmationTimer = null;
}

async function handleSessionDelete(session, deleteButton) {
  if (sendButton.disabled && session.session_id === currentSession) {
    statusNode.textContent = "Wait for the current response before deleting this conversation.";
    return;
  }
  if (pendingDeleteSession !== session.session_id) {
    clearDeleteConfirmation();
    pendingDeleteSession = session.session_id;
    statusNode.textContent = "Select Confirm to permanently delete this conversation.";
    await loadSessions();
    sessionsNode.querySelector(".session-delete.confirming")?.focus();
    deleteConfirmationTimer = setTimeout(() => {
      pendingDeleteSession = null;
      deleteConfirmationTimer = null;
      statusNode.textContent = initialStatus;
      void loadSessions();
    }, 15000);
    return;
  }

  clearDeleteConfirmation();
  deleteButton.disabled = true;
  deleteButton.textContent = "Deleting…";
  try {
    await api(`/api/sessions/${encodeURIComponent(session.session_id)}`, {
      method: "DELETE",
    });
    if (session.session_id === currentSession) {
      currentSession = null;
      document.querySelector("#trace-request").textContent = "—";
      document.querySelector("#trace-tools").textContent = "None";
      document.querySelector("#trace-sources").textContent = "None";
      resetTrustRail();
      const remaining = await api("/api/sessions");
      if (remaining.length) {
        await openSession(remaining[0]);
      } else {
        await loadSessions();
        document.querySelector("#conversation-title").textContent = "New conversation";
        showTenantPlaceholder();
        document.querySelector("#message-input").focus();
      }
    } else {
      await loadSessions();
    }
    statusNode.textContent = "Conversation deleted.";
  } catch (exception) {
    deleteButton.disabled = false;
    deleteButton.textContent = "Delete";
    statusNode.textContent = `Conversation was not deleted. ${exception.message}`;
    await loadSessions();
  }
}

function updateTrace(trace, sources) {
  document.querySelector("#trace-request").textContent = trace.request_id.slice(0, 13) + "…";
  document.querySelector("#trace-tools").textContent = trace.tools.join(", ") || "None";
  document.querySelector("#trace-sources").textContent = String(sources.length);
  document.querySelectorAll("#trust-rail li").forEach((node) => node.classList.add("active"));
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const error = document.querySelector("#login-error");
  error.textContent = "";
  try {
    const payload = Object.fromEntries(new FormData(loginForm));
    const result = await api("/auth/login", { method: "POST", body: JSON.stringify(payload) });
    resetWorkspaceState();
    setIdentity(result.identity);
    await createSession();
    document.querySelector("#message-input").focus();
  } catch (exception) {
    error.textContent = exception.message;
  }
});

function fillDemoPassword() {
  passwordInput.value = demoPasswords[usernameSelect.value] || "";
}

usernameSelect.addEventListener("change", fillDemoPassword);
fillDemoPassword();

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = document.querySelector("#message-input");
  const message = input.value.trim();
  if (!message) return;
  if (!currentSession) await createSession();
  resetTrustRail();
  addMessage("user", message);
  input.value = "";
  sendButton.disabled = true;
  statusNode.textContent = "Following the tenant-scoped route…";
  const assistantContent = addMessage("assistant", "");
  try {
    await streamChat({ session_id: currentSession, message }, (eventName, data) => {
      if (eventName === "phase") {
        statusNode.textContent = data.label;
        const node = document.querySelector(`#trust-rail li[data-node="${data.node}"]`);
        if (node) node.classList.add("active");
      } else if (eventName === "token") {
        assistantContent.textContent += data;
        assistantContent.parentElement.scrollIntoView({ behavior: "smooth", block: "end" });
      } else if (eventName === "done") {
        const sources = Array.isArray(data.sources) ? data.sources : [];
        renderSources(assistantContent.parentElement, sources);
        updateTrace(data.trace, sources);
        assistantContent.parentElement.scrollIntoView({ behavior: "smooth", block: "end" });
        statusNode.textContent = "Complete. Credentials and internal context were not exposed.";
      } else if (eventName === "error") {
        throw new Error(data);
      }
    });
    await loadSessions();
  } catch (exception) {
    assistantContent.textContent = exception.message;
    statusNode.textContent = "The request stopped safely. Check the message and retry.";
  } finally {
    sendButton.disabled = false;
    input.focus();
  }
});

document.querySelector("#new-chat").addEventListener("click", async () => {
  clearDeleteConfirmation();
  await createSession();
});

document.querySelector("#logout").addEventListener("click", async () => {
  workspace.hidden = true;
  resetWorkspaceState();
  loginShell.hidden = false;
  try {
    await api("/auth/logout", { method: "POST", body: "{}" });
  } catch (exception) {
    document.querySelector("#login-error").textContent =
      "Sign-out could not be confirmed. Reload before signing in again.";
  }
});

(async () => {
  try {
    const identity = await api("/api/me");
    setIdentity(identity);
    const sessions = await api("/api/sessions");
    if (sessions.length) await openSession(sessions[0]);
    else await createSession();
  } catch (_) {
    resetWorkspaceState();
    loginShell.hidden = false;
    workspace.hidden = true;
  }
})();
