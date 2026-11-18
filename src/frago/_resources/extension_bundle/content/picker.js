// frago bridge — Shadow DOM Element Picker
//
// Hover to highlight semantic content blocks, ArrowUp/ArrowDown to expand or
// narrow DOM depth, Click to select as Focus, Esc to cancel.

(() => {
    if (globalThis.FragoElementPicker) return;

    let active = false;
    let hostEl = null;
    let boxEl = null;
    let pillEl = null;
    let currentEl = null;
    let downStack = [];
    let onSelectCb = null;
    let onCancelCb = null;

    function isOwnNode(node) {
        if (!node) return false;
        if (node === hostEl) return true;
        if (node.id === "__frago-picker-host" || node.id === "__frago-selection-pill-host") {
            return true;
        }
        return !!(node.closest && node.closest('[data-frago-ext-ui="1"]'));
    }

    function pickTargetAtPoint(x, y) {
        const stack = document.elementsFromPoint(x, y);
        for (const el of stack) {
            if (!el || el.nodeType !== 1) continue;
            if (isOwnNode(el)) continue;
            const tag = el.tagName.toUpperCase();
            if (tag === "HTML" || tag === "BODY") continue;
            return el;
        }
        return null;
    }

    function updateOverlay(el) {
        currentEl = el;
        if (!boxEl || !pillEl) return;
        if (!el) {
            boxEl.style.display = "none";
            pillEl.style.display = "none";
            return;
        }
        const rect = el.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) {
            boxEl.style.display = "none";
            pillEl.style.display = "none";
            return;
        }
        boxEl.style.display = "block";
        boxEl.style.left = `${Math.max(0, rect.left)}px`;
        boxEl.style.top = `${Math.max(0, rect.top)}px`;
        boxEl.style.width = `${Math.min(window.innerWidth, rect.width)}px`;
        boxEl.style.height = `${Math.min(window.innerHeight, rect.height)}px`;

        const tag = el.tagName.toLowerCase();
        const textLen = (el.innerText || el.textContent || "").trim().length;
        if (pillEl._tagEl) pillEl._tagEl.textContent = `<${tag}>`;
        if (pillEl._metaEl) {
            pillEl._metaEl.textContent = `${Math.round(rect.width)}×${Math.round(rect.height)} · ${textLen} 字 · ↑↓ 调层级 · Click 拾取 · Esc 退出`;
        }
        pillEl.style.display = "inline-flex";
        const pillTop = rect.top > 34 ? rect.top - 30 : Math.min(window.innerHeight - 32, rect.top + 6);
        const pillLeft = Math.max(6, Math.min(window.innerWidth - 360, rect.left));
        pillEl.style.top = `${pillTop}px`;
        pillEl.style.left = `${pillLeft}px`;
    }

    function onMouseMove(e) {
        if (!active) return;
        const target = pickTargetAtPoint(e.clientX, e.clientY);
        if (target && target !== currentEl) {
            downStack = [];
            updateOverlay(target);
        }
    }

    function findMeaningfulChild(el) {
        if (!el) return null;
        for (const child of el.children) {
            if (isOwnNode(child)) continue;
            const rect = child.getBoundingClientRect();
            const hasText = (child.innerText || child.textContent || "").trim().length > 0;
            if (rect.width > 0 && rect.height > 0 && hasText) {
                return child;
            }
        }
        return null;
    }

    function onKeyDown(e) {
        if (!active) return;
        if (e.key === "Escape") {
            e.preventDefault();
            e.stopPropagation();
            const cb = onCancelCb;
            stop();
            if (cb) cb();
            return;
        }
        if (e.key === "ArrowUp") {
            e.preventDefault();
            e.stopPropagation();
            if (!currentEl || !currentEl.parentElement) return;
            const parent = currentEl.parentElement;
            const pTag = parent.tagName.toUpperCase();
            if (pTag === "HTML") return;
            downStack.push(currentEl);
            updateOverlay(parent);
            return;
        }
        if (e.key === "ArrowDown") {
            e.preventDefault();
            e.stopPropagation();
            if (downStack.length > 0) {
                updateOverlay(downStack.pop());
                return;
            }
            const child = findMeaningfulChild(currentEl);
            if (child) updateOverlay(child);
            return;
        }
        if (e.key === "Enter" && currentEl) {
            e.preventDefault();
            e.stopPropagation();
            const chosen = currentEl;
            const cb = onSelectCb;
            stop();
            if (cb) cb(chosen);
        }
    }

    function onMouseDown(e) {
        if (!active) return;
        e.preventDefault();
        e.stopPropagation();
    }

    function onClick(e) {
        if (!active) return;
        e.preventDefault();
        e.stopPropagation();
        const chosen = currentEl || pickTargetAtPoint(e.clientX, e.clientY);
        const cb = onSelectCb;
        stop();
        if (chosen && cb) cb(chosen);
    }

    function mountOverlay() {
        hostEl = document.createElement("div");
        hostEl.id = "__frago-picker-host";
        hostEl.setAttribute("data-frago-ext-ui", "1");
        hostEl.style.cssText =
            "position:fixed;inset:0;pointer-events:none;z-index:2147483647;";

        const shadow = hostEl.attachShadow({ mode: "open" });
        const style = document.createElement("style");
        style.textContent = `
            .frago-box {
                position: fixed;
                display: none;
                border: 1.5px solid #15b34d;
                background: rgba(21, 179, 77, 0.08);
                border-radius: 6px;
                box-sizing: border-box;
                box-shadow:
                    0 0 0 1px rgba(255, 255, 255, 0.72),
                    0 0 0 3px rgba(21, 179, 77, 0.14);
                transition: left 70ms ease-out, top 70ms ease-out, width 70ms ease-out, height 70ms ease-out;
                pointer-events: none;
            }
            .frago-pill {
                position: fixed;
                display: none;
                align-items: center;
                gap: 7px;
                background: rgba(20, 20, 22, 0.9);
                backdrop-filter: blur(10px);
                -webkit-backdrop-filter: blur(10px);
                color: rgba(255, 255, 255, 0.9);
                font: 500 11px/1.3 "Geist Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                padding: 4px 10px 4px 6px;
                border-radius: 8px;
                border: 1px solid rgba(255, 255, 255, 0.14);
                white-space: nowrap;
                box-shadow: 0 8px 24px rgba(0, 0, 0, 0.28);
                pointer-events: none;
                font-variant-numeric: tabular-nums;
            }
            .frago-pill-tag {
                font-family: "Geist Mono", "SF Mono", ui-monospace, Menlo, monospace;
                font-size: 10.5px;
                font-weight: 600;
                padding: 1px 5px;
                border-radius: 5px;
                background: rgba(21, 179, 77, 0.18);
                border: 1px solid rgba(21, 179, 77, 0.36);
                color: #4ade80;
            }
            .frago-pill-meta {
                color: rgba(255, 255, 255, 0.72);
            }
        `;
        boxEl = document.createElement("div");
        boxEl.className = "frago-box";
        pillEl = document.createElement("div");
        pillEl.className = "frago-pill";
        const tagBadge = document.createElement("span");
        tagBadge.className = "frago-pill-tag";
        const metaText = document.createElement("span");
        metaText.className = "frago-pill-meta";
        pillEl.appendChild(tagBadge);
        pillEl.appendChild(metaText);
        pillEl._tagEl = tagBadge;
        pillEl._metaEl = metaText;

        shadow.appendChild(style);
        shadow.appendChild(boxEl);
        shadow.appendChild(pillEl);
        (document.documentElement || document.body).appendChild(hostEl);
    }

    function start({ onSelect, onCancel } = {}) {
        if (active) stop();
        active = true;
        onSelectCb = typeof onSelect === "function" ? onSelect : null;
        onCancelCb = typeof onCancel === "function" ? onCancel : null;
        downStack = [];
        currentEl = null;
        mountOverlay();
        document.documentElement.style.cursor = "crosshair";
        window.addEventListener("mousemove", onMouseMove, true);
        window.addEventListener("keydown", onKeyDown, true);
        window.addEventListener("mousedown", onMouseDown, true);
        window.addEventListener("click", onClick, true);
    }

    function stop() {
        if (!active) return;
        active = false;
        window.removeEventListener("mousemove", onMouseMove, true);
        window.removeEventListener("keydown", onKeyDown, true);
        window.removeEventListener("mousedown", onMouseDown, true);
        window.removeEventListener("click", onClick, true);
        document.documentElement.style.cursor = "";
        if (hostEl && hostEl.parentNode) {
            hostEl.parentNode.removeChild(hostEl);
        }
        hostEl = null;
        boxEl = null;
        pillEl = null;
        currentEl = null;
        downStack = [];
        onSelectCb = null;
        onCancelCb = null;
    }

    function isActive() {
        return active;
    }

    globalThis.FragoElementPicker = { start, stop, isActive };
})();
