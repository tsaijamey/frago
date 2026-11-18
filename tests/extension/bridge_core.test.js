const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const extractor = require(path.resolve(
    __dirname,
    "../../src/frago/_resources/extension_bundle/shared/page_extractor.js"
));
const composer = require(path.resolve(
    __dirname,
    "../../src/frago/_resources/extension_bundle/shared/message_composer.js"
));

// Minimal lightweight DOM mock supporting the properties used by page_extractor.js
function el(tagName, attrs = {}, children = []) {
    const node = {
        nodeType: 1,
        tagName: tagName.toUpperCase(),
        attributes: { ...attrs },
        id: attrs.id || "",
        className: attrs.class || "",
        childNodes: [],
        parentElement: null,
        previousElementSibling: null,
        nextElementSibling: null,
        getAttribute(name) {
            return Object.prototype.hasOwnProperty.call(this.attributes, name)
                ? this.attributes[name]
                : null;
        },
        hasAttribute(name) {
            return Object.prototype.hasOwnProperty.call(this.attributes, name);
        },
    };
    const list = Array.isArray(children) ? children : [children];
    let prevEl = null;
    for (const item of list) {
        const child = typeof item === "string"
            ? { nodeType: 3, nodeValue: item, parentElement: node }
            : item;
        child.parentElement = node;
        if (child.nodeType === 1) {
            child.previousElementSibling = prevEl;
            if (prevEl) prevEl.nextElementSibling = child;
            prevEl = child;
        }
        node.childNodes.push(child);
    }
    return node;
}

function comment(text) {
    return { nodeType: 8, nodeValue: text };
}

test("extractPageContext strips scripts, styles, hidden elements, extension UI, and preserves semantic markdown", () => {
    const dom = el("body", {}, [
        comment("hidden html comment should be stripped"),
        el("script", {}, ["console.log('SECRET_SCRIPT_NOISE');"]),
        el("style", {}, [".secret-css { display: block; }"]),
        el("noscript", {}, ["Enable JS"]),
        el("svg", {}, [el("text", {}, ["SVG_NOISE"])]),
        el("canvas", {}, ["CANVAS_NOISE"]),
        el("template", {}, [el("p", {}, ["TEMPLATE_NOISE"])]),
        el("iframe", {}, ["IFRAME_NOISE"]),
        el("div", { id: "__frago-picker-host", "data-frago-ext-ui": "1" }, [
            "PICKER_UI_NOISE",
        ]),
        el("div", { hidden: "" }, ["HIDDEN_ATTR_NOISE"]),
        el("div", { "aria-hidden": "true" }, ["ARIA_HIDDEN_NOISE"]),
        el("div", { style: "color: red; display: none;" }, ["DISPLAY_NONE_NOISE"]),
        el("div", { style: "visibility: hidden" }, ["VISIBILITY_HIDDEN_NOISE"]),
        el("div", { style: "opacity: 0" }, ["OPACITY_ZERO_NOISE"]),
        el("div", { class: "computed-hidden" }, ["COMPUTED_STYLE_HIDDEN_NOISE"]),

        el("h1", {}, ["产品设计文档"]),
        el("p", {}, [
            "这是第一段正文，包含",
            el("strong", {}, ["关键指标"]),
            "和",
            el("a", { href: "/docs/spec" }, ["规范链接"]),
            "。",
        ]),
        el("blockquote", {}, [el("p", {}, ["重要引用说明"])]),
        el("ul", {}, [
            el("li", {}, ["第一条"]),
            el("li", {}, ["第二条"]),
        ]),
        el("pre", {}, [
            el("code", { class: "language-python" }, ["def hello():\n    return 'world'"]),
        ]),
        el("table", {}, [
            el("tr", {}, [el("th", {}, ["字段"]), el("th", {}, ["含义"])]),
            el("tr", {}, [el("td", {}, ["focus"]), el("td", {}, ["焦点文本"])]),
        ]),
    ]);

    const res = extractor.extractPageContext(dom, {
        title: "测试文档",
        url: "https://example.com/guide#top",
        baseUrl: "https://example.com/guide#top",
        getComputedStyle(node) {
            if (node.className === "computed-hidden") {
                return { display: "none", visibility: "visible", opacity: "1" };
            }
            return { display: "block", visibility: "visible", opacity: "1" };
        },
    });

    assert.equal(res.normalizedUrl, "https://example.com/guide");
    for (const noise of [
        "SECRET_SCRIPT_NOISE",
        "secret-css",
        "Enable JS",
        "SVG_NOISE",
        "CANVAS_NOISE",
        "TEMPLATE_NOISE",
        "IFRAME_NOISE",
        "PICKER_UI_NOISE",
        "HIDDEN_ATTR_NOISE",
        "ARIA_HIDDEN_NOISE",
        "DISPLAY_NONE_NOISE",
        "VISIBILITY_HIDDEN_NOISE",
        "OPACITY_ZERO_NOISE",
        "COMPUTED_STYLE_HIDDEN_NOISE",
        "hidden html comment",
    ]) {
        assert.ok(!res.markdown.includes(noise), `noise "${noise}" leaked into markdown`);
    }

    assert.match(res.markdown, /^# 产品设计文档/m);
    assert.match(res.markdown, /\*\*关键指标\*\*/);
    assert.match(res.markdown, /\[规范链接\]\(https:\/\/example\.com\/docs\/spec\)/);
    assert.match(res.markdown, /> 重要引用说明/);
    assert.match(res.markdown, /- 第一条\n- 第二条/);
    assert.match(res.markdown, /```python\ndef hello\(\):\n {4}return 'world'\n```/);
    assert.match(res.markdown, /\| 字段 \| 含义 \|\n\| --- \| --- \|\n\| focus \| 焦点文本 \|/);
});

test("injectFocusAnchors accurately embeds multiple anchors with context disambiguation and markdown tolerance", () => {
    const pageMd = [
        "# 第一章",
        "",
        "系统启动时会检查配置，然后执行重试策略。",
        "",
        "## 第二章",
        "",
        "遇到超时问题时请执行**重试策略**，并记录日志。",
        "",
        "```js",
        "const timeoutMs = 5000;",
        "```",
    ].join("\n");

    const focuses = [
        {
            focusNumber: 1,
            text: "重试策略",
            markdown: "重试策略",
            contextBefore: "遇到超时问题时请执行",
            contextAfter: "，并记录日志。",
        },
        {
            focusNumber: 2,
            text: "const timeoutMs = 5000;",
            markdown: "```js\nconst timeoutMs = 5000;\n```",
            contextBefore: "并记录日志。",
            contextAfter: "",
        },
    ];

    const anchored = extractor.injectFocusAnchors(pageMd, focuses);
    assert.deepEqual(anchored.matchedNumbers, [1, 2]);
    assert.deepEqual(anchored.unmatchedNumbers, []);

    // Anchor #1 must land in Chapter 2 (not Chapter 1!) thanks to contextBefore/After
    const ch1End = anchored.markdown.indexOf("## 第二章");
    const anchor1Start = anchored.markdown.indexOf("<<< 🎯 FOCUS #1 开始 >>>");
    const anchor1End = anchored.markdown.indexOf("<<< 🎯 FOCUS #1 结束 >>>");
    assert.ok(anchor1Start > ch1End, "Focus #1 should be anchored in Chapter 2");
    assert.ok(anchor1End > anchor1Start);
    assert.ok(
        anchored.markdown.slice(anchor1Start, anchor1End).includes("重试策略"),
        "Anchor #1 wraps the matched text"
    );

    // Anchor #2 must wrap the code block
    const anchor2Start = anchored.markdown.indexOf("<<< 🎯 FOCUS #2 开始 >>>");
    const anchor2End = anchored.markdown.indexOf("<<< 🎯 FOCUS #2 结束 >>>");
    assert.ok(anchor2Start > anchor1End);
    assert.ok(anchored.markdown.slice(anchor2Start, anchor2End).includes("const timeoutMs = 5000;"));
});

test("composeBridgePayload deduplicates multiple Focus items on the same page into a single anchored full-page context", () => {
    const fullPageMd = [
        "# 接口说明",
        "",
        "第一段介绍了鉴权方式。",
        "",
        "第二段介绍了限流阈值每秒 100 次。",
        "",
        "第三段介绍了错误码约定。",
    ].join("\n");

    const focusItems = [
        {
            id: "f1",
            kind: "selection",
            title: "API 文档",
            url: "https://api.example.com/docs#auth",
            markdown: "第一段介绍了鉴权方式。",
            text: "第一段介绍了鉴权方式。",
            enabled: true,
        },
        {
            id: "f2",
            kind: "element",
            title: "API 文档",
            url: "https://api.example.com/docs#ratelimit",
            selector: "main > p:nth-of-type(2)",
            markdown: "第二段介绍了限流阈值每秒 100 次。",
            text: "第二段介绍了限流阈值每秒 100 次。",
            enabled: true,
        },
        {
            id: "f3",
            kind: "selection",
            title: "API 文档",
            url: "https://api.example.com/docs",
            markdown: "第三段介绍了错误码约定。",
            text: "第三段介绍了错误码约定。",
            enabled: true,
        },
    ];

    const payload = composer.composeBridgePayload({
        instruction: "请对比这三点是否有遗漏",
        focusItems,
        includeFullPage: true,
        activePage: {
            title: "API 文档",
            url: "https://api.example.com/docs#ratelimit",
            markdown: fullPageMd,
        },
        pageSnapshots: {
            "https://api.example.com/docs": {
                title: "API 文档",
                url: "https://api.example.com/docs",
                markdown: fullPageMd,
            },
        },
    });

    assert.equal(payload.ok, true);
    assert.equal(payload.stats.focusCount, 3);
    assert.equal(payload.stats.pageCount, 1);
    assert.equal(payload.documents.length, 0);

    // Only ONE "[页面 1]" block appears in the output
    const pageMatches = payload.text.match(/#### \[页面 \d+\]/g) || [];
    assert.equal(pageMatches.length, 1);

    // All three Focus items appear in top summary AND all three anchors appear inside the single full-page section
    for (const n of [1, 2, 3]) {
        assert.ok(payload.text.includes(`#### [FOCUS #${n}]`));
        assert.ok(payload.text.includes(`<<< 🎯 FOCUS #${n} 开始 >>>`));
        assert.ok(payload.text.includes(`<<< 🎯 FOCUS #${n} 结束 >>>`));
    }
});

test("composeBridgePayload supports zero-Focus direct send with activePage full context", () => {
    const payload = composer.composeBridgePayload({
        instruction: "",
        focusItems: [],
        includeFullPage: true,
        activePage: {
            title: "日报页面",
            url: "https://intranet.example.com/report",
            markdown: "# 今日汇总\n\n完成 3 项发布。",
        },
    });

    assert.equal(payload.ok, true);
    assert.equal(payload.stats.focusCount, 0);
    assert.equal(payload.stats.pageCount, 1);
    assert.ok(!payload.text.includes("Focus 焦点内容"));
    assert.ok(payload.text.includes("# 今日汇总"));
});

test("composeBridgePayload offloads ultra-long pages into base64 markdown documents while preserving anchor excerpt", () => {
    const filler = "这是一段用于填充超长页面的中文可见内容，用于验证超长页面自动文档附件保护逻辑。\n\n".repeat(450);
    const longMd = `# 长文标题\n\n${filler}核心焦点句：本季度营收同比增长 42%。\n\n${filler}`;
    assert.ok(longMd.length > 30_000);

    const payload = composer.composeBridgePayload({
        instruction: "重点核查焦点数字",
        focusItems: [
            {
                id: "f1",
                kind: "selection",
                title: "财报长文",
                url: "https://finance.example.com/q3",
                markdown: "核心焦点句：本季度营收同比增长 42%。",
                text: "核心焦点句：本季度营收同比增长 42%。",
                enabled: true,
            },
        ],
        includeFullPage: true,
        activePage: {
            title: "财报长文",
            url: "https://finance.example.com/q3",
            markdown: longMd,
        },
    });

    assert.equal(payload.ok, true);
    assert.equal(payload.stats.offloadedToDocuments, true);
    assert.equal(payload.documents.length, 1);
    assert.match(payload.documents[0].name, /^page-context-1-.*\.md$/);
    assert.match(payload.documents[0].data, /^data:text\/markdown;base64,/);

    // Decode base64 back to UTF-8 and verify complete full page + anchor intact
    const b64 = payload.documents[0].data.replace(/^data:text\/markdown;base64,/, "");
    const decoded = Buffer.from(b64, "base64").toString("utf8");
    assert.ok(decoded.includes("<<< 🎯 FOCUS #1 开始 >>>"));
    assert.ok(decoded.includes("核心焦点句：本季度营收同比增长 42%。"));
    assert.ok(decoded.length > 30_000);

    // Inline prompt stays concise with excerpt around Focus #1
    assert.ok(payload.text.length < 15_000);
    assert.ok(payload.text.includes("超长页面保护"));
    assert.ok(payload.text.includes("<<< 🎯 FOCUS #1 开始 >>>"));
});
