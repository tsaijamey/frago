"""真人数据防护自身的回归测试（20260725 事故的护栏）。

事故经过见 tests/conftest.py 顶部。这里只钉两件事：
1. 模块级路径常量真的被改指到了临时目录，不再指向真人的家目录；
2. 万一有常量漏网，写真人数据位置会当场炸，而不是静默写成功。

第 2 条用 conftest 里的判定函数直接验，不真去碰 ~/.frago —— 测试自己
NEVER 拿真人数据当靶子。
"""

from pathlib import Path

import pytest

from tests.conftest import _PROTECTED_PATHS, _REAL_HOME, _is_protected


class TestPathsRedirected:
    """事故那条路：模块级常量在 import 期算死，打桩 Path.home() 对它无效。"""

    def test_main_config_no_longer_points_at_real_home(self):
        from frago.init import config_manager

        assert _REAL_HOME not in config_manager.CONFIG_PATH.parents
        assert "_fake_home" in str(config_manager.CONFIG_PATH)

    def test_save_then_load_cannot_touch_real_config(self):
        """事故当晚那句「存一份配置再读回来」，现在落在临时目录。"""
        from frago.init import config_manager
        from frago.init.models import Config

        config_manager.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        config_manager.save_config(Config(init_completed=True))

        assert config_manager.load_config().init_completed is True
        assert not _is_protected(config_manager.CONFIG_PATH)

    @pytest.mark.parametrize(
        "module_name,attr",
        [
            ("frago.init.config_manager", "CONFIG_PATH"),
            ("frago.init.profile_manager", "PROFILES_PATH"),
            ("frago.init.configurator", "CLAUDE_SETTINGS_PATH"),
            ("frago.init.configurator", "CLAUDE_JSON_PATH"),
            ("frago.cli.hook_rules_commands", "RULES_PATH"),
            ("frago.def_.registry", "BOOKS_DIR"),
            ("frago.session.title_manager", "SESSIONS_JSON_PATH"),
            ("frago.recipes.usage_tracker", "USAGE_FILE"),
        ],
    )
    def test_known_real_data_constants_are_redirected(self, module_name, attr):
        """挑几个真人数据里最值钱的：API 密钥、认证、规则库、知识库。"""
        import importlib

        module = importlib.import_module(module_name)
        assert not _is_protected(getattr(module, attr)), (
            f"{module_name}.{attr} 仍指向真人数据位置"
        )


class TestWriteGuard:
    """漏网兜底：判定函数必须认得出真人数据位置。"""

    @pytest.mark.parametrize("target", _PROTECTED_PATHS)
    def test_protected_roots_are_recognised(self, target):
        assert _is_protected(target)

    @pytest.mark.parametrize(
        "target",
        [
            _REAL_HOME / ".frago" / "config.json",
            _REAL_HOME / ".frago" / "profiles.json",
            _REAL_HOME / ".frago" / "books" / "registry.json",
            _REAL_HOME / ".claude" / "settings.json",
            _REAL_HOME / ".claude.json",
        ],
    )
    def test_files_under_protected_roots_are_recognised(self, target):
        assert _is_protected(target)

    @pytest.mark.parametrize(
        "target",
        [
            Path("/tmp/whatever.json"),
            _REAL_HOME / "Repos" / "frago" / "pyproject.toml",
            _REAL_HOME / "Documents" / "note.txt",
        ],
    )
    def test_unrelated_paths_are_not_flagged(self, target):
        """仓库自身在 ~/Repos 下，NEVER 因为在家目录内就被误拦。"""
        assert not _is_protected(target)

    def test_writing_real_config_raises(self):
        """守门人真的拦得住 —— 直接对着真人配置发起写入，必须炸。"""
        with pytest.raises(RuntimeError, match="20260725"):
            (_REAL_HOME / ".frago" / "config.json").write_text("{}")

    def test_opening_real_config_for_write_raises(self):
        # 故意不套 with：守门人必须在 open 返回之前就炸掉，
        # 真拿到句柄就说明防护已经失守。
        with pytest.raises(RuntimeError, match="真人数据"):
            open(_REAL_HOME / ".frago" / "config.json", "w")  # noqa: SIM115

    def test_deleting_real_config_raises(self):
        with pytest.raises(RuntimeError, match="真人数据"):
            (_REAL_HOME / ".frago" / "config.json").unlink()

    def test_reading_is_still_allowed(self):
        """只拦写与删。读不毁数据，且少数用例确实要读真实布局。"""
        target = _REAL_HOME / ".frago"
        assert _is_protected(target)
        target.exists()  # 不抛
