"""Global test fixtures for frago."""
import asyncio
import builtins
import contextlib
import os
import shutil
import sys
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# The CLI refuses to run from the source checkout (frago.server.launch_guard),
# but the suite necessarily does exactly that: it lives in the repo, runs in the
# repo venv, and drives the top-level callback through click's CliRunner. This
# is the guard's one sanctioned bypass.
os.environ.setdefault("FRAGO_ALLOW_CHECKOUT_CLI", "1")


# ============================================================
# 真人数据防护：重定向 + 守门人
#
# 20260725 事故：给 agent_core 写单元测试时，用例里一句「存一份配置再读回来」
# 把真人的 ~/.frago/config.json 覆盖成了空白默认值，近一个月的任务渠道、
# 主代理常驻会话、桌宠守护声明全部丢失，只能从历史会话转录里捞回 6/26 的版本。
#
# 根因不是粗心：`mock_home` 只打桩 Path.home()，而模块里那些
# `X_PATH = Path.home() / ".frago" / ...` 常量在 import 期就已算成绝对路径，
# 之后改 Path.home() 对它们无效。当晚那个会话恰恰先查了 conftest、
# 确认 mock_home 是套件惯例、然后才用的它 —— 是文档级误导，不是失误。
#
# 两道防护都 autouse，测试作者无需知道这个坑存在：
#   _redirect_protected_paths —— 把所有指向真人数据位置的模块级 Path 常量
#       改指到本用例的 tmp_path 镜像下。动态扫描而非硬编码名单，
#       将来新增同类常量自动被覆盖。
#   _guard_protected_writes —— 兜底。万一有常量漏网（例如函数内部现算的路径），
#       任何落到真人数据位置的写/删动作当场炸掉并指名道姓，
#       NEVER 让它静默写成功。
#
# 只拦写与删，不拦读 —— 读不毁数据，且少数用例确实要读真实布局。
# ============================================================

# conftest 在任何 Path.home() 打桩之前加载，此刻取到的必定是真身。
_REAL_HOME = Path.home()


def _import_all_frago_modules() -> None:
    """套件加载期把 frago 全部子模块导进来，让下面那张网变密。

    重定向靠扫 sys.modules 工作，只能改到「已经导入」的模块。而产品代码里
    大量路径常量所在的模块是函数内部才 import 的（为避免循环依赖），
    等某个用例执行到那一行才进 sys.modules —— 那时 autouse fixture 早跑完了,
    常量仍指着真人的家目录。先全量导入，扫描才盖得全。
    """
    import importlib
    import pkgutil

    import frago

    for mod in pkgutil.walk_packages(frago.__path__, prefix="frago."):
        # 导不进来的模块（缺可选依赖等）也不会在用例里被用到，跳过即可。
        with contextlib.suppress(Exception):
            importlib.import_module(mod.name)


_import_all_frago_modules()

# 真人数据位置。仓库自身在 ~/Repos 下，不在此列，所以不会误伤 repo 内的读写。
_PROTECTED_PATHS = (
    _REAL_HOME / ".frago",
    _REAL_HOME / ".claude",
    _REAL_HOME / ".claude.json",
    _REAL_HOME / ".local" / "share" / "opencode",
)


def _is_protected(target) -> bool:
    """target 是否落在真人数据位置内（含位置本身）。"""
    try:
        p = Path(target)
        if not p.is_absolute():
            p = Path.cwd() / p
    except (TypeError, ValueError):
        return False
    return any(p == base or base in p.parents for base in _PROTECTED_PATHS)


@pytest.fixture(autouse=True)
def _redirect_protected_paths(tmp_path, monkeypatch):
    """把 frago 各模块里指向真人数据位置的 Path 常量改指到 tmp_path 镜像。

    扫 sys.modules 而非写死清单：pytest 收集用例时已 import 到被测模块，
    新增的同类常量下次自动进网，不需要有人记得来更新名单。
    """
    fake_home = tmp_path / "_fake_home"
    for module in list(sys.modules.values()):
        name = getattr(module, "__name__", "")
        if not name.startswith("frago"):
            continue
        try:
            members = list(vars(module).items())
        except Exception:
            continue
        for attr, value in members:
            if isinstance(value, Path) and _is_protected(value):
                monkeypatch.setattr(
                    module, attr, fake_home / value.relative_to(_REAL_HOME), raising=False
                )


@pytest.fixture(autouse=True)
def _guard_protected_writes(request, monkeypatch):
    """拦住一切落到真人数据位置的写/删，当场报错而不是静默成功。"""

    def _explode(target, how: str):
        raise RuntimeError(
            f"测试 {request.node.nodeid} 试图 {how} 真人数据: {target}\n"
            f"这条路通向 20260725 那次事故（真人 config.json 被测试覆盖）。\n"
            f"改法：不要用 mock_home —— 它只打桩 Path.home()，"
            f"对 import 期就算死的模块级路径常量无效。\n"
            f"改用 monkeypatch.setattr(<模块>, '<常量名>', tmp_path / ...) "
            f"直接把那个常量指到临时目录。"
        )

    def wrap(orig, how, pick_target, is_write=None):
        """给一个写/删函数套上防护。

        pick_target 从本次调用的实参里取出「要动哪个路径」；
        is_write 为 None 表示这个函数天然就是写或删，无需再判模式。
        """

        def guarded(*args, **kwargs):
            if is_write is None or is_write(args, kwargs):
                target = pick_target(args, kwargs)
                if _is_protected(target):
                    _explode(target, how)
            return orig(*args, **kwargs)

        return guarded

    def first_arg(args, kwargs):
        """取第一个实参（Path 方法的 self、或 rmtree 的 path）。"""
        if args:
            return args[0]
        for key in ("path", "file"):
            if key in kwargs:
                return kwargs[key]
        return None

    def second_arg(keyword):
        """取第二个实参（改名类操作的目标端）。"""

        def pick(args, kwargs):
            return args[1] if len(args) > 1 else kwargs.get(keyword)

        return pick

    def open_target(args, kwargs):
        return kwargs.get("file", args[0] if args else None)

    def is_write_mode(args, kwargs):
        mode = kwargs.get("mode")
        if mode is None and len(args) > 1 and isinstance(args[1], str):
            mode = args[1]
        return any(c in (mode or "r") for c in "wax+")

    monkeypatch.setattr(Path, "write_text", wrap(Path.write_text, "写入", first_arg))
    monkeypatch.setattr(Path, "write_bytes", wrap(Path.write_bytes, "写入", first_arg))
    monkeypatch.setattr(Path, "open", wrap(Path.open, "打开写入", first_arg, is_write_mode))
    monkeypatch.setattr(Path, "unlink", wrap(Path.unlink, "删除", first_arg))
    monkeypatch.setattr(Path, "rename", wrap(Path.rename, "改名顶替", second_arg("target")))
    monkeypatch.setattr(
        builtins, "open", wrap(builtins.open, "打开写入", open_target, is_write_mode)
    )
    monkeypatch.setattr(os, "replace", wrap(os.replace, "改名顶替", second_arg("dst")))
    monkeypatch.setattr(shutil, "rmtree", wrap(shutil.rmtree, "递归删除", first_arg))


# ============================================================
# Fixture: Isolated Temp Directory Structure
# ============================================================


@pytest.fixture
def temp_frago_home(tmp_path: Path) -> Generator[Path]:
    """Create isolated ~/.frago directory structure.

    Creates:
        tmp_path/.frago/
            sessions/claude/
            recipes/atomic/, recipes/workflows/
            config.json
        tmp_path/.claude/
            projects/
            skills/
            commands/
    """
    frago_dir = tmp_path / ".frago"
    claude_dir = tmp_path / ".claude"

    # Create directory structure
    (frago_dir / "sessions" / "claude").mkdir(parents=True)
    (frago_dir / "recipes" / "atomic").mkdir(parents=True)
    (frago_dir / "recipes" / "workflows").mkdir(parents=True)
    (claude_dir / "projects").mkdir(parents=True)
    (claude_dir / "skills").mkdir(parents=True)
    (claude_dir / "commands").mkdir(parents=True)

    # Create empty config
    (frago_dir / "config.json").write_text("{}")

    yield tmp_path


@pytest.fixture
def mock_home(temp_frago_home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Mock Path.home() to return isolated temp directory."""
    monkeypatch.setattr(Path, "home", lambda: temp_frago_home)
    # Also set FRAGO_SESSION_DIR for session storage
    monkeypatch.setenv(
        "FRAGO_SESSION_DIR", str(temp_frago_home / ".frago" / "sessions")
    )
    return temp_frago_home


# ============================================================
# Fixture: Singleton Cleanup
# ============================================================


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset all singleton instances between tests.

    This runs automatically after each test to ensure clean state.
    """
    yield

    # Reset RecipeRegistry singleton
    try:
        import frago.recipes.registry as recipe_reg

        recipe_reg._registry_instance = None
    except ImportError:
        pass

    # Reset SyncService singleton
    try:
        from frago.server.services.sync_service import SyncService

        SyncService._instance = None
    except ImportError:
        pass

    # Reset StateManager singleton
    try:
        from frago.server.state import StateManager

        StateManager.reset_instance()
    except ImportError:
        pass

    # Reset RecipeService cache
    try:
        from frago.server.services.recipe_service import RecipeService

        RecipeService._cache = None
    except ImportError:
        pass


# ============================================================
# Fixture: Subprocess Mocking
# ============================================================


@pytest.fixture
def mock_subprocess():
    """Mock subprocess.run and subprocess.Popen for all tests."""
    with patch("subprocess.run") as mock_run, patch("subprocess.Popen") as mock_popen:
        # Default successful response
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        yield {"run": mock_run, "popen": mock_popen}


@pytest.fixture
def mock_frago_subprocess():
    """Mock frago-specific subprocess calls via base.py."""
    with patch("frago.server.services.subprocess_utils.run_subprocess") as mock_run, patch(
        "frago.server.services.subprocess_utils.run_subprocess_background"
    ) as mock_bg:
        mock_run.return_value = MagicMock(returncode=0, stdout="{}", stderr="")

        yield {"run_subprocess": mock_run, "run_subprocess_background": mock_bg}


# ============================================================
# Fixture: Async Event Loop
# ============================================================


@pytest.fixture
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ============================================================
# Fixture: Sample Test Data
# ============================================================


@pytest.fixture
def sample_session_data() -> dict:
    """Return sample session JSONL record data."""
    return {
        "type": "user",
        "sessionId": "test-session-123",
        "timestamp": "2025-01-15T10:00:00Z",
        "message": {"content": "Test message"},
    }


@pytest.fixture
def sample_recipe_metadata() -> dict:
    """Return sample recipe metadata.yaml content."""
    return {
        "name": "test_recipe",
        "description": "A test recipe",
        "type": "atomic",
        "runtime": "python",
        "tags": ["test"],
    }


@pytest.fixture
def sample_skill_frontmatter() -> str:
    """Return sample SKILL.md content."""
    return """---
name: test-skill
description: A test skill for unit testing
---

# Test Skill

This is a test skill.
"""
