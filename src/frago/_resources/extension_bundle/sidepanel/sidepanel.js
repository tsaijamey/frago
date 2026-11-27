import {
    BridgeApiError,
    browseSystemDirectories,
    buildWebSocketUrl,
    checkServerInfo,
    createWorkbenchSession,
    fetchSessionRecords,
    getSessionFileContent,
    getSystemDirectories,
    listEmployees,
    listWorkbenchAgents,
    listWorkbenchSessions,
    loadServerConfig,
    normalizeServerUrl,
    pollPendingWorkbenchSession,
    saveServerConfig,
    sendToWorkbenchSession,
    stopWorkbenchSession,
} from "./api.js";
import {
    BRIDGE_DRAFT_KEY,
    emptyDraft,
    loadBridgeSettings,
    loadDraft,
    normalizeDraft,
    saveBridgeSettings,
    saveDraft,
} from "./state.js";

const extractor = globalThis.FragoPageExtractor;
const composer = globalThis.FragoMessageComposer;
const md = globalThis.FragoMarkdown;
const recLib = globalThis.FragoSessionRecords;

// ══════════ Keep SW aware that Side Panel is open ══════════
let panelPort = null;
try {
    panelPort = chrome.runtime.connect({ name: "frago-sidepanel" });
} catch (_) { /* ignore outside extension runtime */ }

// ══════════ Panel State ══════════
const state = {
    serverCfg: { serverUrl: "http://127.0.0.1:8093", token: "" },
    connOk: false,
    wsState: "disconnected",
    ws: null,
    wsPingTimer: null,
    wsReconnectTimer: null,

    draft: emptyDraft(),
    settings: {
        selectionPillMode: "auto",
        lastNewSessionCwd: "",
        selectedSessionId: "",
        lastEmployeeId: "",
        lastAgent: "",
    },

    activeTabId: null,
    activePage: null,

    sessions: [],
    selectedSid: "",
    sessionFilter: "all",
    sessionSearch: "",
    showWorkers: false,

    newSessionMode: false,
    employees: [],
    selectedEmployeeId: "",
    agents: [],
    defaultAgent: "",
    defaultCwd: "",
    currentBrowsePath: "",
    parentBrowsePath: "",
    pendingHandle: null,

    records: [],
    recordsSid: "",
    recordsLoading: false,
    recordsError: "",
    optimisticMessages: [],
    awaitingAgent: false,
    awaitingSinceSeq: -1,

    stickToBottom: true,
    lastStreamSignature: "",
    pollTimer: null,
    expandedContextKeys: new Set(),
    expandedActivityKeys: new Set(),
    decisionDrafts: new Map(),

    activeCiteId: null,
    citeDrawerReqId: 0,
    citeExtDef: null,
    citePopTimer: null,
};

// ══════════ DOM References ══════════
const el = {
    sessionPickerBtn: document.getElementById("session-picker-btn"),
    activeSessionDot: document.getElementById("active-session-dot"),
    activeSessionEmp: document.getElementById("active-session-emp"),
    activeSessionTitle: document.getElementById("active-session-title"),
    newSessionBtn: document.getElementById("new-session-btn"),
    stopSessionBtn: document.getElementById("stop-session-btn"),
    openWebuiBtn: document.getElementById("open-webui-btn"),
    toggleSettingsBtn: document.getElementById("toggle-settings-btn"),
    connDot: document.getElementById("conn-dot"),

    sessionDrawer: document.getElementById("session-drawer"),
    sessionSearchInput: document.getElementById("session-search-input"),
    refreshSessionsBtn: document.getElementById("refresh-sessions-btn"),
    showWorkersCheckbox: document.getElementById("show-workers-checkbox"),
    sessionList: document.getElementById("session-list"),

    settingsDrawer: document.getElementById("settings-drawer"),
    connLabel: document.getElementById("conn-label"),
    serverUrlInput: document.getElementById("server-url-input"),
    serverTokenInput: document.getElementById("server-token-input"),
    saveConnBtn: document.getElementById("save-conn-btn"),
    openOptionsBtn: document.getElementById("open-options-btn"),
    diagEid: document.getElementById("diag-eid"),
    diagWs: document.getElementById("diag-ws"),
    diagNative: document.getElementById("diag-native"),
    diagProxy: document.getElementById("diag-proxy"),

    newSessionBar: document.getElementById("new-session-bar"),
    cancelNewSessionBtn: document.getElementById("cancel-new-session-btn"),
    employeeChips: document.getElementById("employee-chips"),
    agentSelect: document.getElementById("agent-select"),
    cwdInput: document.getElementById("cwd-input"),
    browseDirBtn: document.getElementById("browse-dir-btn"),
    agentHint: document.getElementById("agent-hint"),
    dirBrowser: document.getElementById("dir-browser"),
    dirCurrentPath: document.getElementById("dir-current-path"),
    dirUpBtn: document.getElementById("dir-up-btn"),
    dirUseBtn: document.getElementById("dir-use-btn"),
    dirEntries: document.getElementById("dir-entries"),

    bannerToast: document.getElementById("banner-toast"),
    chatStream: document.getElementById("chat-stream"),
    liveStatusRow: document.getElementById("live-status-row"),
    liveStatusText: document.getElementById("live-status-text"),
    scrollBottomBtn: document.getElementById("scroll-bottom-btn"),

    toggleFullpageBtn: document.getElementById("toggle-fullpage-btn"),
    fullpageCharsBadge: document.getElementById("fullpage-chars-badge"),
    pickElementBtn: document.getElementById("pick-element-btn"),
    captureSelectionBtn: document.getElementById("capture-selection-btn"),
    captureShotBtn: document.getElementById("capture-shot-btn"),
    pillToggleCheckbox: document.getElementById("pill-toggle-checkbox"),
    attachmentPills: document.getElementById("attachment-pills"),
    instructionInput: document.getElementById("instruction-input"),
    sendBtn: document.getElementById("send-btn"),

    citePopover: document.getElementById("cite-popover"),
    citePopBadge: document.getElementById("cite-pop-badge"),
    citePopTitle: document.getElementById("cite-pop-title"),
    citePopPath: document.getElementById("cite-pop-path"),
    citePopExcerpt: document.getElementById("cite-pop-excerpt"),
    citePopHint: document.getElementById("cite-pop-hint"),
    citePreviewDrawer: document.getElementById("cite-preview-drawer"),
    citeDrawerTitle: document.getElementById("cite-drawer-title"),
    citeDrawerPath: document.getElementById("cite-drawer-path"),
    citeDrawerBanner: document.getElementById("cite-drawer-banner"),
    citeDrawerBody: document.getElementById("cite-drawer-body"),
    citeDrawerClose: document.getElementById("cite-drawer-close"),
    citeExtModal: document.getElementById("cite-ext-modal"),
    citeExtTitle: document.getElementById("cite-ext-title"),
    citeExtUrl: document.getElementById("cite-ext-url"),
    citeExtExcerpt: document.getElementById("cite-ext-excerpt"),
    citeExtCancel: document.getElementById("cite-ext-cancel"),
    citeExtOpen: document.getElementById("cite-ext-open"),
};

// ══════════ SVG Icon Helper ══════════
const SVG_NS = "http://www.w3.org/2000/svg";
const ICON_PATHS = {
    crosshair: [
        ["circle", { cx: "12", cy: "12", r: "9" }],
        ["line", { x1: "22", y1: "12", x2: "18", y2: "12" }],
        ["line", { x1: "6", y1: "12", x2: "2", y2: "12" }],
        ["line", { x1: "12", y1: "6", x2: "12", y2: "2" }],
        ["line", { x1: "12", y1: "22", x2: "12", y2: "18" }],
    ],
    scissors: [
        ["circle", { cx: "6", cy: "6", r: "3" }],
        ["path", { d: "M8.12 8.12 12 12" }],
        ["path", { d: "M20 4 8.12 15.88" }],
        ["circle", { cx: "6", cy: "18", r: "3" }],
        ["path", { d: "M14.8 14.8 20 20" }],
    ],
    fileText: [
        ["path", { d: "M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" }],
        ["polyline", { points: "14 2 14 8 20 8" }],
        ["line", { x1: "16", y1: "13", x2: "8", y2: "13" }],
        ["line", { x1: "16", y1: "17", x2: "8", y2: "17" }],
    ],
    chevronRight: [
        ["path", { d: "m9 18 6-6-6-6" }],
    ],
    zap: [
        ["polygon", { points: "13 2 3 14 12 14 11 22 21 10 12 10 13 2" }],
    ],
    checkCircle: [
        ["path", { d: "M22 11.08V12a10 10 0 1 1-5.93-9.14" }],
        ["polyline", { points: "22 4 12 14.01 9 11.01" }],
    ],
    alertCircle: [
        ["circle", { cx: "12", cy: "12", r: "10" }],
        ["line", { x1: "12", y1: "8", x2: "12", y2: "12" }],
        ["line", { x1: "12", y1: "16", x2: "12.01", y2: "16" }],
    ],
    terminal: [
        ["polyline", { points: "4 17 10 11 4 5" }],
        ["line", { x1: "12", y1: "19", x2: "20", y2: "19" }],
    ],
    wrench: [
        ["path", { d: "M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" }],
    ],
    thought: [
        ["path", { d: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" }],
    ],
    cornerDownRight: [
        ["polyline", { points: "15 10 20 15 15 20" }],
        ["path", { d: "M4 4v7a4 4 0 0 0 4 4h12" }],
    ],
    camera: [
        ["path", { d: "M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z" }],
        ["circle", { cx: "12", cy: "13", r: "3" }],
    ],
    x: [
        ["path", { d: "M18 6 6 18" }],
        ["path", { d: "m6 6 12 12" }],
    ],
    folder: [
        ["path", { d: "M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z" }],
    ],
};

function createSvgIcon(name, size = 13, extraClass = "") {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("width", String(size));
    svg.setAttribute("height", String(size));
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.7");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("class", `icon-svg${extraClass ? ` ${extraClass}` : ""}`);
    for (const [tag, attrs] of ICON_PATHS[name] || []) {
        const node = document.createElementNS(SVG_NS, tag);
        for (const [k, v] of Object.entries(attrs)) {
            node.setAttribute(k, v);
        }
        svg.appendChild(node);
    }
    return svg;
}

// ══════════ Helpers & Toast ══════════
let toastTimer = null;
function showToast(msg, kind = "info") {
    if (toastTimer) clearTimeout(toastTimer);
    el.bannerToast.textContent = msg;
    el.bannerToast.className = `banner-toast ${kind === "err" ? "is-err" : kind === "ok" ? "is-ok" : ""}`;
    toastTimer = setTimeout(() => {
        el.bannerToast.className = "banner-toast is-hidden";
    }, 3400);
}

function shortenPath(path) {
    const parts = String(path || "").split(/[\\/]/).filter(Boolean);
    if (parts.length <= 2) return path || "";
    return `…/${parts.slice(-2).join("/")}`;
}

function formatRelativeTime(ts) {
    if (!ts) return "";
    const diffSec = Math.max(0, Math.floor((Date.now() - Number(ts)) / 1000));
    if (diffSec < 60) return "刚刚";
    const mins = Math.floor(diffSec / 60);
    if (mins < 60) return `${mins}分钟前`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}小时前`;
    return `${Math.floor(hours / 24)}天前`;
}

function formatCharCount(n) {
    if (!n) return "0字";
    if (n >= 10000) return `${(n / 1000).toFixed(1)}k字`;
    return `${n}字`;
}

function sendRuntimeMessage(payload) {
    return new Promise((resolve) => {
        if (!chrome?.runtime?.sendMessage) {
            resolve({ ok: false, error: "当前不在扩展运行时内" });
            return;
        }
        chrome.runtime.sendMessage(payload, (resp) => {
            if (chrome.runtime.lastError) {
                resolve({ ok: false, error: chrome.runtime.lastError.message });
                return;
            }
            resolve(resp || { ok: false, error: "未收到扩展响应" });
        });
    });
}

async function getActiveBrowserTab() {
    if (!chrome?.tabs?.query) return null;
    const tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    return tabs?.[0] || null;
}

function getSelectedSession() {
    return state.sessions.find((s) => s.session_id === state.selectedSid) || null;
}

function formatSessionTitle(sess) {
    if (!sess) return "";
    if (sess.custom_title) return sess.custom_title;
    const raw = String(sess.title || "").trim();
    if (!raw) return sess.session_id ? sess.session_id.slice(0, 8) : "";
    const parsed = recLib?.parseBridgeContextMessage ? recLib.parseBridgeContextMessage(raw) : null;
    if (parsed?.isBridgeMessage && parsed.instruction) {
        return parsed.instruction.split(/\r?\n/)[0].trim();
    }
    return raw.split(/\r?\n/)[0].trim() || raw;
}

function isNearBottom() {
    const node = el.chatStream;
    return node.scrollHeight - node.scrollTop - node.clientHeight < 64;
}

function scrollStreamToBottom(smooth = true) {
    const node = el.chatStream;
    state.stickToBottom = true;
    el.scrollBottomBtn.classList.add("is-hidden");
    node.scrollTo({
        top: node.scrollHeight,
        behavior: smooth ? "smooth" : "auto",
    });
}

function autoResizeTextarea() {
    const ta = el.instructionInput;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(128, Math.max(36, ta.scrollHeight))}px`;
}

// ══════════ Connection, Diagnostics & WebSocket ══════════
async function refreshDiagnostics() {
    el.diagEid.textContent = chrome?.runtime?.id || "-";
    el.diagWs.textContent = state.wsState;
    const diag = await sendRuntimeMessage({ type: "get_diagnostics" });
    if (diag && diag.ok) {
        el.diagNative.textContent = diag.nativeHostConnected ? "connected" : "disconnected";
        el.diagProxy.textContent = diag.proxyConnected ? "connected" : "idle";
    } else {
        el.diagNative.textContent = "unknown";
        el.diagProxy.textContent = "unknown";
    }
}

async function checkConnection() {
    el.connDot.className = "status-dot is-checking";
    el.connLabel.textContent = "检测连接中…";
    try {
        const info = await checkServerInfo(state.serverCfg);
        state.connOk = true;
        el.connDot.className = "status-dot is-ok";
        el.connLabel.textContent = `已连接 (${info?.version || "frago"})`;
        return true;
    } catch (err) {
        state.connOk = false;
        el.connDot.className = "status-dot is-err";
        el.connLabel.textContent = err instanceof BridgeApiError ? err.message : "连接失败";
        return false;
    }
}

function closeWebSocket() {
    if (state.wsPingTimer) {
        clearInterval(state.wsPingTimer);
        state.wsPingTimer = null;
    }
    if (state.wsReconnectTimer) {
        clearTimeout(state.wsReconnectTimer);
        state.wsReconnectTimer = null;
    }
    if (state.ws) {
        try {
            state.ws.onopen = null;
            state.ws.onmessage = null;
            state.ws.onclose = null;
            state.ws.onerror = null;
            state.ws.close();
        } catch (_) { /* ignore */ }
        state.ws = null;
    }
    state.wsState = "disconnected";
    el.diagWs.textContent = state.wsState;
}

function scheduleWsReconnect() {
    if (state.wsReconnectTimer) return;
    state.wsReconnectTimer = setTimeout(() => {
        state.wsReconnectTimer = null;
        connectWebSocket();
    }, 3500);
}

function connectWebSocket() {
    closeWebSocket();
    let wsUrl = "";
    try {
        wsUrl = buildWebSocketUrl(state.serverCfg);
    } catch (_) {
        return;
    }
    state.wsState = "connecting";
    el.diagWs.textContent = state.wsState;

    try {
        const ws = new WebSocket(wsUrl);
        state.ws = ws;

        ws.onopen = () => {
            state.wsState = "connected";
            el.diagWs.textContent = "connected";
            state.wsPingTimer = setInterval(() => {
                if (ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ type: "ping" }));
                }
            }, 25_000);
        };

        ws.onmessage = (evt) => {
            let msg = null;
            try {
                msg = JSON.parse(evt.data);
            } catch (_) {
                return;
            }
            if (!msg || typeof msg.type !== "string") return;

            if (msg.type === "session_records_append") {
                const sid = msg.data?.session_id;
                const incoming = msg.data?.records;
                if (sid && sid === state.selectedSid && Array.isArray(incoming) && incoming.length > 0) {
                    applyIncomingRecords(incoming);
                }
            } else if (msg.type === "session_turn_done") {
                const sid = msg.data?.session_id;
                if (sid && sid === state.selectedSid) {
                    state.awaitingAgent = false;
                    pollActiveSessionRecords({ force: true });
                    loadSessions({ silent: true });
                }
            } else if (msg.type === "session_created" || msg.type === "session_updated") {
                loadSessions({ silent: true });
            }
        };

        ws.onclose = () => {
            if (state.ws === ws) {
                state.ws = null;
                state.wsState = "disconnected";
                el.diagWs.textContent = "reconnecting";
                if (state.wsPingTimer) {
                    clearInterval(state.wsPingTimer);
                    state.wsPingTimer = null;
                }
                scheduleWsReconnect();
            }
        };

        ws.onerror = () => {
            el.diagWs.textContent = "error";
        };
    } catch (_) {
        state.wsState = "error";
        el.diagWs.textContent = "error";
        scheduleWsReconnect();
    }
}

// ══════════ Active Page Extraction ══════════
async function refreshActivePage({ silent = false } = {}) {
    const tab = await getActiveBrowserTab();
    if (!tab || tab.id == null) {
        state.activeTabId = null;
        state.activePage = null;
        renderContextBar();
        return null;
    }
    state.activeTabId = tab.id;
    const resp = await sendRuntimeMessage({
        type: "frago.bridge.ensureTabInjected",
        tabId: tab.id,
        payload: { type: "frago.bridge.extractFullPage" },
    });
    if (resp && resp.ok && resp.page) {
        state.activePage = resp.page;
        if (extractor && resp.page.normalizedUrl) {
            state.draft.pageSnapshots[resp.page.normalizedUrl] = resp.page;
            await saveDraft(state.draft);
        }
    } else {
        state.activePage = null;
        if (!silent && resp?.error) {
            showToast(resp.error, "err");
        }
    }
    renderContextBar();
    return state.activePage;
}

// ══════════ Session Loading, Switching & Header ══════════
async function loadSessions({ silent = false } = {}) {
    try {
        const list = await listWorkbenchSessions(state.serverCfg);
        state.sessions = Array.isArray(list) ? list : [];

        // Auto-bind persisted session or keep current
        if (state.selectedSid && !state.sessions.some((s) => s.session_id === state.selectedSid)) {
            // Keep selectedSid if it's newly claimed and list hasn't caught up yet
            if (!state.records.length) {
                state.selectedSid = "";
            }
        }
        if (!state.selectedSid && state.settings.selectedSessionId) {
            const found = state.sessions.find((s) => s.session_id === state.settings.selectedSessionId);
            if (found) {
                await selectSession(found.session_id, { closeDrawer: false });
            }
        }
        renderHeader();
        renderSessionList();
        if (!state.selectedSid && !state.newSessionMode) {
            renderChatStream({ force: true });
        }
    } catch (err) {
        if (!silent) {
            el.sessionList.innerHTML = `<div class="drawer-empty">会话加载失败：${err.message}</div>`;
        }
    }
}

function renderHeader() {
    if (state.newSessionMode) {
        el.activeSessionDot.className = "status-dot is-checking";
        el.activeSessionEmp.classList.add("is-hidden");
        el.activeSessionTitle.textContent = "新建会话（待发送首条消息）";
        el.stopSessionBtn.classList.add("is-hidden");
        el.openWebuiBtn.classList.add("is-hidden");
        el.newSessionBtn.classList.add("is-active");
        return;
    }

    el.newSessionBtn.classList.remove("is-active");
    const sess = getSelectedSession();
    const runState = recLib.deriveLiveRunState(state.records, sess);

    if (!state.selectedSid) {
        el.activeSessionDot.className = "status-dot is-idle";
        el.activeSessionEmp.classList.add("is-hidden");
        el.activeSessionTitle.textContent = "选择或新建会话";
        el.stopSessionBtn.classList.add("is-hidden");
        el.openWebuiBtn.classList.add("is-hidden");
        return;
    }

    el.openWebuiBtn.classList.remove("is-hidden");
    const isRunning = Boolean(runState.isRunning || state.awaitingAgent);
    const needDecision = Boolean(runState.needDecision);

    el.activeSessionDot.className = `status-dot ${
        needDecision ? "is-decision" : isRunning ? "is-running" : "is-idle"
    }`;

    if (sess?.employee_title) {
        el.activeSessionEmp.textContent = sess.employee_title;
        el.activeSessionEmp.classList.remove("is-hidden");
    } else {
        el.activeSessionEmp.classList.add("is-hidden");
    }

    el.activeSessionTitle.textContent = sess
        ? formatSessionTitle(sess)
        : `会话 ${state.selectedSid.slice(0, 8)}`;

    if (isRunning || sess?.alive) {
        el.stopSessionBtn.classList.remove("is-hidden");
    } else {
        el.stopSessionBtn.classList.add("is-hidden");
    }
}

function filteredSessions() {
    const q = state.sessionSearch.trim().toLowerCase();
    return state.sessions.filter((s) => {
        if (!state.showWorkers && (s.origin === "worker" || s.origin === "subagent")) {
            return false;
        }
        if (state.sessionFilter === "running" && s.status !== "running") {
            return false;
        }
        if (state.sessionFilter === "recent") {
            const ageMs = Date.now() - Number(s.last_active_at || 0);
            if (ageMs > 24 * 3600 * 1000) return false;
        }
        if (!q) return true;
        const hay = [
            s.custom_title,
            s.title,
            s.employee_title,
            s.employee_id,
            s.directory,
            s.session_id,
            s.family,
        ]
            .filter(Boolean)
            .join(" ")
            .toLowerCase();
        return hay.includes(q);
    });
}

function renderSessionList() {
    const list = filteredSessions();
    el.sessionList.innerHTML = "";
    if (list.length === 0) {
        const empty = document.createElement("div");
        empty.className = "drawer-empty";
        empty.textContent = state.sessions.length === 0
            ? "暂无会话，点击右上角「+ 新建」开始对话。"
            : "没有匹配条件的会话。";
        el.sessionList.appendChild(empty);
        return;
    }

    for (const s of list) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = `session-item ${state.selectedSid === s.session_id ? "is-selected" : ""}`;

        const top = document.createElement("div");
        top.className = "session-row-top";

        const dot = document.createElement("span");
        dot.className = `status-dot ${
            s.need_decision ? "is-decision" : s.status === "running" ? "is-running" : "is-idle"
        }`;

        const title = document.createElement("span");
        title.className = "session-item-title";
        title.textContent = formatSessionTitle(s) || s.session_id;

        top.appendChild(dot);
        if (s.employee_title) {
            const emp = document.createElement("span");
            emp.className = "emp-badge";
            emp.textContent = s.employee_title;
            top.appendChild(emp);
        }
        top.appendChild(title);

        const meta = document.createElement("div");
        meta.className = "session-row-meta";
        const left = document.createElement("span");
        left.className = "session-meta-left";
        const statusText = s.need_decision ? "等待拍板" : s.status === "running" ? "运行中" : "空闲";
        left.textContent = `${statusText} · ${s.family || "session"} · ${shortenPath(s.directory)}`;
        const right = document.createElement("span");
        right.textContent = formatRelativeTime(s.last_active_at);

        meta.appendChild(left);
        meta.appendChild(right);

        btn.appendChild(top);
        btn.appendChild(meta);

        btn.addEventListener("click", () => {
            selectSession(s.session_id, { closeDrawer: true });
        });
        el.sessionList.appendChild(btn);
    }
}

async function selectSession(sid, { closeDrawer = true } = {}) {
    state.newSessionMode = false;
    el.newSessionBar.classList.add("is-hidden");
    if (closeDrawer) {
        el.sessionDrawer.classList.add("is-hidden");
    }

    const changed = state.selectedSid !== sid;
    state.selectedSid = sid;
    await saveBridgeSettings({ selectedSessionId: sid });

    if (changed) {
        closeAllCitations();
        state.records = [];
        state.recordsSid = sid;
        state.recordsError = "";
        state.optimisticMessages = [];
        state.awaitingAgent = false;
        state.awaitingSinceSeq = -1;
        state.stickToBottom = true;
        state.lastStreamSignature = "";
        renderHeader();
        renderSessionList();
        renderChatStream({ force: true });
    } else {
        renderHeader();
        renderSessionList();
    }

    await loadInitialSessionRecords(sid);
    schedulePolling();
}

// ══════════ Records Fetching, Incremental Polling & Reconciliation ══════════
function reconcileOptimisticMessages() {
    const records = state.records;
    if (!records.length) return;

    if (state.optimisticMessages.length) {
        const latestRecordSeq = records[records.length - 1]?.seq ?? -1;
        // Remove optimistic items once a real user.say appears after awaitingSinceSeq
        state.optimisticMessages = state.optimisticMessages.filter((opt) => {
            const matched = records.some((r) => {
                if (!r || (r.kind !== "user.say" && r.kind !== "context.inject")) return false;
                if ((r.seq ?? 0) <= opt.afterSeq) return false;
                const txt = String(r.payload?.text || r.payload?.content || "");
                if (!opt.needle) return true;
                return txt.includes(opt.needle) || latestRecordSeq > opt.afterSeq + 1;
            });
            return !matched;
        });
    }

    // Clear awaitingAgent once an agent.say appears after awaitingSinceSeq
    if (state.awaitingAgent) {
        const hasReply = records.some(
            (r) => r && r.kind === "agent.say" && (r.seq ?? 0) > state.awaitingSinceSeq
        );
        if (hasReply) {
            state.awaitingAgent = false;
        }
    }
}

function applyIncomingRecords(batch) {
    if (!Array.isArray(batch) || batch.length === 0) return;
    const prevLastId = state.records[state.records.length - 1]?.id || "";
    const merged = recLib.mergeRecords(state.records, batch);
    if (merged === state.records) return;
    state.records = merged;
    reconcileOptimisticMessages();
    const newLastId = state.records[state.records.length - 1]?.id || "";
    renderHeader();
    renderChatStream();
    if (newLastId !== prevLastId && state.stickToBottom) {
        scrollStreamToBottom(true);
    }
}

async function loadInitialSessionRecords(sid) {
    if (!sid) return;
    state.recordsLoading = true;
    state.recordsError = "";
    renderChatStream({ force: true });
    try {
        let combined = await fetchSessionRecords(state.serverCfg, sid, { limit: 200, tail: true });
        combined = Array.isArray(combined) ? combined : [];

        // Backfill older pages if fewer than 40 human/agent turns are present
        let hops = 0;
        while (
            state.selectedSid === sid &&
            hops < 3 &&
            recLib.countTalkRecords(combined) < 40 &&
            combined.length > 0 &&
            (combined[0].seq ?? 0) > 0
        ) {
            const firstSeq = combined[0].seq ?? 0;
            const prevStart = Math.max(0, firstSeq - 200);
            const page = await fetchSessionRecords(state.serverCfg, sid, {
                limit: 200,
                tail: false,
                after: prevStart,
            });
            if (!Array.isArray(page) || page.length === 0) break;
            const prevLen = combined.length;
            const byId = new Map();
            for (const r of page) if (r?.id) byId.set(r.id, r);
            for (const r of combined) if (r?.id) byId.set(r.id, r);
            combined = Array.from(byId.values()).sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0));
            if (combined.length === prevLen) break;
            hops += 1;
        }

        if (state.selectedSid !== sid) return;
        state.records = combined;
        state.recordsSid = sid;
        state.recordsLoading = false;
        reconcileOptimisticMessages();
        renderHeader();
        renderChatStream({ force: true });
        scrollStreamToBottom(false);
    } catch (err) {
        if (state.selectedSid !== sid) return;
        state.recordsLoading = false;
        state.recordsError = err instanceof BridgeApiError ? err.message : String(err?.message || err);
        renderChatStream({ force: true });
    }
}

let pollInFlight = false;
async function pollActiveSessionRecords({ force = false } = {}) {
    const sid = state.selectedSid;
    if (!sid || state.newSessionMode) return;
    if (pollInFlight && !force) return;
    pollInFlight = true;
    try {
        const prev = state.records;
        if (!prev.length) {
            const tailBatch = await fetchSessionRecords(state.serverCfg, sid, { limit: 200, tail: true });
            if (state.selectedSid === sid && Array.isArray(tailBatch) && tailBatch.length > 0) {
                applyIncomingRecords(tailBatch);
            }
            return;
        }

        const lastSeq = prev[prev.length - 1]?.seq ?? 0;
        const batch = await fetchSessionRecords(state.serverCfg, sid, {
            after: lastSeq,
            limit: 200,
        });
        if (state.selectedSid !== sid) return;
        if (recLib.shouldReloadTailOnPoll(prev, batch)) {
            const fullTail = await fetchSessionRecords(state.serverCfg, sid, { limit: 200, tail: true });
            if (state.selectedSid === sid && Array.isArray(fullTail)) {
                state.records = fullTail;
                reconcileOptimisticMessages();
                renderHeader();
                renderChatStream({ force: true });
                if (state.stickToBottom) scrollStreamToBottom(true);
            }
            return;
        }
        if (Array.isArray(batch) && batch.length > 0) {
            applyIncomingRecords(batch);
        } else if (state.awaitingAgent || state.optimisticMessages.length > 0) {
            const wasAwaiting = state.awaitingAgent;
            reconcileOptimisticMessages();
            if (wasAwaiting !== state.awaitingAgent) {
                renderHeader();
                renderChatStream();
            }
        }
    } catch (_) {
        // Silent during background poll; header dot / next poll handles recovery
    } finally {
        pollInFlight = false;
    }
}

function schedulePolling() {
    if (state.pollTimer) {
        clearTimeout(state.pollTimer);
        state.pollTimer = null;
    }
    if (!state.selectedSid || state.newSessionMode) return;

    const sess = getSelectedSession();
    const runState = recLib.deriveLiveRunState(state.records, sess);
    const active = Boolean(state.awaitingAgent || runState.isRunning);
    const intervalMs = active ? 1200 : 5000;

    state.pollTimer = setTimeout(async () => {
        await pollActiveSessionRecords();
        if (active) {
            await loadSessions({ silent: true });
        }
        schedulePolling();
    }, intervalMs);
}

// ══════════ Stream Rendering (Human / Activity / Agent / Decision Card) ══════════
function renderUserBubble(seg, isOptimistic = false) {
    const wrap = document.createElement("div");
    wrap.className = "msg-block msg-human";

    const bubble = document.createElement("div");
    bubble.className = `human-bubble ${isOptimistic ? "is-optimistic" : ""}`;

    const parsed = seg.parsed || {};
    const hasMeta =
        (parsed.employeeNames?.length > 0) ||
        (parsed.skillNames?.length > 0) ||
        parsed.command ||
        parsed.isAnswer ||
        seg.queued ||
        isOptimistic;

    if (hasMeta) {
        const meta = document.createElement("div");
        meta.className = "human-meta-row";
        if (isOptimistic) {
            const c = document.createElement("span");
            c.className = "msg-chip is-queued";
            c.textContent = "发送中…";
            meta.appendChild(c);
        } else if (seg.queued) {
            const c = document.createElement("span");
            c.className = "msg-chip is-queued";
            c.textContent = "排队消息";
            meta.appendChild(c);
        }
        if (parsed.isAnswer) {
            const c = document.createElement("span");
            c.className = "msg-chip is-answer";
            c.textContent = "决策回复";
            meta.appendChild(c);
        }
        if (parsed.command) {
            const c = document.createElement("span");
            c.className = "msg-chip";
            c.textContent = `/${parsed.command}`;
            meta.appendChild(c);
        }
        for (const emp of parsed.employeeNames || []) {
            const c = document.createElement("span");
            c.className = "msg-chip";
            c.textContent = `@${emp}`;
            meta.appendChild(c);
        }
        for (const sk of parsed.skillNames || []) {
            const c = document.createElement("span");
            c.className = "msg-chip is-skill";
            c.textContent = `/${sk}`;
            meta.appendChild(c);
        }
        bubble.appendChild(meta);
    }

    if (parsed.instruction) {
        const instr = document.createElement("div");
        instr.className = "human-instruction";
        instr.textContent = parsed.instruction;
        bubble.appendChild(instr);
    }

    if (Array.isArray(parsed.focusItems) && parsed.focusItems.length > 0) {
        const fq = document.createElement("div");
        fq.className = "focus-quotes";
        for (const f of parsed.focusItems) {
            const card = document.createElement("div");
            card.className = "focus-quote-chip";
            const title = document.createElement("div");
            title.className = "focus-quote-title";
            title.appendChild(createSvgIcon(f.kind === "element" ? "crosshair" : "scissors", 12));
            const titleSpan = document.createElement("span");
            titleSpan.textContent = f.title || "网页选区";
            title.appendChild(titleSpan);
            if (f.kindLabel) {
                const kindSpan = document.createElement("span");
                kindSpan.className = "focus-quote-kind";
                kindSpan.textContent = f.kindLabel;
                title.appendChild(kindSpan);
            }
            const body = document.createElement("div");
            body.className = "focus-quote-text";
            body.textContent = f.preview || f.body || "";
            card.appendChild(title);
            if (body.textContent) card.appendChild(body);
            fq.appendChild(card);
        }
        bubble.appendChild(fq);
    }

    if (Array.isArray(parsed.fullPagePages) && parsed.fullPagePages.length > 0) {
        const ctxKey = seg.key || `ctx-${parsed.fullPagePages[0].title}`;
        const box = document.createElement("div");
        box.className = "collapsed-ctx-box";

        const isOpen = state.expandedContextKeys.has(ctxKey);
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = `collapsed-ctx-toggle${isOpen ? " is-open" : ""}`;
        const firstPage = parsed.fullPagePages[0];
        const multiSuffix = parsed.fullPagePages.length > 1 ? ` 等 ${parsed.fullPagePages.length} 页` : "";

        const labelWrap = document.createElement("span");
        labelWrap.className = "collapsed-ctx-label";
        labelWrap.appendChild(createSvgIcon("fileText", 12));
        const titleEl = document.createElement("span");
        titleEl.className = "collapsed-ctx-title";
        titleEl.textContent = `${firstPage.title}${multiSuffix}`;
        const countEl = document.createElement("span");
        countEl.className = "collapsed-ctx-count";
        countEl.textContent = formatCharCount(firstPage.charCount);
        labelWrap.appendChild(titleEl);
        labelWrap.appendChild(countEl);

        const arrow = createSvgIcon("chevronRight", 12, "toggle-chevron");
        toggle.appendChild(labelWrap);
        toggle.appendChild(arrow);

        const body = document.createElement("div");
        body.className = `collapsed-ctx-body ${isOpen ? "" : "is-hidden"}`;
        body.textContent = parsed.rawFullPageText || "";

        toggle.addEventListener("click", () => {
            if (state.expandedContextKeys.has(ctxKey)) {
                state.expandedContextKeys.delete(ctxKey);
                body.classList.add("is-hidden");
                toggle.classList.remove("is-open");
            } else {
                state.expandedContextKeys.add(ctxKey);
                body.classList.remove("is-hidden");
                toggle.classList.add("is-open");
            }
        });

        box.appendChild(toggle);
        box.appendChild(body);
        bubble.appendChild(box);
    }

    const baseUrl = normalizeServerUrl(state.serverCfg.serverUrl);
    if (Array.isArray(parsed.images) && parsed.images.length > 0) {
        const imgs = document.createElement("div");
        imgs.className = "msg-images";
        for (const imgInfo of parsed.images) {
            if (imgInfo.dataUrl || imgInfo.apiPath) {
                const img = document.createElement("img");
                img.className = "msg-image-thumb";
                img.src = imgInfo.dataUrl || `${baseUrl}${imgInfo.apiPath}`;
                img.alt = imgInfo.name || "attachment";
                imgs.appendChild(img);
            }
        }
        if (imgs.childNodes.length > 0) {
            bubble.appendChild(imgs);
        }
    }

    wrap.appendChild(bubble);
    return wrap;
}

function renderDecisionCard(decision, key, answered) {
    const card = document.createElement("div");
    card.className = `decision-card ${answered ? "is-answered" : ""}`;

    let draft = state.decisionDrafts.get(key);
    if (!draft) {
        draft = { selected: new Set(), customText: "", submitting: false };
        state.decisionDrafts.set(key, draft);
    }

    const head = document.createElement("div");
    head.className = "decision-head";
    const badge = document.createElement("span");
    badge.className = "decision-badge";
    badge.appendChild(createSvgIcon(answered ? "checkCircle" : "zap", 12));
    const badgeText = document.createElement("span");
    badgeText.textContent = answered ? "已提交决定" : "等待拍板";
    badge.appendChild(badgeText);
    head.appendChild(badge);
    card.appendChild(head);

    const qEl = document.createElement("div");
    qEl.className = "decision-question";
    qEl.textContent = decision.question;
    card.appendChild(qEl);

    if (decision.context) {
        const ctxEl = document.createElement("div");
        ctxEl.className = "decision-context";
        ctxEl.textContent = decision.context;
        card.appendChild(ctxEl);
    }

    if (Array.isArray(decision.options) && decision.options.length > 0) {
        const optsWrap = document.createElement("div");
        optsWrap.className = "decision-options";
        for (const opt of decision.options) {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.disabled = answered || draft.submitting;
            btn.className = `decision-opt-btn ${draft.selected.has(opt.label) ? "is-picked" : ""}`;

            const inner = document.createElement("div");
            const lbl = document.createElement("div");
            lbl.className = "decision-opt-label";
            lbl.textContent = opt.label;
            inner.appendChild(lbl);
            if (opt.description) {
                const desc = document.createElement("div");
                desc.className = "decision-opt-desc";
                desc.textContent = opt.description;
                inner.appendChild(desc);
            }
            btn.appendChild(inner);

            btn.addEventListener("click", () => {
                if (draft.selected.has(opt.label)) {
                    draft.selected.delete(opt.label);
                    btn.classList.remove("is-picked");
                } else {
                    draft.selected.add(opt.label);
                    btn.classList.add("is-picked");
                }
                updateSubmitBtn();
            });
            optsWrap.appendChild(btn);
        }
        card.appendChild(optsWrap);
    }

    let customInput = null;
    if (!answered && decision.allowCustom !== false) {
        const row = document.createElement("div");
        row.className = "decision-custom-row";
        customInput = document.createElement("input");
        customInput.type = "text";
        customInput.className = "decision-custom-input";
        customInput.placeholder = "可选补充说明或自定义决定…";
        customInput.value = draft.customText;
        customInput.addEventListener("input", () => {
            draft.customText = customInput.value;
            updateSubmitBtn();
        });
        row.appendChild(customInput);
        card.appendChild(row);
    }

    let submitBtn = null;
    function updateSubmitBtn() {
        if (!submitBtn) return;
        const canSubmit = !answered && !draft.submitting && (draft.selected.size > 0 || draft.customText.trim().length > 0);
        submitBtn.disabled = !canSubmit;
        submitBtn.textContent = draft.submitting ? "提交中…" : "提交决定";
    }

    if (!answered) {
        submitBtn = document.createElement("button");
        submitBtn.type = "button";
        submitBtn.className = "btn btn-primary btn-xs";
        updateSubmitBtn();
        submitBtn.addEventListener("click", async () => {
            const answerText = recLib.composeAnswer(
                decision.question,
                Array.from(draft.selected),
                draft.customText
            );
            draft.submitting = true;
            updateSubmitBtn();
            try {
                await dispatchSessionMessage(answerText, { clearComposerDraft: false });
                state.decisionDrafts.delete(key);
            } catch (err) {
                draft.submitting = false;
                updateSubmitBtn();
                showToast(`决策提交失败：${err.message}`, "err");
            }
        });
        card.appendChild(submitBtn);
    }

    return card;
}

function renderActivitySegment(seg) {
    const wrap = document.createElement("div");
    wrap.className = "msg-block msg-activity";

    const parts = [];
    if (seg.toolCount > 0) parts.push(`${seg.toolCount} 次工具调用`);
    if (seg.thinkCount > 0) parts.push(`${seg.thinkCount} 次思考`);
    const summaryLabel = parts.join(" · ") || "执行过程";

    const isOpen = state.expandedActivityKeys.has(seg.key);
    const pill = document.createElement("button");
    pill.type = "button";
    pill.className = `activity-pill${isOpen ? " is-open" : ""}`;
    pill.appendChild(createSvgIcon("terminal", 12));
    const summarySpan = document.createElement("span");
    summarySpan.textContent = summaryLabel;
    pill.appendChild(summarySpan);
    pill.appendChild(createSvgIcon("chevronRight", 12, "toggle-chevron"));

    const details = document.createElement("div");
    details.className = `activity-details ${isOpen ? "" : "is-hidden"}`;
    for (const item of seg.items) {
        const row = document.createElement("div");
        row.className = "activity-row";
        const head = document.createElement("div");
        head.className = `activity-row-head${item.isError ? " is-err" : ""}`;
        if (item.kind === "tool.call") {
            head.appendChild(createSvgIcon("wrench", 12));
            const txt = document.createElement("span");
            txt.textContent = item.name;
            head.appendChild(txt);
        } else if (item.kind === "tool.result") {
            head.appendChild(createSvgIcon(item.isError ? "alertCircle" : "checkCircle", 12));
            const txt = document.createElement("span");
            txt.textContent = item.isError ? "工具返回错误" : "工具结果";
            head.appendChild(txt);
        } else {
            head.appendChild(createSvgIcon("thought", 12));
            const txt = document.createElement("span");
            txt.textContent = "思考";
            head.appendChild(txt);
        }
        row.appendChild(head);
        const bodyText = item.detail || item.text || "";
        if (bodyText) {
            const body = document.createElement("div");
            body.className = "activity-row-body";
            body.textContent = bodyText;
            row.appendChild(body);
        }
        details.appendChild(row);
    }

    pill.addEventListener("click", () => {
        if (state.expandedActivityKeys.has(seg.key)) {
            state.expandedActivityKeys.delete(seg.key);
            details.classList.add("is-hidden");
            pill.classList.remove("is-open");
        } else {
            state.expandedActivityKeys.add(seg.key);
            details.classList.remove("is-hidden");
            pill.classList.add("is-open");
        }
    });

    wrap.appendChild(pill);
    wrap.appendChild(details);

    if (seg.decision) {
        wrap.appendChild(renderDecisionCard(seg.decision, seg.key, seg.decisionAnswered));
    }
    return wrap;
}

// ══════════ Citation Popover, 8093 Sandbox File Preview & External Modal ══════════
function syncActiveCiteClasses(citeId) {
    state.activeCiteId = citeId || null;
    if (!el.chatStream) return;
    el.chatStream.querySelectorAll("[data-cite-id]").forEach((node) => {
        if (citeId && node.getAttribute("data-cite-id") === citeId) {
            node.classList.add("active");
        } else {
            node.classList.remove("active");
        }
    });
}

function hideCitePopover() {
    if (state.citePopTimer) {
        clearTimeout(state.citePopTimer);
        state.citePopTimer = null;
    }
    if (el.citePopover) el.citePopover.classList.add("is-hidden");
}

function scheduleHideCitePopover() {
    if (state.citePopTimer) clearTimeout(state.citePopTimer);
    state.citePopTimer = setTimeout(() => {
        hideCitePopover();
    }, 120);
}

function showCitePopover(def, anchorEl) {
    if (!def || !el.citePopover || !anchorEl) return;
    if (state.citePopTimer) {
        clearTimeout(state.citePopTimer);
        state.citePopTimer = null;
    }
    const isWeb = def.kind === "web";
    el.citePopBadge.textContent = `[${def.label}]`;
    el.citePopBadge.classList.toggle("web", isWeb);
    el.citePopTitle.textContent = def.title || def.uri;
    el.citePopPath.textContent = isWeb
        ? def.uri
        : `${def.filePath || ""}${def.line ? `#${def.line}` : ""}`;
    if (def.excerpt) {
        el.citePopExcerpt.textContent = def.excerpt;
        el.citePopExcerpt.classList.remove("is-hidden");
    } else {
        el.citePopExcerpt.textContent = "";
        el.citePopExcerpt.classList.add("is-hidden");
    }
    el.citePopHint.textContent = isWeb ? "点击后弹窗确认并打开外部网页 ↗" : "点击通过本机服务预览对应源码";

    el.citePopover.classList.remove("is-hidden");
    const rect = anchorEl.getBoundingClientRect();
    const popRect = el.citePopover.getBoundingClientRect();
    const vw = window.innerWidth || 380;
    const vh = window.innerHeight || 640;
    const left = Math.max(8, Math.min(rect.left, vw - popRect.width - 8));
    const preferBelow = rect.bottom + 8 + popRect.height <= vh - 8;
    const top = preferBelow ? rect.bottom + 6 : Math.max(8, rect.top - popRect.height - 6);
    el.citePopover.style.left = `${left}px`;
    el.citePopover.style.top = `${top}px`;
}

function closeCiteDrawer() {
    state.citeDrawerReqId += 1;
    if (el.citePreviewDrawer) el.citePreviewDrawer.classList.add("is-hidden");
    syncActiveCiteClasses(null);
}

function openCiteExtModal(def) {
    if (!def || !el.citeExtModal) return;
    hideCitePopover();
    state.citeExtDef = def;
    syncActiveCiteClasses(def.id);
    el.citeExtTitle.textContent = `[${def.label}] ${def.title || "外部来源"}`;
    el.citeExtUrl.textContent = def.uri;
    if (def.excerpt) {
        el.citeExtExcerpt.textContent = def.excerpt;
        el.citeExtExcerpt.classList.remove("is-hidden");
    } else {
        el.citeExtExcerpt.textContent = "";
        el.citeExtExcerpt.classList.add("is-hidden");
    }
    el.citeExtModal.classList.remove("is-hidden");
}

function closeCiteExtModal() {
    state.citeExtDef = null;
    if (el.citeExtModal) el.citeExtModal.classList.add("is-hidden");
    if (el.citePreviewDrawer?.classList.contains("is-hidden")) {
        syncActiveCiteClasses(null);
    }
}

function closeAllCitations() {
    hideCitePopover();
    closeCiteExtModal();
    closeCiteDrawer();
}

function renderCiteDrawerError(msg) {
    el.citeDrawerBody.innerHTML = "";
    const box = document.createElement("div");
    box.className = "cite-drawer-state is-err";
    box.textContent = msg;
    el.citeDrawerBody.appendChild(box);
}

async function openFilePreviewDrawer({ mode, def = null, path = "", line = "" }) {
    const sid = state.selectedSid;
    const targetPath = def ? def.filePath : path;
    const targetLine = def ? def.line : line;
    if (!sid || !targetPath) {
        showToast("当前未选中会话或文件路径无效", "err");
        return;
    }

    hideCitePopover();
    syncActiveCiteClasses(def ? def.id : null);

    const fileName = targetPath.split("/").pop() || targetPath;
    el.citeDrawerTitle.textContent = def ? `[${def.label}] ${def.title || fileName}` : fileName;
    el.citeDrawerPath.textContent = targetLine ? `${targetPath}#${targetLine}` : targetPath;

    el.citeDrawerBanner.className = `cite-drawer-banner ${mode === "cite" ? "cite-mode" : "file-mode"}`;
    if (mode === "cite") {
        const rangeLabel = targetLine ? `（已定位 ${targetLine}）` : "";
        const excerptTxt = def?.excerpt ? `：${def.excerpt}` : "";
        el.citeDrawerBanner.textContent = `句段核实模式${rangeLabel}${excerptTxt}`;
    } else {
        el.citeDrawerBanner.textContent = targetLine
            ? `全文预览模式（目标行 ${targetLine}，未进入句段核实）`
            : "全文预览模式（经 8093 鉴权沙箱只读加载）";
    }
    el.citeDrawerBanner.classList.remove("is-hidden");

    el.citeDrawerBody.innerHTML = "";
    const loadingBox = document.createElement("div");
    loadingBox.className = "cite-drawer-state";
    loadingBox.textContent = "正在通过本机服务加载文件内容…";
    el.citeDrawerBody.appendChild(loadingBox);
    el.citePreviewDrawer.classList.remove("is-hidden");

    const reqId = ++state.citeDrawerReqId;
    try {
        // Strictly fetch via 8093 authenticated sandbox endpoint; never open file:// directly.
        const data = await getSessionFileContent(state.serverCfg, sid, targetPath, "cited");
        if (reqId !== state.citeDrawerReqId || state.selectedSid !== sid) return;

        if (data?.too_large) {
            renderCiteDrawerError("文件体积超过预览上限，请在 WebUI 或本地编辑器中查看。");
            return;
        }
        if (data?.is_text === false || typeof data?.text !== "string") {
            renderCiteDrawerError("该文件为二进制或非文本格式，无法在此预览。");
            return;
        }

        const range = mode === "cite" ? md.parseLineAnchorRange(targetLine) : null;
        const lines = data.text.split(/\r\n|\n|\r/);
        const table = document.createElement("div");
        table.className = "cite-code-table";
        let firstHighlightedEl = null;

        for (let idx = 0; idx < lines.length; idx += 1) {
            const lineNum = idx + 1;
            const isHl = Boolean(range && lineNum >= range.startLine && lineNum <= range.endLine);
            const row = document.createElement("div");
            row.className = `cite-code-line${isHl ? " hl" : ""}`;
            row.setAttribute("data-line", String(lineNum));
            if (isHl && !firstHighlightedEl) firstHighlightedEl = row;

            const ln = document.createElement("span");
            ln.className = "cite-ln";
            ln.textContent = String(lineNum);

            const lc = document.createElement("span");
            lc.className = "cite-lc";
            lc.textContent = lines[idx] || " ";

            row.appendChild(ln);
            row.appendChild(lc);
            table.appendChild(row);
        }

        el.citeDrawerBody.innerHTML = "";
        el.citeDrawerBody.appendChild(table);
        if (firstHighlightedEl && typeof firstHighlightedEl.scrollIntoView === "function") {
            firstHighlightedEl.scrollIntoView({ block: "center" });
        }
    } catch (err) {
        if (reqId !== state.citeDrawerReqId) return;
        const status = err?.status || 0;
        if (status === 401 || status === 403) {
            renderCiteDrawerError(`权限或沙箱校验未通过（${status}）：${err.detail || err.message}`);
        } else if (status === 404) {
            renderCiteDrawerError("目标文件不存在或未在本会话上下文中引用。");
        } else {
            renderCiteDrawerError(`文件预览失败：${err?.message || "未知错误"}`);
        }
    }
}

function handleCitationClick(def) {
    if (!def || def.kind === "invalid") return;
    if (def.kind === "web") {
        openCiteExtModal(def);
        return;
    }
    openFilePreviewDrawer({ mode: "cite", def });
}

function renderAgentSegment(seg, { isStreaming = false } = {}) {
    const wrap = document.createElement("div");
    wrap.className = "msg-block msg-agent";

    const bubble = document.createElement("div");
    bubble.className = `agent-bubble ${seg.subagent ? "is-subagent" : ""}`;

    if (seg.subagent && seg.record?.agent_path?.length) {
        const tag = document.createElement("div");
        tag.className = "agent-role-tag";
        tag.appendChild(createSvgIcon("cornerDownRight", 11));
        const tagTxt = document.createElement("span");
        tagTxt.textContent = `子任务 · ${seg.record.agent_path.join(" / ")}`;
        tag.appendChild(tagTxt);
        bubble.appendChild(tag);
    }

    if (seg.bodyText) {
        const mdContainer = document.createElement("div");
        mdContainer.className = "md-body";
        md.renderMarkdown(seg.bodyText, mdContainer, document, {
            streaming: isStreaming,
            activeCiteId: state.activeCiteId,
            onCiteHover: (def, anchor) => showCitePopover(def, anchor),
            onCiteLeave: () => scheduleHideCitePopover(),
            onCiteClick: (def) => handleCitationClick(def),
            onFileLinkClick: ({ path, line }) => openFilePreviewDrawer({ mode: "file", path, line }),
        });
        bubble.appendChild(mdContainer);
    }

    if (seg.decision) {
        bubble.appendChild(renderDecisionCard(seg.decision, seg.key, seg.decisionAnswered));
    }

    wrap.appendChild(bubble);
    return wrap;
}

function computeStreamSignature() {
    const lastRec = state.records[state.records.length - 1];
    const sess = getSelectedSession();
    return [
        state.selectedSid,
        state.newSessionMode ? "new" : "chat",
        state.pendingHandle || "",
        state.recordsLoading ? "loading" : "ready",
        state.recordsError || "",
        state.records.length,
        lastRec?.id || "",
        lastRec?.seq ?? -1,
        state.optimisticMessages.map((m) => m.id).join(","),
        sess?.status || "",
        sess?.need_decision ? "1" : "0",
        state.awaitingAgent ? "1" : "0",
        !state.selectedSid ? state.sessions.slice(0, 4).map((s) => s.session_id).join(",") : "",
    ].join("|");
}

function renderChatStream({ force = false } = {}) {
    const sig = computeStreamSignature();
    const sess = getSelectedSession();
    const runState = recLib.deriveLiveRunState(state.records, sess);

    // Update live status bar even when records signature didn't change
    if (state.pendingHandle) {
        el.liveStatusRow.classList.remove("is-hidden");
        el.liveStatusText.textContent = "正在启动新会话并认领 session_id…";
    } else if (state.selectedSid && (runState.isRunning || state.awaitingAgent)) {
        el.liveStatusRow.classList.remove("is-hidden");
        el.liveStatusText.textContent = runState.latestActivityLabel || "Agent 正在思考并生成回复…";
    } else {
        el.liveStatusRow.classList.add("is-hidden");
    }

    if (!force && sig === state.lastStreamSignature) {
        return;
    }
    state.lastStreamSignature = sig;

    const stream = el.chatStream;
    const prevScrollTop = stream.scrollTop;
    stream.innerHTML = "";

    // Empty / Unbound state
    if (!state.selectedSid && !state.optimisticMessages.length && !state.pendingHandle) {
        const empty = document.createElement("div");
        empty.className = "stream-empty";
        const t = document.createElement("div");
        t.className = "empty-title";
        t.textContent = state.newSessionMode
            ? "在下方输入首条消息即可创建新会话"
            : "选择一个会话，或点击顶部「+ 新建」";
        const d = document.createElement("div");
        d.className = "empty-desc";
        d.textContent = "发送后消息会立刻上屏，Agent 回复、工具进度和决策拍板都会直接在这里实时显示。";
        empty.appendChild(t);
        empty.appendChild(d);

        if (!state.newSessionMode && state.sessions.length > 0) {
            const quick = document.createElement("div");
            quick.className = "empty-quick-list";
            const recent = state.sessions
                .filter((s) => s.origin !== "worker" && s.origin !== "subagent")
                .slice(0, 4);
            for (const s of recent) {
                const btn = document.createElement("button");
                btn.type = "button";
                btn.className = "quick-session-btn";
                const left = document.createElement("span");
                left.className = "session-item-title";
                left.textContent = formatSessionTitle(s) || s.session_id.slice(0, 8);
                const right = document.createElement("span");
                right.className = "ctx-meta";
                right.textContent = formatRelativeTime(s.last_active_at);
                btn.appendChild(left);
                btn.appendChild(right);
                btn.addEventListener("click", () => selectSession(s.session_id));
                quick.appendChild(btn);
            }
            empty.appendChild(quick);
        }
        stream.appendChild(empty);
        return;
    }

    if (state.recordsLoading && state.records.length === 0) {
        const loading = document.createElement("div");
        loading.className = "drawer-empty";
        loading.textContent = "正在加载会话消息流…";
        stream.appendChild(loading);
    }

    if (state.recordsError) {
        const errEl = document.createElement("div");
        errEl.className = "msg-error";
        errEl.textContent = `会话消息读取失败：${state.recordsError}`;
        stream.appendChild(errEl);
    }

    const segments = recLib.buildChatSegments(state.records);
    const streamActive = Boolean(state.selectedSid && (runState.isRunning || state.awaitingAgent));
    let lastAgentIdx = -1;
    for (let idx = segments.length - 1; idx >= 0; idx -= 1) {
        if (segments[idx].type === "agent.say") {
            lastAgentIdx = idx;
            break;
        }
    }
    for (let idx = 0; idx < segments.length; idx += 1) {
        const seg = segments[idx];
        if (seg.type === "user.say") {
            stream.appendChild(renderUserBubble(seg, false));
        } else if (seg.type === "activity") {
            stream.appendChild(renderActivitySegment(seg));
        } else if (seg.type === "agent.say") {
            stream.appendChild(renderAgentSegment(seg, { isStreaming: streamActive && idx === lastAgentIdx }));
        } else if (seg.type === "notice") {
            const box = document.createElement("div");
            box.className = "msg-notice";
            box.textContent = `${seg.title}${seg.status ? ` (${seg.status})` : ""}${seg.text ? `\n${seg.text.slice(0, 240)}` : ""}`;
            stream.appendChild(box);
        } else if (seg.type === "error") {
            const box = document.createElement("div");
            box.className = "msg-error";
            box.textContent = seg.text;
            stream.appendChild(box);
        }
    }

    for (const opt of state.optimisticMessages) {
        stream.appendChild(renderUserBubble(opt, true));
    }

    if (state.stickToBottom) {
        stream.scrollTop = stream.scrollHeight;
    } else {
        stream.scrollTop = prevScrollTop;
    }
}

// ══════════ Context Bar & Lightweight Attachment Pills ══════════
function renderContextBar() {
    const enabled = state.draft.includeFullPage !== false;
    el.toggleFullpageBtn.classList.toggle("is-active", enabled);
    if (state.activePage) {
        const chars = state.activePage.charCount || state.activePage.markdown?.length || 0;
        const ultra = chars > 30_000 ? " · .md" : "";
        el.fullpageCharsBadge.textContent = `${formatCharCount(chars)}${ultra}`;
    } else {
        el.fullpageCharsBadge.textContent = enabled ? "无正文" : "已关";
    }
    updateSendButtonState();
}

function renderAttachmentPills() {
    const focuses = state.draft.focusItems || [];
    const shots = state.draft.screenshots || [];
    el.attachmentPills.innerHTML = "";

    if (focuses.length === 0 && shots.length === 0) {
        el.attachmentPills.classList.add("is-hidden");
        updateSendButtonState();
        return;
    }

    el.attachmentPills.classList.remove("is-hidden");

    focuses.forEach((item, idx) => {
        const pill = document.createElement("span");
        pill.className = "attach-pill";
        pill.title = `${item.title || "网页选区"}\n${item.url || ""}`;

        const iconSvg = createSvgIcon(item.kind === "element" ? "crosshair" : "scissors", 12, "attach-pill-icon");
        const preview = String(item.text || item.markdown || "").replace(/\s+/g, " ").trim().slice(0, 36);
        const textSpan = document.createElement("span");
        textSpan.className = "attach-pill-text";
        textSpan.textContent = preview || item.title || "选区";

        const rm = document.createElement("button");
        rm.type = "button";
        rm.className = "attach-pill-remove";
        rm.appendChild(createSvgIcon("x", 11));
        rm.title = "移除";
        rm.setAttribute("aria-label", "移除");
        rm.addEventListener("click", async () => {
            state.draft.focusItems.splice(idx, 1);
            await saveDraft(state.draft);
            renderAttachmentPills();
        });

        pill.appendChild(iconSvg);
        pill.appendChild(textSpan);
        pill.appendChild(rm);
        el.attachmentPills.appendChild(pill);
    });

    shots.forEach((shot, idx) => {
        const pill = document.createElement("span");
        pill.className = "attach-pill";

        const img = document.createElement("img");
        img.className = "attach-pill-thumb";
        img.src = shot.dataUrl;
        img.alt = "screenshot";

        const textSpan = document.createElement("span");
        textSpan.className = "attach-pill-text";
        textSpan.textContent = `截图 ${idx + 1}`;

        const rm = document.createElement("button");
        rm.type = "button";
        rm.className = "attach-pill-remove";
        rm.appendChild(createSvgIcon("x", 11));
        rm.title = "移除";
        rm.setAttribute("aria-label", "移除");
        rm.addEventListener("click", async () => {
            state.draft.screenshots.splice(idx, 1);
            await saveDraft(state.draft);
            renderAttachmentPills();
        });

        pill.appendChild(img);
        pill.appendChild(textSpan);
        pill.appendChild(rm);
        el.attachmentPills.appendChild(pill);
    });

    updateSendButtonState();
}

function updateSendButtonState() {
    const hasText = Boolean(el.instructionInput.value.trim());
    const hasAttachments =
        (state.draft.focusItems?.length || 0) > 0 ||
        (state.draft.screenshots?.length || 0) > 0;
    const hasPage = state.draft.includeFullPage !== false && Boolean(state.activePage?.markdown?.trim());
    const canSend = (hasText || hasAttachments || hasPage) && !state.pendingHandle;
    el.sendBtn.disabled = !canSend;
}

// ══════════ Lightweight New Session Config Bar ══════════
async function loadNewSessionMetadata() {
    try {
        const [empResp, agentsResp, dirsResp] = await Promise.all([
            listEmployees(state.serverCfg).catch(() => ({ employees: [] })),
            listWorkbenchAgents(state.serverCfg).catch(() => ({ agents: [], default: "" })),
            getSystemDirectories(state.serverCfg).catch(() => ({})),
        ]);
        state.employees = Array.isArray(empResp?.employees) ? empResp.employees : (Array.isArray(empResp) ? empResp : []);
        state.agents = Array.isArray(agentsResp?.agents) ? agentsResp.agents : [];
        state.defaultAgent = agentsResp?.default || "";
        state.defaultCwd = dirsResp?.cwd || dirsResp?.home || dirsResp?.default_cwd || "";

        if (!el.cwdInput.value && (state.settings.lastNewSessionCwd || state.defaultCwd)) {
            el.cwdInput.value = state.settings.lastNewSessionCwd || state.defaultCwd;
        }
        renderNewSessionBar();
    } catch (_) { /* ignore */ }
}

function isAgentSelectable(ag) {
    if (!ag) return false;
    if (typeof ag.selectable === "boolean") return ag.selectable;
    if (typeof ag.available === "boolean") return ag.available;
    return Boolean(ag.installed);
}

function renderNewSessionBar() {
    el.employeeChips.innerHTML = "";
    const noneChip = document.createElement("button");
    noneChip.type = "button";
    noneChip.className = `emp-chip ${!state.selectedEmployeeId ? "is-active" : ""}`;
    noneChip.textContent = "普通会话";
    noneChip.addEventListener("click", () => applyEmployeeSelection(""));
    el.employeeChips.appendChild(noneChip);

    for (const emp of state.employees) {
        const empId = emp.member_post_id || emp.id || "";
        if (!empId) continue;
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = `emp-chip ${state.selectedEmployeeId === empId ? "is-active" : ""}`;
        chip.textContent = emp.title || empId;
        chip.addEventListener("click", () => applyEmployeeSelection(empId));
        el.employeeChips.appendChild(chip);
    }

    el.agentSelect.innerHTML = "";
    for (const ag of state.agents) {
        const opt = document.createElement("option");
        const selectable = isAgentSelectable(ag);
        const label = ag.display_name || ag.label || ag.agent_type;
        opt.value = ag.agent_type;
        opt.textContent = selectable ? label : `${label} (不可用)`;
        opt.disabled = !selectable;
        el.agentSelect.appendChild(opt);
    }
    const preferredAgent = state.settings.lastAgent || state.defaultAgent;
    if (preferredAgent && Array.from(el.agentSelect.options).some((o) => o.value === preferredAgent && !o.disabled)) {
        el.agentSelect.value = preferredAgent;
    } else {
        const firstEnabled = Array.from(el.agentSelect.options).find((o) => !o.disabled);
        if (firstEnabled) el.agentSelect.value = firstEnabled.value;
    }
    updateAgentHint();
}

function applyEmployeeSelection(empId) {
    state.selectedEmployeeId = empId || "";
    saveBridgeSettings({ lastEmployeeId: state.selectedEmployeeId }).catch(() => {});
    const emp = state.employees.find((e) => (e.member_post_id || e.id) === state.selectedEmployeeId);
    if (emp) {
        const empAgent = emp.agent_kernel || emp.default_agent;
        const empCwd = emp.cwd || emp.default_cwd;
        if (empAgent && Array.from(el.agentSelect.options).some((o) => o.value === empAgent && !o.disabled)) {
            el.agentSelect.value = empAgent;
        }
        if (empCwd) {
            el.cwdInput.value = empCwd;
        }
    }
    renderNewSessionBar();
}

function updateAgentHint() {
    const chosen = state.agents.find((a) => a.agent_type === el.agentSelect.value);
    if (chosen && !isAgentSelectable(chosen) && chosen.reason) {
        el.agentHint.textContent = chosen.reason;
        el.agentHint.classList.remove("is-hidden");
    } else {
        el.agentHint.classList.add("is-hidden");
    }
}

async function openDirectoryBrowser(path = "") {
    try {
        const res = await browseSystemDirectories(state.serverCfg, path);
        state.currentBrowsePath = res.current || res.path || path;
        state.parentBrowsePath = res.parent || "";
        el.dirCurrentPath.textContent = state.currentBrowsePath || "~";
        el.dirEntries.innerHTML = "";
        for (const entry of res.entries || []) {
            const item = document.createElement("button");
            item.type = "button";
            item.className = "dir-entry";
            item.appendChild(createSvgIcon("folder", 12));
            const label = document.createElement("span");
            label.textContent = entry.name;
            item.appendChild(label);
            item.addEventListener("click", () => openDirectoryBrowser(entry.path));
            el.dirEntries.appendChild(item);
        }
        el.dirBrowser.classList.remove("is-hidden");
    } catch (err) {
        showToast(`目录读取失败：${err.message}`, "err");
    }
}

function enterNewSessionMode() {
    el.sessionDrawer.classList.add("is-hidden");
    state.newSessionMode = true;
    state.selectedSid = "";
    state.records = [];
    state.optimisticMessages = [];
    state.lastStreamSignature = "";
    el.newSessionBar.classList.remove("is-hidden");
    renderHeader();
    renderChatStream({ force: true });
    el.instructionInput.focus();
}

function exitNewSessionMode() {
    state.newSessionMode = false;
    el.newSessionBar.classList.add("is-hidden");
    renderHeader();
    renderChatStream({ force: true });
}

// ══════════ Sending Messages & Live Chat Loop ══════════
async function dispatchSessionMessage(overrideText = null, { clearComposerDraft = true } = {}) {
    if (!state.connOk) {
        const ok = await checkConnection();
        if (!ok) {
            showToast("未连接到 Frago Server，请先检查服务状态", "err");
            return;
        }
    }

    // Build payload
    let text = "";
    let images = [];
    let documents = [];
    let optimisticParsed = null;

    if (overrideText !== null) {
        text = String(overrideText).trim();
        if (!text) return;
        optimisticParsed = recLib.parseUserSayPayload({ text });
    } else {
        const includeFull = state.draft.includeFullPage !== false;
        if (includeFull && (!state.activePage || !state.activePage.markdown)) {
            await refreshActivePage({ silent: true });
        }
        const rawInstruction = el.instructionInput.value.trim();
        const hasFocus = (state.draft.focusItems?.length || 0) > 0;
        const hasShots = (state.draft.screenshots?.length || 0) > 0;
        const hasPage = includeFull && Boolean(state.activePage?.markdown?.trim());

        const effectiveInstruction = (!rawInstruction && !hasFocus && !hasPage && hasShots)
            ? "请查看附带的网页截图。"
            : rawInstruction;

        const composed = composer.composeBridgePayload({
            instruction: effectiveInstruction,
            focusItems: state.draft.focusItems,
            includeFullPage: includeFull,
            activePage: state.activePage,
            pageSnapshots: state.draft.pageSnapshots,
        });

        if (!composed.ok) {
            showToast(composed.error || "请输入消息或附带网页内容", "err");
            return;
        }
        text = composed.text;
        documents = composed.documents || [];
        images = (state.draft.screenshots || []).map((s) => s.dataUrl).filter(Boolean);
        optimisticParsed = recLib.parseUserSayPayload({ text });
        if (images.length > 0) {
            optimisticParsed.images = images.map((dataUrl, i) => ({
                name: `screenshot-${i + 1}.png`,
                dataUrl,
            }));
        }
    }

    // Clear attachment pills & input immediately for responsive chat feel
    if (clearComposerDraft) {
        state.draft.focusItems = [];
        state.draft.screenshots = [];
        state.draft.instruction = "";
        el.instructionInput.value = "";
        autoResizeTextarea();
        await saveDraft(state.draft);
        renderAttachmentPills();
    }

    const lastSeq = state.records.length > 0 ? (state.records[state.records.length - 1]?.seq ?? -1) : -1;
    const optId = `opt-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    const needleSource = (optimisticParsed?.instruction || text).replace(/\s+/g, " ").trim();
    state.optimisticMessages.push({
        id: optId,
        key: optId,
        afterSeq: lastSeq,
        needle: needleSource.slice(0, 40),
        parsed: optimisticParsed,
    });
    state.awaitingAgent = true;
    state.awaitingSinceSeq = lastSeq;
    state.stickToBottom = true;

    // 1. New Session Flow
    if (state.newSessionMode || !state.selectedSid) {
        const agent = el.agentSelect.value || state.defaultAgent || "claude";
        const cwd = el.cwdInput.value.trim() || state.defaultCwd || "";
        await saveBridgeSettings({ lastNewSessionCwd: cwd, lastAgent: agent });

        state.newSessionMode = false;
        el.newSessionBar.classList.add("is-hidden");
        renderHeader();
        renderChatStream({ force: true });
        scrollStreamToBottom(true);

        const created = await createWorkbenchSession(state.serverCfg, {
            agent,
            cwd,
            text,
            images,
            documents,
            employee: state.selectedEmployeeId || "",
        });

        if (created?.session_id) {
            await loadSessions({ silent: true });
            await selectSession(created.session_id, { closeDrawer: true });
            const hasReply = state.records.some(
                (r) => r && r.kind === "agent.say" && (r.seq ?? 0) > state.awaitingSinceSeq
            );
            state.awaitingAgent = !hasReply;
            renderHeader();
            renderChatStream();
            schedulePolling();
            return;
        }

        if (created?.handle) {
            state.pendingHandle = created.handle;
            renderChatStream({ force: true });
            await waitForPendingSessionClaim(created.handle);
            return;
        }

        throw new Error("服务端未返回 session_id 或 handle");
    }

    // 2. Existing Session Flow
    const targetSid = state.selectedSid;
    renderHeader();
    renderChatStream({ force: true });
    scrollStreamToBottom(true);
    schedulePolling();

    // Send with wait=true (matching WebUI), while WS + 1.2s polling stream live updates immediately
    sendToWorkbenchSession(state.serverCfg, targetSid, {
        text,
        images,
        documents,
        wait: true,
    })
        .then(async (res) => {
            if (state.selectedSid === targetSid) {
                await pollActiveSessionRecords({ force: true });
                if (res?.status !== "queued") {
                    state.awaitingAgent = false;
                    renderHeader();
                    renderChatStream();
                }
                schedulePolling();
            }
        })
        .catch((err) => {
            if (state.selectedSid === targetSid) {
                state.optimisticMessages = state.optimisticMessages.filter((m) => m.id !== optId);
                state.awaitingAgent = false;
                renderHeader();
                renderChatStream({ force: true });
            }
            showToast(`发送失败：${err.message}`, "err");
        });
}

async function waitForPendingSessionClaim(handle) {
    const start = Date.now();
    while (state.pendingHandle === handle && Date.now() - start < 90_000) {
        try {
            const res = await pollPendingWorkbenchSession(state.serverCfg, handle);
            if (res?.session_id) {
                state.pendingHandle = null;
                await loadSessions({ silent: true });
                await selectSession(res.session_id, { closeDrawer: true });
                const hasReply = state.records.some(
                    (r) => r && r.kind === "agent.say" && (r.seq ?? 0) > state.awaitingSinceSeq
                );
                state.awaitingAgent = !hasReply;
                renderHeader();
                renderChatStream();
                schedulePolling();
                return;
            }
            if (res?.status === "failed" || res?.error) {
                state.pendingHandle = null;
                state.awaitingAgent = false;
                renderChatStream({ force: true });
                showToast(`新会话启动失败：${res.error || "未知错误"}`, "err");
                return;
            }
        } catch (_) { /* keep polling */ }
        await new Promise((r) => setTimeout(r, 650));
    }
    if (state.pendingHandle === handle) {
        state.pendingHandle = null;
        state.awaitingAgent = false;
        renderChatStream({ force: true });
        showToast("等待新会话认领超时，请刷新会话列表查看", "err");
    }
}

// ══════════ Webpage Capture Tools ══════════
async function onPickElement() {
    const tab = await getActiveBrowserTab();
    if (!tab || tab.id == null) {
        showToast("未找到当前网页标签页", "err");
        return;
    }
    const resp = await sendRuntimeMessage({
        type: "frago.bridge.ensureTabInjected",
        tabId: tab.id,
        payload: { type: "frago.bridge.startPicker" },
    });
    if (resp && resp.ok) {
        showToast("请在网页上悬停区块并点击带入对话（↑/↓ 调层级，Esc 退出）", "info");
    } else {
        showToast(resp?.error || "当前页面无法启动区块拾取器", "err");
    }
}

async function onCaptureSelection() {
    const tab = await getActiveBrowserTab();
    if (!tab || tab.id == null) {
        showToast("未找到当前网页标签页", "err");
        return;
    }
    const resp = await sendRuntimeMessage({
        type: "frago.bridge.ensureTabInjected",
        tabId: tab.id,
        payload: { type: "frago.bridge.captureSelection" },
    });
    if (!resp || !resp.ok || !resp.focus) {
        showToast(resp?.error || "请先在网页中划词选中一段文本", "err");
        return;
    }
    const addResp = await sendRuntimeMessage({
        type: "frago.bridge.addFocus",
        focus: resp.focus,
        pageSnapshot: resp.pageSnapshot || null,
    });
    if (addResp && addResp.ok && addResp.draft) {
        state.draft = normalizeDraft(addResp.draft);
        renderAttachmentPills();
        showToast("已将选中内容带入对话", "ok");
    }
}

async function onCaptureScreenshot() {
    const resp = await sendRuntimeMessage({ type: "frago.bridge.captureScreenshot" });
    if (!resp || !resp.ok || !resp.screenshot) {
        showToast(resp?.error || "截图失败（请确保当前标签页为普通网页）", "err");
        return;
    }
    state.draft.screenshots = [...(state.draft.screenshots || []), resp.screenshot].slice(0, 6);
    await saveDraft(state.draft);
    renderAttachmentPills();
    showToast("已附带当前窗口截图", "ok");
}

// ══════════ Event Wiring ══════════
function bindEvents() {
    // Header & Popovers
    el.sessionPickerBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        el.settingsDrawer.classList.add("is-hidden");
        const willOpen = el.sessionDrawer.classList.contains("is-hidden");
        el.sessionDrawer.classList.toggle("is-hidden");
        if (willOpen) {
            loadSessions({ silent: true });
            el.sessionSearchInput.focus();
        }
    });

    el.toggleSettingsBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        el.sessionDrawer.classList.add("is-hidden");
        const willOpen = el.settingsDrawer.classList.contains("is-hidden");
        el.settingsDrawer.classList.toggle("is-hidden");
        if (willOpen) refreshDiagnostics();
    });

    document.addEventListener("click", (e) => {
        if (!el.sessionDrawer.contains(e.target) && !el.sessionPickerBtn.contains(e.target)) {
            el.sessionDrawer.classList.add("is-hidden");
        }
        if (!el.settingsDrawer.contains(e.target) && !el.toggleSettingsBtn.contains(e.target)) {
            el.settingsDrawer.classList.add("is-hidden");
        }
    });

    el.newSessionBtn.addEventListener("click", () => {
        if (state.newSessionMode) {
            exitNewSessionMode();
        } else {
            enterNewSessionMode();
            loadNewSessionMetadata();
        }
    });
    el.cancelNewSessionBtn.addEventListener("click", exitNewSessionMode);

    el.stopSessionBtn.addEventListener("click", async () => {
        if (!state.selectedSid) return;
        try {
            const res = await stopWorkbenchSession(state.serverCfg, state.selectedSid, { force: false });
            if (res?.alive && !res.stopped && res.busy) {
                await stopWorkbenchSession(state.serverCfg, state.selectedSid, { force: true });
            }
            state.awaitingAgent = false;
            showToast("已发送停止信号", "ok");
            await loadSessions({ silent: true });
            await pollActiveSessionRecords({ force: true });
        } catch (err) {
            showToast(`停止失败：${err.message}`, "err");
        }
    });

    el.openWebuiBtn.addEventListener("click", async () => {
        if (!state.selectedSid) return;
        const baseUrl = normalizeServerUrl(state.serverCfg.serverUrl);
        await sendRuntimeMessage({
            type: "frago.bridge.openWebuiSession",
            baseUrl,
            url: `${baseUrl}/#/sessions/${encodeURIComponent(state.selectedSid)}`,
        });
    });

    // Session Switcher Filter/Search
    el.sessionSearchInput.addEventListener("input", () => {
        state.sessionSearch = el.sessionSearchInput.value;
        renderSessionList();
    });
    el.refreshSessionsBtn.addEventListener("click", () => loadSessions());
    el.showWorkersCheckbox.addEventListener("change", () => {
        state.showWorkers = el.showWorkersCheckbox.checked;
        renderSessionList();
    });
    document.querySelectorAll(".filter-pill").forEach((pill) => {
        pill.addEventListener("click", () => {
            document.querySelectorAll(".filter-pill").forEach((p) => p.classList.remove("is-active"));
            pill.classList.add("is-active");
            state.sessionFilter = pill.dataset.filter || "all";
            renderSessionList();
        });
    });

    // Settings Drawer
    el.saveConnBtn.addEventListener("click", async () => {
        state.serverCfg = await saveServerConfig({
            serverUrl: el.serverUrlInput.value,
            token: el.serverTokenInput.value,
        });
        el.serverUrlInput.value = state.serverCfg.serverUrl;
        const ok = await checkConnection();
        if (ok) {
            connectWebSocket();
            await Promise.all([loadSessions(), loadNewSessionMetadata()]);
            if (state.selectedSid) await loadInitialSessionRecords(state.selectedSid);
            showToast("服务连接已更新", "ok");
        } else {
            showToast("连接测试失败，请检查地址与 Token", "err");
        }
        refreshDiagnostics();
    });
    el.openOptionsBtn.addEventListener("click", () => {
        if (chrome?.runtime?.openOptionsPage) chrome.runtime.openOptionsPage();
    });

    // New Session Bar
    el.agentSelect.addEventListener("change", updateAgentHint);
    el.browseDirBtn.addEventListener("click", () => {
        if (el.dirBrowser.classList.contains("is-hidden")) {
            openDirectoryBrowser(el.cwdInput.value.trim() || state.defaultCwd || "");
        } else {
            el.dirBrowser.classList.add("is-hidden");
        }
    });
    el.dirUpBtn.addEventListener("click", () => {
        if (state.parentBrowsePath) openDirectoryBrowser(state.parentBrowsePath);
    });
    el.dirUseBtn.addEventListener("click", () => {
        if (state.currentBrowsePath) el.cwdInput.value = state.currentBrowsePath;
        el.dirBrowser.classList.add("is-hidden");
    });

    // Stream Scroll Tracking
    el.chatStream.addEventListener("scroll", () => {
        const near = isNearBottom();
        state.stickToBottom = near;
        el.scrollBottomBtn.classList.toggle("is-hidden", near);
    });
    el.scrollBottomBtn.addEventListener("click", () => scrollStreamToBottom(true));

    // Bottom Context Bar & Composer
    el.toggleFullpageBtn.addEventListener("click", async () => {
        state.draft.includeFullPage = state.draft.includeFullPage === false;
        await saveDraft(state.draft);
        renderContextBar();
    });
    el.pickElementBtn.addEventListener("click", onPickElement);
    el.captureSelectionBtn.addEventListener("click", onCaptureSelection);
    el.captureShotBtn.addEventListener("click", onCaptureScreenshot);

    el.pillToggleCheckbox.addEventListener("change", async () => {
        const mode = el.pillToggleCheckbox.checked ? "auto" : "off";
        state.settings = await saveBridgeSettings({ selectionPillMode: mode });
        await sendRuntimeMessage({ type: "frago.bridge.setPillPreference", mode });
    });

    let saveDraftTimer = null;
    el.instructionInput.addEventListener("input", () => {
        autoResizeTextarea();
        updateSendButtonState();
        state.draft.instruction = el.instructionInput.value;
        if (saveDraftTimer) clearTimeout(saveDraftTimer);
        saveDraftTimer = setTimeout(() => {
            saveDraft(state.draft);
        }, 250);
    });

    el.instructionInput.addEventListener("keydown", (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
            e.preventDefault();
            if (!el.sendBtn.disabled) {
                dispatchSessionMessage().catch((err) => showToast(err.message, "err"));
            }
        }
    });

    el.sendBtn.addEventListener("click", () => {
        dispatchSessionMessage().catch((err) => showToast(err.message, "err"));
    });

    // Citation Preview Drawer & External Confirmation Modal
    if (el.citeDrawerClose) {
        el.citeDrawerClose.addEventListener("click", closeCiteDrawer);
    }
    if (el.citeExtCancel) {
        el.citeExtCancel.addEventListener("click", closeCiteExtModal);
    }
    if (el.citeExtModal) {
        el.citeExtModal.addEventListener("click", (e) => {
            if (e.target === el.citeExtModal) closeCiteExtModal();
        });
    }
    if (el.citeExtOpen) {
        el.citeExtOpen.addEventListener("click", () => {
            const targetUri = state.citeExtDef?.uri || "";
            closeCiteExtModal();
            if (targetUri && /^https?:\/\//i.test(targetUri)) {
                window.open(targetUri, "_blank", "noopener,noreferrer");
            }
        });
    }
    document.addEventListener("keydown", (e) => {
        if (e.key !== "Escape") return;
        if (el.citeExtModal && !el.citeExtModal.classList.contains("is-hidden")) {
            closeCiteExtModal();
        } else if (el.citePreviewDrawer && !el.citePreviewDrawer.classList.contains("is-hidden")) {
            closeCiteDrawer();
        } else if (el.citePopover && !el.citePopover.classList.contains("is-hidden")) {
            hideCitePopover();
        }
    });

    // Sync selection additions from page floating pill / context menu
    if (chrome?.runtime?.onMessage) {
        chrome.runtime.onMessage.addListener((msg) => {
            if (msg?.type === "frago.bridge.draftUpdated" && msg.draft) {
                state.draft = normalizeDraft(msg.draft);
                renderAttachmentPills();
                renderContextBar();
            }
        });
    }
    if (chrome?.storage?.onChanged) {
        chrome.storage.onChanged.addListener((changes, area) => {
            if (area === "local" && changes[BRIDGE_DRAFT_KEY]?.newValue) {
                state.draft = normalizeDraft(changes[BRIDGE_DRAFT_KEY].newValue);
                renderAttachmentPills();
                renderContextBar();
            }
        });
    }

    // Track browser tab switches & navigation so full-page context stays fresh
    if (chrome?.tabs?.onActivated) {
        chrome.tabs.onActivated.addListener(() => {
            refreshActivePage({ silent: true });
        });
    }
    if (chrome?.tabs?.onUpdated) {
        chrome.tabs.onUpdated.addListener((tabId, info) => {
            if (info.status === "complete" && tabId === state.activeTabId) {
                refreshActivePage({ silent: true });
            }
        });
    }
}

// ══════════ Bootstrap ══════════
async function init() {
    state.serverCfg = await loadServerConfig();
    el.serverUrlInput.value = state.serverCfg.serverUrl;
    el.serverTokenInput.value = state.serverCfg.token;

    state.draft = await loadDraft();
    state.settings = await loadBridgeSettings();
    state.selectedEmployeeId = state.settings.lastEmployeeId || "";

    el.instructionInput.value = state.draft.instruction || "";
    autoResizeTextarea();
    el.pillToggleCheckbox.checked = state.settings.selectionPillMode !== "off";

    renderContextBar();
    renderAttachmentPills();
    renderHeader();
    bindEvents();

    await refreshActivePage({ silent: true });
    const ok = await checkConnection();
    if (ok) {
        connectWebSocket();
        await Promise.all([loadSessions(), loadNewSessionMetadata()]);
    }
    refreshDiagnostics();
}

init();
