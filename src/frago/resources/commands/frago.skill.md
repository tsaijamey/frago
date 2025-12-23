---
description: "Create Claude Code Skills from conversation context or user-provided methods"
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
            2. Quick Reference section
            3. Usage section (step by step)
            4. Examples section (if applicable)

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
    "Use when user needs [specific scenario]. Covers [feature1], [feature2]."
    "[Action] guide. Use when [keyword1], [keyword2] are mentioned."

BAD description patterns:
    "A useful tool" (too vague)
    "PDF processing" (doesn't say when to use)
</description_quality>

<yaml_rules>
name:
    - lowercase, numbers, hyphens only
    - ≤64 chars
    - NO: underscore, uppercase, "claude", "anthropic"

description:
    - ≤1024 chars
    - Third person
    - Include trigger keywords
</yaml_rules>

<forbidden>
❌ Using Tab indentation in YAML
❌ name doesn't match directory name
❌ Nested references (SKILL.md → index.md → details.md)
❌ SKILL.md > 500 lines without splitting
❌ description too vague without trigger words

✅ Space indentation
✅ name = directory name
✅ One level of reference (SKILL.md → REFERENCE.md)
✅ Detailed content split into supporting files
</forbidden>

<commands>
/frago.skill "<context or method>"      => analyze and create skill
/frago.skill from conversation          => extract patterns from current chat
/frago.skill update <name>              => iterate existing skill
</commands>

<template_skill_md>
---
name: skill-name-here
description: What this skill does. Use when user needs [specific scenario]. Covers [feature keywords].
---

# Skill Title

## Functionality

Briefly describe what problem this skill solves, when it should be triggered.

## Usage

1. First operation step
2. Second operation step
3. Verify results

## Examples

```bash
# Example command or code
```

## Reference

Detailed documentation in [REFERENCE.md](REFERENCE.md) (if applicable)
</template_skill_md>

<template_reference_md>
# Reference Documentation

## Table of Contents
- [Section 1: Basic Concepts](#section-1)
- [Section 2: Detailed Explanation](#section-2)

## Section 1: Basic Concepts
...

## Section 2: Detailed Explanation
...
</template_reference_md>
