// frago bridge — Focus + Full-Page deduplication, ultra-long page attachment
// fallback, and deterministic Workbench message composition.
//
// Zero external dependencies. Runs identically in:
//   1. Extension Side Panel (via globalThis.FragoMessageComposer)
//   2. Node.js unit tests (`node --test` via module.exports)

(function (root, factory) {
    const extractor = typeof require === "function"
        ? require("./page_extractor.js")
        : root.FragoPageExtractor;
    const api = factory(extractor);
    if (typeof module === "object" && module && module.exports) {
        module.exports = api;
    }
    if (root) {
        root.FragoMessageComposer = api;
    }
})(typeof globalThis !== "undefined" ? globalThis : this, function (extractor) {
    "use strict";

    const DEFAULT_MAX_INLINE_CHARS = 30_000;
    const MAX_DOCUMENTS_PER_REQUEST = 8;

    function normalizePageUrl(url) {
        if (extractor && typeof extractor.normalizePageUrl === "function") {
            return extractor.normalizePageUrl(url);
        }
        const s = String(url || "").trim();
        const idx = s.indexOf("#");
        return idx >= 0 ? s.slice(0, idx) : s;
    }

    function utf8ToBase64(text) {
        const str = String(text || "");
        if (typeof Buffer !== "undefined") {
            return Buffer.from(str, "utf8").toString("base64");
        }
        const bytes = new TextEncoder().encode(str);
        const CHUNK = 0x8000;
        let binary = "";
        for (let i = 0; i < bytes.length; i += CHUNK) {
            binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
        }
        return btoa(binary);
    }

    function slugifyFilename(title, url, index) {
        let base = "";
        try {
            const u = new URL(url);
            base = `${u.hostname}${u.pathname}`;
        } catch (_) {
            base = title || `page-${index}`;
        }
        const cleaned = String(base)
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, "-")
            .replace(/^-+|-+$/g, "")
            .slice(0, 48);
        return `page-context-${index}-${cleaned || "page"}.md`;
    }

    function buildExcerptAroundAnchors(anchoredMarkdown, focusNumbers, fallbackChars = 4000) {
        const text = String(anchoredMarkdown || "");
        if (!focusNumbers || focusNumbers.length === 0) {
            const head = text.slice(0, fallbackChars);
            return text.length > fallbackChars ? `${head}\n\n...(正文已截断，完整内容见附件)...` : head;
        }

        const windows = [];
        const PAD = 1000;
        for (const num of focusNumbers) {
            const startTag = `<<< 🎯 FOCUS #${num} 开始 >>>`;
            const endTag = `<<< 🎯 FOCUS #${num} 结束 >>>`;
            const sIdx = text.indexOf(startTag);
            if (sIdx === -1) continue;
            const eIdxRaw = text.indexOf(endTag, sIdx);
            const eIdx = eIdxRaw === -1 ? sIdx + startTag.length : eIdxRaw + endTag.length;
            windows.push({
                start: Math.max(0, sIdx - PAD),
                end: Math.min(text.length, eIdx + PAD),
            });
        }

        if (windows.length === 0) {
            const head = text.slice(0, fallbackChars);
            return text.length > fallbackChars ? `${head}\n\n...(正文已截断，完整内容见附件)...` : head;
        }

        windows.sort((a, b) => a.start - b.start);
        const merged = [windows[0]];
        for (let i = 1; i < windows.length; i += 1) {
            const prev = merged[merged.length - 1];
            const cur = windows[i];
            if (cur.start <= prev.end + 120) {
                prev.end = Math.max(prev.end, cur.end);
            } else {
                merged.push(cur);
            }
        }

        return merged
            .map((w) => {
                const prefix = w.start > 0 ? "...\n" : "";
                const suffix = w.end < text.length ? "\n..." : "";
                return `${prefix}${text.slice(w.start, w.end)}${suffix}`;
            })
            .join("\n\n---\n\n");
    }

    function composeBridgePayload({
        instruction = "",
        focusItems = [],
        includeFullPage = true,
        activePage = null,
        pageSnapshots = {},
        maxInlineChars = DEFAULT_MAX_INLINE_CHARS,
    } = {}) {
        const cleanInstruction = String(instruction || "").trim();
        const enabledFocuses = (Array.isArray(focusItems) ? focusItems : [])
            .filter((item) => item && item.enabled !== false)
            .map((item, idx) => ({
                ...item,
                focusNumber: idx + 1,
                normalizedUrl: normalizePageUrl(item.url || ""),
            }));

        const pageMap = new Map();

        function ensurePageEntry(url, titleFallback) {
            const normUrl = normalizePageUrl(url || "");
            const key = normUrl || "__current_page__";
            if (!pageMap.has(key)) {
                const snap = normUrl && pageSnapshots ? pageSnapshots[normUrl] : null;
                pageMap.set(key, {
                    key,
                    url: url || (snap && snap.url) || "",
                    normalizedUrl: normUrl,
                    title: (snap && snap.title) || titleFallback || "",
                    markdown: (snap && snap.markdown) || "",
                    focuses: [],
                });
            }
            return pageMap.get(key);
        }

        // Group focuses by normalized page URL
        for (const focus of enabledFocuses) {
            const entry = ensurePageEntry(focus.url, focus.title);
            if (!entry.title && focus.title) entry.title = focus.title;
            entry.focuses.push(focus);
        }

        // Deduplicate & merge activePage if includeFullPage is enabled
        if (includeFullPage && activePage && String(activePage.markdown || "").trim()) {
            const activeNorm = normalizePageUrl(activePage.url || "");
            const key = activeNorm || "__current_page__";
            if (pageMap.has(key)) {
                const existing = pageMap.get(key);
                existing.url = activePage.url || existing.url;
                existing.title = activePage.title || existing.title;
                existing.markdown = activePage.markdown;
            } else {
                pageMap.set(key, {
                    key,
                    url: activePage.url || "",
                    normalizedUrl: activeNorm,
                    title: activePage.title || "",
                    markdown: activePage.markdown,
                    focuses: [],
                });
            }
        }

        // Build anchored page blocks when includeFullPage is enabled
        const pageEntries = [];
        if (includeFullPage) {
            let pageIndex = 1;
            for (const entry of pageMap.values()) {
                if (!String(entry.markdown || "").trim()) continue;
                const anchored = extractor.injectFocusAnchors(entry.markdown, entry.focuses);
                pageEntries.push({
                    pageIndex,
                    title: entry.title || entry.url || `页面 ${pageIndex}`,
                    url: entry.url,
                    normalizedUrl: entry.normalizedUrl,
                    focuses: entry.focuses,
                    anchoredMarkdown: anchored.markdown,
                    charCount: anchored.markdown.length,
                    matchedNumbers: anchored.matchedNumbers,
                    unmatchedNumbers: anchored.unmatchedNumbers,
                });
                pageIndex += 1;
            }
        }

        const hasContext = enabledFocuses.length > 0 || pageEntries.length > 0;
        if (!cleanInstruction && !hasContext) {
            return {
                ok: false,
                error: "请填写附加指令、选入 Focus 焦点，或勾选附带当前页完整可见上下文。",
            };
        }

        const totalPageChars = pageEntries.reduce((sum, p) => sum + p.charCount, 0);
        const shouldOffloadDocs = totalPageChars > maxInlineChars;

        const sections = [];
        if (cleanInstruction) {
            sections.push(cleanInstruction);
        } else if (enabledFocuses.length > 0 && pageEntries.length > 0) {
            sections.push("请结合以下网页 Focus 焦点与完整页面可见上下文进行分析处理。");
        } else if (enabledFocuses.length > 0) {
            sections.push("请处理以下从网页选入的 Focus 焦点内容。");
        } else {
            sections.push("请阅读以下当前网页的完整可见上下文并协助处理。");
        }

        if (enabledFocuses.length > 0) {
            const focusLines = [`---`, `### 🎯 Focus 焦点内容（共 ${enabledFocuses.length} 处）`];
            for (const focus of enabledFocuses) {
                const kindLabel = focus.kind === "element" ? "网页区块" : "划词焦点";
                const selectorPart = focus.selector ? ` · \`${focus.selector}\`` : "";
                focusLines.push(
                    "",
                    `#### [FOCUS #${focus.focusNumber}] ${focus.title || "未命名页面"}（${kindLabel}${selectorPart}）`,
                    `- 来源：${focus.url || "当前页"}`
                );
                const body = String(focus.markdown || focus.text || "").trim();
                if (body) {
                    focusLines.push("", body);
                }
            }
            sections.push(focusLines.join("\n"));
        }

        const documents = [];
        if (pageEntries.length > 0) {
            const pageHeader = [
                `---`,
                `### 📄 网页完整可见上下文（共 ${pageEntries.length} 页，按页去重并已原地锚定 Focus）`,
            ];
            const pageBlocks = [pageHeader.join("\n")];

            for (const page of pageEntries) {
                const meta = [
                    "",
                    `#### [页面 ${page.pageIndex}] ${page.title}（约 ${page.charCount} 字）`,
                    `- URL：${page.url || "未知"}`,
                ];
                if (page.focuses.length > 0) {
                    const nums = page.focuses.map((f) => `#${f.focusNumber}`).join(", ");
                    meta.push(`- 本页关联 Focus：${nums}`);
                }
                if (page.unmatchedNumbers.length > 0) {
                    const misses = page.unmatchedNumbers.map((n) => `#${n}`).join(", ");
                    meta.push(`- 提示：Focus ${misses} 未在当前清洗正文里精确回位，已保留上方原文`);
                }

                if (shouldOffloadDocs && documents.length < MAX_DOCUMENTS_PER_REQUEST) {
                    const fileName = slugifyFilename(page.title, page.url, page.pageIndex);
                    const fullDocText = [
                        `# ${page.title}`,
                        `- URL: ${page.url}`,
                        `- 字符数: ${page.charCount}`,
                        "",
                        page.anchoredMarkdown,
                    ].join("\n");
                    documents.push({
                        name: fileName,
                        data: `data:text/markdown;base64,${utf8ToBase64(fullDocText)}`,
                    });
                    const excerpt = buildExcerptAroundAnchors(
                        page.anchoredMarkdown,
                        page.matchedNumbers
                    );
                    meta.push(
                        `- 超长页面保护：整页全文共 ${page.charCount} 字，已完整挂载为文档附件 \`${fileName}\`（下方为 Focus 锚点窗口摘录）`,
                        "",
                        excerpt
                    );
                } else {
                    meta.push("", page.anchoredMarkdown);
                }

                pageBlocks.push(meta.join("\n"));
            }

            sections.push(pageBlocks.join("\n"));
        }

        return {
            ok: true,
            text: sections.join("\n\n"),
            documents,
            stats: {
                focusCount: enabledFocuses.length,
                pageCount: pageEntries.length,
                totalPageChars,
                offloadedToDocuments: documents.length > 0,
            },
        };
    }

    return {
        DEFAULT_MAX_INLINE_CHARS,
        MAX_DOCUMENTS_PER_REQUEST,
        utf8ToBase64,
        composeBridgePayload,
    };
});
