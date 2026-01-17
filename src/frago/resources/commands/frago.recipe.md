---
description: "Create reusable browser operation recipe scripts (supports Atomic and Workflow Recipe)"
---

# /frago.recipe - Recipe Creator

<info>
Create reusable Recipes (Atomic or Workflow).
</info>

<ref_docs>
LOAD_BEFORE_START: use Task tool (subagent_type=Explore) to parallel read:
~/.claude/commands/frago/rules/SCREENSHOT_RULES.md
~/.claude/commands/frago/guides/SELECTOR_PRIORITY.md
~/.claude/commands/frago/guides/RECIPE_FIELDS.md
~/.claude/commands/frago/guides/INTERACTIVE_RECIPE_GUIDE.md (if user needs interactive UI)
~/.claude/commands/frago/scripts/recipe_workflow.sh
~/.claude/commands/frago/scripts/common_commands.sh
</ref_docs>

<role>
Recipe Creator
OUTPUT: Reusable Recipe (Atomic or Workflow)
</role>

<types>
Atomic:
    use: single operation, data extraction
    SUPPORTED DIRS (ONLY these two):
        ~/.frago/recipes/atomic/chrome/   => runtime: chrome-js
        ~/.frago/recipes/atomic/system/   => runtime: python / shell

Workflow:
    use: orchestrate multiple recipes
    runtime: python
    dir: ~/.frago/recipes/workflows/
    REQUIRED: flow field describing execution steps (see <flow_design>)

Interactive (special Workflow):
    use: user collaboration via web UI
    runtime: python
    dir: ~/.frago/recipes/workflows/<name>/
    structure:
        recipe.md (tags must include "interactive")
        recipe.py (launcher + viewer setup)
        assets/
            index.html
            app.js
            style.css
    SEE: ~/.claude/commands/frago/guides/INTERACTIVE_RECIPE_GUIDE.md
</types>

if START:
    use SKILL_SENSE:
        run `frago skill list | grep -E "keyword1|keyword2"`
        if MATCH:
            read skill for design patterns, best practices

    use CLARIFY:
        SITE: which website?
        TASK: what to accomplish?
        PRECONDITION: required state?

if CLARIFIED:
    use NAMING:
        format: <platform>_<verb>_<object>_<modifier>
        good: youtube_extract_video_transcript
        bad: youtube_transcript (ambiguous)

if EXPLORING:
    for each step:
        execute => wait => verify
        run `frago chrome click '[selector]'`
        run `frago chrome wait 0.5`
        run `frago chrome screenshot /tmp/step1.png`
        run `frago chrome exec-js "document.querySelector('.success') !== null" --return-value`
    KEY: every step must verify result

if EXPLORED:
    use DETERMINE_TYPE:
        single page, extraction => Atomic
        system op (file, clipboard) => Atomic
        calls multiple recipes => Workflow
        batch processing => Workflow
        user decisions needed mid-process => Interactive Workflow
        media annotation, creative review => Interactive Workflow

if READY:
    use GENERATE_FILES:
        Atomic (chrome):
            ~/.frago/recipes/atomic/chrome/<name>/
                recipe.md (metadata)
                recipe.js (script)

        Atomic (system):
            ~/.frago/recipes/atomic/system/<name>/
                recipe.md (metadata)
                recipe.py or recipe.sh (script)

        Workflow:
            ~/.frago/recipes/workflows/<name>/
                recipe.md (metadata)
                recipe.py (script)
                examples/ (optional)

        Interactive Workflow:
            ~/.frago/recipes/workflows/<name>/
                recipe.md (metadata, tags: [interactive])
                recipe.py (launcher: scan dir, setup viewer, open browser)
                assets/
                    index.html (entry point)
                    app.js (state, API calls, event handlers)
                    style.css

    use VALIDATE:
        run `frago recipe validate <dir>`
        run `frago recipe validate <dir> --format json`
        if FAIL => fix structure first, DO NOT proceed

if VALIDATED:
    use TEST (MANDATORY):
        1. CHECK_ENV:
            run `frago status`
            run `frago chrome exec-js "window.location.href" --return-value`
            run `frago chrome get-title`
            if PAGE_NOT_MATCH => prompt user to navigate

        2. EXECUTE:
            run `frago recipe run <name> --output-file /tmp/test_result.json`

        3. VERIFY_DATA:
            strictly validate output, not just "no error"
            check: format matches spec, key fields non-empty

        4. REPORT:
            PASS:
                ## PASS: <recipe_name>
                **Returned data**: <json>
                **Validation**:
                - [x] format matches spec
                - [x] key fields non-empty

            WARN:
                ## WARN: <recipe_name>
                **Returned**: "" or null
                **Expected**: <from spec>
                **Analysis**: script ran but extracted nothing, likely selector failure
                => FIX before completing

            FAIL:
                ## FAIL: <recipe_name>
                **Error**: <error log>
                **Cause**: selector invalid / page wrong
                => FIX before completing

        PRINCIPLE: runs without error ≠ correct
        Recipe creation is NOT complete until TEST passes

<env_vars>
if recipe needs env vars (API keys, secrets):
    1. declare in recipe.md frontmatter:
       ```
       # recipe.md
       ---
       env:
         API_KEY:
           required: true
           description: "API key for service X"
         TIMEOUT:
           default: "30"
       ---
       ```
    2. add actual values to ~/.frago/.env (auto-loaded by frago recipe run)
</env_vars>

<flow_design>
WORKFLOW recipes MUST include a flow field describing execution steps:

```yaml
flow:
  - step: 1
    action: "action_name"
    description: "What this step does"
    recipe: "dependent_recipe"  # optional, if calling another recipe
    inputs:
      - source: "params.input_name"
      - source: "step.1.output_name"
    outputs:
      - name: "output_name"
        type: "string"  # string, number, boolean, list, object
```

RULES:
  - step numbers must be sequential starting from 1
  - each step with recipe must reference a dependency
  - inputs can reference: params.<name>, step.<n>.<output>, env.<var>
  - outputs define data available to subsequent steps

SPECIAL STEPS:
  - if workflow calls agent (frago agent, Claude API), use action: "call_agent"
  - agent steps are dynamic at runtime, flow only marks "agent is called here"
  - example:
    ```yaml
    - step: 3
      action: "call_agent"
      description: "Use Claude agent to analyze data"
      inputs:
        - source: "step.2.data"
      outputs:
        - name: "analysis_result"
          type: "object"
    ```

VALIDATION:
  - `frago recipe validate` checks flow field exists and has valid structure
  - recipe references in flow must exist in dependencies list
</flow_design>

<forbidden>
❌ chmod +x on recipe scripts
❌ shebang lines in recipe.py/recipe.js
❌ direct execution: `uv run recipe.py`, `python recipe.py`, `node recipe.js`
❌ CLI env override: `frago recipe run <name> -e KEY=VALUE`
❌ hardcode secrets in recipe scripts

✅ ONLY USE: `frago recipe run <name> --params '{...}'`
</forbidden>

<output_requirements>
Recipe scripts MUST output detailed progress for Agent/Bash visibility:

✅ MUST output:
    step start/complete markers
    element counts, data counts
    error context (selector, URL, params)
    final result summary

❌ AVOID:
    silent execution (no output)
    JSON-only without progress
    vague errors (just "failed")

output pattern:
    [step1] finding target...
    [step1] ✓ found 15 items
    [step2] extracting...
    [step2] ✓ extracted 15 records
    [result] {"success": true, "count": 15, ...}
</output_requirements>

<commands>
/frago.recipe create "<desc>"           => create Atomic
/frago.recipe create workflow "<desc>"  => create Workflow
/frago.recipe update <name> "<reason>"  => update recipe
/frago.recipe list                      => list all
/frago.recipe validate <path>           => validate
</commands>

<template_atomic_js>
(async () => {
  console.log('[start] executing recipe...');

  function findElement(selectors, description) {
    for (const sel of selectors) {
      const elem = document.querySelector(sel.selector);
      if (elem) {
        console.log(`[found] ${description} (${sel.selector})`);
        return elem;
      }
    }
    console.error(`[error] cannot find ${description}, tried: ${selectors.map(s => s.selector).join(', ')}`);
    throw new Error(`Cannot find ${description}`);
  }

  async function waitForElement(selector, description, timeout = 5000) {
    console.log(`[wait] ${description}...`);
    const startTime = Date.now();
    while (Date.now() - startTime < timeout) {
      const elem = document.querySelector(selector);
      if (elem) {
        console.log(`[ok] ${description} appeared`);
        return elem;
      }
      await new Promise(r => setTimeout(r, 100));
    }
    console.error(`[error] timeout: ${description} (${timeout}ms)`);
    throw new Error(`Timeout: ${description}`);
  }

  const elem = findElement([
    { selector: '[aria-label="..."]', priority: 5 },
    { selector: '#id', priority: 4 },
    { selector: '.class', priority: 3 }
  ], 'element description');
  elem.click();
  console.log('[clicked] element');

  await waitForElement('.result', 'result appears');

  console.log('[done] recipe completed');
  return result;
})();
</template_atomic_js>

<template_workflow_py>
from frago.recipes import RecipeRunner, RecipeExecutionError
import json
import sys

def main():
    print('[start] executing workflow...', file=sys.stderr)
    runner = RecipeRunner()

    print('[step1] calling atomic_recipe_name...', file=sys.stderr)
    result = runner.run('atomic_recipe_name', params={...})
    if not result["success"]:
        print(f'[error] recipe failed: {result.get("error", "unknown")}', file=sys.stderr)
        raise RecipeExecutionError(...)
    print('[step1] ✓ done', file=sys.stderr)

    # progress to stderr, final result to stdout
    print('[done] workflow completed', file=sys.stderr)
    print(json.dumps(output))

if __name__ == "__main__":
    main()
</template_workflow_py>
