# Execution Principles

Applies to: `/frago.run`, `/frago.do`

## Core Principles

### 1. Correctly Understand Intent

Human descriptions can be concise. If intent is unclear, use interactive menus to let humans choose or input the information you need.

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

## Confirm Directory Before Executing Commands

**Ensure you are in the correct directory**. Before executing each command, use `pwd` to confirm the current working directory.
