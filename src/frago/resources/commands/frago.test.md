---
description: "Test and validate existing frago recipe scripts"
---

# /frago.test - QA Engineer

<info>
Test and validate existing recipes.
NOTE: Test is also MANDATORY step in /frago.recipe creation flow.
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
        run `frago skill list | grep -E "keyword"`
        run `frago recipe list`
        run `frago recipe info <name>`
        if SKILL_MATCH:
            read skill for testing guidance

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
</commands>

<test_layers>
STRUCTURE: `frago recipe validate` => fields, format, script exists, flow valid (workflow)
FUNCTION: `frago recipe run` => actual execution
DATA: manual inspection => output matches expectation
FLOW: verify flow steps match code logic (workflow only)
</test_layers>

<flow_verification>
if WORKFLOW:
    use VERIFY_FLOW:
        1. read recipe.md flow field
        2. read recipe.py code
        3. verify step count matches major code blocks
        4. verify recipe calls in code match flow[].recipe entries
        5. verify data flow makes sense (inputs/outputs chain)

    REPORT_FLOW:
        - [x] flow steps match code structure
        - [x] all dependencies appear in flow
        - [x] input/output chain is logical
</flow_verification>
