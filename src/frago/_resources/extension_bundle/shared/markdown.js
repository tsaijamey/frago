// frago bridge — CSP-safe Markdown parser and DOM renderer.
//
// Zero external dependencies. Runs identically in:
//   1. Extension Side Panel (via globalThis.FragoMarkdown)
//   2. Node.js unit tests (`node --test` via module.exports)

(function (root, factory) {
    const api = factory();
    if (typeof module === "object" && module && module.exports) {
        module.exports = api;
    }
    if (root) {
        root.FragoMarkdown = api;
    }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
    "use strict";

    function isSafeUrl(raw) {
        const s = String(raw || "").trim();
        if (!s) return false;
        try {
            const u = new URL(s);
            return u.protocol === "http:" || u.protocol === "https:" || u.protocol === "mailto:";
        } catch (_) {
            return false;
        }
    }

    function safeDecodeURIComponent(raw) {
        return String(raw || "").replace(/%(?:[0-9A-Fa-f]{2})+/g, (seq) => {
            try {
                return decodeURIComponent(seq);
            } catch (_) {
                return seq;
            }
        });
    }

    function parseLineAnchorRange(line) {
        const s = String(line || "").trim();
        if (!s) return null;
        const m = s.match(/^L(\d+)(?:-L?(\d+))?$/i);
        if (!m) return null;
        const startLine = Number(m[1]);
        const rawEnd = m[2] ? Number(m[2]) : startLine;
        if (!Number.isFinite(startLine) || startLine < 1) return null;
        const endLine = Number.isFinite(rawEnd) && rawEnd >= startLine ? rawEnd : startLine;
        return { startLine, endLine };
    }

    function parseFileUrl(raw) {
        const s = String(raw || "").trim();
        if (!/^file:\/\//i.test(s)) return null;
        const hashIdx = s.indexOf("#");
        const beforeHash = hashIdx >= 0 ? s.slice(0, hashIdx) : s;
        const fragment = hashIdx >= 0 ? s.slice(hashIdx + 1).trim() : "";
        let rawPath = beforeHash.slice("file://".length);
        if (/^localhost\//i.test(rawPath)) {
            rawPath = rawPath.slice("localhost".length);
        }
        if (!rawPath.startsWith("/")) return null;
        const decodedPath = safeDecodeURIComponent(rawPath);
        const lineMatch = fragment.match(/^(L\d+(?:-L?\d+)?)$/i);
        return {
            path: decodedPath,
            line: lineMatch ? lineMatch[1].toUpperCase() : undefined,
        };
    }

    function validateCitationUri(rawUri) {
        const trimmed = String(rawUri || "").trim();
        if (!trimmed) return { kind: "invalid" };

        const fileParsed = parseFileUrl(trimmed);
        if (fileParsed) {
            const range = parseLineAnchorRange(fileParsed.line);
            return {
                kind: "local",
                filePath: fileParsed.path,
                line: fileParsed.line,
                hlStart: range ? range.startLine : undefined,
                hlEnd: range ? range.endLine : undefined,
            };
        }

        try {
            const u = new URL(trimmed);
            if (u.protocol === "https:" || u.protocol === "http:") {
                return { kind: "web" };
            }
        } catch (_) {
            // Fall through to invalid
        }
        return { kind: "invalid" };
    }

    function parseFootnoteBody(rawBody) {
        const body = String(rawBody || "").trim();
        if (!body) {
            return { title: "", uri: "", excerpt: "" };
        }
        // Standard GFM citation entry: [Title](URI "optional excerpt") or [Title](URI 'optional excerpt')
        const mdLinkMatch = body.match(
            /^\[([^\]]+)\]\(\s*([^)\s]+)(?:\s+(?:"([^"]*)"|'([^']*)'))?\s*\)\s*(.*)$/
        );
        if (mdLinkMatch) {
            const title = mdLinkMatch[1].trim();
            const uri = mdLinkMatch[2].trim();
            const excerpt = (mdLinkMatch[3] || mdLinkMatch[4] || mdLinkMatch[5] || "").trim();
            return { title: title || uri, uri, excerpt };
        }
        // Bare URI fallback: URI "optional excerpt"
        const bareMatch = body.match(/^(\S+)(?:\s+(?:"([^"]*)"|'([^']*)'))?\s*(.*)$/);
        if (bareMatch) {
            const uri = bareMatch[1].trim();
            const excerpt = (bareMatch[2] || bareMatch[3] || bareMatch[4] || "").trim();
            return { title: uri, uri, excerpt };
        }
        return { title: body, uri: "", excerpt: "" };
    }

    function stripFootnoteDefinitions(rawText) {
        const text = String(rawText || "").replace(/\r\n?/g, "\n");
        const lines = text.split("\n");
        const defs = [];
        const defsById = new Map();
        const keptLines = [];
        let inFence = false;
        let fenceChar = "";
        let fenceLen = 0;

        for (let i = 0; i < lines.length; i += 1) {
            const line = lines[i];

            if (!inFence) {
                const fenceOpen = line.match(/^\s{0,3}(```+|~~~+)/);
                if (fenceOpen) {
                    inFence = true;
                    fenceChar = fenceOpen[1][0];
                    fenceLen = fenceOpen[1].length;
                    keptLines.push(line);
                    continue;
                }
            } else {
                const closeRe = new RegExp(`^\\s{0,3}${fenceChar}{${fenceLen},}\\s*$`);
                if (closeRe.test(line)) {
                    inFence = false;
                    fenceChar = "";
                    fenceLen = 0;
                }
                keptLines.push(line);
                continue;
            }

            // Indented code block (4+ spaces or tab) when not continuing a footnote definition
            if (/^(?: {4}|\t)/.test(line)) {
                keptLines.push(line);
                continue;
            }

            const defMatch = line.match(/^\[\^([A-Za-z0-9_-]+)\]:\s*(.*)$/);
            if (defMatch) {
                const id = defMatch[1];
                const parts = [defMatch[2]];
                // Absorb optional indented continuation lines belonging to this footnote definition
                while (i + 1 < lines.length && /^(?: {2,}|\t)\S/.test(lines[i + 1])) {
                    i += 1;
                    parts.push(lines[i].trim());
                }
                const parsed = parseFootnoteBody(parts.join(" "));
                const validated = validateCitationUri(parsed.uri);
                const def = {
                    id,
                    label: id,
                    title: parsed.title || id,
                    uri: parsed.uri,
                    excerpt: parsed.excerpt,
                    kind: validated.kind,
                    filePath: validated.filePath,
                    line: validated.line,
                    hlStart: validated.hlStart,
                    hlEnd: validated.hlEnd,
                };
                if (!defsById.has(id)) {
                    defs.push(def);
                } else {
                    const idx = defs.findIndex((d) => d.id === id);
                    if (idx >= 0) defs[idx] = def;
                }
                defsById.set(id, def);
                continue;
            }

            keptLines.push(line);
        }

        return {
            cleanedText: keptLines.join("\n"),
            definitions: defs,
            definitionsMap: defsById,
        };
    }

    function parseFootnoteDefinitionsFromMarkdown(rawText) {
        return stripFootnoteDefinitions(rawText).definitions;
    }

    const CLAUSE_SPLIT_RE = /[。；;，,\n]|\.\s/;

    function wrapClauseNodesWithCite(nodes, def) {
        let splitIdx = -1;
        let splitTextOffset = -1;

        for (let idx = nodes.length - 1; idx >= 0; idx -= 1) {
            const node = nodes[idx];
            if (node.type === "citeSpan" || node.type === "citePill" || node.type === "citePending") {
                splitIdx = idx + 1;
                break;
            }
            if (node.type === "text") {
                let lastMatchEnd = -1;
                const re = new RegExp(CLAUSE_SPLIT_RE.source, "g");
                let m;
                while ((m = re.exec(node.text)) !== null) {
                    lastMatchEnd = m.index + m[0].length;
                }
                if (lastMatchEnd >= 0) {
                    splitIdx = idx;
                    splitTextOffset = lastMatchEnd;
                    break;
                }
            }
        }

        const pillNode = { type: "citePill", def };
        let prefix = [];
        let clauseNodes = [];

        if (splitIdx === -1) {
            clauseNodes = nodes.slice();
        } else if (splitTextOffset >= 0) {
            const target = nodes[splitIdx];
            const headText = target.text.slice(0, splitTextOffset);
            const tailText = target.text.slice(splitTextOffset);
            prefix = nodes.slice(0, splitIdx);
            if (headText) prefix.push({ type: "text", text: headText });
            if (tailText) clauseNodes.push({ type: "text", text: tailText });
            clauseNodes.push(...nodes.slice(splitIdx + 1));
        } else {
            prefix = nodes.slice(0, splitIdx);
            clauseNodes = nodes.slice(splitIdx);
        }

        const spanNode = {
            type: "citeSpan",
            def,
            children: [...clauseNodes, pillNode],
        };
        return [...prefix, spanNode];
    }

    function parseInline(text, options = {}) {
        const src = String(text || "");
        const defsMap = options.definitionsMap instanceof Map ? options.definitionsMap : null;
        const streaming = Boolean(options.streaming);
        let nodes = [];
        let i = 0;

        function pushText(str) {
            if (!str) return;
            const prev = nodes[nodes.length - 1];
            if (prev && prev.type === "text") {
                prev.text += str;
            } else {
                nodes.push({ type: "text", text: str });
            }
        }

        while (i < src.length) {
            // Backslash escape: \[^N], \[...], \`, \*, \\ etc.
            if (src[i] === "\\" && i + 1 < src.length) {
                const nextCh = src[i + 1];
                if ("\\`*_{}[]()#+-.!^~".includes(nextCh)) {
                    pushText(nextCh);
                    i += 2;
                    continue;
                }
            }

            // Inline code: `...`
            if (src[i] === "`") {
                const close = src.indexOf("`", i + 1);
                if (close > i + 1) {
                    nodes.push({ type: "code", text: src.slice(i + 1, close) });
                    i = close + 1;
                    continue;
                }
            }

            // Standard GFM Footnote Reference: [^N]
            if (src[i] === "[" && src[i + 1] === "^") {
                const refMatch = src.slice(i).match(/^\[\^([A-Za-z0-9_-]+)\]/);
                if (refMatch) {
                    const id = refMatch[1];
                    const def = defsMap ? defsMap.get(id) : undefined;
                    if (def) {
                        if (def.kind === "invalid") {
                            pushText(`[${def.label}]`);
                        } else {
                            nodes = wrapClauseNodesWithCite(nodes, def);
                        }
                    } else if (streaming) {
                        nodes.push({ type: "citePending", label: id });
                    } else {
                        pushText(refMatch[0]);
                    }
                    i += refMatch[0].length;
                    continue;
                }
            }

            // Link: [label](url)
            if (src[i] === "[") {
                const closeBracket = src.indexOf("]", i + 1);
                if (closeBracket > i + 1 && src[closeBracket + 1] === "(") {
                    const closeParen = src.indexOf(")", closeBracket + 2);
                    if (closeParen > closeBracket + 2) {
                        const label = src.slice(i + 1, closeBracket);
                        const href = src.slice(closeBracket + 2, closeParen).trim();
                        const fileTarget = parseFileUrl(href);
                        if (fileTarget) {
                            nodes.push({
                                type: "fileLink",
                                label,
                                href,
                                path: fileTarget.path,
                                line: fileTarget.line,
                            });
                            i = closeParen + 1;
                            continue;
                        }
                        if (isSafeUrl(href)) {
                            nodes.push({ type: "link", label, href });
                            i = closeParen + 1;
                            continue;
                        }
                    }
                }
            }

            // Bold: **...** or __...__
            if (src.startsWith("**", i) || src.startsWith("__", i)) {
                const marker = src.slice(i, i + 2);
                const close = src.indexOf(marker, i + 2);
                if (close > i + 2 && !src.slice(i + 2, close).includes("\n")) {
                    nodes.push({ type: "strong", children: parseInline(src.slice(i + 2, close), options) });
                    i = close + 2;
                    continue;
                }
            }

            // Strikethrough: ~~...~~
            if (src.startsWith("~~", i)) {
                const close = src.indexOf("~~", i + 2);
                if (close > i + 2 && !src.slice(i + 2, close).includes("\n")) {
                    nodes.push({ type: "del", children: parseInline(src.slice(i + 2, close), options) });
                    i = close + 2;
                    continue;
                }
            }

            // Italic: *...* (avoid matching list bullets or mid-word underscores)
            if (src[i] === "*" && src[i + 1] !== "*" && src[i + 1] !== " ") {
                const close = src.indexOf("*", i + 1);
                if (close > i + 1 && src[close - 1] !== " " && !src.slice(i + 1, close).includes("\n")) {
                    nodes.push({ type: "em", children: parseInline(src.slice(i + 1, close), options) });
                    i = close + 1;
                    continue;
                }
            }

            // Bare URL auto-link
            if (src.startsWith("https://", i) || src.startsWith("http://", i)) {
                const prevChar = i > 0 ? src[i - 1] : " ";
                if (/[\s(>：:]/.test(prevChar) || i === 0) {
                    const m = src.slice(i).match(/^https?:\/\/[^\s<>"')\]]+/);
                    if (m && isSafeUrl(m[0])) {
                        nodes.push({ type: "link", label: m[0], href: m[0] });
                        i += m[0].length;
                        continue;
                    }
                }
            }

            pushText(src[i]);
            i += 1;
        }

        return nodes;
    }

    function splitTableRow(line) {
        let trimmed = String(line || "").trim();
        if (trimmed.startsWith("|")) trimmed = trimmed.slice(1);
        if (trimmed.endsWith("|")) trimmed = trimmed.slice(0, -1);
        return trimmed.split("|").map((cell) => cell.trim());
    }

    function isTableSeparator(line) {
        const trimmed = String(line || "").trim();
        if (!trimmed.includes("|") && !trimmed.includes("-")) return false;
        const cells = splitTableRow(trimmed);
        return cells.length > 0 && cells.every((c) => /^:?-{2,}:?$/.test(c));
    }

    function parseBlockList(cleanedText, inlineOptions) {
        const text = String(cleanedText || "").replace(/\r\n?/g, "\n");
        if (!text.trim()) return [];
        const lines = text.split("\n");
        const blocks = [];
        let i = 0;

        while (i < lines.length) {
            const line = lines[i];
            const trimmed = line.trim();

            if (!trimmed) {
                i += 1;
                continue;
            }

            // Fenced code block
            const fenceMatch = line.match(/^\s{0,3}(```+|~~~+)\s*([a-zA-Z0-9_+-]*)/);
            if (fenceMatch) {
                const fence = fenceMatch[1];
                const fenceChar = fence[0];
                const lang = fenceMatch[2] || "";
                const codeLines = [];
                i += 1;
                while (i < lines.length) {
                    const closeRe = new RegExp(`^\\s{0,3}${fenceChar}{${fence.length},}\\s*$`);
                    if (closeRe.test(lines[i])) {
                        i += 1;
                        break;
                    }
                    codeLines.push(lines[i]);
                    i += 1;
                }
                blocks.push({ type: "code", lang, code: codeLines.join("\n") });
                continue;
            }

            // Indented code block (4 spaces or tab)
            if (/^(?: {4}|\t)/.test(line)) {
                const codeLines = [];
                while (i < lines.length && (/^(?: {4}|\t)/.test(lines[i]) || !lines[i].trim())) {
                    if (!lines[i].trim()) {
                        let lookahead = i + 1;
                        while (lookahead < lines.length && !lines[lookahead].trim()) lookahead += 1;
                        if (lookahead >= lines.length || !/^(?: {4}|\t)/.test(lines[lookahead])) break;
                        codeLines.push("");
                    } else {
                        codeLines.push(lines[i].replace(/^(?: {4}|\t)/, ""));
                    }
                    i += 1;
                }
                blocks.push({ type: "code", lang: "", code: codeLines.join("\n") });
                continue;
            }

            // Heading
            const headingMatch = line.match(/^\s{0,3}(#{1,6})\s+(.+?)\s*#*$/);
            if (headingMatch) {
                blocks.push({
                    type: "heading",
                    level: headingMatch[1].length,
                    children: parseInline(headingMatch[2], inlineOptions),
                });
                i += 1;
                continue;
            }

            // Horizontal rule
            if (/^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/.test(line)) {
                blocks.push({ type: "hr" });
                i += 1;
                continue;
            }

            // GFM Table
            if (line.includes("|") && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
                const headers = splitTableRow(line);
                i += 2;
                const rows = [];
                while (i < lines.length && lines[i].trim() && lines[i].includes("|")) {
                    rows.push(splitTableRow(lines[i]));
                    i += 1;
                }
                blocks.push({
                    type: "table",
                    headers: headers.map((h) => parseInline(h, inlineOptions)),
                    rows: rows.map((row) => row.map((cell) => parseInline(cell, inlineOptions))),
                });
                continue;
            }

            // Blockquote
            if (/^\s*>\s?/.test(line)) {
                const quoteLines = [];
                while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
                    quoteLines.push(lines[i].replace(/^\s*>\s?/, ""));
                    i += 1;
                }
                blocks.push({
                    type: "blockquote",
                    blocks: parseBlockList(quoteLines.join("\n"), inlineOptions),
                });
                continue;
            }

            // Unordered / Ordered list
            const ulMatch = line.match(/^(\s{0,3})[-*+]\s+(.*)$/);
            const olMatch = line.match(/^(\s{0,3})(\d+)\.\s+(.*)$/);
            if (ulMatch || olMatch) {
                const ordered = Boolean(olMatch);
                const items = [];
                while (i < lines.length) {
                    const cur = lines[i];
                    const m = ordered
                        ? cur.match(/^\s{0,3}\d+\.\s+(.*)$/)
                        : cur.match(/^\s{0,3}[-*+]\s+(.*)$/);
                    if (m) {
                        items.push([m[1]]);
                        i += 1;
                        continue;
                    }
                    if (/^\s{2,}\S/.test(cur) && items.length > 0) {
                        items[items.length - 1].push(cur.trim());
                        i += 1;
                        continue;
                    }
                    break;
                }
                blocks.push({
                    type: "list",
                    ordered,
                    items: items.map((parts) => parseInline(parts.join(" "), inlineOptions)),
                });
                continue;
            }

            // Paragraph
            const paraLines = [];
            while (i < lines.length) {
                const cur = lines[i];
                if (!cur.trim()) break;
                if (/^\s{0,3}(```+|~~~+)/.test(cur)) break;
                if (/^(?: {4}|\t)/.test(cur)) break;
                if (/^\s{0,3}#{1,6}\s+/.test(cur)) break;
                if (/^\s*>\s?/.test(cur)) break;
                if (/^\s{0,3}([-*+]|\d+\.)\s+/.test(cur)) break;
                if (/^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/.test(cur)) break;
                if (cur.includes("|") && i + 1 < lines.length && isTableSeparator(lines[i + 1])) break;
                paraLines.push(cur);
                i += 1;
            }
            blocks.push({
                type: "paragraph",
                lines: paraLines.map((l) => parseInline(l, inlineOptions)),
            });
        }

        return blocks;
    }

    function parseMarkdownBlocks(rawText, options = {}) {
        const { cleanedText, definitions, definitionsMap } = stripFootnoteDefinitions(rawText);
        const inlineOptions = {
            definitionsMap,
            streaming: Boolean(options.streaming),
        };
        const blocks = parseBlockList(cleanedText, inlineOptions);
        blocks.definitions = definitions;
        return blocks;
    }

    function appendInlineNodes(parent, nodes, doc, options = {}) {
        for (const node of nodes) {
            if (node.type === "text") {
                parent.appendChild(doc.createTextNode(node.text));
            } else if (node.type === "code") {
                const code = doc.createElement("code");
                code.className = "md-inline-code";
                code.textContent = node.text;
                parent.appendChild(code);
            } else if (node.type === "strong") {
                const el = doc.createElement("strong");
                appendInlineNodes(el, node.children, doc, options);
                parent.appendChild(el);
            } else if (node.type === "em") {
                const el = doc.createElement("em");
                appendInlineNodes(el, node.children, doc, options);
                parent.appendChild(el);
            } else if (node.type === "del") {
                const el = doc.createElement("del");
                appendInlineNodes(el, node.children, doc, options);
                parent.appendChild(el);
            } else if (node.type === "fileLink") {
                const a = doc.createElement("a");
                a.href = "#";
                a.textContent = node.label;
                a.className = "md-link md-file-link";
                a.setAttribute("data-file-path", node.path);
                if (node.line) a.setAttribute("data-file-line", node.line);
                a.title = node.line ? `${node.path}#${node.line}` : node.path;
                a.addEventListener("click", (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    if (typeof options.onFileLinkClick === "function") {
                        options.onFileLinkClick({ path: node.path, line: node.line });
                    }
                });
                parent.appendChild(a);
            } else if (node.type === "link") {
                const a = doc.createElement("a");
                a.href = node.href;
                a.textContent = node.label;
                a.target = "_blank";
                a.rel = "noopener noreferrer";
                a.className = "md-link";
                parent.appendChild(a);
            } else if (node.type === "citeSpan") {
                const def = node.def;
                const span = doc.createElement("span");
                const isActive = Boolean(options.activeCiteId && options.activeCiteId === def.id);
                span.className = `cite-span${def.kind === "web" ? " web" : ""}${isActive ? " active" : ""}`;
                span.setAttribute("data-cite-id", def.id);
                span.addEventListener("mouseenter", () => {
                    if (typeof options.onCiteHover === "function") {
                        options.onCiteHover(def, span);
                    }
                });
                span.addEventListener("mouseleave", () => {
                    if (typeof options.onCiteLeave === "function") {
                        options.onCiteLeave();
                    }
                });
                span.addEventListener("click", (e) => {
                    e.stopPropagation();
                    if (typeof options.onCiteClick === "function") {
                        options.onCiteClick(def, span);
                    }
                });
                appendInlineNodes(span, node.children, doc, options);
                parent.appendChild(span);
            } else if (node.type === "citePill") {
                const def = node.def;
                const btn = doc.createElement("button");
                btn.type = "button";
                const isActive = Boolean(options.activeCiteId && options.activeCiteId === def.id);
                btn.className = `cite-pill${def.kind === "web" ? " web" : ""}${isActive ? " active" : ""}`;
                btn.setAttribute("data-cite-id", def.id);
                btn.setAttribute("data-testid", `cite-pill-${def.id}`);
                btn.setAttribute("aria-label", `[${def.label}] ${def.title}`);
                btn.textContent = def.kind === "web" ? `${def.label} ↗` : def.label;
                btn.addEventListener("mouseenter", () => {
                    if (typeof options.onCiteHover === "function") {
                        options.onCiteHover(def, btn);
                    }
                });
                btn.addEventListener("mouseleave", () => {
                    if (typeof options.onCiteLeave === "function") {
                        options.onCiteLeave();
                    }
                });
                btn.addEventListener("click", (e) => {
                    e.stopPropagation();
                    if (typeof options.onCiteClick === "function") {
                        options.onCiteClick(def, btn);
                    }
                });
                parent.appendChild(btn);
            } else if (node.type === "citePending") {
                const pending = doc.createElement("span");
                pending.className = "cite-pill pending";
                pending.setAttribute("data-cite-pending", node.label);
                pending.setAttribute("data-testid", `cite-pill-pending-${node.label}`);
                pending.textContent = node.label;
                parent.appendChild(pending);
            }
        }
    }

    function appendBlocks(parent, blocks, doc, options = {}) {
        for (const block of blocks) {
            if (block.type === "heading") {
                const tag = `h${Math.min(6, Math.max(1, block.level))}`;
                const h = doc.createElement(tag);
                h.className = `md-h md-h${block.level}`;
                appendInlineNodes(h, block.children, doc, options);
                parent.appendChild(h);
            } else if (block.type === "paragraph") {
                const p = doc.createElement("p");
                p.className = "md-p";
                block.lines.forEach((lineNodes, idx) => {
                    if (idx > 0) p.appendChild(doc.createElement("br"));
                    appendInlineNodes(p, lineNodes, doc, options);
                });
                parent.appendChild(p);
            } else if (block.type === "hr") {
                const hr = doc.createElement("hr");
                hr.className = "md-hr";
                parent.appendChild(hr);
            } else if (block.type === "blockquote") {
                const bq = doc.createElement("blockquote");
                bq.className = "md-quote";
                appendBlocks(bq, block.blocks, doc, options);
                parent.appendChild(bq);
            } else if (block.type === "list") {
                const listEl = doc.createElement(block.ordered ? "ol" : "ul");
                listEl.className = "md-list";
                for (const itemNodes of block.items) {
                    const li = doc.createElement("li");
                    appendInlineNodes(li, itemNodes, doc, options);
                    listEl.appendChild(li);
                }
                parent.appendChild(listEl);
            } else if (block.type === "code") {
                const wrap = doc.createElement("div");
                wrap.className = "md-code-wrap";
                const bar = doc.createElement("div");
                bar.className = "md-code-bar";
                const langSpan = doc.createElement("span");
                langSpan.className = "md-code-lang";
                langSpan.textContent = block.lang || "text";
                bar.appendChild(langSpan);

                if (options.enableCopy !== false) {
                    const copyBtn = doc.createElement("button");
                    copyBtn.type = "button";
                    copyBtn.className = "md-code-copy";
                    const labelSpan = doc.createElement("span");
                    labelSpan.textContent = "复制";
                    if (doc.createElementNS) {
                        const svg = doc.createElementNS("http://www.w3.org/2000/svg", "svg");
                        svg.setAttribute("width", "11");
                        svg.setAttribute("height", "11");
                        svg.setAttribute("viewBox", "0 0 24 24");
                        svg.setAttribute("fill", "none");
                        svg.setAttribute("stroke", "currentColor");
                        svg.setAttribute("stroke-width", "1.75");
                        svg.setAttribute("stroke-linecap", "round");
                        svg.setAttribute("stroke-linejoin", "round");
                        svg.setAttribute("aria-hidden", "true");
                        const r = doc.createElementNS("http://www.w3.org/2000/svg", "rect");
                        r.setAttribute("x", "9");
                        r.setAttribute("y", "9");
                        r.setAttribute("width", "13");
                        r.setAttribute("height", "13");
                        r.setAttribute("rx", "2");
                        const p = doc.createElementNS("http://www.w3.org/2000/svg", "path");
                        p.setAttribute("d", "M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1");
                        svg.appendChild(r);
                        svg.appendChild(p);
                        copyBtn.appendChild(svg);
                    }
                    copyBtn.appendChild(labelSpan);
                    copyBtn.addEventListener("click", () => {
                        if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
                            navigator.clipboard.writeText(block.code).then(() => {
                                labelSpan.textContent = "已复制";
                                setTimeout(() => { labelSpan.textContent = "复制"; }, 1400);
                            }).catch(() => {});
                        }
                    });
                    bar.appendChild(copyBtn);
                }

                const pre = doc.createElement("pre");
                pre.className = "md-pre";
                const code = doc.createElement("code");
                code.textContent = block.code;
                pre.appendChild(code);

                wrap.appendChild(bar);
                wrap.appendChild(pre);
                parent.appendChild(wrap);
            } else if (block.type === "table") {
                const scroll = doc.createElement("div");
                scroll.className = "md-table-wrap";
                const table = doc.createElement("table");
                table.className = "md-table";
                const thead = doc.createElement("thead");
                const trHead = doc.createElement("tr");
                for (const cellNodes of block.headers) {
                    const th = doc.createElement("th");
                    appendInlineNodes(th, cellNodes, doc, options);
                    trHead.appendChild(th);
                }
                thead.appendChild(trHead);
                table.appendChild(thead);

                if (block.rows.length > 0) {
                    const tbody = doc.createElement("tbody");
                    for (const row of block.rows) {
                        const tr = doc.createElement("tr");
                        for (const cellNodes of row) {
                            const td = doc.createElement("td");
                            appendInlineNodes(td, cellNodes, doc, options);
                            tr.appendChild(td);
                        }
                        tbody.appendChild(tr);
                    }
                    table.appendChild(tbody);
                }
                scroll.appendChild(table);
                parent.appendChild(scroll);
            }
        }
    }

    function appendSourcesFoot(parent, definitions, doc, options = {}) {
        if (!Array.isArray(definitions) || definitions.length === 0) return;
        const foot = doc.createElement("div");
        foot.className = "cite-sources-foot";
        foot.setAttribute("data-testid", "cite-sources-foot");

        const label = doc.createElement("span");
        label.className = "cite-sources-label";
        label.textContent = "来源";
        foot.appendChild(label);

        for (const def of definitions) {
            if (def.kind === "invalid") {
                const chip = doc.createElement("span");
                chip.className = "cite-src-chip invalid";
                chip.setAttribute("data-cite-id", def.id);
                const n = doc.createElement("span");
                n.className = "n";
                n.textContent = `[${def.label}]`;
                const txt = doc.createElement("span");
                txt.textContent = `${def.title}（已拦截不安全链接）`;
                chip.appendChild(n);
                chip.appendChild(txt);
                foot.appendChild(chip);
                continue;
            }
            const btn = doc.createElement("button");
            btn.type = "button";
            const isWeb = def.kind === "web";
            const isActive = Boolean(options.activeCiteId && options.activeCiteId === def.id);
            btn.className = `cite-src-chip${isWeb ? " web" : ""}${isActive ? " active" : ""}`;
            btn.setAttribute("data-cite-id", def.id);
            const n = doc.createElement("span");
            n.className = "n";
            n.textContent = `[${def.label}]`;
            const title = doc.createElement("span");
            title.textContent = def.title;
            btn.appendChild(n);
            btn.appendChild(title);
            if (!isWeb && def.line) {
                const lineTag = doc.createElement("span");
                lineTag.className = "line-tag";
                lineTag.textContent = `#${def.line}`;
                btn.appendChild(lineTag);
            }
            btn.addEventListener("mouseenter", () => {
                if (typeof options.onCiteHover === "function") {
                    options.onCiteHover(def, btn);
                }
            });
            btn.addEventListener("mouseleave", () => {
                if (typeof options.onCiteLeave === "function") {
                    options.onCiteLeave();
                }
            });
            btn.addEventListener("click", (e) => {
                e.stopPropagation();
                if (typeof options.onCiteClick === "function") {
                    options.onCiteClick(def, btn);
                }
            });
            foot.appendChild(btn);
        }

        parent.appendChild(foot);
    }

    function renderMarkdown(text, container, doc = globalThis.document, options = {}) {
        if (!container || !doc) return null;
        while (container.firstChild) {
            container.removeChild(container.firstChild);
        }
        const blocks = parseMarkdownBlocks(text, options);
        const frag = doc.createDocumentFragment();
        appendBlocks(frag, blocks, doc, options);
        appendSourcesFoot(frag, blocks.definitions || [], doc, options);
        container.appendChild(frag);
        return container;
    }

    return {
        isSafeUrl,
        parseFileUrl,
        parseLineAnchorRange,
        validateCitationUri,
        parseFootnoteDefinitionsFromMarkdown,
        parseInline,
        parseMarkdownBlocks,
        renderMarkdown,
    };
});
