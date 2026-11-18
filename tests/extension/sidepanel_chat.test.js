const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const md = require(path.resolve(
    __dirname,
    "../../src/frago/_resources/extension_bundle/shared/markdown.js"
));
const recLib = require(path.resolve(
    __dirname,
    "../../src/frago/_resources/extension_bundle/shared/session_records.js"
));
const composer = require(path.resolve(
    __dirname,
    "../../src/frago/_resources/extension_bundle/shared/message_composer.js"
));

test("markdown parser parses headings, fenced code, tables, lists, blockquotes, and rejects unsafe links", () => {
    const sample = [
        "# 标题一",
        "",
        "这是一段包含 **加粗**、`inline_code` 和 [安全链接](https://frago.ai) 以及 [危险链接](javascript:alert(1)) 的文本。",
        "",
        "> 引用段落",
        "",
        "- 第一项",
        "- 第二项",
        "",
        "```js",
        "const x = 1;",
        "```",
        "",
        "| 列A | 列B |",
        "| --- | --- |",
        "| 值1 | 值2 |",
    ].join("\n");

    const blocks = md.parseMarkdownBlocks(sample);
    assert.equal(blocks[0].type, "heading");
    assert.equal(blocks[0].level, 1);

    const para = blocks[1];
    assert.equal(para.type, "paragraph");
    const linkNodes = para.lines[0].filter((n) => n.type === "link");
    assert.equal(linkNodes.length, 1);
    assert.equal(linkNodes[0].href, "https://frago.ai");
    assert.equal(md.isSafeUrl("javascript:alert(1)"), false);

    assert.equal(blocks[2].type, "blockquote");
    assert.equal(blocks[3].type, "list");
    assert.equal(blocks[3].items.length, 2);
    assert.equal(blocks[4].type, "code");
    assert.equal(blocks[4].lang, "js");
    assert.equal(blocks[5].type, "table");
    assert.equal(blocks[5].headers.length, 2);
    assert.equal(blocks[5].rows.length, 1);
});

test("parseBridgeContextMessage collapses FragoMessageComposer payload cleanly", () => {
    const composed = composer.composeBridgePayload({
        instruction: "请帮我提炼重点",
        focusItems: [
            {
                kind: "selection",
                title: "示例文档",
                url: "https://example.com/doc",
                selector: "article p",
                markdown: "核心指标提升 42%",
                text: "核心指标提升 42%",
            },
        ],
        includeFullPage: true,
        activePage: {
            title: "示例文档",
            url: "https://example.com/doc",
            markdown: "# 示例文档\n\n开头背景。\n\n核心指标提升 42%\n\n结尾说明。",
        },
    });
    assert.equal(composed.ok, true);

    const parsed = recLib.parseUserSayPayload({ text: `<frago-employee name="writer">...</frago-employee>\n\n${composed.text}` });
    assert.deepEqual(parsed.employeeNames, ["writer"]);
    assert.equal(parsed.isBridgeMessage, true);
    assert.equal(parsed.instruction, "请帮我提炼重点");
    assert.equal(parsed.focusItems.length, 1);
    assert.ok(parsed.focusItems[0].preview.includes("核心指标提升 42%"));
    assert.equal(parsed.fullPagePages.length, 1);
    assert.equal(parsed.fullPagePages[0].title, "示例文档");
    assert.ok(parsed.rawFullPageText.includes("<<< 🎯 FOCUS #1 开始 >>>"));
});

test("parseUserSayPayload extracts attached webui_uploads images", () => {
    const raw = [
        "请看截图",
        "",
        "[附带图片，请用读文件的工具逐一打开查看]:",
        "- /Users/frago/.frago/webui_uploads/abc-123/shot.png",
    ].join("\n");
    const parsed = recLib.parseUserSayPayload({ text: raw });
    assert.equal(parsed.instruction, "请看截图");
    assert.equal(parsed.images.length, 1);
    assert.equal(parsed.images[0].apiPath, "/api/workbench/uploads/abc-123/shot.png");
});

test("splitTrailingDecisionBlock parses YAML answer-needed-by-human and composes answer", () => {
    const reply = [
        "分析已完成，请拍板下一步：",
        "",
        "```answer-needed-by-human",
        "question: 选择哪种实现路径？",
        "context: 方案 A 更快，方案 B 更稳",
        "options:",
        "  - label: 方案 A",
        "    description: 快速上线",
        "  - label: 方案 B",
        "    description: 完整重构",
        "allow_custom: true",
        "```",
    ].join("\n");

    const { bodyText, decision } = recLib.splitTrailingDecisionBlock(reply);
    assert.equal(bodyText, "分析已完成，请拍板下一步：");
    assert.ok(decision);
    assert.equal(decision.question, "选择哪种实现路径？");
    assert.equal(decision.options.length, 2);
    assert.equal(decision.options[0].label, "方案 A");
    assert.equal(decision.allowCustom, true);

    const ans = recLib.composeAnswer(decision.question, ["方案 B"], "优先稳定性");
    assert.equal(ans, "【answer】选择哪种实现路径？\n选中：方案 B\n补充：优先稳定性");
});

test("buildChatSegments folds think/tool calls and tracks decision answered state", () => {
    const records = [
        { id: "r1", seq: 1, kind: "user.say", agent_path: [], payload: { text: "问题 1" } },
        { id: "r2", seq: 2, kind: "agent.think", agent_path: [], payload: { text: "思考中" } },
        { id: "r3", seq: 3, kind: "tool.call", agent_path: [], payload: { name: "Bash", input: { command: "ls" } } },
        { id: "r4", seq: 4, kind: "tool.result", agent_path: [], payload: { output: "ok", is_error: false } },
        {
            id: "r5",
            seq: 5,
            kind: "agent.say",
            agent_path: [],
            payload: {
                text: "请确认\n\n```answer-needed-by-human\nquestion: 继续吗？\noptions:\n  - label: 继续\n```",
            },
        },
        { id: "r6", seq: 6, kind: "hook", agent_path: [], payload: {} },
    ];

    const segs = recLib.buildChatSegments(records);
    assert.equal(segs.length, 3);
    assert.equal(segs[0].type, "user.say");
    assert.equal(segs[1].type, "activity");
    assert.equal(segs[1].toolCount, 1);
    assert.equal(segs[1].thinkCount, 1);
    assert.equal(segs[2].type, "agent.say");
    assert.ok(segs[2].decision);
    assert.equal(segs[2].decisionAnswered, false);

    // Adding a subsequent human answer marks the decision card as answered
    const segs2 = recLib.buildChatSegments([
        ...records,
        { id: "r7", seq: 7, kind: "user.say", agent_path: [], payload: { text: "【answer】继续吗？\n选中：继续" } },
    ]);
    assert.equal(segs2[2].decisionAnswered, true);
});

test("mergeRecords deduplicates, sorts by seq, and detects renumbered polls", () => {
    const prev = [
        { id: "a", seq: 10, kind: "user.say", payload: {} },
        { id: "b", seq: 11, kind: "agent.say", payload: {} },
    ];
    assert.equal(recLib.shouldReloadTailOnPoll(prev, [{ id: "b", seq: 11 }]), false);
    assert.equal(recLib.shouldReloadTailOnPoll(prev, [{ id: "x", seq: 11 }]), true);

    const merged = recLib.mergeRecords(prev, [
        { id: "old", seq: 5, kind: "user.say", payload: {} },
        { id: "b", seq: 11, kind: "agent.say", payload: {} },
        { id: "c", seq: 12, kind: "agent.say", payload: {} },
    ]);
    assert.deepEqual(
        merged.map((r) => r.id),
        ["a", "b", "c"]
    );
});

test("deriveLiveRunState detects active tool execution after last agent.say", () => {
    const records = [
        { id: "r1", seq: 1, kind: "user.say", payload: { text: "查一下" } },
        { id: "r2", seq: 2, kind: "tool.call", payload: { name: "Read", input: { file_path: "/tmp/a.py" } } },
    ];
    const run = recLib.deriveLiveRunState(records, { status: "running", alive: true, need_decision: false });
    assert.equal(run.isRunning, true);
    assert.ok(run.latestActivityLabel.includes("Read"));

    const finishedRecords = [
        ...records,
        { id: "r3", seq: 3, kind: "tool.result", payload: { output: "ok" } },
        { id: "r4", seq: 4, kind: "agent.say", payload: { text: "已完成。" } },
        { id: "r5", seq: 5, kind: "call.envelope", payload: { channel: "turn-duration", duration_ms: 1200 } },
    ];
    const doneState = recLib.deriveLiveRunState(finishedRecords, { status: "running", alive: true, need_decision: false });
    assert.equal(doneState.isRunning, false);
});
