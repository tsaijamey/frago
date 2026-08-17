"""The published list, and what a published page is allowed to say.

Publishing is the one place in frago where a decision made on a personal machine
becomes visible to strangers, so the tests here are about what does *not* leave
the box as much as what does.
"""

import pytest

from frago.recipes import publish as pub


@pytest.fixture(autouse=True)
def registry(tmp_path, monkeypatch):
    monkeypatch.setattr(pub, "PUBLISHED_PATH", tmp_path / "published.json")
    monkeypatch.setattr(pub, "_cache", None, raising=False)


class TestList:
    def test_nothing_is_published_by_default(self):
        assert pub.load() == {}
        assert pub.published_slot("anything") is None

    def test_publish_then_read_back(self):
        entry = pub.publish("weekly_report")
        assert entry["slot"] == "default"
        assert pub.published_slot("weekly_report") == "default"
        assert pub.is_published("weekly_report")

    def test_publish_names_one_slot_only(self):
        pub.publish("weekly_report", slot="public_view")
        assert pub.is_published("weekly_report", "public_view")
        assert not pub.is_published("weekly_report", "acme_client")

    def test_unpublish_removes_it(self):
        pub.publish("weekly_report")
        assert pub.unpublish("weekly_report") is True
        assert pub.published_slot("weekly_report") is None

    def test_unpublish_is_quiet_about_what_was_never_there(self):
        assert pub.unpublish("never_published") is False

    def test_a_later_edit_is_seen_without_restart(self):
        """The list is read on every anonymous request; a stale cache is an outage
        in one direction and a leak in the other."""
        pub.publish("a")
        assert pub.published_slot("a") == "default"
        pub.unpublish("a")
        assert pub.published_slot("a") is None

    @pytest.mark.parametrize("name", ["../../etc/passwd", "a/b", "..", "", "with space"])
    def test_a_name_that_could_escape_is_simply_not_published(self, name):
        """Reached straight from a URL path, so this must answer rather than raise."""
        assert pub.published_slot(name) is None

    def test_a_corrupt_file_publishes_nothing(self):
        pub.published_path().parent.mkdir(parents=True, exist_ok=True)
        pub.published_path().write_text("{ not json", encoding="utf-8")
        assert pub.load() == {}


class TestPublicView:
    def test_absolute_paths_never_reach_a_visitor(self):
        """dataDir is how the page's files are found server-side; the visitor
        gets the files, never the layout of the disk."""
        state = {"dataDir": "/Users/someone/.frago/data/client-x", "public": {"title": "Q3"}}
        assert pub.public_view(state) == {"title": "Q3"}

    def test_a_slot_that_declares_nothing_public_says_nothing(self):
        state = {"dataDir": "/private", "apiKey": "sk-live-123", "rows": [1, 2, 3]}
        assert pub.public_view(state) == {}

    def test_a_non_dict_public_block_is_refused(self):
        assert pub.public_view({"public": ["title"]}) == {}
        assert pub.public_view({"public": "yes"}) == {}

    def test_the_returned_view_is_a_copy(self):
        state = {"public": {"title": "Q3"}}
        view = pub.public_view(state)
        view["title"] = "tampered"
        assert state["public"]["title"] == "Q3"


class TestSlotStateOnDisk:
    """Found by audit 20260817: slot state was written 0644.

    It is the document that holds the absolute paths and occasionally the keys —
    the very reason a published page is served a filtered copy instead. On a
    server, where a deploy user and a CI runner share the box, world-readable
    means the filesystem hands over what the HTTP gate refuses.
    """

    @pytest.fixture(autouse=True)
    def state_dir(self, tmp_path, monkeypatch):
        from frago.recipes import app_state

        directory = tmp_path / "app-state"
        monkeypatch.setattr(app_state, "APP_STATE_DIR", directory)
        return directory

    def test_a_published_slot_is_owner_only(self, state_dir):
        import os

        from frago.recipes import app_state

        if os.name == "nt":
            pytest.skip("POSIX permission bits")
        path = app_state.publish("probe", {"apiKey": "sk-live-xyz"})
        assert path.stat().st_mode & 0o077 == 0

    def test_the_state_directory_is_owner_only(self, state_dir):
        import os

        from frago.recipes import app_state

        if os.name == "nt":
            pytest.skip("POSIX permission bits")
        app_state.publish("probe", {"a": 1})
        assert state_dir.stat().st_mode & 0o077 == 0

    def test_a_slot_written_by_an_older_frago_is_tightened_on_rewrite(self, state_dir):
        import os

        from frago.recipes import app_state

        if os.name == "nt":
            pytest.skip("POSIX permission bits")
        path = app_state.publish("probe", {"a": 1})
        path.chmod(0o644)
        app_state.publish("probe", {"a": 2})
        assert path.stat().st_mode & 0o077 == 0

    def test_the_content_still_round_trips(self, state_dir):
        from frago.recipes import app_state

        app_state.publish("probe", {"dataDir": "/x", "public": {"t": "中文"}})
        assert app_state.read("probe") == {"dataDir": "/x", "public": {"t": "中文"}}


class TestDangerousDataDir:
    """Found by audit 20260817: a slot whose dataDir was `~/.frago` served the
    real config.json through the published page. Publishing hands over the whole
    directory, so a handful of directories must simply be refused."""

    @pytest.fixture
    def audit(self):
        from frago.cli.recipe_commands import _dangerous_data_dir

        return _dangerous_data_dir

    @pytest.mark.parametrize(
        "target",
        [".frago", ".claude", ".ssh"],
    )
    def test_frago_and_friends_are_refused(self, audit, target):
        from pathlib import Path

        refusal = audit(Path.home() / target)
        assert refusal is not None
        assert "Refusing to publish" in refusal

    def test_the_home_directory_is_refused(self, audit):
        from pathlib import Path

        assert audit(Path.home()) is not None

    def test_the_filesystem_root_is_refused(self, audit):
        from pathlib import Path

        assert audit(Path("/")) is not None

    def test_an_ordinary_output_directory_is_fine(self, audit, tmp_path):
        assert audit(tmp_path / "20260817-report") is None

    def test_a_recipes_own_data_directory_is_fine(self, audit):
        from pathlib import Path

        assert audit(Path.home() / ".frago" / "data" / "acme" / "20260817-q3") is None
