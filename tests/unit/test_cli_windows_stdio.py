"""Regression tests for Windows UTF-8 stdio reconfiguration idempotency."""

from __future__ import annotations

import gc
import io
import platform
import sys

from frago.cli import main as cli_main


def test_force_utf8_stdio_on_windows_is_idempotent_with_reconfigure(monkeypatch):
    """Calling _force_utf8_stdio_on_windows() twice (main() -> cli()) must not
    close the shared underlying buffer and must leave stdout/stderr in UTF-8."""
    raw_out = io.BytesIO()
    raw_err = io.BytesIO()
    fake_out = io.TextIOWrapper(raw_out, encoding="cp1252")
    fake_err = io.TextIOWrapper(raw_err, encoding="cp1252")

    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(sys, "stdout", fake_out)
    monkeypatch.setattr(sys, "stderr", fake_err)

    cli_main._force_utf8_stdio_on_windows()
    cli_main._force_utf8_stdio_on_windows()
    gc.collect()

    assert sys.stdout is fake_out
    assert sys.stderr is fake_err
    assert sys.stdout.encoding.lower().replace("_", "-") == "utf-8"
    assert sys.stderr.encoding.lower().replace("_", "-") == "utf-8"

    sys.stdout.write("中文输出 ✓\n")
    sys.stdout.flush()
    sys.stderr.write("错误提示 ✗\n")
    sys.stderr.flush()

    assert raw_out.getvalue().decode("utf-8") == "中文输出 ✓\n"
    assert raw_err.getvalue().decode("utf-8") == "错误提示 ✗\n"


def test_force_utf8_stdio_on_windows_fallback_without_reconfigure_is_idempotent(monkeypatch):
    """Even if a stream lacks reconfigure(), repeated calls must not wrap twice
    or GC-close the underlying buffer."""
    raw_out = io.BytesIO()
    raw_err = io.BytesIO()

    class _NoReconfigureStream:
        def __init__(self, buf: io.BytesIO, encoding: str = "cp1252") -> None:
            self.buffer = buf
            self.encoding = encoding

    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(sys, "stdout", _NoReconfigureStream(raw_out))
    monkeypatch.setattr(sys, "stderr", _NoReconfigureStream(raw_err))
    saved_retained = list(cli_main._RETAINED_STDIO_STREAMS)
    try:
        cli_main._force_utf8_stdio_on_windows()
        first_out = sys.stdout
        first_err = sys.stderr

        cli_main._force_utf8_stdio_on_windows()
        gc.collect()

        assert sys.stdout is first_out
        assert sys.stderr is first_err
        assert sys.stdout.encoding.lower().replace("_", "-") == "utf-8"
        assert sys.stderr.encoding.lower().replace("_", "-") == "utf-8"

        sys.stdout.write("表格边框 ┌─┐\n")
        sys.stdout.flush()
        sys.stderr.write("告警信息\n")
        sys.stderr.flush()

        assert raw_out.getvalue().decode("utf-8") == "表格边框 ┌─┐\n"
        assert raw_err.getvalue().decode("utf-8") == "告警信息\n"
    finally:
        cli_main._RETAINED_STDIO_STREAMS[:] = saved_retained
