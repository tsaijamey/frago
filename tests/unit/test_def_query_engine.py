"""Single-document rendering for knowledge domains (frago <domain> find --name=)."""

from __future__ import annotations

from pathlib import Path

from frago.def_.query_engine import find


def _write_doc(domain_dir: Path, name: str, entries: list[str]) -> None:
    domain_dir.mkdir(parents=True, exist_ok=True)
    body = f"---\nname: {name}\n---\n\nentries:\n"
    for e in entries:
        body += f"- '{e}'\n"
    (domain_dir / f"{name}.md").write_text(body, encoding="utf-8")


def test_explicit_misc_marker_renders(tmp_path: Path) -> None:
    """``[[[misc]]][[text]]`` sits beside real relations without killing the view.

    An entry can reach the misc group two ways — written bare, or written with
    an explicit marker. The second kind used to raise KeyError('content') and
    take the whole document down with it, so every failure-mode doc that had
    one was unreadable through the only command that prints one.
    """
    domain = tmp_path / "d"
    _write_doc(
        domain,
        "doc",
        [
            "[[[cause]]][[起因]][[结果]]",
            "[[[misc]]][[判据：命令会改用户环境而用户没点名 → 停]]",
        ],
    )

    out = find(domain_dir=domain, schema={}, filters={"name": "doc"})

    assert "起因 → 结果" in out
    assert "判据：命令会改用户环境而用户没点名 → 停" in out


def test_bare_entry_still_renders_beside_relations(tmp_path: Path) -> None:
    """Unmarked entries keep printing as plain text."""
    domain = tmp_path / "d"
    _write_doc(domain, "doc", ["[[[cause]]][[起因]][[结果]]", "一句没有标记的话"])

    out = find(domain_dir=domain, schema={}, filters={"name": "doc"})

    assert "一句没有标记的话" in out


def test_cross_reference_keeps_the_rest_of_the_sentence(tmp_path: Path) -> None:
    """A ``[[other-doc]]`` link inside the text must not truncate the entry.

    Pairing brackets naively closed the field at the link's own ``]]`` and
    dropped everything after it, so the doc read as if it ended mid-sentence.
    """
    domain = tmp_path / "d"
    _write_doc(
        domain,
        "doc",
        ["[[[constraint]]][[这条跟 [[layout-copied]] 不是一回事]][[那条讲版式，这条讲视角]]"],
    )

    out = find(domain_dir=domain, schema={}, filters={"name": "doc"})

    assert "这条跟 [[layout-copied]] 不是一回事 → 那条讲版式，这条讲视角" in out


def test_unbalanced_brackets_keep_their_text(tmp_path: Path) -> None:
    """A half-written marker still shows its text instead of rendering blank."""
    domain = tmp_path / "d"
    _write_doc(domain, "doc", ["[[[cause]]][[没写完的一句"])

    out = find(domain_dir=domain, schema={}, filters={"name": "doc"})

    assert "没写完的一句" in out
