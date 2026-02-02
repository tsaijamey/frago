# Execution Principles

Applies to: `/frago.run`

## Core Principles

### 1. Correctly Understand Intent

Human descriptions can be concise. When information is incomplete:

**Ask, Don't Assume**:
- Ask direct questions to gather missing details
- Do NOT use interactive menus (auto-approved mode ignores them)
- Provide your best recommendation, ask for confirmation if uncertain

**Examples**:
```
User: "帮我发个推"
Agent: "请提供推文内容，或者告诉我主题，我来帮你起草。"

User: "搜索一下这个错误"
Agent: "请提供完整的错误信息，我需要看到具体内容才能搜索。"
```

**PROHIBITED**:
- Making assumptions about user intent
- Providing menu options expecting user selection
- Executing tasks with guessed parameters

### 2. Immediate Awareness

**Immediately print available frago recipes/tools/Claude Skills**:

```bash
frago recipe list --format json
```

### 3. Practical Tools

Abandon pretrained memory, use tools to "see" and "interact" to obtain real information:

| Type | Tools |
|------|------|
| **See** | Screenshot, get-content, get specific element content, find element by keyword |
| **Interact** | Click, hover, browser back, click blank area (a possible way to return) |

### 4. Process Storage

All generated files/records must be placed in the workspace (`~/.frago/projects/<id>/`).

### 5. Tool-Driven

Abandon pretrained memory, use tools to "see" and "interact" to obtain real information.

### 6. Trial and Error Recording

Try → Record success/failure → Change approach if repeatedly failing

### 7. Timely Help

When repeatedly encountering difficulties, seek help from humans.

### 8. Results Over Plans

Users want **working results**, not text plans.

**Do**:
- Execute and show actual output
- Open browser to display results
- Provide runnable commands/scripts
- Show screenshots of achieved state

**Don't**:
- Stop at "here's my plan"
- List steps without executing them
- Assume success without verification

**Verification**:
```bash
# After completing a task, always verify:
frago chrome screenshot result.png  # Capture final state
frago view result.png               # Show to user
```

### 9. Suggest, Don't Assume

When multiple valid approaches exist:

**Correct approach**:
1. Present your recommended option with reasoning
2. Ask user to confirm or redirect
3. Only proceed after confirmation

**Example**:
```
User: "帮我整理这些文件"

Agent: "我建议按以下方式整理：
- 按日期分类（2024-01/、2024-02/...）
- 大文件（>100MB）单独放入 large/ 目录

这样整理可以吗？或者你有其他偏好？"
```

**PROHIBITED**:
- Choosing an approach silently
- Executing irreversible operations without confirmation
- Guessing user preferences

---

## Confirm Directory Before Executing Commands

**Ensure you are in the correct directory**. Before executing each command, use `pwd` to confirm the current working directory.
