/**
 * Multi-Tenant RAG Chatbot — Client-Side JavaScript
 *
 * Handles JWT authentication, tenant loading, chat messaging,
 * session management, source rendering, and error display.
 * Pure vanilla JS — no external dependencies.
 */

// ──────────────────────────────────────────────
// State
// ──────────────────────────────────────────────

const state = {
    tenants: [],
    sessions: [],
    selectedTenantId: null,
    sessionId: null,
    isLoading: false,
    deletingSessionId: null,
    pendingDeleteSessionId: null,
    deleteConfirmationTimer: null,
    token: null,          // JWT access token (from sessionStorage)
    username: null,       // Logged-in username (for display only)
    role: null,           // "user" or "admin" from the signed JWT response
};

// ──────────────────────────────────────────────
// DOM Elements
// ──────────────────────────────────────────────

const tenantSelect = document.getElementById('tenant-select');
const sessionInfo = document.getElementById('session-info');
const sessionList = document.getElementById('session-list');
const tenantInfo = document.getElementById('tenant-info');
const chatMessages = document.getElementById('chat-messages');
const messageInput = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');
const charCount = document.getElementById('char-count');
const loadingIndicator = document.getElementById('loading-indicator');
const errorDisplay = document.getElementById('error-display');
const errorText = document.getElementById('error-text');
const errorDismiss = document.getElementById('error-dismiss');
const newSessionBtn = document.getElementById('new-session-btn');
const reindexBtn = document.getElementById('reindex-btn');
const logoutBtn = document.getElementById('logout-btn');
const authUserBadge = document.getElementById('auth-user-badge');
const adminTenantSection = document.getElementById('admin-tenant-section');
const adminTenantButtons = document.querySelectorAll('.admin-tenant-btn');
const sessionLabel = document.getElementById('session-label');
const savedSessionsLabel = document.getElementById('saved-sessions-label');
const inputWrapper = document.querySelector('.input-wrapper');
const inputFooter = document.querySelector('.input-footer');
const adminReadonlyNote = document.getElementById('admin-readonly-note');

// Login modal elements
const loginOverlay = document.getElementById('login-overlay');
const loginForm = document.getElementById('login-form');
const loginUsernameInput = document.getElementById('login-username');
const loginPasswordInput = document.getElementById('login-password');
const loginError = document.getElementById('login-error');
const loginSubmitBtn = document.getElementById('login-submit-btn');

// ──────────────────────────────────────────────
// JWT Token Helpers
// ──────────────────────────────────────────────

/**
 * Persist the JWT and associated metadata in sessionStorage.
 * sessionStorage is cleared automatically when the browser tab closes.
 * @param {string} token - The JWT access token
 * @param {string} tenantId - The tenant_id from the token response
 * @param {string} username - The username for display
 * @param {string} role - The authenticated account role
 */
function storeToken(token, tenantId, username, role) {
    sessionStorage.setItem('jwt_token', token);
    sessionStorage.setItem('jwt_tenant_id', tenantId);
    sessionStorage.setItem('jwt_username', username);
    sessionStorage.setItem('jwt_role', role);
    state.token = token;
    state.username = username;
    state.role = role;
}

/**
 * Read the role from an older stored token that predates jwt_role storage.
 * This controls presentation only; every admin API still verifies the JWT.
 * @param {string} token - JWT access token
 * @returns {string} Role claim or "user"
 */
function getStoredTokenRole(token) {
    try {
        const encodedPayload = token.split('.')[1];
        const normalized = encodedPayload.replace(/-/g, '+').replace(/_/g, '/');
        const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=');
        return JSON.parse(atob(padded)).role || 'user';
    } catch {
        return 'user';
    }
}

function isAdmin() {
    return state.role === 'admin';
}

/**
 * Load a stored JWT from sessionStorage into the app state.
 * @returns {boolean} True if a valid token was found.
 */
function loadStoredToken() {
    const token = sessionStorage.getItem('jwt_token');
    const tenantId = sessionStorage.getItem('jwt_tenant_id');
    const username = sessionStorage.getItem('jwt_username');
    const role = sessionStorage.getItem('jwt_role');
    if (token && tenantId) {
        state.token = token;
        state.username = username;
        state.role = role || getStoredTokenRole(token);
        return true;
    }
    return false;
}

/**
 * Clear the JWT and reset auth state.
 */
function clearToken() {
    sessionStorage.removeItem('jwt_token');
    sessionStorage.removeItem('jwt_tenant_id');
    sessionStorage.removeItem('jwt_username');
    sessionStorage.removeItem('jwt_role');
    state.token = null;
    state.username = null;
    state.role = null;
}

// ──────────────────────────────────────────────
// API Helpers
// ──────────────────────────────────────────────

/**
 * Build default headers, injecting the JWT Bearer token when available.
 * @returns {object} Headers object for fetch.
 */
function buildHeaders() {
    const headers = { 'Content-Type': 'application/json' };
    if (state.token) {
        headers['Authorization'] = `Bearer ${state.token}`;
    }
    return headers;
}

/**
 * Make an API request and return parsed JSON.
 * Automatically shows the login modal on 401 responses.
 * @param {string} url - API endpoint URL
 * @param {object} options - fetch options
 * @returns {Promise<object>} Parsed response
 */
async function apiRequest(url, options = {}) {
    const response = await fetch(url, {
        headers: buildHeaders(),
        ...options,
    });

    if (response.status === 401) {
        // Token expired or missing — force re-login
        clearToken();
        showLoginModal('Your session has expired. Please sign in again.');
        throw new Error('Session expired. Please sign in again.');
    }

    const data = await response.json();

    if (!response.ok) {
        throw new Error(data.detail || `Request failed (${response.status})`);
    }

    return data;
}

/**
 * Apply account-specific controls after login or restored authentication.
 * Admin browsing is read-only; tenant users retain the normal chat controls.
 */
function configureAccountUI() {
    const admin = isAdmin();

    adminTenantSection.classList.toggle('hidden', !admin);
    newSessionBtn.classList.toggle('hidden', admin);
    reindexBtn.classList.toggle('hidden', !admin);
    adminReadonlyNote.classList.toggle('hidden', !admin);
    inputWrapper.classList.toggle('hidden', admin);
    inputFooter.classList.toggle('hidden', admin);
    sessionLabel.textContent = admin ? 'Selected Session' : 'Current Session';
    savedSessionsLabel.textContent = admin ? 'Tenant Sessions' : 'Saved Sessions';
    messageInput.disabled = admin || state.isLoading;

    if (!admin) {
        adminTenantButtons.forEach((button) => {
            button.classList.remove('active');
            button.setAttribute('aria-pressed', 'false');
        });
    }

    updateSendButton();
}

/** Update the header identity marker for the authenticated account type. */
function updateAuthBadge() {
    const icon = isAdmin() ? '🛡️' : '👤';
    authUserBadge.textContent = `${icon} ${state.username || 'user'}`;
    authUserBadge.classList.toggle('admin', isAdmin());
    authUserBadge.classList.remove('hidden');
}

// ──────────────────────────────────────────────
// Tenant Management
// ──────────────────────────────────────────────

/**
 * Load available tenants from the API and populate the selector.
 * After loading, auto-selects the JWT-bound tenant so the user
 * cannot switch to a different tenant from the UI.
 */
async function loadTenants() {
    try {
        const data = await apiRequest('/api/tenants');
        state.tenants = data.tenants;
        configureAccountUI();

        // Populate the tenant selector (if present)
        if (tenantSelect) {
            tenantSelect.innerHTML = '';
            state.tenants.forEach((tenant) => {
                const option = document.createElement('option');
                option.value = tenant.tenant_id;
                option.textContent = tenant.tenant_name;
                tenantSelect.appendChild(option);
            });
        }

        if (isAdmin()) {
            initializeAdminWorkspace();
            return;
        }

        // Auto-select the tenant that matches the JWT claim
        const jwtTenantId = sessionStorage.getItem('jwt_tenant_id');
        const targetTenantId = jwtTenantId || (state.tenants[0]?.tenant_id);

        if (targetTenantId) {
            if (tenantSelect) tenantSelect.value = targetTenantId;
            selectTenant(targetTenantId);
            await loadSessions();
        }

        // Lock the selector — the JWT controls which tenant is active
        if (tenantSelect) {
            tenantSelect.disabled = true;
            tenantSelect.title = 'Tenant is determined by your login credentials';
        }
    } catch (error) {
        if (!error.message.includes('expired')) {
            showError('Failed to load tenants: ' + error.message);
        }
    }
}

/** Reset the administrator workspace until a tenant is explicitly selected. */
function initializeAdminWorkspace() {
    state.selectedTenantId = null;
    state.sessionId = null;
    state.sessions = [];
    clearDeleteConfirmation(false);

    tenantInfo.innerHTML = `
        <div class="admin-account-card">
            <span class="admin-account-kicker">Privileged account</span>
            <div class="tenant-info-name">Administrator</div>
            <div class="tenant-info-meta">Cross-tenant session visibility</div>
        </div>
    `;
    sessionInfo.innerHTML = '<span class="session-placeholder">Select a tenant first</span>';
    renderSessionList('Choose Tenant A or Tenant B');
    syncAdminTenantButtons();
    clearChat();
    updateSendButton();
}

/**
 * Select the tenant whose sessions the administrator wants to inspect.
 * @param {string} tenantId - Tenant selected by the administrator
 */
async function selectAdminTenant(tenantId) {
    if (!isAdmin()) return;

    const tenant = state.tenants.find((item) => item.tenant_id === tenantId);
    if (!tenant) {
        showError('That tenant is not available.');
        return;
    }

    clearDeleteConfirmation(false);
    state.selectedTenantId = tenantId;
    state.sessionId = null;
    state.sessions = [];
    syncAdminTenantButtons();

    tenantInfo.innerHTML = `
        <div class="admin-account-card">
            <span class="admin-account-kicker">Admin viewing</span>
            <div class="tenant-info-name">${escapeHtml(tenant.tenant_name)}</div>
            <div class="tenant-info-meta">Read-only tenant session access</div>
        </div>
    `;
    sessionInfo.innerHTML = '<span class="session-placeholder">Choose a saved session</span>';
    renderSessionList('Loading tenant sessions...');
    clearChat();
    updateSendButton();
    await loadSessions();
}

/** Keep the persistent admin tenant controls and current scope in sync. */
function syncAdminTenantButtons() {
    adminTenantButtons.forEach((button) => {
        const active = button.dataset.tenantId === state.selectedTenantId;
        button.classList.toggle('active', active);
        button.setAttribute('aria-pressed', String(active));
    });
}

/**
 * Handle tenant selection change.
 * @param {string} tenantId - The selected tenant ID
 */
function selectTenant(tenantId) {
    state.selectedTenantId = tenantId;
    state.sessionId = null; // Reset session on tenant change
    state.sessions = [];

    const tenant = state.tenants.find(t => t.tenant_id === tenantId);

    // Update tenant info display
    if (tenant) {
        const theme = tenant.metadata?.theme || 'blue';
        tenantInfo.innerHTML = `
            <div class="tenant-info-name" style="text-align:center">${escapeHtml(tenant.tenant_name)}</div>
        `;
    }

    // Reset session display
    sessionInfo.innerHTML = '<span class="session-placeholder">Session created on first message</span>';
    renderSessionList('Loading saved sessions...');

    // Clear chat messages and show welcome
    clearChat();

    // Update send button state
    updateSendButton();
}

// ──────────────────────────────────────────────
// Session Management
// ──────────────────────────────────────────────

/**
 * Render the authenticated tenant's saved sessions in the sidebar.
 * @param {string|null} placeholder - Optional status shown instead of the list.
 */
function renderSessionList(placeholder = null) {
    sessionList.replaceChildren();

    if (placeholder || state.sessions.length === 0) {
        const emptyState = document.createElement('span');
        emptyState.className = 'session-list-placeholder';
        emptyState.textContent = placeholder || 'No saved sessions yet';
        sessionList.appendChild(emptyState);
        return;
    }

    state.sessions.forEach((session) => {
        const card = document.createElement('div');
        const isActive = session.session_id === state.sessionId;
        card.className = `session-item${isActive ? ' active' : ''}`;
        card.dataset.sessionId = session.session_id;

        const openButton = document.createElement('button');
        openButton.type = 'button';
        openButton.className = 'session-open';
        openButton.title = `Open ${session.session_id}`;
        openButton.setAttribute('aria-label', `Open ${session.session_id}`);
        if (isActive) openButton.setAttribute('aria-current', 'true');

        const heading = document.createElement('span');
        heading.className = 'session-item-heading';

        const title = document.createElement('span');
        title.textContent = getSessionDisplayTitle(session);

        const arrow = document.createElement('span');
        arrow.className = 'session-item-arrow';
        arrow.setAttribute('aria-hidden', 'true');
        arrow.textContent = '›';

        const id = document.createElement('code');
        id.className = 'session-item-id';
        id.textContent = session.session_id;

        const updated = document.createElement('time');
        updated.className = 'session-item-time';
        updated.dateTime = session.updated_at;
        updated.textContent = `Updated ${formatSessionTimestamp(session.updated_at)}`;

        const footer = document.createElement('span');
        footer.className = 'session-item-footer';

        heading.append(title, arrow);
        openButton.append(heading, id);
        footer.append(updated);
        card.append(openButton, footer);
        openButton.addEventListener('click', () => openSession(session.session_id));

        if (!isAdmin()) {
            const deleteButton = document.createElement('button');
            const isConfirmingDelete = (
                state.pendingDeleteSessionId === session.session_id
            );
            deleteButton.type = 'button';
            deleteButton.className = (
                `session-delete${isConfirmingDelete ? ' confirming' : ''}`
            );
            deleteButton.textContent = isConfirmingDelete ? 'Confirm delete' : 'Delete';
            deleteButton.title = isConfirmingDelete
                ? `Confirm deletion of ${session.session_id}`
                : `Delete ${session.session_id}`;
            deleteButton.setAttribute(
                'aria-label',
                isConfirmingDelete
                    ? `Confirm deletion of ${session.session_id}`
                    : `Delete ${session.session_id}`
            );
            footer.append(deleteButton);
            deleteButton.addEventListener('click', () => {
                handleSessionDelete(session.session_id, deleteButton);
            });
        }

        sessionList.appendChild(card);
    });
}

/**
 * Avoid repeating the generated session ID as the visible title.
 * @param {object} session - Session metadata returned by the API.
 * @returns {string} Human-readable title.
 */
function getSessionDisplayTitle(session) {
    if (!session.title || session.title.startsWith('Chat session session_')) {
        return 'Chat session';
    }
    return session.title;
}

/**
 * Format an ISO timestamp compactly for the sidebar.
 * @param {string} timestamp - ISO timestamp from the API.
 * @returns {string} Localized date and time.
 */
function formatSessionTimestamp(timestamp) {
    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) return 'recently';

    return new Intl.DateTimeFormat(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
    }).format(date);
}

/**
 * Load all saved sessions for the tenant carried by the JWT.
 */
async function loadSessions() {
    if (!state.token || !state.selectedTenantId) {
        state.sessions = [];
        renderSessionList(
            isAdmin() ? 'Choose Tenant A or Tenant B' : 'Sign in to view saved sessions'
        );
        return;
    }

    try {
        const endpoint = isAdmin()
            ? `/api/admin/tenants/${encodeURIComponent(state.selectedTenantId)}/sessions`
            : '/api/sessions';
        const data = await apiRequest(endpoint);
        state.sessions = data.sessions;
        renderSessionList();
    } catch (error) {
        state.sessions = [];
        renderSessionList('Unable to load saved sessions');
        if (!error.message.includes('expired')) {
            showError('Failed to load sessions: ' + error.message);
        }
    }
}

/**
 * Reopen a saved session and restore its stored messages in the chat area.
 * @param {string} sessionId - Session to reopen.
 */
async function openSession(sessionId) {
    if (state.isLoading || state.deletingSessionId || !sessionId) return;

    clearDeleteConfirmation();
    setLoading(true, !isAdmin());
    hideError();

    try {
        const endpoint = isAdmin()
            ? `/api/admin/tenants/${encodeURIComponent(state.selectedTenantId)}`
                + `/sessions/${encodeURIComponent(sessionId)}`
            : `/api/sessions/${encodeURIComponent(sessionId)}`;
        const data = await apiRequest(endpoint);
        state.sessionId = data.session_id;
        sessionInfo.innerHTML = `<code>${escapeHtml(data.session_id)}</code>`;
        chatMessages.replaceChildren();

        if (data.messages.length === 0) {
            clearChat();
        } else {
            data.messages.forEach((message) => {
                const role = message.role === 'human' || message.role === 'user'
                    ? 'user'
                    : 'assistant';
                appendMessage(role, message.content);
            });
        }

        renderSessionList();
        if (!isAdmin()) messageInput.focus();
    } catch (error) {
        if (!error.message.includes('expired')) {
            showError('Failed to open session: ' + error.message);
        }
    } finally {
        setLoading(false);
    }
}

/**
 * Arm a session's inline confirmation or delete it on the second click.
 * @param {string} sessionId - Session to delete.
 * @param {HTMLButtonElement} deleteButton - Triggering delete control.
 */
function handleSessionDelete(sessionId, deleteButton) {
    if (state.isLoading || state.deletingSessionId || !sessionId) return;

    if (state.pendingDeleteSessionId !== sessionId) {
        clearDeleteConfirmation();
        state.pendingDeleteSessionId = sessionId;
        renderSessionList();
        state.deleteConfirmationTimer = setTimeout(() => {
            state.pendingDeleteSessionId = null;
            state.deleteConfirmationTimer = null;
            renderSessionList();
        }, 15000);
        return;
    }

    clearDeleteConfirmation(false);
    deleteSavedSession(sessionId, deleteButton);
}

/**
 * Reset any pending inline delete confirmation.
 * @param {boolean} rerender - Whether to refresh the session cards.
 */
function clearDeleteConfirmation(rerender = true) {
    if (state.deleteConfirmationTimer) {
        clearTimeout(state.deleteConfirmationTimer);
    }

    const hadPendingConfirmation = Boolean(state.pendingDeleteSessionId);
    state.pendingDeleteSessionId = null;
    state.deleteConfirmationTimer = null;

    if (rerender && hadPendingConfirmation) renderSessionList();
}

/**
 * Delete a saved session after its inline confirmation.
 * @param {string} sessionId - Session to delete.
 * @param {HTMLButtonElement} deleteButton - Confirmed delete control.
 */
async function deleteSavedSession(sessionId, deleteButton) {

    state.deletingSessionId = sessionId;
    deleteButton.disabled = true;
    deleteButton.textContent = 'Deleting...';
    updateSendButton();
    hideError();

    try {
        await apiRequest(`/api/sessions/${encodeURIComponent(sessionId)}`, {
            method: 'DELETE',
        });

        state.sessions = state.sessions.filter(
            (session) => session.session_id !== sessionId
        );

        if (state.sessionId === sessionId) {
            state.sessionId = null;
            sessionInfo.innerHTML = '<span class="session-placeholder">Session created on first message</span>';
            clearChat();
        }

        renderSessionList();
    } catch (error) {
        deleteButton.disabled = false;
        deleteButton.textContent = 'Delete';
        if (!error.message.includes('expired')) {
            showError('Failed to delete session: ' + error.message);
        }
    } finally {
        state.deletingSessionId = null;
        updateSendButton();
    }
}

// ──────────────────────────────────────────────
// Authentication (Login / Logout)
// ──────────────────────────────────────────────

/**
 * Show the login modal overlay.
 * @param {string} [message] - Optional message to display in the modal error area.
 */
function showLoginModal(message) {
    loginOverlay.classList.remove('hidden');
    loginOverlay.style.display = 'flex';
    loginPasswordInput.value = '';
    if (message) {
        loginError.textContent = message;
        loginError.classList.remove('hidden');
    } else {
        loginError.classList.add('hidden');
    }
    // Focus the username field (or password if username already filled)
    if (!loginUsernameInput.value) {
        loginUsernameInput.focus();
    } else {
        loginPasswordInput.focus();
    }
}

/**
 * Hide the login modal overlay.
 */
function hideLoginModal() {
    loginOverlay.classList.add('hidden');
    loginOverlay.style.display = 'none';
    loginError.classList.add('hidden');
}

/**
 * Attempt to log in with the provided credentials.
 * On success: stores the JWT, updates the UI, hides the modal, and loads tenants.
 * On failure: shows an error message in the modal.
 */
async function login() {
    const username = loginUsernameInput.value.trim();
    const password = loginPasswordInput.value;

    if (!username || !password) {
        loginError.textContent = 'Please enter both username and password.';
        loginError.classList.remove('hidden');
        return;
    }

    loginSubmitBtn.disabled = true;
    loginSubmitBtn.textContent = 'Signing in...';
    loginError.classList.add('hidden');

    try {
        // OAuth2 Password Grant requires application/x-www-form-urlencoded
        const formData = new URLSearchParams();
        formData.append('username', username);
        formData.append('password', password);

        const response = await fetch('/api/auth/token', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: formData.toString(),
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'Login failed');
        }

        // Store token and update state
        storeToken(data.access_token, data.tenant_id, username, data.role);

        // Update the user badge in the header
        updateAuthBadge();
        configureAccountUI();

        hideLoginModal();

        // Load tenants now that we are authenticated
        await loadTenants();

    } catch (error) {
        loginError.textContent = error.message || 'Invalid credentials. Please try again.';
        loginError.classList.remove('hidden');
    } finally {
        loginSubmitBtn.disabled = false;
        loginSubmitBtn.textContent = 'Sign In';
    }
}

/**
 * Log out: clear the JWT, reset state, and show the login modal.
 */
function logout() {
    clearToken();
    state.selectedTenantId = null;
    state.sessionId = null;
    state.tenants = [];
    state.sessions = [];
    state.deletingSessionId = null;
    clearDeleteConfirmation(false);
    authUserBadge.classList.add('hidden');
    authUserBadge.classList.remove('admin');
    configureAccountUI();
    if (tenantSelect) tenantSelect.disabled = false;
    tenantInfo.innerHTML = '<span class="info-placeholder">Select a tenant to begin</span>';
    sessionInfo.innerHTML = '<span class="session-placeholder">No active session</span>';
    renderSessionList('Sign in to view saved sessions');
    clearChat();
    showLoginModal();
}

// ──────────────────────────────────────────────
// Chat Messaging
// ──────────────────────────────────────────────

/**
 * Send a chat message to the API.
 */
async function sendMessage() {
    const message = messageInput.value.trim();
    if (
        !message
        || isAdmin()
        || state.isLoading
        || state.deletingSessionId
        || !state.selectedTenantId
    ) return;

    // Add user message to chat
    appendMessage('user', message);
    messageInput.value = '';
    updateCharCount();

    // Set loading state
    setLoading(true);
    hideError();

    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: buildHeaders(),
            body: JSON.stringify({
                // tenant_id is intentionally omitted — the JWT carries it
                session_id: state.sessionId,
                message: message,
            }),
        });

        if (response.status === 401) {
            clearToken();
            showLoginModal('Your session has expired. Please sign in again.');
            setLoading(false);
            return;
        }

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Failed to send message');
        }

        // Create the empty assistant message bubble
        const msgController = createStreamingMessage('assistant');

        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';
        let pendingSources = null;

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n\n');
            buffer = lines.pop(); // Keep the last incomplete chunk in the buffer

            for (const chunk of lines) {
                if (!chunk.trim()) continue;

                const eventMatch = chunk.match(/^event: (.*)$/m);
                const dataMatch = chunk.match(/^data: (.*)$/m);

                if (eventMatch && dataMatch) {
                    const event = eventMatch[1].trim();
                    const data = JSON.parse(dataMatch[1].trim());

                    if (event === 'setup') {
                        state.sessionId = data.session_id;
                        sessionInfo.innerHTML = `<code>${escapeHtml(data.session_id)}</code>`;
                        pendingSources = data.sources;
                    } else if (event === 'token') {
                        msgController.appendToken(data);
                    } else if (event === 'done') {
                        if (pendingSources) {
                            msgController.setSources(pendingSources);
                        }
                    } else if (event === 'error') {
                        throw new Error(data);
                    }
                }
            }
        }

        await loadSessions();
    } catch (error) {
        showError(error.message);
    } finally {
        setLoading(false);
    }
}

/**
 * Append a completed message to the chat display.
 * @param {string} role - 'user' or 'assistant'
 * @param {string} content - Message text
 * @param {Array} sources - Optional source citations
 */
function appendMessage(role, content, sources = []) {
    const controller = createStreamingMessage(role);
    if (sources.length > 0) {
        controller.setSources(sources);
    }
    controller.appendToken(content);
}

/**
 * Creates a new message DOM element and returns a controller to update it incrementally.
 * @param {string} role - 'user' or 'assistant'
 */
function createStreamingMessage(role) {
    // Remove welcome message if it exists
    const welcome = chatMessages.querySelector('.welcome-message');
    if (welcome) welcome.remove();

    const messageEl = document.createElement('div');
    messageEl.className = `message message-${role}`;

    const avatar = role === 'user' ? '👤' : '🤖';

    messageEl.innerHTML = `
        <div class="message-avatar">${avatar}</div>
        <div class="message-body">
            <div class="message-content"></div>
            <div class="sources-container" style="display: none;"></div>
        </div>
    `;

    chatMessages.appendChild(messageEl);

    // Scroll to bottom
    chatMessages.scrollTop = chatMessages.scrollHeight;

    const contentEl = messageEl.querySelector('.message-content');
    const sourcesEl = messageEl.querySelector('.sources-container');
    let fullContent = '';

    return {
        appendToken: (token) => {
            fullContent += token;
            contentEl.innerHTML = formatMessageContent(fullContent);
            chatMessages.scrollTop = chatMessages.scrollHeight;
        },
        setSources: (sources) => {
            if (!sources || sources.length === 0) return;

            sourcesEl.style.display = 'block';
            sourcesEl.innerHTML = `
                <div class="sources-header">
                    <div class="sources-label">📄 Sources (${sources.length})</div>
                    <button class="sources-toggle btn-sm btn-outline">Expand</button>
                </div>
                <div class="sources-content" style="display: none;">
                ${sources.map(s => `
                    <div class="source-item">
                        <div class="source-file">${escapeHtml(s.source_path)}</div>
                        ${s.heading ? `<div class="source-heading">${escapeHtml(s.heading)}</div>` : ''}
                        <div class="source-excerpt">${escapeHtml(s.excerpt)}</div>
                    </div>
                `).join('')}
                </div>
            `;
            const toggleBtn = sourcesEl.querySelector('.sources-toggle');
            const contentDiv = sourcesEl.querySelector('.sources-content');
            toggleBtn.addEventListener('click', () => {
                const isHidden = contentDiv.style.display === 'none';
                contentDiv.style.display = isHidden ? 'block' : 'none';
                toggleBtn.textContent = isHidden ? 'Collapse' : 'Expand';
            });
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
    };
}

/**
 * Format message content, preserving line breaks.
 * @param {string} content - Raw message text
 * @returns {string} HTML-formatted content
 */
function formatMessageContent(content) {
    return escapeHtml(content)
        .replace(/\n/g, '<br>')
        .replace(/`([^`]+)`/g, '<code>$1</code>');
}

/**
 * Clear all chat messages and show the welcome screen.
 */
function clearChat() {
    if (isAdmin()) {
        const tenant = state.tenants.find(
            (item) => item.tenant_id === state.selectedTenantId
        );
        const scopeCopy = tenant
            ? `
                <span class="admin-scope-label">Currently viewing</span>
                <strong>${escapeHtml(tenant.tenant_name)}</strong>
                <span>Choose a saved session from the sidebar to review its messages.</span>
            `
            : `
                <span class="admin-scope-label">No tenant selected</span>
                <strong>Select Tenant A or Tenant B</strong>
                <span>Use the tenant controls in the sidebar to begin.</span>
            `;

        chatMessages.innerHTML = `
            <div class="welcome-message admin-welcome">
                <div class="welcome-icon admin-welcome-icon">🛡️</div>
                <h2>Welcome to Pooled Multi-Tenant Architecture RAG Chatbot Demo – Admin Account</h2>
                <p class="admin-welcome-copy">This is the demo administrator account for the Pooled Multi-Tenant Architecture RAG Chatbot. As an administrator, you can view the chat sessions of both Tenant A and Tenant B by selecting the corresponding tenant using the controls in the sidebar. This cross-tenant visibility is available only to the administrator and demonstrates a privileged capability that is intentionally unavailable to tenant users, in accordance with the separation of concerns enforced by the pooled multi-tenant architecture.</p>
                <div class="admin-scope-status">${scopeCopy}</div>
            </div>
        `;
        return;
    }

    let welcomeCopy = `
        <h2>Welcome to Pooled Multi-Tenant Architecture RAG Chatbot Demo</h2>
        <p>Ask a simple question about your tenant's basic knowledge base.</p>
    `;

    if (state.selectedTenantId === 'tenant-A') {
        welcomeCopy = `
            <h2>Welcome to <i>Pooled Multi-Tenant Architecture RAG Chatbot</i> Demo</h2>
            <p>Tenant A's basic knowledge base covers only:<br> <strong>payment issues</strong>,<strong> refunds</strong>,<strong> and</strong><strong> returns</strong>.</p><br>
            <p>Try asking a simple question, i.e.:<br><em><strong>Can I pay with PayPal?</strong></em>,<br><em><strong>or</strong></em><br><em><strong>How many days do I have to return an item?</strong></em>, etc.</p>
            <br>
            <p style="text-align:left; color:rgba(255,255,255,0.45); font-size:0.85em;">And observe evidence of:</p>
            <table style="text-align:left; border-collapse:collapse; width:100%; margin-top:6px; border: 1px solid rgba(255,255,255,0.1); color:rgba(255,255,255,0.45); font-size:0.82em;">
                <tr><td style="padding:4px 8px; vertical-align:top; white-space:nowrap; border: 1px solid rgba(255,255,255,0.2);"><em>1.</em></td><td style="padding:4px 8px; border: 1px solid rgba(255,255,255,0.2);">Token-by-token rendering (smooth typewriter text flow).</td></tr>
                <tr><td style="padding:4px 8px; vertical-align:top; white-space:nowrap; border: 1px solid rgba(255,255,255,0.2);"><em>2.</em></td><td style="padding:4px 8px; border: 1px solid rgba(255,255,255,0.2);">Source citation badges showing document path, heading, and chunk excerpts at the bottom of each AI message.</td></tr>
                <tr><td style="padding:4px 8px; vertical-align:top; white-space:nowrap; border: 1px solid rgba(255,255,255,0.2);"><em>3.</em></td><td style="padding:4px 8px; border: 1px solid rgba(255,255,255,0.2);">Tenant A's session and context isolation.</td></tr>
                <tr><td style="padding:4px 8px; vertical-align:top; white-space:nowrap; border: 1px solid rgba(255,255,255,0.2);"><em>4.</em></td><td style="padding:4px 8px; border: 1px solid rgba(255,255,255,0.2);">Session list switching dynamically scoped to the logged-in user.</td></tr>
            </table>
        `;
    } else if (state.selectedTenantId === 'tenant-B') {
        welcomeCopy = `
            <h2>Welcome to Pooled Multi-Tenant Architecture RAG Chatbot Demo</h2>
            <p>Tenant B's basic knowledge base covers only <strong>device resets, updates, and troubleshooting</strong>.</p>
            <p>Try asking a simple question, i.e.:<br><em>How do I reset my device?</em>, or<br><em>What does the red light mean?</em>, etc.</p>
        `;
    }

    chatMessages.innerHTML = `
        <div class="welcome-message">
            <div class="welcome-icon">💬</div>
            ${welcomeCopy}
        </div>
    `;
}

// ──────────────────────────────────────────────
// UI State Management
// ──────────────────────────────────────────────

/**
 * Set loading state.
 * @param {boolean} loading - Whether the app is loading
 * @param {boolean} showIndicator - Whether to show the response-generation status
 */
function setLoading(loading, showIndicator = true) {
    state.isLoading = loading;
    sendBtn.disabled = loading || isAdmin() || !messageInput.value.trim();
    messageInput.disabled = loading || isAdmin();
    loadingIndicator.classList.toggle('hidden', !loading || !showIndicator || isAdmin());
}

/**
 * Update send button enabled state.
 */
function updateSendButton() {
    sendBtn.disabled = (
        state.isLoading
        || isAdmin()
        || Boolean(state.deletingSessionId)
        || !messageInput.value.trim()
        || !state.selectedTenantId
    );
}

/**
 * Update character count display.
 */
function updateCharCount() {
    const count = messageInput.value.length;
    charCount.textContent = `${count} / 4000`;
}

/**
 * Show an error message.
 * @param {string} message - Error text
 */
function showError(message) {
    errorText.textContent = message;
    errorDisplay.classList.remove('hidden');
}

/**
 * Hide the error display.
 */
function hideError() {
    errorDisplay.classList.add('hidden');
}

/**
 * Escape HTML special characters.
 * @param {string} text - Raw text
 * @returns {string} Escaped HTML
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ──────────────────────────────────────────────
// Reindex
// ──────────────────────────────────────────────

/**
 * Trigger a reindex of all tenant knowledge bases.
 */
async function reindex() {
    if (!isAdmin()) return;

    reindexBtn.disabled = true;
    reindexBtn.innerHTML = '<span class="spinner"></span> Reindexing...';

    try {
        const data = await apiRequest('/api/admin/reindex', {
            method: 'POST',
            body: JSON.stringify({ tenant_id: null }),
        });

        const summary = data.reindexed
            .map(r => `${r.tenant_id}: ${r.documents} docs, ${r.chunks} chunks`)
            .join(' | ');

        showError(`✅ Reindex complete: ${summary}`);
        // Use a different style for success
        errorDisplay.style.background = '#dcfce7';
        errorDisplay.style.color = '#166534';

        setTimeout(() => {
            hideError();
            errorDisplay.style.background = '';
            errorDisplay.style.color = '';
        }, 4000);

    } catch (error) {
        showError('Reindex failed: ' + error.message);
    } finally {
        reindexBtn.disabled = false;
        reindexBtn.innerHTML = '<span class="btn-icon">🔄</span> Reindex';
    }
}

// ──────────────────────────────────────────────
// Auto-resize Textarea
// ──────────────────────────────────────────────

/**
 * Auto-resize the textarea to fit content.
 */
function autoResize() {
    messageInput.style.height = 'auto';
    messageInput.style.height = Math.min(messageInput.scrollHeight, 120) + 'px';
}

// ──────────────────────────────────────────────
// Event Listeners
// ──────────────────────────────────────────────

// Tenant selection change
if (tenantSelect) {
    tenantSelect.addEventListener('change', (e) => {
        selectTenant(e.target.value);
    });
}

adminTenantButtons.forEach((button) => {
    button.addEventListener('click', () => {
        selectAdminTenant(button.dataset.tenantId);
    });
});

// Send message
sendBtn.addEventListener('click', sendMessage);

// Enter to send (Shift+Enter for new line)
messageInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

// Input changes
messageInput.addEventListener('input', () => {
    updateCharCount();
    updateSendButton();
    autoResize();
});

// New session
newSessionBtn.addEventListener('click', () => {
    if (state.isLoading || state.deletingSessionId) return;
    clearDeleteConfirmation();
    state.sessionId = null;
    sessionInfo.innerHTML = '<span class="session-placeholder">Session created on first message</span>';
    renderSessionList();
    clearChat();
    messageInput.focus();
});

// Reindex
reindexBtn.addEventListener('click', reindex);

// Dismiss error
errorDismiss.addEventListener('click', hideError);

// Logout button
logoutBtn.addEventListener('click', logout);

// Login form submit
loginForm.addEventListener('submit', (e) => {
    e.preventDefault();
    login();
});

// Support pressing Enter inside login password field
loginPasswordInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        e.preventDefault();
        login();
    }
});

// ──────────────────────────────────────────────
// Initialization
// ──────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    // Check if a JWT is already stored from a previous page load this session
    if (loadStoredToken()) {
        // Token found — restore auth badge and load tenants normally
        updateAuthBadge();
        configureAccountUI();
        hideLoginModal();
        loadTenants();
    } else {
        // No token — show the login modal
        showLoginModal();
    }
});
