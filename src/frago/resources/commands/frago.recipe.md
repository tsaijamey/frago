---
description: "创建可复用的浏览器操作配方脚本（支持 Atomic 和 Workflow Recipe）"
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

    use VALIDATE:
        run `frago recipe validate <dir>`

<env_vars>
if recipe needs env vars (API keys, secrets):
    1. declare in recipe.md frontmatter:
       ```yaml
       env:
         API_KEY:
           required: true
           description: "API key for service X"
         TIMEOUT:
           default: "30"
       ```
    2. add actual values to ~/.frago/.env (auto-loaded by frago recipe run)
</env_vars>

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
