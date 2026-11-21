"""Regression tests for builtin hook rules."""

from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from pathlib import Path

import pytest

from frago.init.hook_binary import get_bundled_binary_path

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILTIN_RULES_PATH = REPO_ROOT / "src" / "frago" / "resources" / "hook" / "builtin-rules.json"
RULE_ID = "builtin-bash-git-discard-worktree-deny"
OPEN_WEB_RULE_ID = "builtin-bash-block-system-open-web"


def _load_rules_data() -> dict:
    return json.loads(BUILTIN_RULES_PATH.read_text(encoding="utf-8"))


def _get_rule(rule_id: str) -> dict:
    for rule in _load_rules_data()["rules"]:
        if rule.get("id") == rule_id:
            return rule
    raise KeyError(rule_id)


def _eval_bash_clause(clause: dict, command: str) -> bool:
    ctype = clause["type"]
    if ctype == "bash_regex":
        return re.search(clause["pattern"], command) is not None
    if ctype == "bash_contains":
        return clause["value"] in command
    if ctype == "bash_contains_all":
        return all(v in command for v in clause["values"])
    if ctype == "any_of":
        return any(_eval_bash_clause(c, command) for c in clause["clauses"])
    if ctype == "all_of":
        return all(_eval_bash_clause(c, command) for c in clause["clauses"])
    if ctype == "not":
        return not _eval_bash_clause(clause["clause"], command)
    raise ValueError(f"Unsupported clause type in Python evaluator: {ctype}")


def _match_via_frago_core(tmp_path: Path, commands: list[str]) -> list[list[str]]:
    home_dir = tmp_path / "home"
    hook_dir = home_dir / ".frago" / "hook"
    hook_dir.mkdir(parents=True, exist_ok=True)
    (hook_dir / "builtin-rules.json").write_text(
        BUILTIN_RULES_PATH.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    binary = get_bundled_binary_path()
    payload = "\n".join(
        json.dumps(
            {
                "session_id": "unit-test",
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": cmd},
            },
            ensure_ascii=False,
        )
        for cmd in commands
    )
    env = os.environ.copy()
    env["HOME"] = str(home_dir)
    proc = subprocess.run(
        [str(binary), "--match-only"],
        input=payload + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=True,
    )
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    assert len(lines) == len(commands)
    return [json.loads(line) for line in lines]


def _collect_bash_regex_patterns(clause: dict) -> list[str]:
    ctype = clause["type"]
    if ctype == "bash_regex":
        return [clause["pattern"]]
    if ctype in ("any_of", "all_of"):
        patterns: list[str] = []
        for child in clause["clauses"]:
            patterns.extend(_collect_bash_regex_patterns(child))
        return patterns
    if ctype == "not":
        return _collect_bash_regex_patterns(clause["clause"])
    return []


def test_builtin_rules_json_valid_and_preserves_other_rules() -> None:
    data = _load_rules_data()
    assert data["version"] == 1
    rules_by_id = {r["id"]: r for r in data["rules"]}
    assert RULE_ID in rules_by_id
    assert OPEN_WEB_RULE_ID in rules_by_id
    assert rules_by_id[OPEN_WEB_RULE_ID]["event"] == "PreToolUse"
    assert rules_by_id[OPEN_WEB_RULE_ID]["action"]["type"] == "deny_tool_call"
    assert "frago browser" in rules_by_id[OPEN_WEB_RULE_ID]["action"]["reason"]
    assert "builtin-session-start-irrelevant-hook-silence" in rules_by_id


def test_session_start_injects_irrelevant_hook_silence_rule_via_frago_core(tmp_path: Path) -> None:
    """SessionStart on an isolated HOME must deliver the irrelevant-hook silence
    rule in hookSpecificOutput.additionalContext for main agents across kernels."""
    home_dir = tmp_path / "home"
    hook_dir = home_dir / ".frago" / "hook"
    hook_dir.mkdir(parents=True, exist_ok=True)
    (hook_dir / "builtin-rules.json").write_text(
        BUILTIN_RULES_PATH.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    temp_dir = tmp_path / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    binary = get_bundled_binary_path()
    payload = json.dumps(
        {
            "session_id": f"unit-test-session-start-{uuid.uuid4().hex}",
            "hook_event_name": "SessionStart",
            "source": "startup",
        },
        ensure_ascii=False,
    )
    env = os.environ.copy()
    env["HOME"] = str(home_dir)
    env["TMPDIR"] = str(temp_dir)
    env["TEMP"] = str(temp_dir)
    env["TMP"] = str(temp_dir)
    env.pop("FRAGO_PA", None)
    env.pop("FRAGO_CONV_KEY", None)
    env.pop("FRAGO_AGENT_ROLE", None)
    proc = subprocess.run(
        [str(binary), "--engine"],
        input=payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=True,
    )
    out = json.loads(proc.stdout)
    ctx = out.get("hookSpecificOutput", {}).get("additionalContext", "")
    assert "无关钩子提示静默忽略" in ctx
    assert "additionalContext" in ctx
    assert "备查知识" in ctx
    assert "静默忽略" in ctx
    assert "禁止在回复里声明或解释该提示无关" in ctx


def test_discard_worktree_deny_all_bash_regex_clauses_share_identical_prefix() -> None:
    rule = _get_rule(RULE_ID)
    patterns = _collect_bash_regex_patterns(rule["match"])
    assert len(patterns) == 9
    prefixes: list[str] = []
    for pat in patterns:
        m = re.search(r"(?:checkout|reset|clean|stash|restore)\\b", pat)
        assert m is not None, f"Subcommand boundary missing in pattern: {pat}"
        prefixes.append(pat[: m.start()])
    assert len(set(prefixes)) == 1, "All 9 bash_regex clauses must share an identical command-start prefix"


ALLOWED_COMMANDS = [
    pytest.param(
        "git commit -F - <<'EOF'\n"
        "fix(hook): narrow builtin-bash-git-discard-worktree-deny\n"
        "\n"
        "reset --hard should not be matched across lines.\n"
        "EOF",
        id="2026-09-18-heredoc-bash-git-discard-then-reset-hard",
    ),
    pytest.param(
        "git commit -F - <<'EOF'\n"
        "docs: mention git checkout -- . and git reset --hard in explanation\n"
        "  indented git reset --hard example\n"
        "EOF",
        id="heredoc-inline-or-indented-reference",
    ),
    pytest.param(
        'git commit -m "narrow git-discard-worktree-deny for git reset --hard"',
        id="commit-message-mentions-git-reset-hard",
    ),
    pytest.param(
        'frago todo log 20260919-narrow-git-discard-worktree-deny "实测 git reset --hard 误拦"',
        id="todo-log-quotes-git-reset-hard",
    ),
    pytest.param(
        'frago todo log 20260919-narrow-git-discard-worktree-deny "实测 git checkout -- . 与 git clean -fd 误拦"',
        id="todo-log-quotes-checkout-and-clean",
    ),
    pytest.param(
        'frago todo log 20260919-narrow-git-discard-worktree-deny "实测 eval git reset --hard 与 then 误拦"',
        id="todo-log-quotes-eval-and-then",
    ),
    pytest.param("git checkout main", id="checkout-branch"),
    pytest.param("git checkout -b feat/narrow-rule", id="checkout-new-branch"),
    pytest.param("git restore --staged src/foo.py", id="restore-staged-only-long"),
    pytest.param("git restore -S src/foo.py", id="restore-staged-only-short"),
    pytest.param("git stash", id="stash-default"),
    pytest.param('git stash push -m "backup before git reset --hard"', id="stash-push-msg"),
    pytest.param("git stash pop", id="stash-pop"),
    pytest.param("git reset --soft HEAD~1", id="reset-soft"),
    pytest.param("git reset HEAD src/foo.py", id="reset-mixed-path"),
    pytest.param("git clean -n", id="clean-dry-run"),
    pytest.param("git clean -nd", id="clean-dry-run-dirs"),
    pytest.param('git log -n 5 --grep="reset --hard"', id="git-log-grep"),
    pytest.param('echo "git reset --hard"', id="echo-quoted-reset-hard"),
    pytest.param('git commit -m "fix" && echo "git checkout -- ."', id="compound-echo-after-commit"),
    pytest.param('git commit -m "fix" && echo "check if git reset --hard"', id="compound-echo-if-phrase"),
]

DENIED_COMMANDS = [
    pytest.param("git checkout -- foo.py", id="checkout-double-dash-file"),
    pytest.param("git checkout .", id="checkout-dot"),
    pytest.param("git checkout -f", id="checkout-short-force"),
    pytest.param("git checkout --force main", id="checkout-long-force"),
    pytest.param("git reset --hard", id="reset-hard"),
    pytest.param("git reset --hard HEAD~1", id="reset-hard-head"),
    pytest.param("git -C /tmp/repo clean -fd", id="clean-dash-c-fd"),
    pytest.param("git clean -fdx", id="clean-fdx"),
    pytest.param("cd /tmp/repo && git stash drop", id="cd-and-stash-drop"),
    pytest.param("git stash clear", id="stash-clear"),
    pytest.param("git stash drop stash@{0}", id="stash-drop-ref"),
    pytest.param("sudo git reset --hard", id="sudo-reset-hard"),
    pytest.param("env GIT_DIR=.git git checkout -- .", id="env-var-checkout-dot"),
    pytest.param("GIT_DIR=.git git checkout -- .", id="inline-env-checkout-dot"),
    pytest.param("/usr/bin/git reset --hard", id="abs-bin-git-reset-hard"),
    pytest.param("git restore --staged --worktree .", id="restore-staged-and-worktree"),
    pytest.param("git restore .", id="restore-worktree-default"),
    pytest.param("git restore -SW .", id="restore-combined-sw"),
    pytest.param("echo ok\ngit reset --hard", id="multiline-second-line-exec"),
    pytest.param("echo ok\n  git checkout -- foo.py", id="multiline-indented-second-line-exec"),
    pytest.param('bash -c "git reset --hard"', id="bash-c-double-quoted"),
    pytest.param("sh -c 'git checkout -- .'", id="sh-c-single-quoted"),
    pytest.param('bash -o errexit -c "git reset --hard"', id="bash-option-value-before-c"),
    pytest.param('bash -c -- "git reset --hard"', id="bash-c-double-dash-terminator"),
    pytest.param('bash -o pipefail -c -- "sudo git reset --hard"', id="bash-option-double-dash-sudo"),
    pytest.param('sudo bash -c "git reset --hard"', id="sudo-bash-c"),
    pytest.param('eval "git clean -fd"', id="eval-double-quoted"),
    pytest.param("eval git reset --hard", id="eval-unquoted"),
    pytest.param('eval -- "git reset --hard"', id="eval-double-dash-quoted"),
    pytest.param("(git reset --hard)", id="subshell-reset-hard"),
    pytest.param("true; git checkout .", id="semicolon-checkout-dot"),
    pytest.param("false || git reset --hard", id="or-reset-hard"),
    pytest.param("if true; then git reset --hard; fi", id="shell-if-then-reset-hard"),
    pytest.param("for f in a; do git checkout -- $f; done", id="shell-for-do-checkout"),
    pytest.param("if false; then echo ok; else git reset --hard; fi", id="shell-else-reset-hard"),
    pytest.param("if false; then echo ok; elif true; then git checkout .; fi", id="shell-elif-then-checkout"),
    pytest.param("! git reset --hard", id="shell-logical-not-reset-hard"),
    pytest.param("echo . | xargs git checkout --", id="pipe-xargs-checkout"),
    pytest.param("printf 'a\\n' | xargs -I{} git checkout -- {}", id="pipe-xargs-replace-braces"),
    pytest.param("printf 'a\\n' | xargs -I {} git checkout -- {}", id="pipe-xargs-replace-space-braces"),
    pytest.param("echo a | xargs --max-args=1 git checkout --", id="pipe-xargs-long-option-eq"),
    pytest.param("find . -exec git checkout -- {} +", id="find-exec-checkout"),
]


@pytest.mark.parametrize("command", ALLOWED_COMMANDS)
def test_discard_worktree_deny_allows_safe_and_quoted_commands(tmp_path: Path, command: str) -> None:
    rule = _get_rule(RULE_ID)
    assert not _eval_bash_clause(rule["match"], command), f"Python evaluator unexpectedly matched: {command!r}"
    matched = _match_via_frago_core(tmp_path, [command])[0]
    assert RULE_ID not in matched, f"frago-core unexpectedly matched {RULE_ID}: {command!r}"


@pytest.mark.parametrize("command", DENIED_COMMANDS)
def test_discard_worktree_deny_blocks_real_discard_commands(tmp_path: Path, command: str) -> None:
    rule = _get_rule(RULE_ID)
    assert _eval_bash_clause(rule["match"], command), f"Python evaluator missed real discard command: {command!r}"
    matched = _match_via_frago_core(tmp_path, [command])[0]
    assert RULE_ID in matched, f"frago-core missed {RULE_ID} on: {command!r}"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Regex-only rule layer cannot distinguish column-0 heredoc body lines from real multiline "
        "scripts without engine-level heredoc stripping in frago-core"
    ),
)
@pytest.mark.parametrize(
    "command",
    [
        "git commit -F - <<'EOF'\nfix: example\ngit reset --hard\nEOF",
        "git commit -F - <<'EOF'\nfix: example\ngit checkout -- .\nEOF",
    ],
)
def test_heredoc_column_zero_line_requires_engine_heredoc_stripping(
    tmp_path: Path, command: str
) -> None:
    matched = _match_via_frago_core(tmp_path, [command])[0]
    assert RULE_ID not in matched


def _run_pre_tool_use_via_frago_core_engine(
    tmp_path: Path,
    command: str,
    *,
    agent_role: str | None = None,
) -> dict:
    home_dir = tmp_path / "home"
    hook_dir = home_dir / ".frago" / "hook"
    hook_dir.mkdir(parents=True, exist_ok=True)
    (hook_dir / "builtin-rules.json").write_text(
        BUILTIN_RULES_PATH.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    temp_dir = tmp_path / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    binary = get_bundled_binary_path()
    payload = json.dumps(
        {
            "session_id": f"unit-test-open-web-{uuid.uuid4().hex}",
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
        },
        ensure_ascii=False,
    )
    env = os.environ.copy()
    env["HOME"] = str(home_dir)
    env["TMPDIR"] = str(temp_dir)
    env["TEMP"] = str(temp_dir)
    env["TMP"] = str(temp_dir)
    env.pop("FRAGO_PA", None)
    env.pop("FRAGO_CONV_KEY", None)
    if agent_role is None:
        env.pop("FRAGO_AGENT_ROLE", None)
    else:
        env["FRAGO_AGENT_ROLE"] = agent_role

    proc = subprocess.run(
        [str(binary), "--engine"],
        input=payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=True,
    )
    return json.loads(proc.stdout)


OPEN_WEB_DENIED_COMMANDS = [
    pytest.param("open http://127.0.0.1:8093/", id="open-http-loopback"),
    pytest.param('open -a "Google Chrome" https://example.com', id="open-dash-a-https"),
    pytest.param("cd x && open ./dist/index.html", id="and-open-local-html"),
    pytest.param("open file:///tmp/a.html", id="open-file-url"),
    pytest.param("xdg-open http://localhost:3000", id="xdg-open-http-localhost"),
    pytest.param("xdg-open ./preview.htm", id="xdg-open-local-htm"),
    pytest.param("if true; then open https://example.com; fi", id="if-then-open-https"),
    pytest.param('open -g "http://localhost:5173"', id="open-dash-g-quoted-http"),
    pytest.param('open "/tmp/a.html"', id="open-quoted-abs-html"),
    pytest.param("open '/tmp/my page.html?x=1#y'", id="open-quoted-space-query-hash"),
    pytest.param("open ./dist/index.html?foo=1#bar", id="open-local-html-query-hash"),
    pytest.param("open -b com.google.Chrome https://example.com", id="open-dash-b-bundle"),
    pytest.param("open -n -a Safari ./index.html", id="open-dash-n-a-html"),
    pytest.param("open -u https://example.com", id="open-dash-u-url"),
    pytest.param("sudo xdg-open https://example.com", id="sudo-xdg-open"),
    pytest.param("env DISPLAY=:0 xdg-open http://localhost:3000", id="env-display-xdg-open"),
    pytest.param("DISPLAY=:0 open https://example.com", id="inline-env-open"),
    pytest.param('bash -c "open https://example.com"', id="bash-c-open-https"),
    pytest.param("sh -c 'open ./dist/index.html'", id="sh-c-open-html"),
    pytest.param("(open https://example.com)", id="subshell-open-https"),
    pytest.param("true; open https://example.com", id="semicolon-open-https"),
    pytest.param("false || xdg-open http://localhost:3000", id="or-xdg-open"),
    pytest.param("/usr/bin/open https://example.com", id="abs-bin-open"),
    pytest.param("/usr/bin/xdg-open ./index.htm", id="abs-bin-xdg-open"),
    pytest.param("open -- ./dist/index.html", id="open-double-dash-html"),
    pytest.param("echo ok\nopen https://example.com", id="multiline-second-line-open"),
    pytest.param("open ./foo.txt ./index.html", id="open-multiple-args-with-html"),
    pytest.param('open "https://example.com/?a=1&b=2"', id="open-quoted-https-ampersand"),
]

OPEN_WEB_ALLOWED_COMMANDS = [
    pytest.param("open .", id="open-finder-dot"),
    pytest.param("open ./doc.pdf", id="open-doc-pdf"),
    pytest.param("open ./report.pdf", id="open-report-pdf"),
    pytest.param("open ./photo.png", id="open-photo-png"),
    pytest.param("open -a Finder /tmp", id="open-dash-a-finder"),
    pytest.param("python3 -c \"open('a.html')\"", id="python3-open-html"),
    pytest.param("python -c \"open('index.html')\"", id="python-open-index-html"),
    pytest.param("python3 -c 'import os; open(\"a.html\")'", id="python3-semicolon-open"),
    pytest.param("python3 -c 'import os; open (\"a.html\")'", id="python3-semicolon-space-open"),
    pytest.param('git commit -m "open http://127.0.0.1:8093"', id="git-commit-msg-open-http"),
    pytest.param('git commit -m "open https://example.com"', id="git-commit-msg-open-https"),
    pytest.param('frago todo log id "xdg-open http://localhost:3000"', id="todo-log-xdg-open"),
    pytest.param('frago todo log id "open http://127.0.0.1:8093"', id="todo-log-open"),
    pytest.param("frago browser open http://127.0.0.1:8093", id="frago-browser-open"),
    pytest.param("frago browser navigate http://127.0.0.1:8093 --group test", id="frago-browser-navigate"),
    pytest.param("frago recipe open my_recipe", id="frago-recipe-open"),
    pytest.param('echo "open https://example.com"', id="echo-open-https"),
    pytest.param('grep -rn "xdg-open http://localhost:3000" src/', id="grep-xdg-open"),
    pytest.param("open ./index.html.bak", id="open-html-bak"),
    pytest.param("open ./html-report.pdf", id="open-html-prefix-pdf"),
    pytest.param("open --env FOO=https://example.com ./report.pdf", id="open-env-url-pdf"),
    pytest.param("openssl s_client -connect example.com:443", id="openssl-command"),
    pytest.param("cat ./index.html | head -n 20", id="cat-html-head"),
]


@pytest.mark.parametrize("command", OPEN_WEB_ALLOWED_COMMANDS)
def test_block_system_open_web_allows_safe_and_non_web_commands(
    tmp_path: Path, command: str
) -> None:
    rule = _get_rule(OPEN_WEB_RULE_ID)
    assert not _eval_bash_clause(rule["match"], command), (
        f"Python evaluator unexpectedly matched: {command!r}"
    )
    matched = _match_via_frago_core(tmp_path, [command])[0]
    assert OPEN_WEB_RULE_ID not in matched, (
        f"frago-core unexpectedly matched {OPEN_WEB_RULE_ID}: {command!r}"
    )


@pytest.mark.parametrize("command", OPEN_WEB_DENIED_COMMANDS)
def test_block_system_open_web_blocks_web_and_local_html_commands(
    tmp_path: Path, command: str
) -> None:
    rule = _get_rule(OPEN_WEB_RULE_ID)
    assert _eval_bash_clause(rule["match"], command), (
        f"Python evaluator missed system open web command: {command!r}"
    )
    matched = _match_via_frago_core(tmp_path, [command])[0]
    assert OPEN_WEB_RULE_ID in matched, (
        f"frago-core missed {OPEN_WEB_RULE_ID} on: {command!r}"
    )


@pytest.mark.parametrize(
    ("command", "agent_role"),
    [
        pytest.param("open http://127.0.0.1:8093/", None, id="main-open-http"),
        pytest.param('open -a "Google Chrome" https://example.com', "worker", id="worker-open-chrome"),
        pytest.param("cd x && open ./dist/index.html", "worker", id="worker-open-html"),
        pytest.param("open file:///tmp/a.html", "worker", id="worker-open-file-url"),
        pytest.param("xdg-open http://localhost:3000", "worker", id="worker-xdg-open-http"),
        pytest.param("xdg-open ./preview.htm", "worker", id="worker-xdg-open-htm"),
        pytest.param("if true; then open https://example.com; fi", "worker", id="worker-if-then-open"),
        pytest.param('open -g "http://localhost:5173"', "worker", id="worker-open-g"),
    ],
)
def test_block_system_open_web_engine_denies_and_redirects_to_frago_browser(
    tmp_path: Path, command: str, agent_role: str | None
) -> None:
    out = _run_pre_tool_use_via_frago_core_engine(
        tmp_path, command, agent_role=agent_role
    )
    hook_out = out.get("hookSpecificOutput", {})
    assert hook_out.get("permissionDecision") == "deny", (
        f"Expected deny for {command!r}, got {out!r}"
    )
    reason = hook_out.get("permissionDecisionReason", "")
    assert "frago browser" in reason


@pytest.mark.parametrize(
    "command",
    [
        pytest.param("open .", id="engine-allow-open-dot"),
        pytest.param("open ./doc.pdf", id="engine-allow-open-pdf"),
        pytest.param("open -a Finder /tmp", id="engine-allow-open-finder"),
        pytest.param("python3 -c \"open('a.html')\"", id="engine-allow-python-open"),
        pytest.param('git commit -m "open http://127.0.0.1:8093"', id="engine-allow-git-commit"),
        pytest.param('frago todo log id "xdg-open http://localhost:3000"', id="engine-allow-todo-log"),
        pytest.param("frago browser open http://127.0.0.1:8093", id="engine-allow-frago-browser-open"),
    ],
)
def test_block_system_open_web_engine_allows_non_web_commands(
    tmp_path: Path, command: str
) -> None:
    out = _run_pre_tool_use_via_frago_core_engine(
        tmp_path, command, agent_role="worker"
    )
    hook_out = out.get("hookSpecificOutput", {})
    assert hook_out.get("permissionDecision") != "deny", (
        f"Unexpected deny for {command!r}: {out!r}"
    )
