// frago bridge — Pure WorkbenchRecord transformation, Decision Card parsing,
// Bridge context collapsing, and incremental stream merging.
//
// Zero external dependencies. Runs identically in:
//   1. Extension Side Panel (via globalThis.FragoSessionRecords)
//   2. Node.js unit tests (`node --test` via module.exports)

(function (root, factory) {
    const api = factory();
    if (typeof module === "object" && module && module.exports) {
        module.exports = api;
    }
    if (root) {
        root.FragoSessionRecords = api;
    }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
    "use strict";

    // ══════════ 1. Incremental Record Merging & Pagination Helpers ══════════

    function mergeRecords(prev, incoming) {
        const base = Array.isArray(prev) ? prev : [];
        const batch = Array.isArray(incoming) ? incoming : [];
        if (batch.length === 0) return base;
        const floor = base.length > 0 ? base[0].seq : -Infinity;
        const byId = new Map();
        for (const r of base) {
            if (r && r.id) byId.set(r.id, r);
        }
        let changed = false;
        for (const r of batch) {
            if (!r || !r.id) continue;
            if (r.seq < floor) continue;
            if (!byId.has(r.id)) changed = true;
            byId.set(r.id, r);
        }
        if (!changed && byId.size === base.length) return base;
        return Array.from(byId.values()).sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0));
    }

    function shouldReloadTailOnPoll(prev, batch) {
        if (!Array.isArray(prev) || prev.length === 0) return false;
        if (!Array.isArray(batch) || batch.length === 0) return false;
        const expectedAnchorId = prev[prev.length - 1]?.id;
        return Boolean(expectedAnchorId && batch[0]?.id !== expectedAnchorId);
    }

    function countTalkRecords(records) {
        if (!Array.isArray(records)) return 0;
        let n = 0;
        for (const r of records) {
            if (r && (r.kind === "user.say" || r.kind === "agent.say")) n += 1;
        }
        return n;
    }

    // ══════════ 2. Decision Card Parsing & Answer Composition ══════════

    function unquoteYaml(raw) {
        const s = String(raw || "").trim();
        if (s.length >= 2 && ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'")))) {
            return s.slice(1, -1).replace(/\\"/g, '"').replace(/\\n/g, "\n");
        }
        return s;
    }

    function parseDecisionBlock(yamlStr) {
        const raw = String(yamlStr || "").trim();
        if (!raw) return null;

        // Try JSON first (in case model emits JSON inside answer-needed-by-human fence)
        if (raw.startsWith("{")) {
            try {
                const parsed = JSON.parse(raw);
                if (parsed && typeof parsed === "object" && typeof parsed.question === "string") {
                    const opts = Array.isArray(parsed.options)
                        ? parsed.options
                            .map((o) => {
                                if (typeof o === "string") return { label: o, description: "" };
                                if (o && typeof o === "object") {
                                    return {
                                        label: String(o.label || o.title || o.value || "").trim(),
                                        description: String(o.description || "").trim(),
                                    };
                                }
                                return null;
                            })
                            .filter((o) => o && o.label)
                        : [];
                    return {
                        question: parsed.question.trim(),
                        context: typeof parsed.context === "string" ? parsed.context.trim() : "",
                        options: opts,
                        allowCustom: parsed.allow_custom !== false && parsed.allowCustom !== false,
                    };
                }
            } catch (_) { /* fall through to lightweight YAML parser */ }
        }

        const lines = raw.replace(/\r\n?/g, "\n").split("\n");
        let question = "";
        let context = "";
        let allowCustom = true;
        const options = [];
        let inOptions = false;
        let currentOpt = null;
        let multilineKey = null;
        let multilineLines = [];

        function flushMultiline() {
            if (!multilineKey) return;
            const joined = multilineLines.join("\n").trim();
            if (multilineKey === "question" && !question) question = joined;
            if (multilineKey === "context" && !context) context = joined;
            multilineKey = null;
            multilineLines = [];
        }

        for (const line of lines) {
            if (multilineKey) {
                if (/^\s{2,}/.test(line) || !line.trim()) {
                    multilineLines.push(line.replace(/^\s{2}/, ""));
                    continue;
                }
                flushMultiline();
            }

            if (!line.trim() || /^\s*#/.test(line)) continue;

            const topKv = line.match(/^([a-zA-Z_][a-zA-Z0-9_-]*):\s*(.*)$/);
            if (topKv) {
                const key = topKv[1];
                const val = topKv[2].trim();
                inOptions = key === "options";
                if (key !== "options") currentOpt = null;

                if (key === "question") {
                    if (val === "|" || val === ">") {
                        multilineKey = "question";
                        multilineLines = [];
                    } else {
                        question = unquoteYaml(val);
                    }
                } else if (key === "context") {
                    if (val === "|" || val === ">") {
                        multilineKey = "context";
                        multilineLines = [];
                    } else {
                        context = unquoteYaml(val);
                    }
                } else if (key === "allow_custom" || key === "allowCustom") {
                    allowCustom = val.toLowerCase() !== "false";
                }
                continue;
            }

            if (inOptions) {
                const itemMatch = line.match(/^\s*-\s+(.*)$/);
                if (itemMatch) {
                    const rest = itemMatch[1].trim();
                    const kv = rest.match(/^([a-zA-Z_][a-zA-Z0-9_-]*):\s*(.*)$/);
                    if (kv && (kv[1] === "label" || kv[1] === "title" || kv[1] === "value")) {
                        currentOpt = { label: unquoteYaml(kv[2]), description: "" };
                        options.push(currentOpt);
                    } else if (kv && kv[1] === "description") {
                        currentOpt = { label: "", description: unquoteYaml(kv[2]) };
                        options.push(currentOpt);
                    } else {
                        currentOpt = { label: unquoteYaml(rest), description: "" };
                        options.push(currentOpt);
                    }
                    continue;
                }
                const subKv = line.match(/^\s+([a-zA-Z_][a-zA-Z0-9_-]*):\s*(.*)$/);
                if (subKv && currentOpt) {
                    const k = subKv[1];
                    const v = unquoteYaml(subKv[2]);
                    if ((k === "label" || k === "title" || k === "value") && !currentOpt.label) {
                        currentOpt.label = v;
                    } else if (k === "description") {
                        currentOpt.description = v;
                    }
                }
            }
        }
        flushMultiline();

        const validOptions = options.filter((o) => o && o.label);
        if (!question && validOptions.length === 0) return null;
        return {
            question: question || "需要你的决策",
            context,
            options: validOptions,
            allowCustom,
        };
    }

    function splitTrailingDecisionBlock(text) {
        const src = String(text || "");
        const re = /(?:^|\n)```answer-needed-by-human\s*\n([\s\S]*?)\n```\s*$/;
        const match = src.match(re);
        if (!match) {
            return { bodyText: src, decision: null };
        }
        const decision = parseDecisionBlock(match[1]);
        if (!decision) {
            return { bodyText: src, decision: null };
        }
        const bodyText = src.slice(0, match.index).trimEnd();
        return { bodyText, decision };
    }

    function normalizeUiComponentDecision(raw) {
        if (!raw || typeof raw !== "object") return null;
        if (raw.frago_ui_component !== "decision-card") return null;
        const question = String(raw.question || "").trim();
        if (!question) return null;
        const options = Array.isArray(raw.options)
            ? raw.options
                .map((o) => {
                    if (typeof o === "string") return { label: o, description: "" };
                    if (o && typeof o === "object") {
                        return {
                            label: String(o.label || o.title || "").trim(),
                            description: String(o.description || "").trim(),
                        };
                    }
                    return null;
                })
                .filter((o) => o && o.label)
            : [];
        return {
            question,
            context: typeof raw.context === "string" ? raw.context.trim() : "",
            options,
            allowCustom: raw.allow_custom !== false && raw.allowCustom !== false,
            delegated: true,
        };
    }

    function parseUiComponentOutput(payload) {
        if (!payload || typeof payload !== "object") return null;
        if (payload.ui_component) {
            const direct = normalizeUiComponentDecision(payload.ui_component);
            if (direct) return direct;
        }
        const out = typeof payload.output === "string" ? payload.output.trim() : "";
        if (out.startsWith("{") && out.includes("frago_ui_component")) {
            try {
                return normalizeUiComponentDecision(JSON.parse(out));
            } catch (_) {
                return null;
            }
        }
        return null;
    }

    function composeAnswer(question, selections, customText = "") {
        const picked = (Array.isArray(selections) ? selections : [])
            .map((s) => String(s || "").trim())
            .filter(Boolean);
        const extra = String(customText || "").trim();
        const lines = [`【answer】${String(question || "").trim()}`];
        if (picked.length > 0) {
            lines.push(`选中：${picked.join("；")}`);
        }
        if (extra) {
            lines.push(`补充：${extra}`);
        }
        return lines.join("\n");
    }

    // ══════════ 3. Control Block Stripping & Bridge Context Collapsing ══════════

    function stripTagBlock(text, tagName) {
        const found = [];
        const re = new RegExp(`^\\s*<${tagName}([^>]*)>([\\s\\S]*?)<\\/${tagName}>\\s*`, "i");
        let rest = text;
        let guard = 0;
        while (guard < 8) {
            const m = rest.match(re);
            if (!m) break;
            found.push({ attrs: m[1] || "", body: m[2] || "" });
            rest = rest.slice(m[0].length);
            guard += 1;
        }
        return { rest, found };
    }

    function extractAttachedImages(text) {
        const src = String(text || "");
        const marker = "[附带图片，请用读文件的工具逐一打开查看]:";
        const idx = src.indexOf(marker);
        if (idx === -1) return { text: src, images: [] };

        const before = src.slice(0, idx).trimEnd();
        const afterRaw = src.slice(idx + marker.length);
        const lines = afterRaw.split(/\r?\n/);
        const images = [];
        let splitIdx = lines.length;

        for (let i = 0; i < lines.length; i += 1) {
            const trimmed = lines[i].trim();
            if (!trimmed) {
                if (images.length > 0) {
                    splitIdx = i + 1;
                    break;
                }
                continue;
            }
            const m = trimmed.match(/^-\s+(.+)$/);
            if (m) {
                const rawPath = m[1].trim();
                const uploadMatch = rawPath.match(/webui_uploads\/([^/]+)\/([^/]+)$/);
                images.push({
                    rawPath,
                    name: uploadMatch ? uploadMatch[2] : rawPath.split(/[\\/]/).pop() || "image",
                    apiPath: uploadMatch ? `/api/workbench/uploads/${encodeURIComponent(uploadMatch[1])}/${encodeURIComponent(uploadMatch[2])}` : "",
                });
            } else {
                splitIdx = i;
                break;
            }
        }

        const tail = lines.slice(splitIdx).join("\n").trimStart();
        const combined = [before, tail].filter(Boolean).join("\n\n");
        return { text: combined, images };
    }

    function parseBridgeContextMessage(rawText) {
        const src = String(rawText || "");
        const focusMarkerRe = /\n---\n### 🎯 Focus 焦点内容（共 \d+ 处）/;
        const pageMarkerRe = /\n---\n### 📄 网页完整可见上下文（共 \d+ 页[^\n]*）/;

        const focusMatch = src.match(focusMarkerRe);
        const pageMatch = src.match(pageMarkerRe);

        if (!focusMatch && !pageMatch) {
            return {
                isBridgeMessage: false,
                instruction: src,
                focusItems: [],
                fullPagePages: [],
                rawFullPageText: "",
            };
        }

        const firstMarkerIdx = Math.min(
            focusMatch ? focusMatch.index : Infinity,
            pageMatch ? pageMatch.index : Infinity
        );
        const instruction = src.slice(0, firstMarkerIdx).trim();

        const focusEndIdx = pageMatch ? pageMatch.index : src.length;
        const focusSection = focusMatch ? src.slice(focusMatch.index, focusEndIdx) : "";
        const pageSection = pageMatch ? src.slice(pageMatch.index).replace(/^\n---\n/, "") : "";

        // Parse Focus previews: #### [FOCUS #N] Title（kind...）
        const focusItems = [];
        if (focusSection) {
            const focusChunks = focusSection.split(/\n(?=#### \[FOCUS #\d+\])/).slice(1);
            for (const chunk of focusChunks) {
                const lines = chunk.split("\n");
                const headMatch = lines[0].match(/^#### \[FOCUS #(\d+)\]\s*(.+?)(?:（([^）]+)）)?\s*$/);
                const sourceLine = lines.find((l) => l.startsWith("- 来源：")) || "";
                const sourceUrl = sourceLine.replace("- 来源：", "").trim();
                const bodyStart = lines.findIndex((l, idx) => idx > 0 && !l.startsWith("- 来源：") && l.trim());
                const body = bodyStart >= 0 ? lines.slice(bodyStart).join("\n").trim() : "";
                focusItems.push({
                    num: headMatch ? Number(headMatch[1]) : focusItems.length + 1,
                    title: headMatch ? headMatch[2].trim() : "网页焦点",
                    kindLabel: headMatch?.[3] || "",
                    url: sourceUrl,
                    preview: body.replace(/\s+/g, " ").slice(0, 120),
                    body,
                });
            }
        }

        // Parse Full Page entries: #### [页面 N] Title（约 M 字）
        const fullPagePages = [];
        if (pageSection) {
            const pageChunks = pageSection.split(/\n(?=#### \[页面 \d+\])/).slice(1);
            for (const chunk of pageChunks) {
                const lines = chunk.split("\n");
                const headMatch = lines[0].match(/^#### \[页面 \d+\]\s*(.+?)(?:（约\s*(\d+)\s*字）)?\s*$/);
                const urlLine = lines.find((l) => l.startsWith("- URL：")) || "";
                const url = urlLine.replace("- URL：", "").trim();
                fullPagePages.push({
                    title: headMatch ? headMatch[1].trim() : "当前网页",
                    charCount: headMatch?.[2] ? Number(headMatch[2]) : chunk.length,
                    url,
                });
            }
        }

        return {
            isBridgeMessage: true,
            instruction,
            focusItems,
            fullPagePages,
            rawFullPageText: pageSection.trim(),
        };
    }

    function parseUserSayPayload(payload, rawTextFallback = "") {
        let text = typeof payload?.text === "string" ? payload.text : String(rawTextFallback || "");

        const emp = stripTagBlock(text, "frago-employee");
        text = emp.rest;
        const skill = stripTagBlock(text, "must-use-skill");
        text = skill.rest;
        const cb = stripTagBlock(text, "frago-async-callback");
        text = cb.rest;

        const imgRes = extractAttachedImages(text);
        text = imgRes.text;

        const command = payload?.command ? String(payload.command) : "";
        const bridge = parseBridgeContextMessage(text);

        const employeeNames = emp.found
            .map((item) => {
                const m = item.attrs.match(/(?:name|id)=["']([^"']+)["']/);
                return m ? m[1] : "";
            })
            .filter(Boolean);
        const skillNames = skill.found
            .map((item) => {
                const m = item.attrs.match(/name=["']([^"']+)["']/);
                return m ? m[1] : "";
            })
            .filter(Boolean);

        return {
            employeeNames,
            skillNames,
            hasAsyncCallback: cb.found.length > 0,
            command,
            images: imgRes.images,
            isAnswer: bridge.instruction.startsWith("【answer】"),
            ...bridge,
            rawText: text.trim(),
        };
    }

    // ══════════ 4. Stream Folding & Live Run State ══════════

    function isMainSessionRecord(record) {
        return !record?.agent_path || record.agent_path.length === 0;
    }

    function isHiddenInternalRecord(record) {
        if (!record) return true;
        if (record.kind === "hook" || record.kind === "usage.tick" || record.kind === "session.state") {
            return true;
        }
        if (record.kind === "context.inject") {
            const tag = record.payload?.tag || "";
            if (tag === "queue-operation") {
                return record.payload?.operation !== "enqueue";
            }
            if (!["queued_command", "task-notification", "local-command-output"].includes(tag)) {
                return true;
            }
        }
        return false;
    }

    function summarizeToolCall(record) {
        const p = record?.payload || {};
        const name = String(p.name || p.tool || "Tool");
        let detail = "";
        if (p.input && typeof p.input === "object") {
            if (typeof p.input.command === "string") detail = p.input.command;
            else if (typeof p.input.file_path === "string") detail = p.input.file_path;
            else if (typeof p.input.path === "string") detail = p.input.path;
            else if (typeof p.input.pattern === "string") detail = p.input.pattern;
            else if (typeof p.input.query === "string") detail = p.input.query;
            else if (typeof p.input.question === "string") detail = p.input.question;
        }
        return {
            id: record.id,
            kind: "tool.call",
            name,
            detail: String(detail || "").replace(/\s+/g, " ").slice(0, 120),
        };
    }

    function buildChatSegments(records) {
        const list = Array.isArray(records) ? records : [];

        // Track last human turn index to determine which Decision Cards are already answered
        const visible = [];
        for (const r of list) {
            if (!isHiddenInternalRecord(r)) visible.push(r);
        }

        const humanSeqs = [];
        for (const r of visible) {
            if (r.kind === "user.say" || (r.kind === "context.inject" && r.payload?.tag === "queued_command")) {
                humanSeqs.push(r.seq ?? 0);
            }
        }
        const latestHumanSeq = humanSeqs.length > 0 ? humanSeqs[humanSeqs.length - 1] : -Infinity;

        const segments = [];
        let pendingActivity = null;

        function flushActivity() {
            if (!pendingActivity) return;
            segments.push(pendingActivity);
            pendingActivity = null;
        }

        for (const r of visible) {
            const mainSession = isMainSessionRecord(r);

            if (r.kind === "agent.think" || r.kind === "tool.call" || r.kind === "tool.result") {
                const uiDecision = r.kind === "tool.result" && mainSession
                    ? parseUiComponentOutput(r.payload)
                    : null;

                if (!pendingActivity) {
                    pendingActivity = {
                        type: "activity",
                        key: `act-${r.id}`,
                        seq: r.seq ?? 0,
                        thinkCount: 0,
                        toolCount: 0,
                        items: [],
                        latestLabel: "",
                        decision: null,
                        decisionRecordId: null,
                        decisionAnswered: false,
                    };
                }

                if (r.kind === "agent.think") {
                    pendingActivity.thinkCount += 1;
                    const txt = String(r.payload?.text || "").trim();
                    if (txt) {
                        pendingActivity.items.push({
                            id: r.id,
                            kind: "agent.think",
                            text: txt.slice(0, 400),
                        });
                    }
                    pendingActivity.latestLabel = "正在思考…";
                } else if (r.kind === "tool.call") {
                    pendingActivity.toolCount += 1;
                    const summary = summarizeToolCall(r);
                    pendingActivity.items.push(summary);
                    pendingActivity.latestLabel = `执行 ${summary.name}${summary.detail ? `: ${summary.detail}` : ""}`;
                } else if (r.kind === "tool.result") {
                    const out = String(r.payload?.output || "").trim();
                    pendingActivity.items.push({
                        id: r.id,
                        kind: "tool.result",
                        isError: Boolean(r.payload?.is_error),
                        text: out.slice(0, 300),
                    });
                    if (uiDecision) {
                        pendingActivity.decision = uiDecision;
                        pendingActivity.decisionRecordId = r.id;
                        pendingActivity.decisionAnswered = (r.seq ?? 0) < latestHumanSeq;
                    }
                }
                continue;
            }

            if (r.kind === "agent.say") {
                const rawText = String(r.payload?.text || "");
                const parsed = mainSession
                    ? splitTrailingDecisionBlock(rawText)
                    : { bodyText: rawText, decision: null };

                // Inherit delegated decision card from preceding activity if agent.say didn't emit a trailing YAML block
                let finalDecision = parsed.decision;
                let decisionAnswered = (r.seq ?? 0) < latestHumanSeq;
                if (!finalDecision && pendingActivity?.decision) {
                    finalDecision = pendingActivity.decision;
                    decisionAnswered = pendingActivity.decisionAnswered;
                    pendingActivity.decision = null;
                } else if (finalDecision && pendingActivity?.decision) {
                    pendingActivity.decision = null;
                }

                flushActivity();
                segments.push({
                    type: "agent.say",
                    key: r.id,
                    record: r,
                    bodyText: parsed.bodyText,
                    decision: finalDecision,
                    decisionAnswered,
                    subagent: !mainSession,
                });
                continue;
            }

            flushActivity();

            if (r.kind === "user.say") {
                segments.push({
                    type: "user.say",
                    key: r.id,
                    record: r,
                    parsed: parseUserSayPayload(r.payload),
                });
            } else if (r.kind === "context.inject") {
                const tag = r.payload?.tag || "";
                if (tag === "queued_command") {
                    segments.push({
                        type: "user.say",
                        key: r.id,
                        record: r,
                        queued: true,
                        parsed: parseUserSayPayload({ text: r.payload?.text || "" }),
                    });
                } else if (tag === "task-notification") {
                    segments.push({
                        type: "notice",
                        key: r.id,
                        record: r,
                        title: r.payload?.summary || "后台任务通知",
                        status: r.payload?.status || "",
                        text: String(r.payload?.result || r.payload?.text || ""),
                    });
                } else if (tag === "local-command-output") {
                    segments.push({
                        type: "notice",
                        key: r.id,
                        record: r,
                        title: "命令输出",
                        text: String(r.payload?.text || ""),
                    });
                } else if (tag === "queue-operation" && r.payload?.operation === "enqueue") {
                    segments.push({
                        type: "user.say",
                        key: r.id,
                        record: r,
                        queued: true,
                        parsed: parseUserSayPayload({ text: r.payload?.content || r.payload?.text || "" }),
                    });
                }
            } else if (r.kind === "error") {
                segments.push({
                    type: "error",
                    key: r.id,
                    record: r,
                    text: String(r.payload?.message || r.payload?.text || r.payload?.error || "发生未知错误"),
                });
            }
        }

        flushActivity();
        return segments;
    }

    function deriveLiveRunState(records, sessionCard = null) {
        const list = Array.isArray(records) ? records : [];
        let lastAgentSayIdx = -1;
        let lastUserSayIdx = -1;
        let lastTurnDoneIdx = -1;
        let lastWorkIdx = -1;
        for (let i = list.length - 1; i >= 0; i -= 1) {
            const r = list[i];
            const k = r?.kind;
            if (lastAgentSayIdx === -1 && k === "agent.say") lastAgentSayIdx = i;
            if (lastUserSayIdx === -1 && k === "user.say") lastUserSayIdx = i;
            if (
                lastTurnDoneIdx === -1 &&
                k === "call.envelope" &&
                (!r?.payload?.channel || r.payload.channel === "turn-duration")
            ) {
                lastTurnDoneIdx = i;
            }
            if (lastWorkIdx === -1 && (k === "agent.think" || k === "tool.call" || k === "tool.result")) {
                lastWorkIdx = i;
            }
            if (lastAgentSayIdx !== -1 && lastUserSayIdx !== -1 && lastTurnDoneIdx !== -1 && lastWorkIdx !== -1) {
                break;
            }
        }

        let latestActivityLabel = "";
        for (let i = list.length - 1; i > lastAgentSayIdx; i -= 1) {
            const r = list[i];
            if (!r) continue;
            if (r.kind === "tool.call") {
                const s = summarizeToolCall(r);
                latestActivityLabel = `正在执行 ${s.name}${s.detail ? ` · ${s.detail}` : ""}`;
                break;
            }
            if (r.kind === "agent.think") {
                latestActivityLabel = "正在思考中…";
                break;
            }
        }

        const cardRunning = sessionCard?.status === "running";
        const hasPendingTurn = lastUserSayIdx > lastAgentSayIdx && lastUserSayIdx !== -1;
        const turnExplicitlyDone =
            lastTurnDoneIdx !== -1 &&
            lastTurnDoneIdx > lastUserSayIdx &&
            lastTurnDoneIdx > lastWorkIdx &&
            lastAgentSayIdx > lastUserSayIdx;
        const isRunning = turnExplicitlyDone
            ? false
            : Boolean(cardRunning || (sessionCard?.alive && hasPendingTurn));

        return {
            isRunning,
            needDecision: Boolean(sessionCard?.need_decision),
            latestActivityLabel: latestActivityLabel || (isRunning ? "Agent 处理中…" : ""),
        };
    }

    return {
        mergeRecords,
        shouldReloadTailOnPoll,
        countTalkRecords,
        parseDecisionBlock,
        splitTrailingDecisionBlock,
        parseUiComponentOutput,
        composeAnswer,
        parseBridgeContextMessage,
        parseUserSayPayload,
        buildChatSegments,
        deriveLiveRunState,
    };
});
