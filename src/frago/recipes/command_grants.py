"""Which outside commands a recipe may run on this machine, and what each may see.

A recipe that starts ``gh`` needs more than the ``gh`` binary. ``gh`` reads its
login from a config directory the moment it starts, and a confined run cannot
see that directory — ``github_star_watch`` failed exactly this way from the day
isolation arrived (2026-08-31) until this module existed, with
``operation not permitted`` against a file nobody had heard of.

Where that directory is depends on the machine. Homebrew puts ``gh`` under
``/opt/homebrew`` and its config in ``~/.config/gh``; a snap moves the whole
home, so on the demo server the same config sits in
``~/snap/gh/current/.config/gh`` and the binary is a link to ``/usr/bin/snap``.
Every other distribution and installer has an answer of its own. A table of
those answers written into the platform would never be finished, and the
entries it lacked would fail in the quietest way there is.

So the platform does not know what ``gh`` is. A recipe declares the command by
name (``uses_commands: [gh]``); the first run on a machine asks CoreAgent to
look at how that command is installed *here*, say which directories it reads
and whether handing them over read-only is safe, and the answer is recorded
beside the recipe's data (``app_state.GRANTS_FILE``). Every later run reads the
record and spends nothing. When the recipe's code changes, the record no
longer matches and the question is asked again.

**The record lives with the recipe.** ``~/.frago/recipe-data/<recipe>/`` —
machine-level, because where ``gh`` is installed does not depend on which
account is running the recipe, and inside the recipe's own tree so it goes
when the recipe's data goes. The recipe can read it and cannot write it: see
``View.platform_owned``.

**What is checked afterwards, by us, not by the model.** Every directory the
answer names has to exist, and none may be the home directory, anything above
it, frago's own tree, or a handful of places that are never a command's own
(keys, cloud credentials). The model is asked to hold to the same rules; this is
the part that does not depend on it having done so.

**What the command works on counts too, and so does writing.** ``du`` has no
config of its own; what it needs is the directories the recipe hands it to
measure, and ``mv`` needs to write where it moves things. Measured on
2026-09-18 with a probe declaring ``[du, mv]``: both were allowed with nothing
handed over, and the run could not read ``~/Library/Caches`` or make a
directory in ``~/.Trash``. So an answer names, besides the command's own
places, the places the recipe's code points the command at, each marked
``read`` or ``write``. Writing is still judged by CoreAgent against the code it
reads, and screened here by the same rules as reading; an entry recorded before
this distinction existed reads as ``read``.

**What this does not do.** Where nothing is confined — isolation turned off,
or a machine with no backend (Windows) — there is nothing to hand over, and no
question is asked.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from frago.recipes import isolation
from frago.recipes.app_state import grants_path, machine_root

logger = logging.getLogger(__name__)

#: CoreAgent's instructions for this job, under ``~/.frago/coreagent/``.
#: Shipped in the package and laid down by ``frago.init.user_resource_seed``.
INSTRUCTIONS = "command-audit.md"

#: Seconds CoreAgent gets for one command. It reads the recipe's code, then
#: runs a handful of ``which`` and ``ls`` calls to check each place the code
#: names. Sixteen rounds were enough while the question was only "where is
#: this command's config"; a recipe that points ``mv`` at a dozen places used
#: all sixteen without an answer (2026-09-19).
AUDIT_TIMEOUT = 300
AUDIT_MAX_ROUNDS = 40

#: How many superseded answers each command keeps, so "what did it say last
#: time" is in the file rather than in a log nobody keeps.
EARLIER_KEPT = 5

#: Version of the record's layout.
FORMAT = 1


class AuditFailed(RuntimeError):
    """CoreAgent could not give an answer this module can use."""


# ── what the recipe says about the command ─────────────────────────────────


def _word(command: str) -> re.Pattern[str]:
    """The command's name as a word of its own: ``gh`` in ``"gh"`` or ``gh api``,
    not in ``ghost`` or ``/gh/``."""
    return re.compile(r"(?<![\w./-])" + re.escape(command) + r"(?![\w-])")


def mentions(recipe_dir: Path | None, command: str) -> list[tuple[str, int, str]]:
    """Every line of the recipe's code that names the command.

    ``(relative file, line number, line)``. Only for pointing CoreAgent at the
    right places; what decides whether it is asked again is ``fingerprint``.
    """
    word = _word(command)
    found: list[tuple[str, int, str]] = []
    for path in code_files(recipe_dir):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        rel = str(path.relative_to(recipe_dir))
        for number, line in enumerate(lines, start=1):
            if word.search(line):
                found.append((rel, number, line))
    return found


def code_files(recipe_dir: Path | None) -> list[Path]:
    """The recipe's code: what actually runs, without its own tests."""
    if recipe_dir is None or not Path(recipe_dir).is_dir():
        return []
    return [
        path for path in sorted(Path(recipe_dir).rglob("*"))
        if path.is_file()
        and path.suffix.lower() in isolation._CODE_SUFFIXES
        and not isolation._is_a_test(path)
        and "__pycache__" not in path.parts
    ]


def fingerprint(command: str, recipe_dir: Path | None) -> str:
    """The recipe's code as one value, for one command.

    **The whole of the code, not the lines that name the command.** The line
    that actually starts ``gh`` in ``github_star_watch`` is
    ``argv = [self._gh_path(), "api", "graphql", …]`` — the name is not on it.
    A fingerprint of the lines naming the command would stay the same while
    that line changed to ``repo delete``, and the old answer would go on
    covering a different command. The isolation's own scan says the same about
    itself: a command name built at run time is invisible to reading the
    source. So any change to the code is asked about again. It costs one
    model call the first time a changed recipe runs, which is rare next to the
    runs it covers.
    """
    digest = hashlib.sha256(command.encode("utf-8"))
    for path in code_files(recipe_dir):
        try:
            content = path.read_bytes()
        except OSError:
            continue
        digest.update(b"\0" + str(path.relative_to(recipe_dir)).encode("utf-8") + b"\0" + content)
    return "sha256:" + digest.hexdigest()


# ── the record ─────────────────────────────────────────────────────────────


def load(recipe_name: str) -> dict[str, Any]:
    """The record for one recipe. An absent or unreadable one reads as empty,
    which means every declared command is asked about again — the direction a
    damaged file should fail in."""
    path = grants_path(recipe_name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    except (OSError, ValueError) as err:
        logger.warning("命令放行登记 %s 读不出（%s），按没有登记处理", path, err)
        data = {}
    if not isinstance(data, dict) or not isinstance(data.get("commands"), dict):
        data = {}
    data.setdefault("format", FORMAT)
    data.setdefault("recipe", recipe_name)
    data.setdefault("commands", {})
    return data


def _write(recipe_name: str, record: dict[str, Any]) -> None:
    path = grants_path(recipe_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def seal(recipe_name: str) -> None:
    """Lay down an empty record where the recipe's tree exists and none is there.

    Only for Linux's sake, and said here so nobody removes it as clutter: a
    mount can make an existing file read-only but cannot forbid creating one,
    so an absent record inside a writable tree is a record the recipe could
    write first. On macOS the kernel's rule covers an absent path as well; the
    file is laid down anyway so both machines look the same.

    A tree that does not exist is left alone. The run cannot create it — its
    parent is outside the view — so there is nothing to forge into.
    """
    root = machine_root(recipe_name)
    path = grants_path(recipe_name)
    if not root.is_dir() or path.exists():
        return
    try:
        _write(recipe_name, {"format": FORMAT, "recipe": recipe_name, "commands": {}})
    except OSError as err:
        logger.warning("没能在 %s 放下空的放行登记：%s", path, err)


# ── asking ────────────────────────────────────────────────────────────────


#: Places no command's answer may include, whatever CoreAgent says. Matched as
#: "is this path, or inside it"; the home directory and anything above it are
#: refused separately.
def _never(home: Path) -> list[Path]:
    return [
        home / ".frago",
        home / ".ssh",
        home / ".gnupg",
        home / ".aws",
        home / ".kube",
        home / ".docker",
        home / "Library" / "Keychains",
    ]


#: How far a place is handed over. Anything CoreAgent writes that is not one
#: of these reads as the narrower one.
READ = "read"
WRITE = "write"


def _access(one: dict[str, Any]) -> str:
    return WRITE if str((one or {}).get("access") or "").strip().lower() == WRITE else READ


def screen(paths: list[dict[str, Any]], home: Path | None = None
           ) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Split CoreAgent's list into what may be handed over and what may not.

    Returns ``(kept, dropped)``, each ``[{"path", "why", "access"}]``. The model
    is told the same rules; this is the half that holds when it did not follow
    them. Writing is screened by exactly the rules reading is: a place that may
    never be read may never be written either, and the reverse needs no rule of
    its own because writing is only ever asked for places already named.
    """
    home = (home or Path.home()).resolve()
    never = [p.resolve() if p.exists() else p for p in _never(home)]
    kept: list[dict[str, str]] = []
    dropped: list[dict[str, str]] = []
    for one in paths:
        raw = str((one or {}).get("path") or "").strip()
        why = str((one or {}).get("why") or "").strip()
        access = _access(one)
        if not raw:
            continue
        path = Path(raw).expanduser()
        if not path.is_absolute():
            dropped.append({"path": raw, "why": "不是绝对路径"})
            continue
        if not path.exists():
            dropped.append({"path": raw, "why": "这台机器上不存在"})
            continue
        real = path.resolve()
        if real == Path("/") or real == home or home.is_relative_to(real):
            dropped.append({"path": raw, "why": "是家目录或它上面的目录，交出去等于没有隔离"})
            continue
        hit = next((n for n in never if real == n or real.is_relative_to(n)
                    or n.is_relative_to(real)), None)
        if hit is not None:
            dropped.append({"path": raw, "why": f"碰到了 {hit}，那里从来不是某个命令自己的东西"})
            continue
        kept.append({"path": str(path), "why": why, "access": access})
    return kept, dropped


def _paths(entry: dict[str, Any], access: str) -> list[Path]:
    """The places one recorded answer hands over at one level."""
    return [Path(one["path"]) for one in entry.get("paths") or []
            if isinstance(one, dict) and one.get("path") and _access(one) == access]


def _instructions_ready() -> bool:
    target = Path.home() / ".frago" / "coreagent" / INSTRUCTIONS
    if target.is_file():
        return True
    # A machine that has only ever used the command line has never started the
    # server that lays the shipped files down. Do it here rather than fail.
    try:
        from frago.init.user_resource_seed import seed_user_resources

        seed_user_resources()
    except Exception:  # noqa: BLE001
        logger.warning("铺设随包资源失败", exc_info=True)
    return target.is_file()


def _allowed_tools(command: str, recipe_dir: Path | None) -> list[str]:
    """Read-only looking around, and one directory whose files may be opened.

    ``ls`` says whether a directory is there and what it holds by name; nothing
    here prints the contents of anything outside the recipe's own code, because
    the directories being asked about are exactly the ones holding login
    tokens, and the model is somebody else's server. The recipe's code it may
    read in full: how the command is called is half of the question.
    """
    # ``//`` marks an absolute path. A single leading ``/`` is read the way
    # Claude Code reads it — relative to the working directory — so the rule
    # this line used to write, ``Read(/Users/…/<recipe>/**)``, allowed nothing,
    # and CoreAgent was refused every file of the code it was asked to judge
    # (measured 2026-09-19: ``du`` denied because the target list was unreadable).
    own = [f"Read(//{str(Path(recipe_dir)).lstrip('/')}/**)"] if recipe_dir else []
    return [*own,
        "Bash(which:*)", "Bash(command -v:*)", "Bash(type:*)",
        "Bash(ls:*)", "Bash(readlink:*)", "Bash(realpath:*)", "Bash(file:*)",
        "Bash(uname:*)",
        f"Bash({command} --version)", f"Bash({command} --help)",
    ]


def _prompt(recipe_name: str, command: str,
            lines: list[tuple[str, int, str]], recipe_dir: Path | None) -> str:
    home = Path.home()
    visible = [str(p) for p in isolation._system_readable()]
    visible += [str(p) for p in isolation._interpreter_readable()]
    context: list[str] = []
    for rel, number, line in lines[:40]:
        context.append(f"{rel}:{number}: {line.strip()[:200]}")
    if len(lines) > 40:
        context.append(f"……另有 {len(lines) - 40} 行没列出")
    return "\n".join([
        f"配方 {recipe_name} 声明它要运行外部命令 `{command}`。",
        "",
        f"这台机器：{platform.system()} {platform.machine()}，家目录 {home}，"
        f"XDG_CONFIG_HOME={os.environ.get('XDG_CONFIG_HOME') or '未设'}。",
        f"配方代码在：{recipe_dir or '未知'}（这个目录下的文件你可以读，看清命令是怎么被调用的）",
        *[f"- {path.relative_to(recipe_dir)}" for path in code_files(recipe_dir)],
        "",
        "配方本来就看得见（只读）的系统与解释器目录：",
        *[f"- {one}" for one in dict.fromkeys(visible)],
        "",
        f"配方源码里提到 `{command}` 的行：",
        *(context or ["（没找到，配方可能是拼出命令名再调用的）"]),
        "",
        "按说明书查清两件事：这个命令在这台机器上运行时自己要读哪些目录；"
        "配方代码拿这个命令去读、去写哪些地方。逐项判断交给这个配方是否安全，"
        "最后一条回复只交那个 JSON 对象。",
    ])


def _last_json(text: str) -> dict[str, Any] | None:
    """The last JSON object in CoreAgent's answer, fenced or bare."""
    for block in reversed(re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)):
        try:
            value = json.loads(block)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    decoder = json.JSONDecoder()
    for start in reversed([m.start() for m in re.finditer(r"\{", text)]):
        try:
            value, _ = decoder.raw_decode(text[start:])
        except ValueError:
            continue
        if isinstance(value, dict) and "verdict" in value:
            return value
    return None


#: How many times one audit is asked when an answer comes back without the
#: object it was asked for. The model sometimes ends on prose; the same
#: question asked again answered properly (measured 2026-09-19, ``du``).
AUDIT_ATTEMPTS = 2


def audit(recipe_name: str, recipe_dir: Path | None, command: str,
          lines: list[tuple[str, int, str]]) -> dict[str, Any]:
    """Ask CoreAgent, and return the entry to record.

    An answer without a usable verdict is asked again, up to
    ``AUDIT_ATTEMPTS`` times in all; every other failure is final at once,
    because asking again would only repeat it.
    """
    for attempt in range(1, AUDIT_ATTEMPTS + 1):
        try:
            return _audit_once(recipe_name, recipe_dir, command, lines)
        except _NoVerdict as err:
            if attempt == AUDIT_ATTEMPTS:
                raise AuditFailed(str(err)) from None
            logger.warning("命令 %s 的审计回答里没有结论，再问一次", command)
    raise AssertionError("unreachable")


class _NoVerdict(AuditFailed):
    """The answer came back, without the object it was asked for."""


def _audit_once(recipe_name: str, recipe_dir: Path | None, command: str,
                lines: list[tuple[str, int, str]]) -> dict[str, Any]:
    """Ask CoreAgent once, and return the entry to record.

    Raises ``AuditFailed`` when there is no answer to record: CoreAgent not
    installed, no connection bound, a timeout, or an answer that is not the
    object it was asked for. Nothing is recorded then, so the next run asks
    again rather than living with a guess.
    """
    from frago.init.hook_binary import get_binary_name, get_hook_deploy_dir

    binary = get_hook_deploy_dir() / get_binary_name()
    if not binary.exists():
        raise AuditFailed(f"frago-core 还没装好（{binary} 不存在）")
    if not _instructions_ready():
        raise AuditFailed(f"审计说明书 ~/.frago/coreagent/{INSTRUCTIONS} 不在，也没能铺设上")

    cwd = Path(recipe_dir) if recipe_dir and Path(recipe_dir).is_dir() else Path.home()
    cmd = [
        str(binary), "--mode", "agent", "--as-role", "coreagent",
        "--instructions", INSTRUCTIONS,
        "--output-format", "json",
        "--timeout", str(AUDIT_TIMEOUT), "--max-rounds", str(AUDIT_MAX_ROUNDS),
        "--cwd", str(cwd),
        "--prompt", _prompt(recipe_name, command, lines, recipe_dir),
    ]
    for rule in _allowed_tools(command, recipe_dir):
        cmd += ["--allowed-tools", rule]

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    # A machine asking a machine. The review passes are there for a person's
    # conversation; here they would only add a model call to every step.
    env["FRAGO_REVIEW"] = "off"
    env["FRAGO_STOP_CHECK"] = "off"

    logger.info("命令 %s（配方 %s）在这台机器上还没审计过，请 CoreAgent 看一次", command, recipe_name)
    try:
        done = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=AUDIT_TIMEOUT + 60, cwd=str(cwd), env=env,
        )
    except subprocess.TimeoutExpired as err:
        raise AuditFailed(f"CoreAgent {AUDIT_TIMEOUT} 秒内没有结束") from err
    except OSError as err:
        raise AuditFailed(f"起不来 frago-core：{err}") from err

    final: dict[str, Any] | None = None
    for line in reversed((done.stdout or "").splitlines()):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and value.get("type") == "final":
            final = value
            break
    if final is None:
        # frago-core ends a failure with a line of advice for a person at a
        # terminal ("hint: …"); the reason is the line before it.
        tail = [line for line in (done.stderr or "").strip().splitlines()
                if line.strip() and not line.startswith("hint:")]
        raise AuditFailed(tail[-1][:400] if tail else f"CoreAgent 没交结论，退出码 {done.returncode}")
    if not final.get("ok"):
        raise AuditFailed(str(final.get("error") or final.get("error_kind") or "CoreAgent 没办完"))

    text = str(final.get("text") or "")
    answer = _last_json(text)
    if answer is None or answer.get("verdict") not in ("allow", "deny"):
        tail = " ".join(text.split())[-300:]
        raise _NoVerdict(
            "CoreAgent 的回答里没有可用的结论（要一个带 verdict 的 JSON 对象）"
            + (f"，它最后说的是：…{tail}" if tail else "，回答是空的")
        )

    kept, dropped = screen(answer.get("paths") or []) if answer["verdict"] == "allow" else ([], [])
    return {
        "fingerprint": fingerprint(command, recipe_dir),
        "verdict": answer["verdict"],
        "executable": str(answer.get("executable") or ""),
        "paths": kept,
        "dropped": dropped,
        "reason": str(answer.get("reason") or "").strip(),
        "audited_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "auditor": {k: final.get(k) for k in ("role", "profile", "model")},
        "machine": f"{platform.system()} {platform.machine()}",
    }


# ── what a run gets ────────────────────────────────────────────────────────


def _declarable(command: str) -> bool:
    """Whether a declared name is one this module may ask about.

    ``validate_metadata`` says why a bad one is bad; this only keeps it out of
    an audit. A path handed to CoreAgent as a "command" would be looked up and
    judged as if it were one, and ``frago`` has its own declaration.
    """
    from frago.recipes.metadata import COMMAND_NAME

    return command != "frago" and bool(COMMAND_NAME.match(command))


def _confined() -> bool:
    """Whether anything is confined on this machine. Where nothing is, a
    command sees everything already and there is nothing to hand over."""
    return isolation.configured() != isolation.OFF and isolation.backend() is not None


def for_run(
    recipe_name: str,
    recipe_dir: Path | None,
    commands: list[str],
    *,
    may_audit: bool = True,
) -> tuple[dict[str, list[Path]], str]:
    """The directories each declared command may see on this run, and why the
    run must not start, if it must not.

    Returns ``({command: [paths]}, refusal)``; an empty refusal means start.

    ``may_audit`` is False for the door that must not block: the server keeps
    long-running recipes alive from inside its event loop, and a first audit
    can take a minute. That door uses what is recorded and refuses what is not,
    saying how to get it recorded.
    """
    if not commands or not _confined():
        return {}, ""

    record = load(recipe_name)
    changed = False
    granted: dict[str, list[Path]] = {}
    refusals: list[str] = []
    where = grants_path(recipe_name)

    for command in dict.fromkeys(commands):
        if not _declarable(command):
            refusals.append(
                f"配方 {recipe_name} 的 uses_commands 里写了 {command!r}，这不是一个能审计的命令名"
                f"（只写命令名，不写路径、不带参数；frago 自己的命令写 uses_frago_cli）。"
                f"先改 recipe.md，frago recipe validate 会说清楚。"
            )
            continue
        lines = mentions(recipe_dir, command)
        current = fingerprint(command, recipe_dir)
        entry = record["commands"].get(command)

        if not isinstance(entry, dict) or entry.get("fingerprint") != current:
            if not may_audit:
                refusals.append(
                    f"配方 {recipe_name} 要用命令 {command}，这台机器还没审计过它"
                    f"{'（配方代码改过）' if isinstance(entry, dict) else ''}。"
                    f"服务端常驻启动时不做审计；先手动跑一次 frago recipe run {recipe_name}，"
                    f"审计通过后这里就能起。"
                )
                continue
            try:
                fresh = audit(recipe_name, recipe_dir, command, lines)
            except AuditFailed as err:
                refusals.append(
                    f"配方 {recipe_name} 要用命令 {command}，要先在这台机器上过一次审计，"
                    f"这次没做成：{err}。检查设置页里 CoreAgent 那一行绑的连接，然后再跑一次。"
                )
                continue
            if isinstance(entry, dict):
                earlier = [{k: v for k, v in entry.items() if k != "earlier"}]
                fresh["earlier"] = (earlier + list(entry.get("earlier") or []))[:EARLIER_KEPT]
            record["commands"][command] = fresh
            entry = fresh
            changed = True

        if entry.get("verdict") == "allow":
            granted[command] = _paths(entry, READ)
        else:
            refusals.append(
                f"配方 {recipe_name} 要用命令 {command}，这台机器审计没放行："
                f"{entry.get('reason') or '没写理由'}。记录在 {where}，"
                f"删掉 {command} 那一条，下次运行会重新审计。"
            )

    if changed:
        try:
            _write(recipe_name, record)
        except OSError as err:
            logger.warning("放行登记写不进 %s：%s（这次照常运行，下次会再审一次）", where, err)

    return granted, "\n".join(refusals)


def recorded(
    recipe_name: str, recipe_dir: Path | None, commands: list[str]
) -> tuple[dict[str, list[Path]], list[str]]:
    """What is already recorded, for ``frago recipe validate``. Never asks.

    Returns the directories recorded for commands whose code has not changed,
    and one sentence per command that the next run will have to ask about.
    ``validate`` describes a recipe; it does not spend money deciding things.
    """
    if not commands or not _confined():
        return {}, []
    record = load(recipe_name)
    granted: dict[str, list[Path]] = {}
    notes: list[str] = []
    for command in dict.fromkeys(commands):
        if not _declarable(command):
            continue  # validate_metadata already says what is wrong with it
        entry = record["commands"].get(command)
        current = fingerprint(command, recipe_dir)
        if not isinstance(entry, dict):
            notes.append(f"命令 {command} 在这台机器上还没审计过，第一次运行时会请 CoreAgent 看一次")
        elif entry.get("fingerprint") != current:
            notes.append(f"配方代码改过，命令 {command} 下次运行会重新审计")
        elif entry.get("verdict") != "allow":
            notes.append(f"命令 {command} 在这台机器上审计没放行：{entry.get('reason') or '没写理由'}")
        else:
            granted[command] = _paths(entry, READ)
    return granted, notes


def writable(
    recipe_name: str, recipe_dir: Path | None, commands: list[str]
) -> dict[str, list[Path]]:
    """The places each declared command was allowed to *write*, from the record.

    Kept apart from ``for_run`` and ``recorded`` so their answer keeps meaning
    what it always meant — what may be read. Read after ``for_run`` has had its
    chance to ask, so a first run gets what its own audit just recorded. Only an
    answer that still matches the code counts: an outdated one was never about
    the code that is about to run.
    """
    if not commands or not _confined():
        return {}
    record = load(recipe_name)
    out: dict[str, list[Path]] = {}
    for command in dict.fromkeys(commands):
        if not _declarable(command):
            continue
        entry = record["commands"].get(command)
        if (not isinstance(entry, dict) or entry.get("verdict") != "allow"
                or entry.get("fingerprint") != fingerprint(command, recipe_dir)):
            continue
        paths = _paths(entry, WRITE)
        if paths:
            out[command] = paths
    return out
