"""Unit tests for frago.todo.store — fully isolated via FRAGO_TODO_DIR."""

import json

import pytest

from frago.todo import store


@pytest.fixture(autouse=True)
def _isolate_todo_dir(tmp_path, monkeypatch):
    """Isolate the todo dir to a tmp path for every test (via FRAGO_TODO_DIR)."""
    monkeypatch.setenv("FRAGO_TODO_DIR", str(tmp_path))


def test_add_creates_file_with_defaults(tmp_path):
    todo = store.add("add chrome fill command")
    assert todo.id.endswith("-add-chrome-fill-command")
    assert todo.status == "todo"
    assert todo.priority == "normal"
    assert todo.created == todo.updated
    assert todo.done_at is None

    path = tmp_path / f"{todo.id}.json"
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["title"] == "add chrome fill command"
    assert data["tags"] == []


def test_add_validates_priority_and_status():
    with pytest.raises(ValueError):
        store.add("x", priority="urgent")
    with pytest.raises(ValueError):
        store.add("x", status="archived")
    with pytest.raises(ValueError):
        store.add("   ")


def test_slug_dedup_same_title_same_day():
    a = store.add("same title")
    b = store.add("same title")
    c = store.add("same title")
    assert a.id != b.id != c.id
    assert b.id == f"{a.id}-2"
    assert c.id == f"{a.id}-3"


def test_cjk_title_transliterated_by_slugify(tmp_path):
    # python-slugify transliterates CJK via unidecode; id stays ascii-safe.
    todo = store.add("加 chrome fill 命令")
    assert " " not in todo.id
    assert (tmp_path / f"{todo.id}.json").exists()


def test_slug_is_ascii_and_length_capped():
    # i18n: a long non-Latin title must yield a short, ASCII-only slug.
    todo = store.add("调研上海万得在 AI agent 方面的近况，包含商业模式与监管边界")
    slug = todo.id.split("-", 1)[1]  # drop the YYYYMMDD prefix
    assert slug.isascii(), f"slug must be ASCII for portability, got {slug!r}"
    assert len(slug) <= store.SLUG_MAX_LENGTH
    assert not slug.endswith("-")  # word_boundary must not leave a trailing sep


def test_latin_title_stays_readable():
    todo = store.add("add chrome fill command")
    assert todo.id.endswith("-add-chrome-fill-command")  # short Latin title intact


def test_resolve_id_exact_prefix_ambiguous_missing():
    a = store.add("alpha one")
    store.add("alpha two")
    # exact
    assert store.resolve_id(a.id) == a.id
    # unique prefix
    assert store.resolve_id(a.id[:-2]) == a.id  # trim last chars -> still unique to 'one'
    # ambiguous prefix (shared date prefix matches both)
    with pytest.raises(ValueError):
        store.resolve_id(a.id[:8])  # YYYYMMDD shared by both
    # missing
    with pytest.raises(KeyError):
        store.resolve_id("nonexistent-zzz")


def test_list_filters_and_priority_sort():
    store.add("low one", priority="low")
    store.add("high one", priority="high")
    store.add("normal one", priority="normal")

    ordered = [t.priority for t in store.list_todos()]
    assert ordered == ["high", "normal", "low"]  # semantic order, not lexical

    highs = store.list_todos(priority="high")
    assert len(highs) == 1 and highs[0].priority == "high"


def test_list_filters_by_status_and_tag():
    store.add("tagged", tags=["cli", "todo"])
    store.add("untagged")
    store.add("doing one", status="doing")

    assert len(store.list_todos(tag="cli")) == 1
    assert len(store.list_todos(status="doing")) == 1


def test_mark_done_stamps_and_is_idempotent():
    todo = store.add("finish me")
    done = store.mark_done(todo.id)
    assert done.status == "done"
    assert done.done_at == done.updated
    first_stamp = done.done_at

    again = store.mark_done(todo.id)
    assert again.done_at == first_stamp  # idempotent, original stamp kept


def test_update_refreshes_updated_and_stamps_done():
    todo = store.add("editable")
    updated = store.update(todo.id, priority="high", status="done", tags=["a"])
    assert updated.priority == "high"
    assert updated.tags == ["a"]
    assert updated.status == "done"
    assert updated.done_at is not None


def test_update_rejects_bad_field_and_value():
    todo = store.add("guard")
    with pytest.raises(ValueError):
        store.update(todo.id, status="nope")
    with pytest.raises(ValueError):
        store.update(todo.id, bogus="x")


def test_next_picks_highest_priority_oldest_active():
    store.add("low", priority="low")
    high = store.add("high", priority="high")
    store.add("done high", priority="high", status="done")

    nxt = store.next_todo()
    assert nxt is not None
    assert nxt.id == high.id  # done one skipped, high beats low


def test_next_none_when_no_active():
    store.add("x", status="done")
    store.add("y", status="dropped")
    assert store.next_todo() is None


def test_remove_deletes_file(tmp_path):
    todo = store.add("delete me")
    removed_id = store.remove(todo.id[:12])  # prefix
    assert removed_id == todo.id
    assert not (tmp_path / f"{todo.id}.json").exists()


def test_list_ignores_md_and_skips_malformed(tmp_path, capsys):
    store.add("valid")
    (tmp_path / "20260408-legacy.md").write_text("# old md todo")  # ignored
    (tmp_path / "20260601-broken.json").write_text("{not json")  # skipped+warn

    todos = store.list_todos()
    assert len(todos) == 1
    assert todos[0].title == "valid"
    assert "malformed" in capsys.readouterr().err


def test_load_tolerates_missing_fields(tmp_path):
    # Hand-written minimal file (only title) should load with defaults.
    (tmp_path / "20260601-minimal.json").write_text('{"title": "minimal"}')
    todo = store.get("20260601-minimal")
    assert todo.title == "minimal"
    assert todo.status == "todo"
    assert todo.id == "20260601-minimal"  # id derived from filename


# ── 分类 ────────────────────────────────────────────────────────────────
# 分类清单存在 config.json 里；conftest 已把 config_manager.CONFIG_PATH 改指到
# 本用例的临时目录，这里不再另打桩。

from frago.todo import categories  # noqa: E402


def _set_created(todo, created):
    """建事务那天都是今天，排序里「早建的在前」要靠手改文件才测得出来。"""
    path = store.todo_dir() / f"{todo.id}.json"
    data = json.loads(path.read_text())
    data["created"] = created
    path.write_text(json.dumps(data))


def test_default_categories_when_unconfigured():
    assert [(c.id, c.name) for c in categories.list_categories()] == [
        ("family", "家庭"), ("work", "工作"), ("hobby", "个人喜好"), ("other", "其他"),
    ]


def test_sort_category_then_priority_then_created():
    work_low = store.add("work low", priority="low", category="work")
    family_low = store.add("family low", priority="low", category="family")
    loose_high = store.add("uncategorized high", priority="high")
    work_high_new = store.add("work high new", priority="high", category="work")
    work_high_old = store.add("work high old", priority="high", category="work")
    _set_created(work_high_new, "2026-09-02")
    _set_created(work_high_old, "2026-09-01")

    ids = [t.id for t in store.list_todos()]
    assert ids == [
        family_low.id,
        work_high_old.id,
        work_high_new.id,
        work_low.id,
        loose_high.id,  # 未分类排在所有分类之后，哪怕它是高优先
    ]
    assert store.next_todo().id == family_low.id


def test_reordering_categories_reorders_list():
    a = store.add("a", category="family")
    b = store.add("b", category="work")
    categories.move_category("work", 1)
    assert [t.id for t in store.list_todos()] == [b.id, a.id]


def test_legacy_file_without_category_still_loads(tmp_path):
    (tmp_path / "20250101-legacy.json").write_text(json.dumps({
        "title": "legacy", "status": "todo", "priority": "high",
        "tags": [], "created": "2025-01-01", "updated": "2025-01-01",
    }))
    store.add("categorized", priority="low", category="other")
    todos = store.list_todos()
    assert [t.title for t in todos] == ["categorized", "legacy"]
    assert todos[1].category is None


def test_unknown_category_sorts_as_uncategorized_but_is_kept(tmp_path):
    orphan = store.add("orphan", priority="high", category="hobby")
    loose = store.add("loose", priority="low")
    kept = store.add("kept", priority="low", category="other")
    categories.remove_category("hobby")

    assert [t.id for t in store.list_todos()] == [kept.id, orphan.id, loose.id]
    assert json.loads((tmp_path / f"{orphan.id}.json").read_text())["category"] == "hobby"
    assert {t.id for t in store.list_todos(category="none")} == {orphan.id, loose.id}


def test_category_must_be_in_list():
    with pytest.raises(ValueError, match="family"):
        store.add("x", category="nope")
    todo = store.add("x")
    with pytest.raises(ValueError, match="unknown category"):
        store.update(todo.id, category="nope")


def test_update_can_set_and_clear_category():
    todo = store.add("x", category="work")
    assert store.update(todo.id, category="family").category == "family"
    assert store.update(todo.id, category="").category is None


def test_category_list_limits_and_validation():
    for i in range(16):
        categories.add_category(f"c{i}", f"分类{i}")
    assert len(categories.list_categories()) == 20
    with pytest.raises(ValueError, match="at most 20"):
        categories.add_category("c99", "多一个")
    with pytest.raises(ValueError, match="duplicate"):
        categories.save_categories([categories.Category("a", "甲"), categories.Category("a", "乙")])
    with pytest.raises(ValueError, match="reserved"):
        categories.save_categories([categories.Category("none", "无")])
    with pytest.raises(ValueError, match="display name"):
        categories.save_categories([categories.Category("a", "  ")])


def test_rename_keeps_todos_attached():
    todo = store.add("x", category="hobby")
    categories.rename_category("hobby", "爱好")
    assert store.get(todo.id).category == "hobby"
    assert categories.list_categories()[2].name == "爱好"


def test_saving_categories_keeps_other_config_sections():
    from frago.init import config_manager

    path = config_manager.CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"daemons": {"enabled": True, "items": []}}))
    categories.add_category("study", "学习", position=1)
    data = json.loads(path.read_text())
    assert data["daemons"] == {"enabled": True, "items": []}
    assert data["todo_categories"][0] == {"id": "study", "name": "学习"}


def test_categorize_rejects_whole_batch_and_writes_nothing():
    a = store.add("a")
    b = store.add("b", category="work")
    with pytest.raises(store.BatchError) as exc:
        store.categorize({a.id: "family", "no-such-todo": "work", b.id: "nope"})
    assert len(exc.value.problems) == 2
    assert store.get(a.id).category is None
    assert store.get(b.id).category == "work"


def test_categorize_applies_and_reports_changes():
    a = store.add("a")
    b = store.add("b", category="work")
    c = store.add("c", category="family")
    changed, unchanged = store.categorize({a.id: "hobby", b.id: "work", c.id: None})
    assert sorted(t.id for t, _ in changed) == sorted([a.id, c.id])
    assert unchanged == 1
    assert store.get(a.id).category == "hobby"
    assert store.get(c.id).category is None


def test_schema_documents_category():
    names = [f["name"] for f in store.TODO_SCHEMA["fields"]]
    assert "category" in names
    assert "category" in store.TODO_SCHEMA["sort"]
