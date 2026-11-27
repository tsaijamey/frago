const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const md = require(path.resolve(
    __dirname,
    "../../src/frago/_resources/extension_bundle/shared/markdown.js"
));

function createMiniDom() {
    class MiniNode {
        constructor(nodeType, tagName = "") {
            this.nodeType = nodeType;
            this.tagName = tagName.toLowerCase();
            this.children = [];
            this.parentNode = null;
            this.attributes = {};
            this.listeners = {};
            this.className = "";
            this.href = "";
            this.type = "";
            this.title = "";
            this.target = "";
            this.rel = "";
            this._text = "";
        }
        get firstChild() {
            return this.children[0] || null;
        }
        get childNodes() {
            return this.children;
        }
        appendChild(child) {
            if (child.nodeType === 11) {
                for (const c of child.children) {
                    c.parentNode = this;
                    this.children.push(c);
                }
                child.children = [];
                return child;
            }
            child.parentNode = this;
            this.children.push(child);
            return child;
        }
        removeChild(child) {
            const idx = this.children.indexOf(child);
            if (idx >= 0) this.children.splice(idx, 1);
            child.parentNode = null;
            return child;
        }
        setAttribute(k, v) {
            this.attributes[k] = String(v);
        }
        getAttribute(k) {
            return this.attributes[k] ?? null;
        }
        addEventListener(ev, fn) {
            if (!this.listeners[ev]) this.listeners[ev] = [];
            this.listeners[ev].push(fn);
        }
        trigger(ev, eventObj = {}) {
            const evt = { preventDefault() {}, stopPropagation() {}, ...eventObj };
            for (const fn of this.listeners[ev] || []) {
                fn(evt);
            }
        }
        get textContent() {
            if (this.nodeType === 3) return this._text;
            return this.children.map((c) => c.textContent).join("");
        }
        set textContent(v) {
            if (this.nodeType === 3) {
                this._text = String(v);
                return;
            }
            this.children = [];
            if (v !== "" && v != null) {
                this.appendChild(doc.createTextNode(String(v)));
            }
        }
        findAll(predicate) {
            const out = [];
            const walk = (node) => {
                if (node.nodeType === 1 && predicate(node)) out.push(node);
                for (const c of node.children) walk(c);
            };
            walk(this);
            return out;
        }
    }

    const doc = {
        createElement(tag) {
            return new MiniNode(1, tag);
        },
        createTextNode(txt) {
            const n = new MiniNode(3);
            n._text = String(txt);
            return n;
        },
        createDocumentFragment() {
            return new MiniNode(11);
        },
    };
    return doc;
}

test("extension markdown parses standard GFM [^N] citations and renders pills + sources foot", () => {
    const sample = [
        "系统使用双层超时保护[^1]，详见外部标准[^2]。",
        "",
        '[^1]: [watchdog.py](file:///Users/demo/src/watchdog.py#L42-L48 "超过阈值触发降级")',
        '[^2]: [RFC 说明](https://example.com/rfc "规范原文")',
    ].join("\n");

    const doc = createMiniDom();
    const container = doc.createElement("div");
    const clicked = [];
    md.renderMarkdown(sample, container, doc, {
        onCiteClick: (def) => clicked.push(def),
    });

    const spans = container.findAll((el) => el.className.split(" ").includes("cite-span"));
    assert.equal(spans.length, 2);
    const pills = container.findAll((el) => el.className.split(" ").includes("cite-pill"));
    assert.equal(pills.length, 2);
    assert.equal(pills[0].textContent, "1");
    assert.equal(pills[1].textContent, "2 ↗");
    assert.equal(pills[1].className.includes("web"), true);

    const chips = container.findAll((el) => el.className.split(" ").includes("cite-src-chip"));
    assert.equal(chips.length, 2);
    assert.equal(chips[0].textContent.includes("#L42-L48"), true);

    pills[0].trigger("click");
    assert.equal(clicked.length, 1);
    assert.equal(clicked[0].kind, "local");
    assert.equal(clicked[0].filePath, "/Users/demo/src/watchdog.py");
    assert.equal(clicked[0].hlStart, 42);
    assert.equal(clicked[0].hlEnd, 48);
});

test("extension markdown enforces URI whitelist and strips unsafe protocols", () => {
    const sample = [
        "局部引用[^1]，危险脚本[^2]，Data协议[^3]，VBS[^4]。",
        "",
        "[^1]: [app.ts](file:///repo/app.ts#L10)",
        "[^2]: [xss](javascript:alert(1))",
        "[^3]: [payload](data:text/html,<script>alert(1)</script>)",
        "[^4]: [legacy](vbscript:msgbox(1))",
    ].join("\n");

    const doc = createMiniDom();
    const container = doc.createElement("div");
    md.renderMarkdown(sample, container, doc);

    const pills = container.findAll((el) => el.className.split(" ").includes("cite-pill"));
    assert.equal(pills.length, 1);
    assert.equal(pills[0].textContent, "1");

    const invalidChips = container.findAll((el) => el.className.includes("cite-src-chip invalid"));
    assert.equal(invalidChips.length, 3);
    assert.equal(invalidChips[0].tagName, "span");
    assert.equal(invalidChips.every((c) => c.textContent.includes("已拦截不安全链接")), true);
});

test("extension markdown isolates code blocks, inline code, escapes, and rejects legacy [[[ !ref_N ]]] syntax", () => {
    const sample = [
        "行内代码 `示例[^1]` 与转义 \\[^1] 与旧私有标签 [[[!ref_1]]]不解析[[[/!ref_1]]]。",
        "",
        "```md",
        "代码块中[^1]",
        "[^99]: [ignored](file:///ignored.py)",
        "```",
        "",
        "    缩进代码块[^1]",
        "",
        "[^1]: [real.py](file:///repo/real.py#L5)",
    ].join("\n");

    const doc = createMiniDom();
    const container = doc.createElement("div");
    md.renderMarkdown(sample, container, doc);

    const pills = container.findAll((el) => el.className.split(" ").includes("cite-pill"));
    assert.equal(pills.length, 0);
    const chips = container.findAll((el) => el.className.split(" ").includes("cite-src-chip"));
    assert.equal(chips.length, 1);
    assert.equal(chips[0].getAttribute("data-cite-id"), "1");
    assert.equal(container.textContent.includes("[[[!ref_1]]]"), true);
});

test("extension markdown handles streaming placeholder, orphan ref degradation, and orphan definition chip", () => {
    const sample = [
        "正文中引用了尚未落盘的[^1]和已定义的[^2]。",
        "",
        "[^2]: [used.py](file:///repo/used.py#L1)",
        "[^3]: [orphan.py](file:///repo/orphan.py#L9)",
    ].join("\n");

    // Streaming = true -> [^1] renders .cite-pill.pending
    const doc1 = createMiniDom();
    const c1 = doc1.createElement("div");
    md.renderMarkdown(sample, c1, doc1, { streaming: true });
    const pending = c1.findAll((el) => el.className.includes("cite-pill pending"));
    assert.equal(pending.length, 1);
    assert.equal(pending[0].textContent, "1");

    // Streaming = false -> [^1] degrades to plain text [^1]; [^3] stays in cite-sources-foot
    const doc2 = createMiniDom();
    const c2 = doc2.createElement("div");
    md.renderMarkdown(sample, c2, doc2, { streaming: false });
    const pendingAfter = c2.findAll((el) => el.className.includes("cite-pill pending"));
    assert.equal(pendingAfter.length, 0);
    assert.equal(c2.textContent.includes("[^1]"), true);
    const chips = c2.findAll((el) => el.className.split(" ").includes("cite-src-chip"));
    assert.equal(chips.length, 2);
    assert.equal(chips.some((c) => c.getAttribute("data-cite-id") === "3"), true);
});

test("extension markdown intercepts file:// links via callback and api.js loads via 8093 scope=cited", async () => {
    const doc = createMiniDom();
    const container = doc.createElement("div");
    const fileClicks = [];
    md.renderMarkdown("查看 [config.py](file:///Users/demo/config.py#L12)", container, doc, {
        onFileLinkClick: (info) => fileClicks.push(info),
    });

    const links = container.findAll((el) => el.className.includes("md-file-link"));
    assert.equal(links.length, 1);
    assert.equal(links[0].href, "#");
    links[0].trigger("click");
    assert.deepEqual(fileClicks, [{ path: "/Users/demo/config.py", line: "L12" }]);

    // Test sidepanel/api.js getSessionFileContent uses authenticated 8093 sandbox endpoint
    const calls = [];
    const prevFetch = globalThis.fetch;
    globalThis.fetch = async (url, init) => {
        calls.push({ url, headers: Object.fromEntries(init.headers.entries()), method: init.method });
        return {
            ok: true,
            status: 200,
            async text() {
                return JSON.stringify({ path: "/Users/demo/config.py", text: "line1\nline2", is_text: true });
            },
        };
    };
    try {
        const apiMod = await import(
            pathToFileURL(
                path.resolve(__dirname, "../../src/frago/_resources/extension_bundle/sidepanel/api.js")
            ).href
        );
        const res = await apiMod.getSessionFileContent(
            { serverUrl: "http://127.0.0.1:8093", token: "tok-123" },
            "sid-abc",
            "/Users/demo/config.py",
            "cited"
        );
        assert.equal(res.is_text, true);
        assert.equal(calls.length, 1);
        assert.equal(
            calls[0].url,
            "http://127.0.0.1:8093/api/workbench/sessions/sid-abc/file?path=%2FUsers%2Fdemo%2Fconfig.py&scope=cited"
        );
        assert.equal(calls[0].headers.authorization, "Bearer tok-123");
    } finally {
        globalThis.fetch = prevFetch;
    }
});
