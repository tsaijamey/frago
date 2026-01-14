---
description: "Create Claude Code Skills from conversation context or user-provided methods"
---

# /frago.skill - Skill Creator

<info>
  Analyze conversation context or user-provided methods, extract reusable patterns, and create Claude Code skills following official specifications.
</info>

<doc_structure>
  XML tags organize content by layer:

  META    : <info> <role> <principle> — skill identity
  PREREQ  : <ref_docs> — load before execution
  INFRA   : <transactional_execution> — frago infrastructure
  LOGIC   : <how_to> — core execution logic (pseudocode)
  RULES   : <yaml_rules> <forbidden> <description_quality> — constraints
  USAGE   : <commands> — invocation syntax
  TEMPLATE: <*_template> — output templates

  Read order: META → PREREQ → INFRA → LOGIC
</doc_structure>

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

<transactional_execution>
  Skills should use frago's transactional execution infrastructure for workspace management and traceability.

  <workspace_management>
    frago run init "task description"     # Initialize run instance
    frago run set-context <run_id>        # Set current context
  </workspace_management>

  <execution_logging>
    frago run log --step "Phase 1: xxx" --status "success"
    frago run screenshot                   # Save screenshot (auto-numbered)
  </execution_logging>

  <recipe_calls>
    frago recipe run <recipe_name> '{...}' # Execute reusable operations
  </recipe_calls>

  <output_naming>
    outputs/
    ├── 01_<function>.json    # Phase 1 output
    ├── 02_<function>.json    # Phase 2 output
    ├── audios/               # Audio directory (if applicable)
    ├── clips/                # Video clips (if applicable)
    └── final_output.xxx      # Final artifact
  </output_naming>

  <phased_workflow>
    Phase 0: Workspace Initialization
      → frago run init + directory structure check

    Phase 1-N: Business Logic
      → Call recipe or execute scripts per phase
      → Name outputs with numbered prefix
      → Log progress via frago run log

    Final: Output Verification
      → Check artifact completeness
  </phased_workflow>

  <reference>
    See ~/.claude/skills/frago-video-raw-to-release/SKILL.md for complete example.
  </reference>
</transactional_execution>

<how_to>
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
</how_to>

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

<skill_md_template>
  ---
  name: skill-name-here
  description: What this skill does. Use when user needs [specific scenario]. Covers [feature keywords].
  ---

  # Skill Title

  ## Functionality

  Briefly describe what problem this skill solves, when it should be triggered.

  ## Workflow

  ### Phase 0: Workspace Initialization

  ```bash
  frago run init "task description"
  ```

  Creates workspace structure:
  - `resources/` - Input materials
  - `outputs/` - Generated artifacts
  - `logs/` - Execution logs

  ### Phase 1: [First Step]

  **Recipe call**:
  ```bash
  frago recipe run <recipe_name> '{
    "param1": "value1"
  }'
  ```

  **Output**: `outputs/01_<function>.json`

  ### Phase 2: [Second Step]

  (Repeat pattern for each phase)

  ### Final: Verification

  Check artifact completeness and expected outputs.

  ## Output Structure

  ```
  outputs/
  ├── 01_<function>.json
  ├── 02_<function>.json
  └── final_output.xxx
  ```

  ## Recipe Dependencies

  | Phase | Recipe | Purpose |
  |-------|--------|---------|
  | 1 | `recipe_name` | Brief description |
  | 2 | `another_recipe` | Brief description |

  ## Reference

  Detailed documentation in [REFERENCE.md](REFERENCE.md) (if applicable)
</skill_md_template>

<reference_md_template>
  # Reference Documentation

  ## Table of Contents
  - [Section 1: Basic Concepts](#section-1)
  - [Section 2: Detailed Explanation](#section-2)

  ## Section 1: Basic Concepts
  ...

  ## Section 2: Detailed Explanation
  ...
</reference_md_template>
