// frago bridge — MV3 service worker
//
// Responsibilities:
//   - Maintain a long-lived native messaging port to `com.frago.bridge`.
//   - Route JSON-RPC requests to the right handler (tab.*, dom.*, visual.*).
//   - Dispatch dom.* into the target tab's content script.
//   - Persist minimal state (group → tab_id) in chrome.storage.session.

const HOST_NAME = "com.frago.bridge";
const KEEPALIVE_MS = 20_000;

let port = null;
let keepaliveTimer = null;

// In-memory group→tab map; mirrored to chrome.storage.session.
const groupToTab = new Map();

async function loadGroups() {
    const { groupBindings = {} } = await chrome.storage.session.get("groupBindings");
    for (const [g, id] of Object.entries(groupBindings)) groupToTab.set(g, id);
}
async function saveGroups() {
    const obj = Object.fromEntries(groupToTab);
    await chrome.storage.session.set({ groupBindings: obj });
}

function connectHost() {
    // Idempotent: multiple lifecycle hooks (onInstalled / onStartup /
    // activate / bootstrap) all call connectHost. Without this guard
    // Chrome spawns N relays simultaneously and the daemon rejects all
    // but the first, triggering disconnect cascades.
    if (port) return;
    let myPort;
    try {
        myPort = chrome.runtime.connectNative(HOST_NAME);
    } catch (e) {
        console.warn("[frago] connectNative failed:", e);
        return;
    }
    port = myPort;
    myPort.onMessage.addListener(onHostMessage);
    myPort.onDisconnect.addListener(() => {
        console.warn("[frago] host disconnected:", chrome.runtime.lastError);
        // Only react if this is still the active port. Stale ports
        // (rejected duplicates from earlier connect storms) must not
        // clear `port` or trigger reconnect — that would kill the
        // working connection.
        if (port === myPort) {
            port = null;
            clearInterval(keepaliveTimer);
            keepaliveTimer = null;
            setTimeout(connectHost, 1_000);
        }
    });
    keepaliveTimer = setInterval(() => {
        try { myPort.postMessage({ jsonrpc: "2.0", method: "system.ping", params: {} }); }
        catch (_) { /* ignore */ }
    }, KEEPALIVE_MS);
    console.log("[frago] connected to native host");
}

function sendResponse(id, result) {
    port?.postMessage({ jsonrpc: "2.0", id, result });
}
function sendError(id, code, message, data) {
    port?.postMessage({ jsonrpc: "2.0", id, error: { code, message, data } });
}

async function onHostMessage(msg) {
    const { id, method, params } = msg || {};
    if (!method) return; // response from host (e.g. pong) — ignore
    try {
        const result = await dispatch(method, params || {});
        if (id != null) sendResponse(id, result);
    } catch (e) {
        if (id != null) sendError(id, e.code || -32004, e.message || String(e), e.data);
    }
}

// ════════════════════════ method dispatch ════════════════════════

async function dispatch(method, params) {
    switch (method) {
        case "system.ping":        return { pong: true, ts: Date.now() };
        case "system.info":        return { manifest: chrome.runtime.getManifest(), extensionId: chrome.runtime.id };
        case "tab.navigate":       return await tabNavigate(params);
        case "tab.startBrowser":   throw { code: -32601, message: "start is a CLI-side responsibility" };
        case "dom.exec_js":        return await domExecJs(params);
        case "dom.get_content":    return await domGetContent(params);
        case "dom.click":          return await domClick(params);
        case "visual.screenshot":  return await visualScreenshot(params);
        // ─── Batch 1: tab management ──────────────────────────────
        case "tabs.list":          return await tabsList(params);
        case "tabs.switch":        return await tabsSwitch(params);
        case "tabs.close":         return await tabsClose(params);
        case "tabs.reset":         return await tabsReset(params);
        case "groups.list":        return groupsList();
        case "groups.info":        return await groupsInfo(params);
        case "groups.close":       return await groupsClose(params);
        case "groups.cleanup":     return await groupsCleanup();
        case "page.scroll":        return await pageScroll(params);
        case "page.scroll_to":     return await pageScrollTo(params);
        case "page.zoom":          return await pageZoom(params);
        case "page.get_title":     return await pageGetTitle(params);
        case "detect.anti_bot":    return await detectAntiBot(params);
        // ─── Visual effects (P3.1 / I) ────────────────────────────
        case "visual.highlight":      return await visualHighlight(params);
        case "visual.pointer":        return await visualPointer(params);
        case "visual.spotlight":      return await visualSpotlight(params);
        case "visual.annotate":       return await visualAnnotate(params);
        case "visual.underline":      return await visualUnderline(params);
        case "visual.clear_effects":  return await visualClearEffects(params);
        default:
            throw { code: -32601, message: `method not found: ${method}` };
    }
}

// ════════════════════════ handlers ════════════════════════

async function resolveTab(params, { create = false, url = null } = {}) {
    const { group, tab_id } = params;
    if (tab_id) return tab_id;
    if (group && groupToTab.has(group)) {
        const id = groupToTab.get(group);
        try { await chrome.tabs.get(id); return id; }
        catch { groupToTab.delete(group); await saveGroups(); }
    }
    if (create && url) {
        const tab = await chrome.tabs.create({ url, active: false });
        if (group) { groupToTab.set(group, tab.id); await saveGroups(); }
        return tab.id;
    }
    throw { code: -32002, message: "no tab for group", data: { group } };
}

function waitForLoad(tabId, timeoutMs = 15_000) {
    return new Promise((resolve, reject) => {
        const t = setTimeout(() => {
            chrome.tabs.onUpdated.removeListener(listener);
            reject({ code: -32005, message: "navigation timeout" });
        }, timeoutMs);
        function listener(updatedId, info) {
            if (updatedId === tabId && info.status === "complete") {
                clearTimeout(t);
                chrome.tabs.onUpdated.removeListener(listener);
                resolve();
            }
        }
        chrome.tabs.onUpdated.addListener(listener);
    });
}

async function tabNavigate({ url, group, tab_id, timeout = 15_000 }) {
    if (!url) throw { code: -32602, message: "url required" };
    let id;
    if (tab_id || groupToTab.has(group)) {
        id = await resolveTab({ group, tab_id });
        await chrome.tabs.update(id, { url });
    } else {
        const tab = await chrome.tabs.create({ url, active: false });
        id = tab.id;
        if (group) { groupToTab.set(group, id); await saveGroups(); }
    }
    await waitForLoad(id, timeout);
    const tab = await chrome.tabs.get(id);
    return { tab_id: id, url: tab.url, title: tab.title };
}

async function domExecJs({ script, group, tab_id }) {
    if (!script) throw { code: -32602, message: "script required" };
    const id = await resolveTab({ group, tab_id });
    const [{ result }] = await chrome.scripting.executeScript({
        target: { tabId: id },
        world: "MAIN",
        func: (src) => {
            try {
                // eslint-disable-next-line no-new-func
                const fn = new Function(`return (${src})`);
                const v = fn();
                return { ok: true, value: v };
            } catch (e) {
                return { ok: false, error: String(e) };
            }
        },
        args: [script],
    });
    if (!result?.ok) throw { code: -32004, message: result?.error || "exec failed" };
    return { value: result.value };
}

async function domGetContent({ selector, group, tab_id }) {
    const id = await resolveTab({ group, tab_id });
    const [{ result }] = await chrome.scripting.executeScript({
        target: { tabId: id },
        func: (sel) => {
            const root = sel ? document.querySelector(sel) : document.body;
            if (!root) return { ok: false, error: "selector not found" };
            return {
                ok: true,
                text: root.innerText || "",
                html: root.outerHTML || "",
                title: document.title,
                url: location.href,
            };
        },
        args: [selector || null],
    });
    if (!result?.ok) throw { code: -32004, message: result?.error || "get_content failed" };
    return result;
}

async function domClick({ selector, group, tab_id }) {
    if (!selector) throw { code: -32602, message: "selector required" };
    const id = await resolveTab({ group, tab_id });
    const [{ result }] = await chrome.scripting.executeScript({
        target: { tabId: id },
        func: (sel) => {
            const el = document.querySelector(sel);
            if (!el) return { ok: false, error: "selector not found" };
            el.click();
            return { ok: true };
        },
        args: [selector],
    });
    if (!result?.ok) throw { code: -32004, message: result?.error || "click failed" };
    return { success: true };
}

// Wait for a tab to reach status:complete. Used as a defensive guard so
// callers that chain navigate→screenshot (or other ops) don't race the
// page load. Times out gracefully — falls through rather than hanging.
function waitTabReady(tabId, timeoutMs = 5000) {
    return new Promise(async (resolve) => {
        try {
            const tab = await chrome.tabs.get(tabId);
            if (tab.status === "complete") { resolve(); return; }
        } catch (_) { resolve(); return; }
        const t = setTimeout(() => {
            chrome.tabs.onUpdated.removeListener(listener);
            resolve();
        }, timeoutMs);
        function listener(updatedId, info) {
            if (updatedId === tabId && info.status === "complete") {
                clearTimeout(t);
                chrome.tabs.onUpdated.removeListener(listener);
                resolve();
            }
        }
        chrome.tabs.onUpdated.addListener(listener);
    });
}

async function visualScreenshot({ group, tab_id, output = null }) {
    const id = await resolveTab({ group, tab_id });

    // 1. Defensive load-wait: covers the navigate→screenshot chain where
    //    caller didn't explicitly wait. Skipped instantly if already complete.
    await waitTabReady(id);

    // captureVisibleTab snaps the foreground tab in the window. Our tabs
    // are created with active:false to avoid stealing user focus, so we
    // must activate the target tab first, then restore the previously-
    // active tab. Without this, the snapshot is whatever tab the user
    // had on top (typically about:blank).
    const tab = await chrome.tabs.get(id);
    let prevActiveId = null;
    if (!tab.active) {
        const [prev] = await chrome.tabs.query({ active: true, windowId: tab.windowId });
        prevActiveId = prev?.id ?? null;
        await chrome.tabs.update(id, { active: true });
    }

    // 2. Compositor settle: chrome.tabs.update({active:true}) resolves
    //    before the freshly-active tab finishes rendering. captureVisibleTab
    //    drives a GPU readback; if compositing is mid-frame, readback fails
    //    with "image readback failed" (heavy pages like Upwork).
    await new Promise(r => setTimeout(r, 150));

    // 3. Retry transient GPU failures with backoff.
    let dataUrl, lastErr;
    try {
        for (let i = 0; i < 3; i++) {
            try {
                dataUrl = await chrome.tabs.captureVisibleTab(
                    tab.windowId, { format: "png" });
                break;
            } catch (e) {
                lastErr = e;
                if (i < 2) await new Promise(r => setTimeout(r, 200 * (i + 1)));
            }
        }
    } finally {
        if (prevActiveId != null && prevActiveId !== id) {
            try { await chrome.tabs.update(prevActiveId, { active: true }); }
            catch (_) { /* prev tab may have closed */ }
        }
    }
    if (!dataUrl) {
        throw { code: -32004,
                message: `screenshot failed after retries: ${lastErr?.message || lastErr}` };
    }
    const b64 = dataUrl.split(",")[1] || "";
    return { tab_id: id, png_base64: b64, output };
}

// ════════════════════════ batch 1: tabs / groups / page ════════════════════════

async function tabsList(_params) {
    const tabs = await chrome.tabs.query({});
    const out = tabs.map((t, i) => ({
        index: i, id: t.id, title: t.title || "", url: t.url || "",
        active: !!t.active, windowId: t.windowId,
    }));
    return { tabs: out };
}

async function tabsSwitch({ tab_id }) {
    if (tab_id == null) throw { code: -32602, message: "tab_id required" };
    const tab = await chrome.tabs.update(tab_id, { active: true });
    try { await chrome.windows.update(tab.windowId, { focused: true }); }
    catch (_) { /* ignore; headless etc. */ }
    return { tab_id, title: tab.title || "", url: tab.url || "" };
}

async function tabsClose({ tab_id }) {
    if (tab_id == null) throw { code: -32602, message: "tab_id required" };
    await chrome.tabs.remove(tab_id);
    // Also drop any group binding pointing at this tab.
    for (const [g, id] of groupToTab.entries()) {
        if (id === tab_id) groupToTab.delete(g);
    }
    await saveGroups();
    return { tab_id, closed: true };
}

async function tabsReset({ group }) {
    const closed = [];
    if (group) {
        const id = groupToTab.get(group);
        if (id != null) {
            try { await chrome.tabs.remove(id); closed.push(id); }
            catch (_) { /* tab already gone */ }
            groupToTab.delete(group);
            await saveGroups();
        }
        return { group, closed };
    }
    // Global reset: close all group tabs; leave other tabs alone.
    for (const [g, id] of groupToTab.entries()) {
        try { await chrome.tabs.remove(id); closed.push(id); }
        catch (_) { /* ignore */ }
    }
    groupToTab.clear();
    await saveGroups();
    return { group: null, closed };
}

function groupsList() {
    const out = {};
    for (const [name, id] of groupToTab.entries()) {
        out[name] = { tab_id: id, tabs: 1 };
    }
    return { groups: out };
}

async function groupsInfo({ name }) {
    if (!name) throw { code: -32602, message: "name required" };
    const id = groupToTab.get(name);
    if (id == null) throw { code: -32002, message: `group not found: ${name}` };
    let tab;
    try { tab = await chrome.tabs.get(id); }
    catch (_) {
        groupToTab.delete(name); await saveGroups();
        throw { code: -32002, message: `group tab missing: ${name}` };
    }
    return { name, tab_id: id, url: tab.url || "", title: tab.title || "",
             tabs: 1 };
}

async function groupsClose({ name }) {
    if (!name) throw { code: -32602, message: "name required" };
    const id = groupToTab.get(name);
    if (id == null) return { name, closed: false };
    try { await chrome.tabs.remove(id); } catch (_) { /* ignore */ }
    groupToTab.delete(name);
    await saveGroups();
    return { name, closed: true, tab_id: id };
}

async function groupsCleanup() {
    let removed = 0;
    for (const [name, id] of [...groupToTab.entries()]) {
        try { await chrome.tabs.get(id); }
        catch (_) { groupToTab.delete(name); removed++; }
    }
    if (removed) await saveGroups();
    return { removed };
}

async function pageScroll({ distance, group, tab_id }) {
    const id = await resolveTab({ group, tab_id });
    const [{ result }] = await chrome.scripting.executeScript({
        target: { tabId: id },
        func: (d) => { window.scrollBy(0, d); return { scrolled: d }; },
        args: [Number(distance) || 0],
    });
    return result;
}

async function pageScrollTo({ group, tab_id, selector, text, block }) {
    const id = await resolveTab({ group, tab_id });
    const [{ result }] = await chrome.scripting.executeScript({
        target: { tabId: id },
        func: (sel, txt, blk) => {
            let el = null;
            if (sel) el = document.querySelector(sel);
            if (!el && txt) {
                const walker = document.createTreeWalker(
                    document.body, NodeFilter.SHOW_TEXT,
                    { acceptNode: (n) => n.textContent.includes(txt)
                        ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT });
                const node = walker.nextNode();
                if (node) el = node.parentElement;
            }
            if (!el) return { ok: false, error: "element not found" };
            el.scrollIntoView({ behavior: "smooth", block: blk || "center" });
            return { ok: true };
        },
        args: [selector || null, text || null, block || "center"],
    });
    if (!result?.ok) throw { code: -32004, message: result?.error || "scroll_to failed" };
    return { success: true };
}

async function pageZoom({ factor, group, tab_id }) {
    const id = await resolveTab({ group, tab_id });
    await chrome.tabs.setZoom(id, Number(factor));
    const got = await chrome.tabs.getZoom(id);
    return { tab_id: id, factor: got };
}

async function pageGetTitle({ group, tab_id }) {
    const id = await resolveTab({ group, tab_id });
    const tab = await chrome.tabs.get(id);
    return { tab_id: id, title: tab.title || "" };
}

// ════════════════════════ anti-bot detection ════════════════════════
//
// Classifies the current page as one of:
//   - {challenge: false}                                (clean page, proceed)
//   - {challenge: true, type: "interactive",  needs_human: true,  ...}
//       Turnstile / hCaptcha / reCAPTCHA widget is present. Programmatic
//       click is detectable (no isTrusted event). Recipe layer should
//       pause and notify a human.
//   - {challenge: true, type: "invisible_or_static", needs_human: false, ...}
//       JS-only challenge (Cloudflare "Just a moment...", etc.) or a
//       block page text. Recipe layer can wait + retry, but cannot
//       click through.
//   - {challenge: true, type: "blocked", needs_human: false, ...}
//       Hard block ("access denied", "unusual activity"). No recovery
//       beyond changing IP / cooling off — recipe layer should fail loud.
//
// Detection is lossy by design: false negatives possible (anti-bot
// vendors evolve). Use as a hint, not a guarantee.

async function detectAntiBot({ group, tab_id }) {
    const id = await resolveTab({ group, tab_id });
    const [{ result }] = await chrome.scripting.executeScript({
        target: { tabId: id },
        func: () => {
            const INTERACTIVE_SELECTORS = [
                "[data-sitekey]",                          // Turnstile / hCaptcha / reCAPTCHA
                'iframe[src*="challenges.cloudflare.com"]',
                'iframe[src*="hcaptcha.com"]',
                'iframe[src*="recaptcha"]',
                'iframe[src*="datadome"]',                 // DataDome captcha
                ".cf-turnstile",
                "#cf-turnstile-response",
            ];
            let interactiveMatch = null;
            for (const sel of INTERACTIVE_SELECTORS) {
                const el = document.querySelector(sel);
                if (el) { interactiveMatch = sel; break; }
            }

            const title = document.title || "";
            const bodyText = (document.body?.innerText || "").slice(0, 2000);
            const titlePatterns = /just a moment|please wait|请稍候|attention required|verifying you are human|checking your browser/i;
            const titleMatch = titlePatterns.test(title);
            const cfRay = /cloudflare ray id/i.test(bodyText);
            const captchaText = /verify you are human|i'?m not a robot|prove you are human/i.test(bodyText);
            const blockedText = /access denied|unusual activity|we noticed unusual|suspicious activity|request blocked|forbidden by upstream/i.test(bodyText);

            // Order matters: interactive widget is the strongest signal
            // (most actionable for recipe layer); blocked is weaker than
            // invisible since some "access denied" pages are actually
            // dressed-up Cloudflare challenges that resolve after wait.
            if (interactiveMatch) {
                return {
                    challenge: true,
                    type: "interactive",
                    needs_human: true,
                    detector: "selector",
                    detector_match: interactiveMatch,
                    title,
                    url: location.href,
                };
            }
            if (titleMatch || cfRay || captchaText) {
                let detector;
                if (titleMatch) detector = "title";
                else if (cfRay) detector = "cf-ray";
                else detector = "body-captcha-text";
                return {
                    challenge: true,
                    type: "invisible_or_static",
                    needs_human: false,
                    detector,
                    title,
                    url: location.href,
                    body_preview: bodyText.slice(0, 300),
                };
            }
            if (blockedText) {
                return {
                    challenge: true,
                    type: "blocked",
                    needs_human: false,
                    detector: "body-blocked-text",
                    title,
                    url: location.href,
                    body_preview: bodyText.slice(0, 300),
                };
            }
            return { challenge: false, title, url: location.href };
        },
        args: [],
    });
    return result;
}

// ════════════════════════ visual effects ════════════════════════
//
// Pure DOM manipulation injected into the page's MAIN world. Equivalent
// to the CDP backend's effects (src/frago/chrome/cdp/session.py) — same
// JS, same data-frago-* markers, so clear_effects from either backend
// cleans up after either one. ``lifetime`` is in milliseconds; 0 means
// permanent (cleared only by visual.clear_effects).

async function _runInTab(id, func, args) {
    const [{ result }] = await chrome.scripting.executeScript({
        target: { tabId: id },
        world: "MAIN",
        func,
        args: args || [],
    });
    return result;
}

async function visualHighlight({ group, tab_id, selector,
                                 color = "magenta",
                                 border_width = 3,
                                 lifetime = 0 }) {
    if (!selector) throw { code: -32602, message: "selector required" };
    const id = await resolveTab({ group, tab_id });
    return await _runInTab(id, (sel, c, w, lt) => {
        const els = document.querySelectorAll(sel);
        els.forEach(el => {
            el.style.border = `${w}px solid ${c}`;
            el.style.outline = `${w}px solid ${c}`;
            el.setAttribute("data-frago-highlight", "true");
            if (lt > 0) {
                setTimeout(() => {
                    el.style.removeProperty("border");
                    el.style.removeProperty("outline");
                    el.removeAttribute("data-frago-highlight");
                }, lt);
            }
        });
        return { matched: els.length };
    }, [selector, color, border_width, lifetime]);
}

async function visualPointer({ group, tab_id, selector, lifetime = 0 }) {
    if (!selector) throw { code: -32602, message: "selector required" };
    const id = await resolveTab({ group, tab_id });
    return await _runInTab(id, (sel, lt) => {
        const els = document.querySelectorAll(sel);
        els.forEach(el => {
            el.style.cursor = "pointer";
            el.style.boxShadow = "0 0 10px magenta";
            el.setAttribute("data-frago-pointer", "true");
            if (lt > 0) {
                setTimeout(() => {
                    el.style.removeProperty("cursor");
                    el.style.removeProperty("box-shadow");
                    el.removeAttribute("data-frago-pointer");
                }, lt);
            }
        });
        return { matched: els.length };
    }, [selector, lifetime]);
}

async function visualSpotlight({ group, tab_id, selector, lifetime = 0 }) {
    if (!selector) throw { code: -32602, message: "selector required" };
    const id = await resolveTab({ group, tab_id });
    return await _runInTab(id, (sel, lt) => {
        // Inject keyframes once
        if (!document.getElementById("frago-spotlight-style")) {
            const style = document.createElement("style");
            style.id = "frago-spotlight-style";
            style.textContent = `
                @keyframes frago-spotlight-fade {
                    0% { box-shadow: 0 0 20px magenta; }
                    90% { box-shadow: 0 0 20px magenta; }
                    100% { box-shadow: none; }
                }`;
            document.head.appendChild(style);
        }
        const els = document.querySelectorAll(sel);
        const lifetimeSec = lt / 1000;
        els.forEach(el => {
            el.style.zIndex = "9999";
            el.style.position = "relative";
            el.setAttribute("data-frago-spotlight", "true");
            if (lt > 0) {
                el.style.animation = `frago-spotlight-fade ${lifetimeSec}s forwards`;
                el.addEventListener("animationend", function handler() {
                    el.style.removeProperty("animation");
                    el.style.removeProperty("z-index");
                    el.style.removeProperty("position");
                    el.removeAttribute("data-frago-spotlight");
                    el.removeEventListener("animationend", handler);
                });
            } else {
                el.style.boxShadow = "0 0 20px magenta";
            }
        });
        return { matched: els.length };
    }, [selector, lifetime]);
}

async function visualAnnotate({ group, tab_id, selector, text,
                                position = "top", lifetime = 0 }) {
    if (!selector) throw { code: -32602, message: "selector required" };
    if (!text) throw { code: -32602, message: "text required" };
    const id = await resolveTab({ group, tab_id });
    return await _runInTab(id, (sel, txt, pos, lt) => {
        const els = document.querySelectorAll(sel);
        els.forEach(el => {
            const a = document.createElement("div");
            a.className = "frago-annotation";
            a.textContent = txt;
            a.style.cssText = `
                position:absolute; background:magenta; color:white;
                padding:5px 8px; border-radius:3px; font-size:12px;
                font-weight:bold; z-index:10000; pointer-events:none`;
            const r = el.getBoundingClientRect();
            switch (pos) {
                case "top":
                    a.style.top = (r.top + window.scrollY - 30) + "px";
                    a.style.left = r.left + "px";
                    break;
                case "bottom":
                    a.style.top = (r.bottom + window.scrollY + 5) + "px";
                    a.style.left = r.left + "px";
                    break;
                case "left":
                    a.style.top = (r.top + window.scrollY) + "px";
                    a.style.left = (r.left - 150) + "px";
                    break;
                case "right":
                    a.style.top = (r.top + window.scrollY) + "px";
                    a.style.left = (r.right + 5) + "px";
                    break;
            }
            document.body.appendChild(a);
            if (lt > 0) setTimeout(() => a.remove(), lt);
        });
        return { matched: els.length };
    }, [selector, text, position, lifetime]);
}

async function visualUnderline({ group, tab_id, selector,
                                 color = "magenta",
                                 width = 3,
                                 duration = 1000 }) {
    if (!selector) throw { code: -32602, message: "selector required" };
    const id = await resolveTab({ group, tab_id });
    return await _runInTab(id, (sel, c, w, dur) => {
        const els = document.querySelectorAll(sel);
        els.forEach(el => {
            const range = document.createRange();
            range.selectNodeContents(el);
            const rects = Array.from(range.getClientRects())
                .filter(r => r.width > 0 && r.height > 0);
            // Merge rects on the same line
            const lineMap = new Map();
            rects.forEach(r => {
                const key = Math.round(r.top);
                if (lineMap.has(key)) {
                    const ex = lineMap.get(key);
                    ex.left = Math.min(ex.left, r.left);
                    ex.right = Math.max(ex.right, r.right);
                    ex.bottom = Math.max(ex.bottom, r.bottom);
                } else {
                    lineMap.set(key, {
                        left: r.left, right: r.right,
                        bottom: r.bottom, top: r.top,
                    });
                }
            });
            const lines = [...lineMap.values()];
            const perLine = lines.length > 0 ? dur / lines.length : 0;
            lines.forEach((line, i) => {
                const u = document.createElement("div");
                u.className = "frago-underline";
                u.style.cssText = `
                    position:absolute; height:${w}px; background:${c};
                    z-index:10000; pointer-events:none;
                    left:${line.left}px;
                    top:${line.bottom + window.scrollY}px;
                    width:0px; transition:width ${perLine}ms linear;`;
                document.body.appendChild(u);
                setTimeout(() => {
                    u.style.width = (line.right - line.left) + "px";
                }, i * perLine);
            });
        });
        return { matched: els.length };
    }, [selector, color, width, duration]);
}

async function visualClearEffects({ group, tab_id }) {
    const id = await resolveTab({ group, tab_id });
    return await _runInTab(id, () => {
        document.querySelectorAll("[data-frago-highlight]").forEach(el => {
            el.style.removeProperty("border");
            el.style.removeProperty("outline");
            el.removeAttribute("data-frago-highlight");
        });
        document.querySelectorAll("[data-frago-pointer]").forEach(el => {
            el.style.removeProperty("cursor");
            el.style.removeProperty("box-shadow");
            el.removeAttribute("data-frago-pointer");
        });
        document.querySelectorAll("[data-frago-spotlight]").forEach(el => {
            el.style.removeProperty("animation");
            el.style.removeProperty("box-shadow");
            el.style.removeProperty("z-index");
            el.style.removeProperty("position");
            el.removeAttribute("data-frago-spotlight");
        });
        document.querySelectorAll(".frago-annotation, .frago-underline").forEach(el => el.remove());
        const styleNode = document.getElementById("frago-spotlight-style");
        if (styleNode) styleNode.remove();
        return { ok: true };
    }, []);
}

// ════════════════════════ popup messaging ════════════════════════
//
// popup/popup.js asks ``{type: "frago.popup.status"}`` to learn whether
// the native host port is alive. Synchronous response — no async work
// needed; just inspect the module-level ``port``.

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg?.type === "frago.popup.status") {
        sendResponse({ ok: !!port, extensionId: chrome.runtime.id });
    }
    return false;  // synchronous response
});

// ════════════════════════ bootstrap ════════════════════════

chrome.runtime.onInstalled.addListener(() => { connectHost(); });
chrome.runtime.onStartup.addListener(() => { connectHost(); });
self.addEventListener("activate", () => { loadGroups(); connectHost(); });

// Connect eagerly on SW wake.
loadGroups().then(connectHost);
