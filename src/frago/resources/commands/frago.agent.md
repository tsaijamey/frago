---
description: "Smart Router: Analyze user intent and invoke corresponding frago slash command to execute tasks"
---

# Frago Agent

Based on user task, immediately use Skill tool to invoke appropriate slash command for execution.

## Available slash commands

| slash command | Purpose | Keywords |
|-------|------|--------|
| /frago.run | Browser automation, open webpage, website interaction | open, access, browse, view |
| /frago.do | One-time task execution | execute, complete, do, apply, download |
| /frago.recipe | Create reusable automation recipes | create recipe, write recipe, automation script |
| /frago.test | Test and validate recipes | test, validate, check recipe |

## Routing Rules

- Tasks requiring research => /frago.run
- One-time tasks => /frago.do
- Create recipe => /frago.recipe
- Test recipe => /frago.test
- When uncertain => /frago.do

## Execution Method

Determine user intent, use Skill tool to invoke corresponding slash command, passing user's original task as args:

```
skill: "frago.run"
args: "user's original task"
```

Now immediately execute the following task (no explanation, directly invoke Skill):

$ARGUMENTS
