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
OPEN_WEB_MAIN_RULE_ID = "builtin-bash-redirect-system-open-web-main"


def _load_rules_data() -> dict:
    return json.loads(BUILTIN_RULES_PATH.read_text(encoding="utf-8"))


def _get_rule(rule_id: str) -> dict:
    for rule in _load_rules_data()["rules"]:
        if rule.get("id") == rule_id:
            return rule
    raise KeyError(rule_id)


def _eval_bash_clause(clause: dict, command: str, env: dict[str, str] | None = None) -> bool:
    ctype = clause["type"]
    if ctype == "bash_regex":
        return re.search(clause["pattern"], command) is not None
    if ctype == "bash_contains":
        return clause["value"] in command
    if ctype == "bash_contains_all":
        return all(v in command for v in clause["values"])
    if ctype == "env_exists":
        return clause["name"] in (env or {})
    if ctype == "env_ne":
        return (env or {}).get(clause["name"]) != clause["value"]
    if ctype == "any_of":
        return any(_eval_bash_clause(c, command, env) for c in clause["clauses"])
    if ctype == "all_of":
        return all(_eval_bash_clause(c, command, env) for c in clause["clauses"])
    if ctype == "not":
        return not _eval_bash_clause(clause["clause"], command, env)
    raise ValueError(f"Unsupported clause type in Python evaluator: {ctype}")


def _match_via_frago_core(
    tmp_path: Path,
    commands: list[str],
    *,
    agent_role: str | None = None,
) -> list[list[str]]:
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
    payload = "\n".join(
        json.dumps(
            {
                "session_id": f"unit-test-{uuid.uuid4().hex}",
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
    assert OPEN_WEB_MAIN_RULE_ID in rules_by_id
    assert rules_by_id[OPEN_WEB_RULE_ID]["event"] == "PreToolUse"
    assert rules_by_id[OPEN_WEB_RULE_ID]["action"]["type"] == "deny_tool_call"
    assert "frago browser" in rules_by_id[OPEN_WEB_RULE_ID]["action"]["reason"]
    assert rules_by_id[OPEN_WEB_MAIN_RULE_ID]["event"] == "PreToolUse"
    assert rules_by_id[OPEN_WEB_MAIN_RULE_ID]["action"]["type"] == "inject_literal"
    assert "frago browser" in rules_by_id[OPEN_WEB_MAIN_RULE_ID]["action"]["text"]
    assert _collect_bash_regex_patterns(rules_by_id[OPEN_WEB_RULE_ID]["match"]) == _collect_bash_regex_patterns(
        rules_by_id[OPEN_WEB_MAIN_RULE_ID]["match"]
    ), "Worker hard-deny and main soft-guidance must share identical target and -R/-t exclusion regexes"
    assert "builtin-session-start-irrelevant-hook-silence" in rules_by_id


def _run_session_start_via_frago_core(
    tmp_path: Path,
    *,
    harness: str | None = None,
    env_overrides: dict[str, str | None] | None = None,
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
    for k, v in (env_overrides or {}).items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v

    cmd = [str(binary), "--engine"]
    if harness:
        cmd.extend(["--harness", harness])
    proc = subprocess.run(
        cmd,
        input=payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=True,
    )
    return json.loads(proc.stdout)


def test_session_start_injects_irrelevant_hook_silence_rule_via_frago_core(tmp_path: Path) -> None:
    """SessionStart on an isolated HOME must deliver the irrelevant-hook silence
    rule (with [MUST] exception guardrail) in hookSpecificOutput.additionalContext."""
    out = _run_session_start_via_frago_core(tmp_path)
    ctx = out.get("hookSpecificOutput", {}).get("additionalContext", "")
    expected_rule = (
        "【无关钩子提示静默忽略 MUST】按规则触发自动推送的补充提示（additionalContext）"
        "若属备查知识且与当前任务无关，直接静默忽略，禁止在回复里声明或解释该提示无关"
        "（明确标注 [MUST] 的安全、交付与格式约束除外）。"
    )
    assert expected_rule in ctx


@pytest.mark.parametrize(
    ("case_name", "env_overrides"),
    [
        ("interactive", None),
        ("managed_worker", {"FRAGO_CONV_KEY": "conv-codex-1", "FRAGO_AGENT_ROLE": "worker"}),
    ],
)
def test_session_start_codex_zero_prior_under_5400_bytes(
    tmp_path: Path, case_name: str, env_overrides: dict[str, str | None] | None
) -> None:
    """Zero-prior Codex SessionStart total additionalContext must remain well under 5,400B."""
    out = _run_session_start_via_frago_core(
        tmp_path / case_name,
        harness="codex",
        env_overrides=env_overrides,
    )
    ctx = out.get("hookSpecificOutput", {}).get("additionalContext", "")
    assert "明确标注 [MUST] 的安全、交付与格式约束除外" in ctx
    assert "完整手册跑" not in ctx
    assert len(ctx.encode("utf-8")) < 5400


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
    pytest.param("open file:///tmp/a.htm?x=1#y", id="open-file-htm-query-hash"),
    pytest.param('open "file:///tmp/my page.html?x=1#y"', id="open-quoted-file-html"),
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
    pytest.param("open file:///tmp/test.pdf", id="open-file-pdf"),
    pytest.param("open file:///tmp/photo.png", id="open-file-png"),
    pytest.param('open "file:///tmp/my doc.pdf?v=1"', id="open-quoted-file-pdf"),
    pytest.param("open file:///tmp/a.html.bak", id="open-file-html-bak"),
    pytest.param("open -R ./dist/index.html", id="open-dash-R-html"),
    pytest.param("open -t ./dist/index.html", id="open-dash-t-html"),
    pytest.param("open -Rt ./dist/index.html", id="open-combined-Rt-html"),
    pytest.param("open -gR ./dist/index.html", id="open-combined-gR-html"),
    pytest.param("open -g -R ./dist/index.html", id="open-dash-g-dash-R-html"),
    pytest.param("open -R file:///tmp/a.html", id="open-dash-R-file-html"),
    pytest.param('open -t "file:///tmp/a.html"', id="open-dash-t-file-html"),
    pytest.param("sudo open -R ./dist/index.html", id="sudo-open-dash-R-html"),
    pytest.param('bash -c "open -R ./dist/index.html"', id="bash-c-open-dash-R-html"),
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
    worker_rule = _get_rule(OPEN_WEB_RULE_ID)
    main_rule = _get_rule(OPEN_WEB_MAIN_RULE_ID)
    assert not _eval_bash_clause(worker_rule["match"], command, {"FRAGO_AGENT_ROLE": "worker"}), (
        f"Python evaluator unexpectedly matched worker deny rule: {command!r}"
    )
    assert not _eval_bash_clause(main_rule["match"], command, {}), (
        f"Python evaluator unexpectedly matched main guidance rule: {command!r}"
    )
    matched_worker = _match_via_frago_core(tmp_path / "worker", [command], agent_role="worker")[0]
    assert OPEN_WEB_RULE_ID not in matched_worker
    assert OPEN_WEB_MAIN_RULE_ID not in matched_worker

    matched_main = _match_via_frago_core(tmp_path / "main", [command], agent_role=None)[0]
    assert OPEN_WEB_RULE_ID not in matched_main
    assert OPEN_WEB_MAIN_RULE_ID not in matched_main


@pytest.mark.parametrize("command", OPEN_WEB_DENIED_COMMANDS)
def test_block_system_open_web_blocks_only_worker_and_guides_main_and_employee(
    tmp_path: Path, command: str
) -> None:
    worker_rule = _get_rule(OPEN_WEB_RULE_ID)
    main_rule = _get_rule(OPEN_WEB_MAIN_RULE_ID)

    assert _eval_bash_clause(worker_rule["match"], command, {"FRAGO_AGENT_ROLE": "worker"})
    assert not _eval_bash_clause(main_rule["match"], command, {"FRAGO_AGENT_ROLE": "worker"})
    assert not _eval_bash_clause(worker_rule["match"], command, {})
    assert _eval_bash_clause(main_rule["match"], command, {})
    assert not _eval_bash_clause(worker_rule["match"], command, {"FRAGO_AGENT_ROLE": "employee"})
    assert _eval_bash_clause(main_rule["match"], command, {"FRAGO_AGENT_ROLE": "employee"})

    matched_worker = _match_via_frago_core(tmp_path / "worker", [command], agent_role="worker")[0]
    assert OPEN_WEB_RULE_ID in matched_worker
    assert OPEN_WEB_MAIN_RULE_ID not in matched_worker

    matched_main = _match_via_frago_core(tmp_path / "main", [command], agent_role=None)[0]
    assert OPEN_WEB_RULE_ID not in matched_main
    assert OPEN_WEB_MAIN_RULE_ID in matched_main

    matched_employee = _match_via_frago_core(tmp_path / "employee", [command], agent_role="employee")[0]
    assert OPEN_WEB_RULE_ID not in matched_employee
    assert OPEN_WEB_MAIN_RULE_ID in matched_employee


@pytest.mark.parametrize(
    "command",
    [
        pytest.param("open http://127.0.0.1:8093/", id="worker-open-http"),
        pytest.param('open -a "Google Chrome" https://example.com', id="worker-open-chrome"),
        pytest.param("cd x && open ./dist/index.html", id="worker-open-html"),
        pytest.param("open file:///tmp/a.html", id="worker-open-file-url"),
        pytest.param("xdg-open http://localhost:3000", id="worker-xdg-open-http"),
        pytest.param("xdg-open ./preview.htm", id="worker-xdg-open-htm"),
        pytest.param("if true; then open https://example.com; fi", id="worker-if-then-open"),
        pytest.param('open -g "http://localhost:5173"', id="worker-open-g"),
    ],
)
def test_block_system_open_web_engine_denies_worker_and_redirects_to_frago_browser(
    tmp_path: Path, command: str
) -> None:
    out = _run_pre_tool_use_via_frago_core_engine(
        tmp_path, command, agent_role="worker"
    )
    hook_out = out.get("hookSpecificOutput", {})
    assert hook_out.get("permissionDecision") == "deny", (
        f"Expected deny for worker on {command!r}, got {out!r}"
    )
    reason = hook_out.get("permissionDecisionReason", "")
    assert "frago browser" in reason


@pytest.mark.parametrize("agent_role", [None, "employee"])
@pytest.mark.parametrize(
    "command",
    [
        pytest.param("open http://127.0.0.1:8093/", id="open-http"),
        pytest.param('open -a "Google Chrome" https://example.com', id="open-chrome"),
        pytest.param("open file:///tmp/a.html", id="open-file-html"),
        pytest.param("cd x && open ./dist/index.html", id="open-local-html"),
        pytest.param("xdg-open http://localhost:3000", id="xdg-open-http"),
        pytest.param("xdg-open ./preview.htm", id="xdg-open-htm"),
    ],
)
def test_block_system_open_web_engine_allows_main_and_employee_with_soft_guidance(
    tmp_path: Path, command: str, agent_role: str | None
) -> None:
    out = _run_pre_tool_use_via_frago_core_engine(
        tmp_path, command, agent_role=agent_role
    )
    hook_out = out.get("hookSpecificOutput", {})
    assert hook_out.get("permissionDecision") != "deny", (
        f"Non-worker ({agent_role}) must not be denied on {command!r}: {out!r}"
    )
    ctx = hook_out.get("additionalContext", "")
    assert "【打开网页前先判场景】" in ctx
    assert "frago browser" in ctx
    assert "仅当用户明确要求在系统默认浏览器打开给人看时" in ctx


@pytest.mark.parametrize("agent_role", ["worker", None, "employee"])
@pytest.mark.parametrize(
    "command",
    [
        pytest.param("open file:///tmp/test.pdf", id="engine-allow-file-pdf"),
        pytest.param("open -R ./dist/index.html", id="engine-allow-open-R"),
        pytest.param("open -t ./dist/index.html", id="engine-allow-open-t"),
        pytest.param("open -Rt ./dist/index.html", id="engine-allow-open-Rt"),
        pytest.param("open -gR ./dist/index.html", id="engine-allow-open-gR"),
        pytest.param("open .", id="engine-allow-open-dot"),
        pytest.param("open ./doc.pdf", id="engine-allow-open-pdf"),
        pytest.param("open -a Finder /tmp", id="engine-allow-open-finder"),
        pytest.param("python3 -c \"open('a.html')\"", id="engine-allow-python-open"),
        pytest.param('git commit -m "open http://127.0.0.1:8093"', id="engine-allow-git-commit"),
        pytest.param('frago todo log id "xdg-open http://localhost:3000"', id="engine-allow-todo-log"),
        pytest.param("frago browser open http://127.0.0.1:8093", id="engine-allow-frago-browser-open"),
    ],
)
def test_block_system_open_web_engine_allows_non_web_and_non_browser_commands_without_guidance(
    tmp_path: Path, command: str, agent_role: str | None
) -> None:
    out = _run_pre_tool_use_via_frago_core_engine(
        tmp_path, command, agent_role=agent_role
    )
    hook_out = out.get("hookSpecificOutput", {})
    assert hook_out.get("permissionDecision") != "deny", (
        f"Unexpected deny for {command!r} ({agent_role}): {out!r}"
    )
    ctx = hook_out.get("additionalContext", "")
    assert "【打开网页前先判场景】" not in ctx


def _run_user_prompt_submit_via_frago_core_engine(
    tmp_path: Path,
    *,
    prompt: str = "请处理待办清单",
    env_overrides: dict[str, str | None] | None = None,
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
            "session_id": f"unit-test-prompt-{uuid.uuid4().hex}",
            "hook_event_name": "UserPromptSubmit",
            "prompt": prompt,
        },
        ensure_ascii=False,
    )
    env = os.environ.copy()
    env["HOME"] = str(home_dir)
    env["TMPDIR"] = str(temp_dir)
    env["TEMP"] = str(temp_dir)
    env["TMP"] = str(temp_dir)
    for k in (
        "FRAGO_PA",
        "FRAGO_CONV_KEY",
        "FRAGO_AGENT_ROLE",
        "FRAGO_SURFACE",
        "FRAGO_STOP_CHECK",
        "FRAGO_SESSION_ORIGIN",
        "FRAGO_UNATTENDED",
        "FRAGO_ALLOW_INTERACTIVE_ASK",
    ):
        env.pop(k, None)
    for k, v in (env_overrides or {}).items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v

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


def test_builtin_rules_schedule_unattended_prompt_rules_via_frago_core(tmp_path: Path) -> None:
    data = _load_rules_data()
    rules_by_id = {r["id"]: r for r in data["rules"]}
    assert "builtin-prompt-unattended-schedule-autonomy" in rules_by_id
    for interactive_id in ("builtin-prompt-decision-card", "builtin-prompt-image-grid"):
        clauses = rules_by_id[interactive_id]["match"]["clauses"]
        assert {"type": "env_ne", "name": "FRAGO_SESSION_ORIGIN", "value": "schedule"} in clauses
        assert {"type": "env_ne", "name": "FRAGO_UNATTENDED", "value": "1"} in clauses

    # 1) 正常 WebUI 主会话：注入出卡提示，不注入无人值守守则
    webui_out = _run_user_prompt_submit_via_frago_core_engine(
        tmp_path,
        env_overrides={"FRAGO_SURFACE": "webui", "FRAGO_CONV_KEY": "conv-webui-1"},
    )
    webui_ctx = webui_out.get("hookSpecificOutput", {}).get("additionalContext", "")
    assert "【要人拍板就出卡片】" in webui_ctx
    assert "【展示图片就出网格卡】" in webui_ctx
    assert "【定时/无人值守运行守则】" not in webui_ctx

    # 2) schedule 来源：即使带着 conv_key / surface=webui，也绝不注入出卡提示，改注入无人值守守则
    sched_out = _run_user_prompt_submit_via_frago_core_engine(
        tmp_path,
        env_overrides={
            "FRAGO_SURFACE": "webui",
            "FRAGO_CONV_KEY": "conv-sched-1",
            "FRAGO_SESSION_ORIGIN": "schedule",
            "FRAGO_UNATTENDED": "1",
        },
    )
    sched_ctx = sched_out.get("hookSpecificOutput", {}).get("additionalContext", "")
    assert "【定时/无人值守运行守则】" in sched_ctx
    assert "严禁调用 `frago app ask`" in sched_ctx
    assert "frago app propose" in sched_ctx
    assert "【要人拍板就出卡片】" not in sched_ctx
    assert "【展示图片就出网格卡】" not in sched_ctx

    # 3) 仅设 FRAGO_UNATTENDED=1 时同样生效
    unattended_out = _run_user_prompt_submit_via_frago_core_engine(
        tmp_path,
        env_overrides={"FRAGO_UNATTENDED": "1", "FRAGO_CONV_KEY": "conv-unatt-1"},
    )
    unattended_ctx = unattended_out.get("hookSpecificOutput", {}).get("additionalContext", "")
    assert "【定时/无人值守运行守则】" in unattended_ctx
    assert "【要人拍板就出卡片】" not in unattended_ctx
    assert "【展示图片就出网格卡】" not in unattended_ctx


CITE_SNIPPET = "【引用网页或本地文件证据时用标准 GFM 脚注 `[^N]`】"


def _run_tool_event_via_frago_core_engine(
    tmp_path: Path,
    *,
    event: str,
    tool_name: str,
    tool_input: dict | None = None,
    session_id: str = "cite-test-session",
    env_overrides: dict[str, str | None] | None = None,
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
            "session_id": session_id,
            "hook_event_name": event,
            "tool_name": tool_name,
            "tool_input": tool_input or {},
        },
        ensure_ascii=False,
    )
    env = os.environ.copy()
    env["HOME"] = str(home_dir)
    env["TMPDIR"] = str(temp_dir)
    env["TEMP"] = str(temp_dir)
    env["TMP"] = str(temp_dir)
    for k in (
        "FRAGO_PA",
        "FRAGO_CONV_KEY",
        "FRAGO_AGENT_ROLE",
        "FRAGO_SURFACE",
        "FRAGO_STOP_CHECK",
        "FRAGO_HARNESS",
    ):
        env.pop(k, None)
    for k, v in (env_overrides or {}).items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v

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


def test_cite_sources_zero_injection_on_plain_chat_and_non_evidence_tools(tmp_path: Path) -> None:
    prompt_out = _run_user_prompt_submit_via_frago_core_engine(
        tmp_path,
        prompt="你好，帮我解释什么是 TCP 握手",
        env_overrides={"FRAGO_SURFACE": "webui", "FRAGO_CONV_KEY": "conv-chat"},
    )
    prompt_ctx = prompt_out.get("hookSpecificOutput", {}).get("additionalContext", "")
    assert CITE_SNIPPET not in prompt_ctx
    assert "[[[!ref_" not in prompt_ctx

    for tool_name, tool_input in [
        ("Edit", {"file_path": "/tmp/a.py"}),
        ("Write", {"file_path": "/tmp/a.py"}),
        ("Glob", {"pattern": "*.py"}),
        ("Bash", {"command": "ls -la"}),
    ]:
        out = _run_tool_event_via_frago_core_engine(
            tmp_path,
            event="PostToolUse",
            tool_name=tool_name,
            tool_input=tool_input,
            session_id=f"non-ev-{tool_name}",
        )
        ctx = out.get("hookSpecificOutput", {}).get("additionalContext", "")
        assert CITE_SNIPPET not in ctx, f"Unexpected cite injection for {tool_name}"


@pytest.mark.parametrize(
    ("tool_name", "tool_input"),
    [
        ("Read", {"file_path": "/tmp/notes.md"}),
        ("Grep", {"pattern": "TODO"}),
        ("WebFetch", {"url": "https://example.com"}),
        ("WebSearch", {"query": "frago release"}),
        ("Bash", {"command": "frago browser get-content --group g1"}),
    ],
)
def test_cite_sources_on_demand_evidence_tools_and_session_dedup(
    tmp_path: Path, tool_name: str, tool_input: dict
) -> None:
    sid = f"ev-{tool_name}-{uuid.uuid4().hex[:8]}"
    first = _run_tool_event_via_frago_core_engine(
        tmp_path,
        event="PostToolUse",
        tool_name=tool_name,
        tool_input=tool_input,
        session_id=sid,
    )
    first_ctx = first.get("hookSpecificOutput", {}).get("additionalContext", "")
    assert CITE_SNIPPET in first_ctx
    assert "[^N]" in first_ctx
    assert "[[[!ref_" not in first_ctx

    # Same session second evidence tool call must be deduped (session scope)
    second = _run_tool_event_via_frago_core_engine(
        tmp_path,
        event="PostToolUse",
        tool_name="WebFetch",
        tool_input={"url": "https://example.com/2"},
        session_id=sid,
    )
    second_ctx = second.get("hookSpecificOutput", {}).get("additionalContext", "")
    assert CITE_SNIPPET not in second_ctx

    # FRAGO_STOP_CHECK=off suppresses injection
    suppressed = _run_tool_event_via_frago_core_engine(
        tmp_path,
        event="PostToolUse",
        tool_name=tool_name,
        tool_input=tool_input,
        session_id=f"{sid}-off",
        env_overrides={"FRAGO_STOP_CHECK": "off"},
    )
    suppressed_ctx = suppressed.get("hookSpecificOutput", {}).get("additionalContext", "")
    assert CITE_SNIPPET not in suppressed_ctx


def test_cite_sources_five_kernels_agy_and_opencode_alignment(tmp_path: Path) -> None:
    # OpenCode tool-name-map covers all 5 evidence tools
    opencode_map_path = REPO_ROOT / "src" / "frago" / "resources" / "opencode" / "tool-name-map.json"
    tool_map = json.loads(opencode_map_path.read_text(encoding="utf-8"))["map"]
    for raw, expected in [
        ("read", "Read"),
        ("grep", "Grep"),
        ("webfetch", "WebFetch"),
        ("websearch", "WebSearch"),
        ("bash", "Bash"),
    ]:
        assert tool_map.get(raw) == expected

    # AGY harness: PreToolUse injects once per session; PostToolUse does not match
    agy_sid = f"agy-{uuid.uuid4().hex[:8]}"
    post_agy = _run_tool_event_via_frago_core_engine(
        tmp_path,
        event="PostToolUse",
        tool_name="Read",
        tool_input={"file_path": "/tmp/a.md"},
        session_id=agy_sid,
        env_overrides={"FRAGO_HARNESS": "agy"},
    )
    assert CITE_SNIPPET not in post_agy.get("hookSpecificOutput", {}).get("additionalContext", "")

    pre_agy_1 = _run_tool_event_via_frago_core_engine(
        tmp_path,
        event="PreToolUse",
        tool_name="Read",
        tool_input={"file_path": "/tmp/a.md"},
        session_id=agy_sid,
        env_overrides={"FRAGO_HARNESS": "agy"},
    )
    assert CITE_SNIPPET in pre_agy_1.get("hookSpecificOutput", {}).get("additionalContext", "")

    pre_agy_2 = _run_tool_event_via_frago_core_engine(
        tmp_path,
        event="PreToolUse",
        tool_name="WebSearch",
        tool_input={"query": "test"},
        session_id=agy_sid,
        env_overrides={"FRAGO_HARNESS": "agy"},
    )
    assert CITE_SNIPPET not in pre_agy_2.get("hookSpecificOutput", {}).get("additionalContext", "")
