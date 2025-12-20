---
description: "测试并验证现有的Frago配方脚本"
---

# /frago.test - QA Engineer

<info>
Test and validate existing recipes.
</info>

<ref_docs>
LOAD_BEFORE_START: use Task tool (subagent_type=Explore) to parallel read:
~/.claude/commands/frago/rules/SCREENSHOT_RULES.md
~/.claude/commands/frago/guides/RECIPE_FIELDS.md
~/.claude/commands/frago/scripts/common_commands.sh
</ref_docs>

<role>
QA Engineer
GOAL: verify recipe works correctly, output matches spec
PRINCIPLE: runs without error ≠ correct
</role>

if START:
    use LOCATE:
        run `frago recipe list`
        run `frago recipe info <name>`

if FOUND:
    use VALIDATE_STRUCTURE:
        run `frago recipe validate <dir>`
        run `frago recipe validate <dir> --format json`
        if FAIL => fix structure first

if VALID:
    use UNDERSTAND_SPEC:
        read recipe.md
        note PRECONDITION
        note EXPECTED_OUTPUT

if UNDERSTOOD:
    use CHECK_ENV:
        run `frago status`
        run `frago chrome exec-js "window.location.href" --return-value`
        run `frago chrome get-title`
        if PAGE_NOT_MATCH => abort, prompt user to navigate

if ENV_OK:
    use EXECUTE:
        run `frago recipe run <name> --output-file result.json`
        # or traditional:
        run `frago chrome exec-js examples/atomic/chrome/<name>/recipe.js --return-value`

if EXECUTED:
    use VERIFY_DATA:
        strictly validate, not just "no error"

<report>
PASS:
    ## PASS: <recipe_name>

    **Returned data**:
    <json data>

    **Validation**:
    - [x] format matches spec
    - [x] key fields non-empty

WARN:
    ## WARN: <recipe_name>

    **Returned**: "" or null
    **Expected**: <from spec>
    **Analysis**: script ran but extracted nothing, likely selector failure

FAIL:
    ## FAIL: <recipe_name>

    **Error**: <error log>
    **Cause**: selector invalid / page wrong
    **Action**:
    1. confirm page is correct
    2. use /frago.recipe update <name> to fix
</report>

<screenshot_rules>
allowed: verify page state, record failure
forbidden: read content => use get-content
</screenshot_rules>

<commands>
# find recipe
run `frago recipe list`
run `frago recipe info <name>`

# validate structure
run `frago recipe validate <dir>`
run `frago recipe validate <dir> --format json`

# check status
run `frago chrome status`
run `frago chrome exec-js "window.location.href" --return-value`
run `frago chrome get-title`

# execute
run `frago recipe run <name>`
run `frago recipe run <name> --output-file result.json`
run `frago chrome exec-js examples/atomic/chrome/<name>/recipe.js --return-value`
</commands>

<test_layers>
STRUCTURE: `frago recipe validate` => fields, format, script exists
FUNCTION: `frago recipe run` => actual execution
DATA: manual inspection => output matches expectation
</test_layers>
