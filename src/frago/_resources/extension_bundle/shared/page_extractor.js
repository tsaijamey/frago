// frago bridge — full-page visible DOM extraction, markdown conversion,
// and in-page Focus anchor injection.
//
// Zero external dependencies. Runs identically in:
//   1. Chrome Content Script (via globalThis.FragoPageExtractor)
//   2. Extension Side Panel (via <script> or import)
//   3. Node.js unit tests (`node --test` via module.exports)

(function (root, factory) {
    const api = factory();
    if (typeof module === "object" && module && module.exports) {
        module.exports = api;
    }
    if (root) {
        root.FragoPageExtractor = api;
    }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
    "use strict";

    const SKIP_TAGS = new Set([
        "SCRIPT",
        "STYLE",
        "NOSCRIPT",
        "SVG",
        "CANVAS",
        "TEMPLATE",
        "IFRAME",
        "OBJECT",
        "EMBED",
        "VIDEO",
        "AUDIO",
        "MAP",
        "AREA",
        "LINK",
        "META",
        "HEAD",
        "TITLE",
    ]);

    const BLOCK_TAGS = new Set([
        "ADDRESS",
        "ARTICLE",
        "ASIDE",
        "BLOCKQUOTE",
        "DD",
        "DETAILS",
        "DIALOG",
        "DIV",
        "DL",
        "DT",
        "FIELDSET",
        "FIGCAPTION",
        "FIGURE",
        "FOOTER",
        "FORM",
        "H1",
        "H2",
        "H3",
        "H4",
        "H5",
        "H6",
        "HEADER",
        "HGROUP",
        "HR",
        "LI",
        "MAIN",
        "NAV",
        "OL",
        "P",
        "PRE",
        "SECTION",
        "TABLE",
        "UL",
    ]);

    function isExtensionUiNode(node) {
        if (!node || node.nodeType !== 1) return false;
        const attr = typeof node.getAttribute === "function"
            ? node.getAttribute("data-frago-ext-ui")
            : null;
        if (attr === "1" || attr === "true") return true;
        if (node.id === "__frago-picker-host" || node.id === "__frago-selection-pill-host") {
            return true;
        }
        return false;
    }

    function parseInlineStyleFlags(styleText) {
        if (!styleText || typeof styleText !== "string") {
            return { hidden: false };
        }
        const lower = styleText.toLowerCase();
        if (/(?:^|;)\s*display\s*:\s*none\b/.test(lower)) return { hidden: true };
        if (/(?:^|;)\s*visibility\s*:\s*(?:hidden|collapse)\b/.test(lower)) return { hidden: true };
        if (/(?:^|;)\s*opacity\s*:\s*0(?:\.0+)?\s*(?:;|$)/.test(lower)) return { hidden: true };
        return { hidden: false };
    }

    function isElementVisible(el, options = {}) {
        if (!el || el.nodeType !== 1) return true;
        const tag = String(el.tagName || "").toUpperCase();
        if (SKIP_TAGS.has(tag)) return false;
        if (isExtensionUiNode(el)) return false;

        if (typeof el.hasAttribute === "function" && el.hasAttribute("hidden")) {
            return false;
        }
        if (typeof el.getAttribute === "function") {
            const ariaHidden = el.getAttribute("aria-hidden");
            if (ariaHidden && ariaHidden.toLowerCase() === "true") return false;
            if (tag === "INPUT") {
                const inputType = (el.getAttribute("type") || "").toLowerCase();
                if (inputType === "hidden") return false;
            }
            const inlineStyle = el.getAttribute("style");
            if (parseInlineStyleFlags(inlineStyle).hidden) return false;
        }
        if (el.style && typeof el.style === "object") {
            if (el.style.display === "none") return false;
            if (el.style.visibility === "hidden" || el.style.visibility === "collapse") return false;
            if (el.style.opacity === "0" || el.style.opacity === 0) return false;
        }

        const styleFn = options.getComputedStyle
            || (typeof getComputedStyle === "function" ? getComputedStyle : null);
        if (styleFn) {
            try {
                const cs = styleFn(el);
                if (cs) {
                    if (cs.display === "none") return false;
                    if (cs.visibility === "hidden" || cs.visibility === "collapse") return false;
                    if (cs.opacity !== "" && cs.opacity !== undefined && parseFloat(cs.opacity) === 0) {
                        return false;
                    }
                }
            } catch (_) {
                // Ignore style lookup errors on detached/mock nodes
            }
        }
        return true;
    }

    function normalizeUrl(rawUrl, baseUrl) {
        const s = String(rawUrl || "").trim();
        if (!s) return "";
        if (/^(?:javascript|vbscript|data):/i.test(s)) return "";
        if (!baseUrl) return s;
        try {
            return new URL(s, baseUrl).href;
        } catch (_) {
            return s;
        }
    }

    function normalizePageUrl(rawUrl) {
        const s = String(rawUrl || "").trim();
        if (!s) return "";
        try {
            const u = new URL(s);
            u.hash = "";
            return u.href;
        } catch (_) {
            const hashIdx = s.indexOf("#");
            return hashIdx >= 0 ? s.slice(0, hashIdx) : s;
        }
    }

    function computeCssSelector(el, stopAt) {
        if (!el || el.nodeType !== 1) return "";
        const parts = [];
        let cur = el;
        while (cur && cur.nodeType === 1) {
            const tag = String(cur.tagName || "").toLowerCase();
            if (!tag) break;
            if (tag === "html") break;
            if (cur === stopAt || tag === "body") {
                parts.unshift(tag);
                break;
            }
            const id = cur.id ? String(cur.id).trim() : "";
            if (id && /^[A-Za-z_][A-Za-z0-9_-]*$/.test(id)) {
                parts.unshift(`#${id}`);
                break;
            }
            let index = 1;
            let sibling = cur.previousElementSibling;
            while (sibling) {
                if (String(sibling.tagName || "").toLowerCase() === tag) {
                    index += 1;
                }
                sibling = sibling.previousElementSibling;
            }
            let hasSameTagSibling = index > 1;
            if (!hasSameTagSibling) {
                let next = cur.nextElementSibling;
                while (next) {
                    if (String(next.tagName || "").toLowerCase() === tag) {
                        hasSameTagSibling = true;
                        break;
                    }
                    next = next.nextElementSibling;
                }
            }
            parts.unshift(hasSameTagSibling ? `${tag}:nth-of-type(${index})` : tag);
            cur = cur.parentElement;
        }
        return parts.join(" > ");
    }

    function extractRawVisibleText(node, options = {}) {
        if (!node) return "";
        if (node.nodeType === 3) return String(node.nodeValue || "");
        if (node.nodeType !== 1) return "";
        if (!isElementVisible(node, options)) return "";
        const tag = String(node.tagName || "").toUpperCase();
        if (tag === "BR") return "\n";
        let out = "";
        const children = node.childNodes || [];
        for (let i = 0; i < children.length; i += 1) {
            out += extractRawVisibleText(children[i], options);
        }
        return out;
    }

    function extractCodeLanguage(el) {
        const cls = (typeof el.getAttribute === "function" ? el.getAttribute("class") : el.className) || "";
        const m = String(cls).match(/(?:language|lang)-([A-Za-z0-9_+-]+)/i);
        return m ? m[1] : "";
    }

    function cleanCellText(str) {
        return String(str || "")
            .replace(/\s+/g, " ")
            .replace(/\|/g, "\\|")
            .trim();
    }

    function renderTable(tableEl, options, ctx) {
        const rows = [];
        function collectRows(node) {
            if (!node || node.nodeType !== 1) return;
            if (!isElementVisible(node, options)) return;
            const tag = String(node.tagName || "").toUpperCase();
            if (tag === "TR") {
                const cells = [];
                const children = node.childNodes || [];
                for (let i = 0; i < children.length; i += 1) {
                    const child = children[i];
                    if (child.nodeType !== 1) continue;
                    const ctag = String(child.tagName || "").toUpperCase();
                    if ((ctag === "TH" || ctag === "TD") && isElementVisible(child, options)) {
                        cells.push(cleanCellText(renderNode(child, options, ctx)));
                    }
                }
                if (cells.length > 0) rows.push(cells);
                return;
            }
            const children = node.childNodes || [];
            for (let i = 0; i < children.length; i += 1) {
                collectRows(children[i]);
            }
        }
        collectRows(tableEl);
        if (rows.length === 0) return "";
        const colCount = Math.max(...rows.map((r) => r.length));
        if (colCount === 0) return "";
        const padRow = (r) => {
            const padded = r.slice();
            while (padded.length < colCount) padded.push("");
            return `| ${padded.join(" | ")} |`;
        };
        const lines = [padRow(rows[0]), `| ${Array(colCount).fill("---").join(" | ")} |`];
        for (let i = 1; i < rows.length; i += 1) {
            lines.push(padRow(rows[i]));
        }
        return `\n\n${lines.join("\n")}\n\n`;
    }

    function renderList(listEl, options, ctx) {
        const tag = String(listEl.tagName || "").toUpperCase();
        const ordered = tag === "OL";
        const depth = ctx.listDepth || 0;
        const nextCtx = { ...ctx, listDepth: depth + 1 };
        const items = [];
        let num = 1;
        const children = listEl.childNodes || [];
        for (let i = 0; i < children.length; i += 1) {
            const child = children[i];
            if (child.nodeType !== 1) continue;
            if (String(child.tagName || "").toUpperCase() !== "LI") continue;
            if (!isElementVisible(child, options)) continue;
            const rawContent = renderChildren(child, options, nextCtx).trim();
            if (!rawContent) continue;
            const indent = "  ".repeat(depth);
            const prefix = ordered ? `${num}. ` : "- ";
            num += 1;
            const lines = rawContent.split("\n");
            const first = `${indent}${prefix}${lines[0].trim()}`;
            const rest = lines.slice(1).map((line) => (line.trim() ? `${indent}  ${line}` : "")).filter(Boolean);
            items.push(rest.length > 0 ? `${first}\n${rest.join("\n")}` : first);
        }
        if (items.length === 0) return "";
        return `\n\n${items.join("\n")}\n\n`;
    }

    function renderChildren(node, options, ctx) {
        const children = node.childNodes || [];
        let out = "";
        for (let i = 0; i < children.length; i += 1) {
            out += renderNode(children[i], options, ctx);
        }
        return out;
    }

    function wrapWithAnchor(md, anchorEntries) {
        if (!anchorEntries || anchorEntries.length === 0 || !md.trim()) return md;
        let wrapped = md.trim();
        for (const entry of anchorEntries) {
            wrapped = `<<< 🎯 FOCUS #${entry.focusNumber} 开始 >>>\n${wrapped}\n<<< 🎯 FOCUS #${entry.focusNumber} 结束 >>>`;
        }
        return `\n\n${wrapped}\n\n`;
    }

    function renderNode(node, options = {}, ctx = { listDepth: 0, inPre: false }) {
        if (!node) return "";
        if (node.nodeType === 8) return ""; // Comment
        if (node.nodeType === 3) {
            const val = String(node.nodeValue || "");
            if (ctx.inPre) return val;
            return val.replace(/[\t\r\n ]+/g, " ");
        }
        if (node.nodeType !== 1) return "";
        if (!isElementVisible(node, options)) return "";

        const tag = String(node.tagName || "").toUpperCase();
        const anchorEntries = options.anchorElementMap ? options.anchorElementMap.get(node) : null;

        let result = "";
        if (tag === "BR") {
            result = "\n";
        } else if (tag === "HR") {
            result = "\n\n---\n\n";
        } else if (/^H[1-6]$/.test(tag)) {
            const level = Number(tag[1]);
            const inner = renderChildren(node, options, ctx).replace(/\s+/g, " ").trim();
            result = inner ? `\n\n${"#".repeat(level)} ${inner}\n\n` : "";
        } else if (tag === "P") {
            const inner = renderChildren(node, options, ctx).trim();
            result = inner ? `\n\n${inner}\n\n` : "";
        } else if (tag === "BLOCKQUOTE") {
            const inner = cleanMarkdown(renderChildren(node, options, ctx));
            if (inner) {
                const quoted = inner.split("\n").map((l) => (l ? `> ${l}` : ">")).join("\n");
                result = `\n\n${quoted}\n\n`;
            }
        } else if (tag === "PRE") {
            const codeChild = Array.from(node.childNodes || []).find(
                (c) => c.nodeType === 1 && String(c.tagName || "").toUpperCase() === "CODE"
            );
            const lang = codeChild ? extractCodeLanguage(codeChild) : extractCodeLanguage(node);
            const rawCode = extractRawVisibleText(codeChild || node, options).replace(/^\n+|\n+$/g, "");
            if (rawCode.trim()) {
                result = `\n\n\`\`\`${lang}\n${rawCode}\n\`\`\`\n\n`;
            }
        } else if (tag === "CODE") {
            const inner = extractRawVisibleText(node, options).replace(/\s+/g, " ").trim();
            result = inner ? `\`${inner}\`` : "";
        } else if (tag === "STRONG" || tag === "B") {
            const inner = renderChildren(node, options, ctx).trim();
            result = inner ? `**${inner}**` : "";
        } else if (tag === "EM" || tag === "I") {
            const inner = renderChildren(node, options, ctx).trim();
            result = inner ? `*${inner}*` : "";
        } else if (tag === "DEL" || tag === "S") {
            const inner = renderChildren(node, options, ctx).trim();
            result = inner ? `~~${inner}~~` : "";
        } else if (tag === "A") {
            const href = normalizeUrl(
                typeof node.getAttribute === "function" ? node.getAttribute("href") : node.href,
                options.baseUrl
            );
            const inner = renderChildren(node, options, ctx).replace(/\s+/g, " ").trim();
            if (!inner) {
                result = "";
            } else if (href) {
                result = `[${inner}](${href})`;
            } else {
                result = inner;
            }
        } else if (tag === "IMG") {
            const alt = cleanCellText(
                typeof node.getAttribute === "function" ? node.getAttribute("alt") : node.alt
            );
            const rawSrc = typeof node.getAttribute === "function" ? node.getAttribute("src") : node.src;
            const src = /^data:/i.test(String(rawSrc || "").trim())
                ? "image"
                : normalizeUrl(rawSrc, options.baseUrl);
            if (alt && src) {
                result = `![${alt}](${src})`;
            } else if (alt) {
                result = `![${alt}]()`;
            }
        } else if (tag === "UL" || tag === "OL") {
            result = renderList(node, options, ctx);
        } else if (tag === "TABLE") {
            result = renderTable(node, options, ctx);
        } else if (BLOCK_TAGS.has(tag)) {
            const inner = renderChildren(node, options, ctx).trim();
            result = inner ? `\n\n${inner}\n\n` : "";
        } else {
            result = renderChildren(node, options, ctx);
        }

        if (anchorEntries && anchorEntries.length > 0 && result.trim()) {
            return wrapWithAnchor(result, anchorEntries);
        }
        return result;
    }

    function cleanMarkdown(md) {
        const normalized = String(md || "").replace(/\r\n?/g, "\n");
        const lines = normalized.split("\n");
        let inFence = false;
        const cleanedLines = lines.map((line) => {
            if (/^```/.test(line.trim())) {
                inFence = !inFence;
                return line.trim();
            }
            if (inFence) return line;
            return line.replace(/[ \t]+$/g, "").replace(/^[ \t]+(?=\S)/g, (ws) => {
                // Keep list indentation up to reasonable depth
                return ws.length >= 2 && /^[ \t]+(?:[-*]|\d+\.)\s/.test(line) ? ws : "";
            });
        });
        return cleanedLines
            .join("\n")
            .replace(/\n{3,}/g, "\n\n")
            .trim();
    }

    function extractElementMarkdown(el, options = {}) {
        if (!el) return "";
        return cleanMarkdown(renderNode(el, options));
    }

    function extractPageContext(rootEl, options = {}) {
        const md = extractElementMarkdown(rootEl, options);
        const url = options.url || "";
        return {
            title: String(options.title || "").trim(),
            url,
            normalizedUrl: normalizePageUrl(url),
            markdown: md,
            charCount: md.length,
        };
    }

    // Build a stripped plain-text version of markdown alongside a character
    // index map back to the original markdown string.
    function buildSearchIndex(markdown) {
        const chars = [];
        const map = [];
        let lastWasSpace = true;
        for (let i = 0; i < markdown.length; i += 1) {
            const ch = markdown[i];
            if (/\s/.test(ch)) {
                if (!lastWasSpace) {
                    chars.push(" ");
                    map.push(i);
                    lastWasSpace = true;
                }
                continue;
            }
            // Strip common inline markdown punctuation when building normalized search text
            // while keeping alphanumeric, CJK, and regular punctuation intact.
            if (ch === "*" || ch === "`" || ch === "~") {
                continue;
            }
            chars.push(ch);
            map.push(i);
            lastWasSpace = false;
        }
        return {
            plain: chars.join("").trimEnd(),
            map,
        };
    }

    function normalizeForSearch(str) {
        return String(str || "")
            .replace(/[*`~]/g, "")
            .replace(/\s+/g, " ")
            .trim();
    }

    function scoreContextMatch(haystack, start, end, beforeCtx, afterCtx) {
        let score = 0;
        const normBefore = normalizeForSearch(beforeCtx);
        const normAfter = normalizeForSearch(afterCtx);
        if (normBefore) {
            const sliceBefore = haystack.slice(Math.max(0, start - normBefore.length - 20), start);
            const tail = normBefore.slice(-Math.min(20, normBefore.length));
            if (sliceBefore.includes(tail)) score += 2;
        }
        if (normAfter) {
            const sliceAfter = haystack.slice(end, Math.min(haystack.length, end + normAfter.length + 20));
            const head = normAfter.slice(0, Math.min(20, normAfter.length));
            if (sliceAfter.includes(head)) score += 2;
        }
        return score;
    }

    function findBestNeedleRange(pageMarkdown, focus, occupiedRanges) {
        const candidates = [];
        const rawMd = String(focus.markdown || "").trim();
        const rawText = String(focus.text || "").trim();
        const tryDirect = [rawMd, rawText].filter(Boolean);

        // 1. Direct exact substring match on pageMarkdown
        for (const needle of tryDirect) {
            let from = 0;
            while (from <= pageMarkdown.length - needle.length) {
                const idx = pageMarkdown.indexOf(needle, from);
                if (idx === -1) break;
                const end = idx + needle.length;
                const overlaps = occupiedRanges.some((r) => !(end <= r.start || idx >= r.end));
                if (!overlaps) {
                    const score = 10 + scoreContextMatch(
                        pageMarkdown,
                        idx,
                        end,
                        focus.contextBefore,
                        focus.contextAfter
                    );
                    candidates.push({ start: idx, end, score });
                }
                from = idx + 1;
            }
            if (candidates.length > 0) {
                candidates.sort((a, b) => b.score - a.score || a.start - b.start);
                return candidates[0];
            }
        }

        // 2. Normalized search index fallback (handles markdown formatting differences)
        const idxInfo = buildSearchIndex(pageMarkdown);
        const normNeedles = [normalizeForSearch(rawMd), normalizeForSearch(rawText)].filter(Boolean);
        for (const needle of normNeedles) {
            if (needle.length < 2) continue;
            let from = 0;
            while (from <= idxInfo.plain.length - needle.length) {
                const idx = idxInfo.plain.indexOf(needle, from);
                if (idx === -1) break;
                const plainEnd = idx + needle.length;
                const mdStart = idxInfo.map[idx];
                const lastPlainIdx = plainEnd - 1;
                const mdEndRaw = idxInfo.map[lastPlainIdx] + 1;
                // Expand mdEnd slightly if trailing markdown closing markers exist (*, `, **)
                let mdEnd = mdEndRaw;
                while (mdEnd < pageMarkdown.length && /[*`~]/.test(pageMarkdown[mdEnd])) {
                    mdEnd += 1;
                }
                let mdStartAdj = mdStart;
                while (mdStartAdj > 0 && /[*`~]/.test(pageMarkdown[mdStartAdj - 1])) {
                    mdStartAdj -= 1;
                }
                const overlaps = occupiedRanges.some((r) => !(mdEnd <= r.start || mdStartAdj >= r.end));
                if (!overlaps) {
                    const score = 5 + scoreContextMatch(
                        idxInfo.plain,
                        idx,
                        plainEnd,
                        focus.contextBefore,
                        focus.contextAfter
                    );
                    candidates.push({ start: mdStartAdj, end: mdEnd, score });
                }
                from = idx + 1;
            }
            if (candidates.length > 0) {
                candidates.sort((a, b) => b.score - a.score || a.start - b.start);
                return candidates[0];
            }
        }

        return null;
    }

    function isBlockBoundary(text, start, end) {
        const prevChar = start === 0 ? "\n" : text[start - 1];
        const nextChar = end >= text.length ? "\n" : text[end];
        return prevChar === "\n" && nextChar === "\n";
    }

    function injectFocusAnchors(pageMarkdown, focuses = []) {
        const source = String(pageMarkdown || "");
        if (!focuses || focuses.length === 0 || !source) {
            return {
                markdown: source,
                matchedNumbers: [],
                unmatchedNumbers: focuses.map((f) => f.focusNumber),
            };
        }

        const matched = [];
        const unmatchedNumbers = [];
        const occupied = [];

        for (const focus of focuses) {
            const num = focus.focusNumber;
            const hit = findBestNeedleRange(source, focus, occupied);
            if (hit) {
                occupied.push(hit);
                matched.push({
                    focusNumber: num,
                    start: hit.start,
                    end: hit.end,
                });
            } else {
                unmatchedNumbers.push(num);
            }
        }

        // Apply insertions from back to front so offsets stay valid
        matched.sort((a, b) => b.start - a.start || b.end - a.end);
        let out = source;
        for (const item of matched) {
            const segment = out.slice(item.start, item.end);
            const block = isBlockBoundary(out, item.start, item.end) || segment.includes("\n");
            const startTag = `<<< 🎯 FOCUS #${item.focusNumber} 开始 >>>`;
            const endTag = `<<< 🎯 FOCUS #${item.focusNumber} 结束 >>>`;
            const replacement = block
                ? `${startTag}\n${segment}\n${endTag}`
                : `${startTag} ${segment} ${endTag}`;
            out = `${out.slice(0, item.start)}${replacement}${out.slice(item.end)}`;
        }

        return {
            markdown: out,
            matchedNumbers: matched.map((m) => m.focusNumber).sort((a, b) => a - b),
            unmatchedNumbers,
        };
    }

    return {
        SKIP_TAGS,
        isExtensionUiNode,
        isElementVisible,
        normalizeUrl,
        normalizePageUrl,
        computeCssSelector,
        extractElementMarkdown,
        extractPageContext,
        cleanMarkdown,
        injectFocusAnchors,
    };
});
