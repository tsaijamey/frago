// frago bridge — Side Panel persistent draft & settings store

export const BRIDGE_DRAFT_KEY = "fragoSessionBridgeDraft";
export const BRIDGE_SETTINGS_KEY = "fragoBridgeSettings";

export function emptyDraft() {
    return {
        focusItems: [],
        pageSnapshots: {},
        screenshots: [],
        instruction: "",
        includeFullPage: true,
    };
}

export function normalizeDraft(raw) {
    const base = emptyDraft();
    if (!raw || typeof raw !== "object") return base;
    return {
        focusItems: Array.isArray(raw.focusItems) ? raw.focusItems : [],
        pageSnapshots: raw.pageSnapshots && typeof raw.pageSnapshots === "object" ? raw.pageSnapshots : {},
        screenshots: Array.isArray(raw.screenshots) ? raw.screenshots : [],
        instruction: typeof raw.instruction === "string" ? raw.instruction : "",
        includeFullPage: raw.includeFullPage !== false,
    };
}

export async function loadDraft() {
    if (!chrome?.storage?.local) return emptyDraft();
    const stored = await chrome.storage.local.get(BRIDGE_DRAFT_KEY);
    return normalizeDraft(stored[BRIDGE_DRAFT_KEY]);
}

export async function saveDraft(draft) {
    const normalized = normalizeDraft(draft);
    if (chrome?.storage?.local) {
        await chrome.storage.local.set({ [BRIDGE_DRAFT_KEY]: normalized });
    }
    return normalized;
}

export async function loadBridgeSettings() {
    const defaults = {
        selectionPillMode: "auto",
        lastNewSessionCwd: "",
        selectedSessionId: "",
        lastEmployeeId: "",
        lastAgent: "",
    };
    if (!chrome?.storage?.local) return defaults;
    const stored = await chrome.storage.local.get(BRIDGE_SETTINGS_KEY);
    return { ...defaults, ...(stored[BRIDGE_SETTINGS_KEY] || {}) };
}

export async function saveBridgeSettings(patch) {
    const current = await loadBridgeSettings();
    const next = { ...current, ...(patch || {}) };
    if (chrome?.storage?.local) {
        await chrome.storage.local.set({ [BRIDGE_SETTINGS_KEY]: next });
    }
    return next;
}
