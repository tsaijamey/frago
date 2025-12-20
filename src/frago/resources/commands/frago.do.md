---
description: "执行一次性的复杂任务（使用完整的frago工具集）"
---

# /frago.do - Task Executor

<info>
One-time task execution, focused on completing user's specific goals.
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
</ref_docs>

<role>
Task Executor
GOAL: complete user's specific task
OUTPUT: Result + Metadata (.metadata.json)
</role>

<faith_check>
REJECT: pretrained knowledge (except natural science, core tech)
TRUST: browser-collected, user-provided
FALLBACK: WebSearch fails => browser google.com / bing.com
BELIEVE_ONLY: natural science, core tech, human consensus, self-collected info
</faith_check>

if START:
    use ENV_SENSE (via Task tool, subagent_type=Explore):
        run `frago --help`
        run `frago recipe list | grep -E "keyword1|keyword2"`
        run `frago run list | grep -E "keyword1|keyword2"`
        <info>
        WHY:
        - discover reusable recipes (avoid re-exploring)
        - check existing results (avoid duplicate work)
        - assess task feasibility
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
            examples: "upwork-python-job-apply", "youtube-batch-download-subtitles"
        run `frago run init "<desc>"`
        run `frago run set-context <id>`

if EXECUTING:
    PRIORITY: Recipe > frago > system > Claude tools
    run `frago recipe list | grep keyword`
    run `frago recipe run <name> --params '{}' --output-file result.json`

if DONE:
    use SAVE:
        run `frago run screenshot "result"`
        run `frago run log --step "done" --status success --action-type analysis --execution-method analysis --data '{"task_completed": true}'`

    use METADATA_UPDATE:
        run `cat ~/.frago/projects/<id>/.metadata.json`
        update .metadata.json with:
            purpose: brief task goal
            method: "1. step1; 2. step2; ..."
            insights: [{ type: "key_factor|lesson|pitfall", summary: "..." }]
            reuse_guidance: how to reuse for similar tasks
        <info>
        WHY: agent can learn from `frago run info <id>` for future similar tasks
        </info>

    use RELEASE:
        run `frago run release`

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
    all outputs in projects/<id>/
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

if Markdown or HTML:
    read ~/.claude/skills/frago-previewable-content/SKILL.md
    <info>
    HOW-TO:
    - Markdown: refer to Part 1, ensure Mermaid syntax and code blocks correct
    - reveal.js: refer to Part 2, use <section> structure and fragment animations
    </info>
</output_formats>

<forbidden>
- violate user's chosen output format
- create documents without confirmation
- output files outside workspace
</forbidden>

<completion>
DONE_WHEN:
    goal achieved (verifiable)
    result in outputs/
    final log: task_completed: true

STOP_WHEN:
    goal achieved
    failed (logged)
    user stop
</completion>

<progress_template>
every 5 steps output:

    COMPLETED 5 steps:
    1. navigate to search (navigation/command)
    2. search jobs (interaction/command)
    3. extract list (extraction/command)
    4. filter results (data_processing/analysis)
    5. apply job 1 (user_interaction/recipe)

    PROGRESS: 1/5 jobs applied
    OUTPUT: outputs/applied_jobs.json
</progress_template>

<completion_summary>
    Task Complete!

    Project: upwork-python-job-apply
    Duration: 30min

    Result:
    - applied 5 Python jobs

    Files:
    - outputs/applied_jobs.json
    - screenshots/*.png

    Logs: projects/<id>/logs/execution.jsonl
</completion_summary>
