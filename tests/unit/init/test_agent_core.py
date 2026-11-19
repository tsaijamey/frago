"""kernel_installed / core_installed / known_agent_cores 的真源单测。"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from frago.init import agent_core, hook_binary, opencode_plugin
from frago.init.models import Config, known_agent_cores
from frago.session.models import ACTIVE_AGENT_TYPES


class TestKnownAgentCores:
    def test_returns_only_active_five_cores_excluding_reserved_placeholders(self) -> None:
        cores = known_agent_cores()
        assert cores == {t.value for t in ACTIVE_AGENT_TYPES}
        assert cores == {"claude", "opencode", "codex", "coreagent", "agy"}
        assert "cursor" not in cores
        assert "cline" not in cores

    def test_config_rejects_reserved_placeholders(self) -> None:
        for reserved in ("cursor", "cline"):
            with pytest.raises(ValueError):
                Config(agent_core=reserved)


class TestKernelInstalledReadOnly:
    def test_empty_home_does_not_create_frago_bin_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        assert agent_core.kernel_installed() is False
        assert agent_core.core_installed("coreagent") is False
        assert not (tmp_path / ".frago" / "bin").exists()
        assert not (tmp_path / ".frago").exists()

    def test_returns_true_when_kernel_binary_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        bin_dir = tmp_path / ".frago" / "bin"
        bin_dir.mkdir(parents=True)
        binary = bin_dir / hook_binary.get_binary_name()
        binary.write_bytes(b"#!/bin/sh\n")

        assert agent_core.kernel_installed() is True
        assert agent_core.core_installed("coreagent") is True


class TestCoreInstalledAlignment:
    def test_agy_found_in_local_bin_via_unified_probe(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        local_bin = tmp_path / ".local" / "bin"
        local_bin.mkdir(parents=True)
        agy_bin = local_bin / "agy"
        agy_bin.write_text("#!/bin/sh\n", encoding="utf-8")
        agy_bin.chmod(agy_bin.stat().st_mode | stat.S_IXUSR)

        assert agent_core.core_installed("agy") is True

    def test_opencode_respects_config_dir_semantic(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from frago.agent_driver.driver import AgentDriver, PaneMatcher

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setattr(opencode_plugin.shutil, "which", lambda _: None)
        dummy = PaneMatcher(name="x", pattern="x")
        fake_opencode = AgentDriver(
            agent_type="opencode",
            display_name="opencode",
            locate=lambda: None,
            launch_command=lambda _ctx: "opencode",
            ready_signal=dummy,
            submit=lambda _s, _p: None,
            done_signal=dummy,
            extract=lambda _p: "",
        )
        monkeypatch.setattr(
            "frago.agent_driver.driver.registered_drivers",
            lambda: {"opencode": fake_opencode},
        )

        # 空 HOME 且 locate 为 None、PATH 无 opencode 时为 False
        assert agent_core.core_installed("opencode") is False

        # 仅有 ~/.config/opencode 目录时，按 is_opencode_present 配置目录语义返回 True
        (tmp_path / ".config" / "opencode").mkdir(parents=True)
        assert os.path.isdir(tmp_path / ".config" / "opencode")
        assert agent_core.core_installed("opencode") is True
