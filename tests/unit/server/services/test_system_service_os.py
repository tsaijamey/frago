"""Unit tests for SystemService OS-level actions relocated from routes/settings.py (Phase 2).

以单元测试为准：断言每个方法的契约（平台分派、错误抛出、命令组装），
而非迎合实现细节。subprocess 全部 mock，不真正起进程。
"""

from unittest.mock import patch

import pytest

from frago.server.services.system_service import (
    SystemService,
    UnsupportedPlatformError,
)


class TestRevealOrOpen:
    def test_darwin_reveal_uses_open_dash_r(self):
        with patch("frago.server.services.system_service.platform.system", return_value="Darwin"), \
             patch("frago.server.services.system_service.subprocess.run") as run:
            SystemService.reveal_or_open("/x/y", reveal=True)
            run.assert_called_once_with(["open", "-R", "/x/y"], check=True)

    def test_darwin_open_uses_open(self):
        with patch("frago.server.services.system_service.platform.system", return_value="Darwin"), \
             patch("frago.server.services.system_service.subprocess.run") as run:
            SystemService.reveal_or_open("/x/y", reveal=False)
            run.assert_called_once_with(["open", "/x/y"], check=True)

    def test_linux_reveal_opens_parent_dir(self):
        with patch("frago.server.services.system_service.platform.system", return_value="Linux"), \
             patch("frago.server.services.system_service.subprocess.run") as run:
            SystemService.reveal_or_open("/a/b/c.txt", reveal=True)
            run.assert_called_once_with(["xdg-open", "/a/b"], check=True)

    def test_unsupported_platform_raises(self):
        with patch("frago.server.services.system_service.platform.system", return_value="Plan9"), \
             patch("frago.server.services.system_service.subprocess.run"):
            with pytest.raises(UnsupportedPlatformError) as ei:
                SystemService.reveal_or_open("/x", reveal=False)
            assert "Plan9" in str(ei.value)


class TestOpenDirectory:
    def test_linux_uses_xdg_open(self):
        with patch("frago.server.services.system_service.platform.system", return_value="Linux"), \
             patch("frago.server.services.system_service.subprocess.run") as run:
            SystemService.open_directory("/home/u/.frago")
            run.assert_called_once_with(["xdg-open", "/home/u/.frago"], check=True)

    def test_unsupported_raises(self):
        with patch("frago.server.services.system_service.platform.system", return_value="Haiku"), \
             patch("frago.server.services.system_service.subprocess.run"):
            with pytest.raises(UnsupportedPlatformError):
                SystemService.open_directory("/x")


class TestFindVscode:
    def test_returns_path_when_code_on_path(self):
        with patch("frago.server.services.system_service.shutil.which", return_value="/usr/bin/code"):
            assert SystemService.find_vscode() == "/usr/bin/code"

    def test_darwin_app_fallback(self):
        with patch("frago.server.services.system_service.shutil.which", return_value=None), \
             patch("frago.server.services.system_service.platform.system", return_value="Darwin"), \
             patch("frago.server.services.system_service.os.path.exists", return_value=True):
            assert SystemService.find_vscode() == "/Applications/Visual Studio Code.app"

    def test_returns_none_when_absent(self):
        with patch("frago.server.services.system_service.shutil.which", return_value=None), \
             patch("frago.server.services.system_service.platform.system", return_value="Linux"):
            assert SystemService.find_vscode() is None


class TestOpenInVscode:
    def test_app_path_uses_open_dash_a(self):
        with patch("frago.server.services.system_service.subprocess.Popen") as popen:
            SystemService.open_in_vscode("/Applications/Visual Studio Code.app", "/cfg.json")
            popen.assert_called_once_with(["open", "-a", "/Applications/Visual Studio Code.app", "/cfg.json"])

    def test_binary_path_invokes_directly(self):
        with patch("frago.server.services.system_service.subprocess.Popen") as popen, \
             patch("frago.server.services.system_service.get_windows_subprocess_kwargs", return_value={}):
            SystemService.open_in_vscode("/usr/bin/code", "/cfg.json")
            args, kwargs = popen.call_args
            assert args[0] == ["/usr/bin/code", "/cfg.json"]
