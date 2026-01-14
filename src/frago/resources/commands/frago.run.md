---
description: "Execute AI-driven browser automation: exploration, task execution, and info gathering for Recipe creation"
---

# /frago.run - Task Runner

<info>
Unified command for exploration and task execution.
Dual goals: complete user's task AND collect reusable insights for Recipe creation.
</info>

<ref_docs>
LOAD_BEFORE_START: use Task tool (subagent_type=Explore) to parallel read:
~/.claude/commands/frago/rules/EXECUTION_PRINCIPLES.md
~/.claude/commands/frago/rules/NAVIGATION_RULES.md
~/.claude/commands/frago/rules/SCREENSHOT_RULES.md
~/.claude/commands/frago/rules/TOOL_PRIORITY.md
~/.claude/commands/frago/rules/WORKSPACE_RULES.md
~/.claude/commands/frago/guides/LOGGING_GUIDE.md
~/.claude/commands/frago/guides/SELECTOR_PRIORITY.md
~/.claude/commands/frago/guides/RECIPE_FIELDS.md
~/.claude/commands/frago/scripts/run_workflow.sh
~/.claude/commands/frago/scripts/common_commands.sh
</ref_docs>

<role>
Task Runner
GOALS:
    1. Complete user's specific task (PRIMARY)
    2. Collect reusable info for future Recipe creation (SECONDARY)
OUTPUT: Task Result + Insights (.metadata.json)
</role>

<faith_check>
REJECT: pretrained knowledge (except natural science, core tech)
TRUST: browser-collected, user-provided
BELIEVE_ONLY: natural science, core tech, human consensus, self-collected info

⚠️ SEARCH RULE (CRITICAL):
    if GUI_AVAILABLE (desktop mode):
        WebSearch => FORBIDDEN (causes system crash!)
        MUST USE: frago chrome navigate "https://google.com/search?q=..."
    if HEADLESS (no GUI):
        WebSearch => allowed as fallback
</faith_check>

if START:
    use ENV_SENSE (via Task tool, subagent_type=Explore):
        run `frago skill list | grep -E "keyword1|keyword2"`
        run `frago recipe list | grep -E "keyword1|keyword2"`
        run `frago run list | grep -E "keyword1|keyword2"`
        if SKILL_MATCH:
            read matched skill for guidance before action
        if EXISTING_PROJECT_FOUND:
            run `frago run info <project_id>`
            consider reusing existing work
        <info>
        WHY:
        - discover applicable skills (get best practices first)
        - discover reusable recipes (avoid re-exploring)
        - check existing results (avoid duplicate work)
        </info>

if TASK_RECEIVED:
    use CLARIFY:
        BROWSER_NEEDED?
            web scraping, UI => yes, use CDP
            API, file processing => no, use CLI/Python
            mixed => try no-browser first

        if BROWSER_NEEDED:
            run `frago status`
            run `frago chrome start`  # or --headless
            <info>
            TIP: first try `frago recipe list | grep <keyword>` to find existing recipes,
            may not need manual browser operation.
            </info>

        if OUTPUT_FORMAT unclear:
            use AskUserQuestion:
                Structured (JSON/CSV) => downstream processing
                Document (Markdown/HTML) => reading, sharing
                Log only => minimal output
            <info>
            GUIDANCE:
            - need program processing => JSON/CSV
            - need detailed reading => Markdown
            - need presentation => reveal.js HTML
            - uncertain => ask user
            </info>

if READY:
    use PROJECT_INIT:
        generate PROJECT_ID: English slug, 3-10 words, hyphen-separated
            MUST: use English words only (no Chinese, no pinyin)
            examples: "upwork-python-job-apply", "youtube-subtitle-api-research"
        run `frago run init "<desc>"`
        run `frago run set-context <id>`

if EXECUTING:
    PRIORITY: Recipe > frago > system > Claude tools
    run `frago recipe list | grep keyword`
    run `frago recipe run <name> --params '{}' --output-file result.json`

    CDP commands auto-log
    Agent logs manually:
        failures, discoveries => _insights
        analysis, recipe_execution => manual log

if DONE:
    use SAVE_RESULT:
        run `frago run screenshot "result"`
        run `frago run log --step "done" --status success --action-type analysis --execution-method analysis --data '{"task_completed": true}'`

    use METADATA_UPDATE:
        run `cat ~/.frago/projects/<id>/.metadata.json`
        update .metadata.json with:
            purpose: brief task goal
            method: "1. step1; 2. step2; ..."
            insights: [{ type: "key_factor|lesson|pitfall", summary: "..." }]
            reuse_guidance: how to reuse for similar tasks
            recipe_potential: { ready: true/false, spec: {...} if ready }
        <info>
        WHY: agent can learn from `frago run info <id>` for future similar tasks
        </info>

    use RELEASE:
        run `frago run release`

<insights_mandatory>
RULE: every 5 logs => at least 1 with _insights

TRIGGERS:
    operation failed/error => type: pitfall (MUST)
    succeeded after retry => type: lesson (MUST)
    found key technique => type: key_factor (MUST)

FORMAT:
    run `frago run log --step "..." --status warning --action-type analysis --execution-method analysis --data '{"_insights": [{"type": "pitfall", "summary": "..."}]}'`
</insights_mandatory>

<rules_critical>
NO_HALLUCINATION_NAV:
    NEVER guess URLs
    => rules/NAVIGATION_RULES.md

NO_SCREENSHOT_READING:
    NEVER read content via screenshot
    use get-content or exec-js
    => rules/SCREENSHOT_RULES.md

TOOL_PRIORITY:
    Recipe > frago > get-content > screenshot
    => rules/TOOL_PRIORITY.md

WORKSPACE_ISOLATION:
    all outputs in ~/.frago/projects/<id>/
    => rules/WORKSPACE_RULES.md

SINGLE_CONTEXT:
    only one active run context at a time
</rules_critical>

<logging>
AUTO: navigate, click, screenshot (CDP commands)

MANUAL action-type:
    recipe_execution, data_processing, analysis, user_interaction, other

MANUAL execution-method:
    command, recipe, file, manual, analysis, tool
</logging>

<output_formats>
structured => *.json, *.csv
document => *.md
presentation => *.html (reveal.js)
text => *.txt
media => *.png (screenshots)

REQUIRED:
    outputs/result.* or outputs/report.* => MUST generate
    logs/execution.jsonl => auto

OPTIONAL:
    scripts/test_*.{py,js,sh}
    screenshots/*.png
    outputs/*.json

FORBIDDEN:
    files outside workspace
    unrelated summaries
    violate user's chosen output format

if Markdown or HTML:
    read ~/.claude/skills/frago-previewable-content/SKILL.md
    <info>
    HOW-TO:
    - Markdown: refer to Part 1, ensure Mermaid syntax and code blocks correct
    - reveal.js: refer to Part 2, use <section> structure and fragment animations
    </info>
</output_formats>

<completion>
DONE_WHEN:
    user's goal achieved (verifiable)
    result saved in outputs/
    final log: task_completed: true

STOP_WHEN:
    goal achieved
    failed (logged with insights)
    user stop
</completion>

<progress_template>
every 5 steps output:

    COMPLETED 5 steps:
    1. navigate to search (navigation/command)
    2. extract data (extraction/command) => key_factor: wait for load
    3. filter results (data_processing/file)
    4. analyze structure (analysis/analysis)
    5. save output (data_processing/file)

    INSIGHTS: 2 key_factor, 1 pitfall
    PROGRESS: 3/10 items processed
</progress_template>

<completion_summary>
    Task Complete!

    Project: <project-id>
    Duration: <time>

    Result:
    - <what was accomplished>

    Files:
    - outputs/<result-file>
    - screenshots/*.png

    Insights for Recipe:
    - <key learnings that could become a Recipe>

    Logs: ~/.frago/projects/<id>/logs/execution.jsonl
</completion_summary>
