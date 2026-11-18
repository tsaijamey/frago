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

    function parseInline(text) {
        const src = String(text || "");
        const nodes = [];
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
            // Inline code: `...`
            if (src[i] === "`") {
                const close = src.indexOf("`", i + 1);
                if (close > i + 1) {
                    nodes.push({ type: "code", text: src.slice(i + 1, close) });
                    i = close + 1;
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
                    nodes.push({ type: "strong", children: parseInline(src.slice(i + 2, close)) });
                    i = close + 2;
                    continue;
                }
            }

            // Strikethrough: ~~...~~
            if (src.startsWith("~~", i)) {
                const close = src.indexOf("~~", i + 2);
                if (close > i + 2 && !src.slice(i + 2, close).includes("\n")) {
                    nodes.push({ type: "del", children: parseInline(src.slice(i + 2, close)) });
                    i = close + 2;
                    continue;
                }
            }

            // Italic: *...* (avoid matching list bullets or mid-word underscores)
            if (src[i] === "*" && src[i + 1] !== "*" && src[i + 1] !== " ") {
                const close = src.indexOf("*", i + 1);
                if (close > i + 1 && src[close - 1] !== " " && !src.slice(i + 1, close).includes("\n")) {
                    nodes.push({ type: "em", children: parseInline(src.slice(i + 1, close)) });
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

    function parseMarkdownBlocks(rawText) {
        const text = String(rawText || "").replace(/\r\n?/g, "\n");
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
            const fenceMatch = line.match(/^\s*(```+|~~~+)\s*([a-zA-Z0-9_+-]*)/);
            if (fenceMatch) {
                const fence = fenceMatch[1];
                const fenceChar = fence[0];
                const lang = fenceMatch[2] || "";
                const codeLines = [];
                i += 1;
                while (i < lines.length) {
                    const closeRe = new RegExp(`^\\s*${fenceChar}{${fence.length},}\\s*$`);
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

            // Heading
            const headingMatch = line.match(/^\s{0,3}(#{1,6})\s+(.+?)\s*#*$/);
            if (headingMatch) {
                blocks.push({
                    type: "heading",
                    level: headingMatch[1].length,
                    children: parseInline(headingMatch[2]),
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
                    headers: headers.map((h) => parseInline(h)),
                    rows: rows.map((row) => row.map((cell) => parseInline(cell))),
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
                    blocks: parseMarkdownBlocks(quoteLines.join("\n")),
                });
                continue;
            }

            // Unordered / Ordered list
            const ulMatch = line.match(/^(\s*)[-*+]\s+(.*)$/);
            const olMatch = line.match(/^(\s*)(\d+)\.\s+(.*)$/);
            if (ulMatch || olMatch) {
                const ordered = Boolean(olMatch);
                const items = [];
                while (i < lines.length) {
                    const cur = lines[i];
                    const m = ordered
                        ? cur.match(/^\s*\d+\.\s+(.*)$/)
                        : cur.match(/^\s*[-*+]\s+(.*)$/);
                    if (m) {
                        items.push([m[1]]);
                        i += 1;
                        continue;
                    }
                    // Indented continuation line
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
                    items: items.map((parts) => parseInline(parts.join(" "))),
                });
                continue;
            }

            // Paragraph
            const paraLines = [];
            while (i < lines.length) {
                const cur = lines[i];
                if (!cur.trim()) break;
                if (/^\s*(```+|~~~+)/.test(cur)) break;
                if (/^\s{0,3}#{1,6}\s+/.test(cur)) break;
                if (/^\s*>\s?/.test(cur)) break;
                if (/^\s*([-*+]|\d+\.)\s+/.test(cur)) break;
                if (/^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/.test(cur)) break;
                if (cur.includes("|") && i + 1 < lines.length && isTableSeparator(lines[i + 1])) break;
                paraLines.push(cur);
                i += 1;
            }
            blocks.push({
                type: "paragraph",
                lines: paraLines.map((l) => parseInline(l)),
            });
        }

        return blocks;
    }

    function appendInlineNodes(parent, nodes, doc) {
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
                appendInlineNodes(el, node.children, doc);
                parent.appendChild(el);
            } else if (node.type === "em") {
                const el = doc.createElement("em");
                appendInlineNodes(el, node.children, doc);
                parent.appendChild(el);
            } else if (node.type === "del") {
                const el = doc.createElement("del");
                appendInlineNodes(el, node.children, doc);
                parent.appendChild(el);
            } else if (node.type === "link") {
                const a = doc.createElement("a");
                a.href = node.href;
                a.textContent = node.label;
                a.target = "_blank";
                a.rel = "noopener noreferrer";
                a.className = "md-link";
                parent.appendChild(a);
            }
        }
    }

    function appendBlocks(parent, blocks, doc, options = {}) {
        for (const block of blocks) {
            if (block.type === "heading") {
                const tag = `h${Math.min(6, Math.max(1, block.level))}`;
                const h = doc.createElement(tag);
                h.className = `md-h md-h${block.level}`;
                appendInlineNodes(h, block.children, doc);
                parent.appendChild(h);
            } else if (block.type === "paragraph") {
                const p = doc.createElement("p");
                p.className = "md-p";
                block.lines.forEach((lineNodes, idx) => {
                    if (idx > 0) p.appendChild(doc.createElement("br"));
                    appendInlineNodes(p, lineNodes, doc);
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
                    appendInlineNodes(li, itemNodes, doc);
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
                    appendInlineNodes(th, cellNodes, doc);
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
                            appendInlineNodes(td, cellNodes, doc);
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

    function renderMarkdown(text, container, doc = globalThis.document, options = {}) {
        if (!container || !doc) return null;
        while (container.firstChild) {
            container.removeChild(container.firstChild);
        }
        const blocks = parseMarkdownBlocks(text);
        const frag = doc.createDocumentFragment();
        appendBlocks(frag, blocks, doc, options);
        container.appendChild(frag);
        return container;
    }

    return {
        isSafeUrl,
        parseInline,
        parseMarkdownBlocks,
        renderMarkdown,
    };
});
