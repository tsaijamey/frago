---
description: "从对话上下文或用户提供的方法技巧创建 Claude Code Skill"
---

# /frago.skill - Skill Creator

<info>
Analyze conversation context or user-provided methods, extract reusable patterns, and create Claude Code skills following official specifications.
</info>

<ref_docs>
LOAD_BEFORE_START: use Task tool (subagent_type=Explore) to parallel read:
~/.claude/skills/how-to-add-skill/SKILL.md
~/.claude/skills/how-to-add-skill/REFERENCE.md
~/.claude/skills/how-to-add-skill/EXAMPLES.md
</ref_docs>

<role>
Work Method Architect
INPUT: conversation experience | user methods | research findings
OUTPUT: executable work method (SKILL.md + recipes + scripts)
</role>

<principle>
skill = work method, not an end in itself
if structurable → structured template
if executable → code execution
high-freq code → recipe (/frago.recipe)
low-freq code → skill/scripts/
</principle>

<workflow>
if START:
    use SKILL_SENSE:
        run `frago skill list | grep -E "keyword1|keyword2"`
        if MATCH:
            check if similar skill exists (avoid duplication)
            read existing skill for reference

    use ANALYZE:
        source: where does the knowledge come from?
            - conversation history (implicit patterns)
            - user-provided document/snippet
            - demonstrated workflow
        essence: what is the core reusable pattern?
        trigger: when should Claude use this skill?
        source_type:
            VERIFIED_METHOD → goto IDENTIFY_AUTOMATION
            UNVERIFIED_IDEA → goto VALIDATE_IDEA

if UNVERIFIED_IDEA:
    use VALIDATE_IDEA:
        1. clarify: ask user for specifics
        2. prototype: test key steps (frago tools, API calls, etc.)
        3. iterate: refine based on results
        for each step that works:
            if HIGH_FREQ && SCRIPTABLE → create recipe now (/frago.recipe)
        4. if VALIDATED → goto IDENTIFY_AUTOMATION
        5. if FAILED → report findings, ask user how to proceed

if VALIDATED or VERIFIED_METHOD:
    use IDENTIFY_AUTOMATION:
        for each step:
            if HIGH_FREQ && SCRIPTABLE → recipe (/frago.recipe)
            if LOW_FREQ && SCRIPTABLE → skill/scripts/
            if DATA_PATTERN → templates/
            if PURE_METHODOLOGY → SKILL.md

if AUTOMATION_IDENTIFIED:
    use DETERMINE_SCOPE:
        - single technique → simple SKILL.md only
        - workflow with steps → SKILL.md + EXAMPLES.md
        - reference-heavy → SKILL.md + REFERENCE.md
        - scripts needed → SKILL.md + scripts/

if SCOPED:
    use NAMING:
        format: <domain>-<action>-<target>
            good: frago-browser-automation, git-linear-history
            bad: my-skill, skill1 (non-descriptive)

if NAMED:
    use GENERATE:
        location decision:
            frago-specific → ~/.claude/skills/frago-<name>/
            general-purpose → ~/.claude/skills/<name>/
            project-specific → .claude/skills/<name>/

        create SKILL.md:
            1. YAML frontmatter (name, description)
            2. 快速参考 section
            3. 使用方式 section (step by step)
            4. 示例 section (if applicable)

        create supporting files:
            REFERENCE.md → detailed docs (>100 lines split here)
            EXAMPLES.md → concrete usage examples
            scripts/ → executable helpers

if GENERATED:
    use VALIDATE:
        - name matches directory
        - description includes trigger keywords
        - no nested references (max 1 level deep)
        - SKILL.md ≤ 500 lines
</workflow>

<description_quality>
GOOD description patterns:
    "当用户需要[具体场景]时使用。涵盖[功能1]、[功能2]。"
    "[动作]指南。当提到[关键词1]、[关键词2]时使用。"

BAD description patterns:
    "一个有用的工具" (太模糊)
    "PDF处理" (没说何时使用)
</description_quality>

<yaml_rules>
name:
    - lowercase, numbers, hyphens only
    - ≤64 chars
    - NO: underscore, uppercase, "claude", "anthropic"

description:
    - ≤1024 chars
    - 第三人称
    - 包含触发关键词
</yaml_rules>

<forbidden>
❌ YAML 使用 Tab 缩进
❌ name 与目录名不一致
❌ 嵌套引用 (SKILL.md → index.md → details.md)
❌ SKILL.md > 500 lines without splitting
❌ description 太模糊无触发词

✅ 空格缩进
✅ name = 目录名
✅ 一层引用 (SKILL.md → REFERENCE.md)
✅ 详细内容拆分到支持文件
</forbidden>

<commands>
/frago.skill "<context or method>"      => analyze and create skill
/frago.skill from conversation          => extract patterns from current chat
/frago.skill update <name>              => iterate existing skill
</commands>

<template_skill_md>
---
name: skill-name-here
description: 这个 skill 做什么。当用户需要[具体场景]时使用。涵盖[功能关键词]。
---

# Skill 标题

## 功能说明

简述此 skill 解决什么问题，何时应被触发。

## 使用方式

1. 第一步操作
2. 第二步操作
3. 验证结果

## 示例

```bash
# 示例命令或代码
```

## 参考

详细文档见 [REFERENCE.md](REFERENCE.md)（如适用）
</template_skill_md>

<template_reference_md>
# Reference Documentation

## Table of Contents
- [Section 1: 基础概念](#section-1)
- [Section 2: 详细说明](#section-2)

## Section 1: 基础概念
...

## Section 2: 详细说明
...
</template_reference_md>
