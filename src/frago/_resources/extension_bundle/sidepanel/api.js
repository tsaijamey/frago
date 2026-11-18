// frago bridge — HTTP client for Frago Server (/api/*)

export const DEFAULT_SERVER_URL = "http://127.0.0.1:8093";
export const SERVER_CONFIG_KEY = "fragoServerConfig";

export function normalizeServerUrl(raw) {
    const cleaned = String(raw || "").trim().replace(/\/+$/, "");
    return cleaned || DEFAULT_SERVER_URL;
}

export async function loadServerConfig() {
    if (!chrome?.storage?.local) {
        return { serverUrl: DEFAULT_SERVER_URL, token: "" };
    }
    const stored = await chrome.storage.local.get(SERVER_CONFIG_KEY);
    const cfg = stored[SERVER_CONFIG_KEY] || {};
    return {
        serverUrl: normalizeServerUrl(cfg.serverUrl),
        token: String(cfg.token || "").trim(),
    };
}

export async function saveServerConfig({ serverUrl, token }) {
    const next = {
        serverUrl: normalizeServerUrl(serverUrl),
        token: String(token || "").trim(),
    };
    if (chrome?.storage?.local) {
        await chrome.storage.local.set({ [SERVER_CONFIG_KEY]: next });
    }
    return next;
}

export class BridgeApiError extends Error {
    constructor(message, { status = 0, code = "NETWORK_ERROR", detail = "" } = {}) {
        super(message);
        this.name = "BridgeApiError";
        this.status = status;
        this.code = code;
        this.detail = detail;
    }
}

async function apiFetch(cfg, path, options = {}) {
    const baseUrl = normalizeServerUrl(cfg?.serverUrl);
    const token = String(cfg?.token || "").trim();
    const headers = new Headers(options.headers || {});
    if (options.body && !headers.has("Content-Type")) {
        headers.set("Content-Type", "application/json");
    }
    if (token && !headers.has("Authorization")) {
        headers.set("Authorization", `Bearer ${token}`);
    }

    let resp;
    try {
        resp = await fetch(`${baseUrl}${path}`, {
            ...options,
            headers,
        });
    } catch (err) {
        throw new BridgeApiError(
            `无法连接到 ${baseUrl}（请确认已启动 frago start）`,
            { status: 0, code: "OFFLINE", detail: String(err?.message || err) }
        );
    }

    let body = null;
    const text = await resp.text();
    if (text) {
        try {
            body = JSON.parse(text);
        } catch (_) {
            body = { detail: text };
        }
    }

    if (!resp.ok) {
        const detail = (body && (body.detail || body.error || body.message)) || `HTTP ${resp.status}`;
        if (resp.status === 401) {
            throw new BridgeApiError("服务端需要 Bearer Token 鉴权，请在连接设置中填写 Token", {
                status: 401,
                code: "UNAUTHORIZED",
                detail,
            });
        }
        throw new BridgeApiError(String(detail), {
            status: resp.status,
            code: "HTTP_ERROR",
            detail: String(detail),
        });
    }

    return body;
}

export function checkServerInfo(cfg) {
    return apiFetch(cfg, "/api/info", { method: "GET" });
}

export function listWorkbenchSessions(cfg) {
    return apiFetch(cfg, "/api/workbench/sessions", { method: "GET" });
}

export function fetchSessionRecords(cfg, sid, { after = null, limit = 200, tail = false } = {}) {
    const params = new URLSearchParams();
    params.set("limit", String(limit));
    if (after !== null && after !== undefined) {
        params.set("after", String(after));
    }
    if (tail) {
        params.set("tail", "true");
    }
    return apiFetch(cfg, `/api/workbench/sessions/${encodeURIComponent(sid)}/records?${params.toString()}`, {
        method: "GET",
    });
}

export function getSessionQueue(cfg, sid) {
    return apiFetch(cfg, `/api/workbench/sessions/${encodeURIComponent(sid)}/queue`, {
        method: "GET",
    });
}

export function stopWorkbenchSession(cfg, sid, { force = false } = {}) {
    return apiFetch(cfg, `/api/workbench/sessions/${encodeURIComponent(sid)}/stop`, {
        method: "POST",
        body: JSON.stringify({ force: Boolean(force) }),
    });
}

export function buildWebSocketUrl(cfg) {
    const baseUrl = normalizeServerUrl(cfg?.serverUrl);
    const token = String(cfg?.token || "").trim();
    const wsBase = baseUrl.replace(/^http:/i, "ws:").replace(/^https:/i, "wss:");
    const url = `${wsBase}/ws`;
    return token ? `${url}?token=${encodeURIComponent(token)}` : url;
}

export function sendToWorkbenchSession(cfg, sid, payload) {
    return apiFetch(cfg, `/api/workbench/sessions/${encodeURIComponent(sid)}/send`, {
        method: "POST",
        body: JSON.stringify({
            text: payload.text || "",
            images: payload.images || [],
            documents: payload.documents || [],
            wait: payload.wait !== false,
        }),
    });
}

export function queueToWorkbenchSession(cfg, sid, payload) {
    return apiFetch(cfg, `/api/workbench/sessions/${encodeURIComponent(sid)}/queue`, {
        method: "POST",
        body: JSON.stringify({
            text: payload.text || "",
            images: payload.images || [],
            documents: payload.documents || [],
            wait: false,
        }),
    });
}

export function listEmployees(cfg) {
    return apiFetch(cfg, "/api/employees", { method: "GET" });
}

export function listWorkbenchAgents(cfg) {
    return apiFetch(cfg, "/api/workbench/agents", { method: "GET" });
}

export function getSystemDirectories(cfg) {
    return apiFetch(cfg, "/api/system/directories", { method: "GET" });
}

export function browseSystemDirectories(cfg, path = "") {
    const qs = path ? `?path=${encodeURIComponent(path)}` : "";
    return apiFetch(cfg, `/api/system/directories/browse${qs}`, { method: "GET" });
}

export function createWorkbenchSession(cfg, payload) {
    return apiFetch(cfg, "/api/workbench/sessions", {
        method: "POST",
        body: JSON.stringify({
            agent: payload.agent,
            cwd: payload.cwd || "",
            text: payload.text || "",
            images: payload.images || [],
            documents: payload.documents || [],
            employee: payload.employee || "",
        }),
    });
}

export function pollPendingWorkbenchSession(cfg, handle) {
    return apiFetch(cfg, `/api/workbench/sessions/pending/${encodeURIComponent(handle)}`, {
        method: "GET",
    });
}
