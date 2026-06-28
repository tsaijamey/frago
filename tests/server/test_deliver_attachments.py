"""Phase 8（spec 20260627 交付即核心）：交付层 drain 附件并逐条经 notify_recipe 投递。

覆盖：TaskLifecycle.deliver 把 outbox 制品作为独立 notify 调用发送（文本一条 +
每个附件一条）；image/file/dir 分别映射到 image_path / file_path（dir 先打 zip）。
"""

from __future__ import annotations

import pytest

from frago.server.services.task_lifecycle import TaskLifecycle


class _RecordingRunner:
    """记录每次 notify_recipe 调用的 params。"""

    calls: list[dict] = []

    def run(self, recipe, params=None):  # noqa: ARG002
        type(self).calls.append(params or {})
        return {"status": "ok"}


@pytest.fixture(autouse=True)
def _patch_runner(monkeypatch):
    _RecordingRunner.calls = []
    import frago.recipes.runner as runner_mod

    monkeypatch.setattr(runner_mod, "RecipeRunner", _RecordingRunner)
    monkeypatch.setattr(
        TaskLifecycle, "_resolve_notify_recipe",
        staticmethod(lambda _channel: "fake_notify"),
    )


def test_text_plus_file_attachment_each_one_call(tmp_path):
    f = tmp_path / "report.md"
    f.write_text("data", encoding="utf-8")
    lc = TaskLifecycle()
    res = lc.deliver(
        "feishu",
        {"text": "done"},
        reply_context={"chat_id": "c1"},
        attachments=[{"kind": "file", "path": str(f)}],
    )
    assert res["status"] == "ok"
    assert len(_RecordingRunner.calls) == 2
    # 第一条是文本正文。
    assert _RecordingRunner.calls[0]["text"] == "done"
    # 第二条是文件附件。
    assert _RecordingRunner.calls[1]["file_path"] == str(f)
    assert _RecordingRunner.calls[1]["reply_context"] == {"chat_id": "c1"}


def test_image_attachment_uses_image_path(tmp_path):
    img = tmp_path / "chart.png"
    img.write_text("x", encoding="utf-8")
    TaskLifecycle().deliver(
        "feishu", {"text": "see chart"},
        attachments=[{"kind": "image", "path": str(img)}],
    )
    assert _RecordingRunner.calls[1]["image_path"] == str(img)


def test_dir_attachment_zipped_to_file(tmp_path):
    d = tmp_path / "build"
    d.mkdir()
    (d / "a.txt").write_text("a", encoding="utf-8")
    TaskLifecycle().deliver(
        "feishu", {"text": "bundle"},
        attachments=[{"kind": "dir", "path": str(d)}],
    )
    fp = _RecordingRunner.calls[1]["file_path"]
    assert fp.endswith(".zip")
    from pathlib import Path

    assert Path(fp).exists()


def test_missing_attachment_path_skipped(tmp_path):
    TaskLifecycle().deliver(
        "feishu", {"text": "hi"},
        attachments=[{"kind": "file", "path": str(tmp_path / "ghost.md")}],
    )
    # 只发了文本，缺失文件被跳过。
    assert len(_RecordingRunner.calls) == 1
    assert _RecordingRunner.calls[0]["text"] == "hi"


def test_empty_text_with_attachment_sends_only_attachment(tmp_path):
    f = tmp_path / "x.md"
    f.write_text("x", encoding="utf-8")
    TaskLifecycle().deliver(
        "feishu", {"text": "  "},
        attachments=[{"kind": "file", "path": str(f)}],
    )
    assert len(_RecordingRunner.calls) == 1
    assert _RecordingRunner.calls[0]["file_path"] == str(f)
