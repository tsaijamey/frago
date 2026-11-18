// frago bridge — content script.
//
// Responsibilities:
// 1. Announce the page (frago.content_ready) and send throttled activity pings
//    (frago.activity) to keep CLI automation tab groups alive.
// 2. Extract full-page visible Markdown context (stripping scripts/styles/hidden
//    nodes and extension UI), capture user selections as Focus items, drive the
//    Shadow DOM Element Picker, and render a non-intrusive Shadow DOM selection
//    pill ("+ 设为 Focus") when the Side Panel is open or explicitly enabled.

(() => {
    if (window.__fragoBridgeInjected) return;
    window.__fragoBridgeInjected = true;

    const extractor = globalThis.FragoPageExtractor;
    const picker = globalThis.FragoElementPicker;

    // ══════════ 1. Existing group keepalive heartbeat ══════════
    const ACTIVITY_THROTTLE_MS = 60_000;
    let lastPing = 0;

    function ping() {
        const now = Date.now();
        if (now - lastPing < ACTIVITY_THROTTLE_MS) return;
        lastPing = now;
        try {
            chrome.runtime.sendMessage({ type: "frago.activity" });
        } catch (_) { /* SW may be asleep or context invalidated; ignore */ }
    }

    for (const evt of ["scroll", "pointerdown", "keydown"]) {
        window.addEventListener(evt, ping, { passive: true, capture: true });
    }

    try {
        chrome.runtime.sendMessage({
            type: "frago.content_ready",
            url: location.href,
        });
    } catch (_) { /* SW may be asleep; ignore */ }

    // ══════════ 2. Page extraction & Focus capture helpers ══════════
    function extractFullPageSnapshot() {
        const root = document.body || document.documentElement;
        if (!extractor || !root) {
            const txt = (root?.innerText || "").trim();
            return {
                title: document.title || "",
                url: location.href,
                normalizedUrl: location.href.split("#")[0],
                markdown: txt,
                charCount: txt.length,
                extractedAt: Date.now(),
            };
        }
        const res = extractor.extractPageContext(root, {
            title: document.title || "",
            url: location.href,
            baseUrl: location.href,
            getComputedStyle: (el) => window.getComputedStyle(el),
        });
        return {
            ...res,
            extractedAt: Date.now(),
        };
    }

    function getRangeSurroundingContext(range, ancestorEl) {
        const fallback = { contextBefore: "", contextAfter: "" };
        if (!range || !ancestorEl) return fallback;
        try {
            const container = ancestorEl.closest?.("article, section, main, div, p, li, td, blockquote")
                || document.body;
            if (!container) return fallback;

            const pre = document.createRange();
            pre.selectNodeContents(container);
            pre.setEnd(range.startContainer, range.startOffset);
            const preStr = pre.toString();

            const post = document.createRange();
            post.selectNodeContents(container);
            post.setStart(range.endContainer, range.endOffset);
            const postStr = post.toString();

            return {
                contextBefore: preStr.slice(-40),
                contextAfter: postStr.slice(0, 40),
            };
        } catch (_) {
            return fallback;
        }
    }

    function captureCurrentSelection() {
        const sel = window.getSelection();
        if (!sel || sel.rangeCount === 0) {
            return { ok: false, error: "当前页面未检测到划词选区" };
        }
        const rawText = sel.toString().trim();
        if (!rawText) {
            return { ok: false, error: "当前选区内容为空" };
        }

        const range = sel.getRangeAt(0);
        const common = range.commonAncestorContainer;
        const ancestorEl = common.nodeType === 1 ? common : common.parentElement;

        let markdown = rawText;
        if (extractor) {
            const container = document.createElement("div");
            container.appendChild(range.cloneContents());
            const converted = extractor.extractElementMarkdown(container, {
                baseUrl: location.href,
            });
            if (converted) markdown = converted;
        }

        const selector = extractor && ancestorEl
            ? extractor.computeCssSelector(ancestorEl, document.body)
            : "";
        const { contextBefore, contextAfter } = getRangeSurroundingContext(range, ancestorEl);
        const pageSnapshot = extractFullPageSnapshot();

        return {
            ok: true,
            focus: {
                kind: "selection",
                title: document.title || "",
                url: location.href,
                selector,
                markdown,
                text: rawText,
                contextBefore,
                contextAfter,
                capturedAt: Date.now(),
            },
            pageSnapshot,
        };
    }

    function captureElementAsFocus(el) {
        if (!el) return null;
        const markdown = extractor
            ? extractor.extractElementMarkdown(el, {
                baseUrl: location.href,
                getComputedStyle: (n) => window.getComputedStyle(n),
            })
            : (el.innerText || el.textContent || "").trim();
        const rawText = (el.innerText || el.textContent || "").trim();
        const selector = extractor
            ? extractor.computeCssSelector(el, document.body)
            : el.tagName.toLowerCase();
        const pageSnapshot = extractFullPageSnapshot();
        return {
            focus: {
                kind: "element",
                title: document.title || "",
                url: location.href,
                selector,
                tagName: el.tagName,
                markdown: markdown || rawText,
                text: rawText || markdown,
                contextBefore: "",
                contextAfter: "",
                capturedAt: Date.now(),
            },
            pageSnapshot,
        };
    }

    // ══════════ 3. Lightweight Shadow DOM Selection Pill ══════════
    let pillEnabled = false;
    let pillHost = null;
    let pillBtn = null;
    let pillTimer = null;

    function destroySelectionPill() {
        if (pillHost && pillHost.parentNode) {
            pillHost.parentNode.removeChild(pillHost);
        }
        pillHost = null;
        pillBtn = null;
    }

    function isEditableElement(node) {
        if (!node) return false;
        const el = node.nodeType === 1 ? node : node.parentElement;
        if (!el) return false;
        const tag = el.tagName?.toUpperCase();
        if (tag === "INPUT" || tag === "TEXTAREA") return true;
        return !!el.isContentEditable;
    }

    function showSelectionPill(rect) {
        destroySelectionPill();
        pillHost = document.createElement("div");
        pillHost.id = "__frago-selection-pill-host";
        pillHost.setAttribute("data-frago-ext-ui", "1");
        const top = Math.max(8, Math.min(window.innerHeight - 40, rect.bottom + 8));
        const left = Math.max(8, Math.min(window.innerWidth - 150, rect.right - 60));
        pillHost.style.cssText =
            `position:fixed;top:${top}px;left:${left}px;z-index:2147483647;`;

        const shadow = pillHost.attachShadow({ mode: "open" });
        const style = document.createElement("style");
        style.textContent = `
            button {
                all: unset;
                display: inline-flex;
                align-items: center;
                gap: 5px;
                padding: 5px 11px 5px 9px;
                border-radius: 999px;
                background: rgba(20, 20, 22, 0.9);
                backdrop-filter: blur(10px);
                -webkit-backdrop-filter: blur(10px);
                color: rgba(255, 255, 255, 0.94);
                font: 500 12px/1.2 "Geist Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                box-shadow: 0 8px 24px rgba(0, 0, 0, 0.24), inset 0 1px 0 rgba(255, 255, 255, 0.1);
                border: 1px solid rgba(255, 255, 255, 0.16);
                cursor: pointer;
                user-select: none;
                transition: transform 0.14s ease, background-color 0.15s ease, border-color 0.15s ease;
            }
            button:hover {
                background: #27272a;
                border-color: rgba(21, 179, 77, 0.55);
                transform: translateY(-1px);
            }
            button.is-done {
                background: #0a8f33;
                border-color: rgba(255, 255, 255, 0.22);
                color: #ffffff;
            }
            svg {
                flex-shrink: 0;
                display: block;
            }
        `;
        const svgNs = "http://www.w3.org/2000/svg";
        function makeIcon(isDone) {
            const svg = document.createElementNS(svgNs, "svg");
            svg.setAttribute("width", "13");
            svg.setAttribute("height", "13");
            svg.setAttribute("viewBox", "0 0 24 24");
            svg.setAttribute("fill", "none");
            svg.setAttribute("stroke", "currentColor");
            svg.setAttribute("stroke-width", "2");
            svg.setAttribute("stroke-linecap", "round");
            svg.setAttribute("stroke-linejoin", "round");
            svg.setAttribute("aria-hidden", "true");
            if (isDone) {
                const p = document.createElementNS(svgNs, "polyline");
                p.setAttribute("points", "20 6 9 17 4 12");
                svg.appendChild(p);
            } else {
                const p1 = document.createElementNS(svgNs, "path");
                p1.setAttribute("d", "M5 12h14");
                const p2 = document.createElementNS(svgNs, "path");
                p2.setAttribute("d", "M12 5v14");
                svg.appendChild(p1);
                svg.appendChild(p2);
            }
            return svg;
        }
        pillBtn = document.createElement("button");
        pillBtn.type = "button";
        const pillText = document.createElement("span");
        pillText.textContent = "带入对话";
        pillBtn.appendChild(makeIcon(false));
        pillBtn.appendChild(pillText);
        pillBtn.addEventListener("mousedown", (e) => {
            // Keep current selection intact until click fires
            e.preventDefault();
            e.stopPropagation();
        });
        pillBtn.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            const captured = captureCurrentSelection();
            if (!captured.ok) {
                destroySelectionPill();
                return;
            }
            try {
                chrome.runtime.sendMessage({
                    type: "frago.bridge.addFocus",
                    focus: captured.focus,
                    pageSnapshot: captured.pageSnapshot,
                });
            } catch (_) { /* ignore */ }
            if (pillBtn) {
                pillBtn.textContent = "";
                pillBtn.appendChild(makeIcon(true));
                const doneText = document.createElement("span");
                doneText.textContent = "已带入对话";
                pillBtn.appendChild(doneText);
                pillBtn.classList.add("is-done");
            }
            setTimeout(destroySelectionPill, 650);
        });

        shadow.appendChild(style);
        shadow.appendChild(pillBtn);
        (document.documentElement || document.body).appendChild(pillHost);
    }

    function scheduleSelectionCheck() {
        if (pillTimer) clearTimeout(pillTimer);
        pillTimer = setTimeout(() => {
            if (!pillEnabled || (picker && picker.isActive())) {
                destroySelectionPill();
                return;
            }
            const sel = window.getSelection();
            if (!sel || sel.isCollapsed || sel.rangeCount === 0) {
                destroySelectionPill();
                return;
            }
            const text = sel.toString().trim();
            if (text.length < 2) {
                destroySelectionPill();
                return;
            }
            if (isEditableElement(sel.anchorNode)) {
                destroySelectionPill();
                return;
            }
            const range = sel.getRangeAt(0);
            const rect = range.getBoundingClientRect();
            if (!rect || (rect.width === 0 && rect.height === 0)) {
                destroySelectionPill();
                return;
            }
            showSelectionPill(rect);
        }, 100);
    }

    document.addEventListener("mouseup", (e) => {
        if (pillHost && (e.target === pillHost || pillHost.contains(e.target))) return;
        scheduleSelectionCheck();
    }, { passive: true });
    document.addEventListener("keyup", scheduleSelectionCheck, { passive: true });
    document.addEventListener("mousedown", (e) => {
        if (pillHost && e.target !== pillHost && !pillHost.contains(e.target)) {
            destroySelectionPill();
        }
    }, { passive: true });

    // Query initial pill state on load
    try {
        chrome.runtime.sendMessage({ type: "frago.bridge.getPillState" }, (resp) => {
            if (chrome.runtime.lastError || !resp) return;
            pillEnabled = !!resp.enabled;
        });
    } catch (_) { /* ignore */ }

    // ══════════ 4. Bridge RPC listener ══════════
    chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
        if (!msg || typeof msg.type !== "string") return false;

        if (msg.type === "frago.bridge.extractFullPage") {
            try {
                sendResponse({ ok: true, page: extractFullPageSnapshot() });
            } catch (err) {
                sendResponse({ ok: false, error: String(err?.message || err) });
            }
            return false;
        }

        if (msg.type === "frago.bridge.captureSelection") {
            try {
                sendResponse(captureCurrentSelection());
            } catch (err) {
                sendResponse({ ok: false, error: String(err?.message || err) });
            }
            return false;
        }

        if (msg.type === "frago.bridge.startPicker") {
            destroySelectionPill();
            if (!picker) {
                sendResponse({ ok: false, error: "Element Picker 模块未加载" });
                return false;
            }
            picker.start({
                onSelect(targetEl) {
                    const captured = captureElementAsFocus(targetEl);
                    if (!captured) return;
                    try {
                        chrome.runtime.sendMessage({
                            type: "frago.bridge.addFocus",
                            focus: captured.focus,
                            pageSnapshot: captured.pageSnapshot,
                        });
                    } catch (_) { /* ignore */ }
                },
            });
            sendResponse({ ok: true });
            return false;
        }

        if (msg.type === "frago.bridge.stopPicker") {
            picker?.stop();
            sendResponse({ ok: true });
            return false;
        }

        if (msg.type === "frago.bridge.pillState") {
            pillEnabled = !!msg.enabled;
            if (!pillEnabled) destroySelectionPill();
            sendResponse({ ok: true });
            return false;
        }

        return false;
    });
})();
