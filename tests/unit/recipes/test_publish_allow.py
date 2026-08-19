"""`allow` and `runnable`: the two fields that decide people rather than data.

`allow` has four states and they are easy to collapse into two by accident —
absent and empty both look like "nothing there" to a careless reader, and they
mean opposite things. So most of these tests are about a damaged or hand-edited
entry landing on the strict side, which is the direction the previous audit
found this codebase failing.
"""

import pytest

from frago.recipes import publish as pub

ZHANG = "a1b2c3d4e5f6"
LI = "ffff0000ffff"


@pytest.fixture(autouse=True)
def registry(tmp_path, monkeypatch):
    monkeypatch.setattr(pub, "PUBLISHED_PATH", tmp_path / "published.json")
    monkeypatch.setattr(pub, "_cache", None, raising=False)


def _write_raw(entry):
    """Put an entry on disk the way a hand-edit or an older frago would."""
    import json

    pub.published_path().write_text(json.dumps({"page": entry}), encoding="utf-8")
    pub._cache = None


class TestTheFourStatesOfAllow:
    def test_an_old_entry_without_the_field_admits_everyone_it_used_to(self):
        _write_raw({"slot": "default", "mode": "identity"})
        entry = pub.published_entry("page")
        assert entry["allow"] is None
        assert pub.allows(entry, ZHANG) is True

    def test_null_says_the_same_thing_on_purpose(self):
        _write_raw({"slot": "default", "mode": "identity", "allow": None})
        assert pub.allows(pub.published_entry("page"), ZHANG) is True

    def test_a_list_admits_only_those_accounts(self):
        pub.publish("page", mode=pub.MODE_IDENTITY, allow=[ZHANG])
        entry = pub.published_entry("page")
        assert pub.allows(entry, ZHANG) is True
        assert pub.allows(entry, LI) is False

    def test_an_empty_list_admits_nobody(self):
        """Unreachable through the CLI. It is where a damaged config lands, and
        landing at "nobody" is the only safe reading of an unreadable rule."""
        _write_raw({"slot": "default", "mode": "identity", "allow": []})
        entry = pub.published_entry("page")
        assert entry["allow"] == []
        assert pub.allows(entry, ZHANG) is False


class TestDamagedEntriesLandOnTheStrictSide:
    @pytest.mark.parametrize("broken", [
        "zhang",                 # a string, not a list
        123,
        {"id": ZHANG},
        [ZHANG, 7],              # one good element and one that is not
        [ZHANG, ""],             # an empty id would match nobody, or everybody
        [[ZHANG]],
    ])
    def test_anything_unreadable_becomes_nobody(self, broken):
        """NEVER salvage the recognisable half of a broken list: the half that
        did not parse might have been the restriction that mattered."""
        _write_raw({"slot": "default", "mode": "identity", "allow": broken})
        entry = pub.published_entry("page")
        assert entry["allow"] == []
        assert pub.allows(entry, ZHANG) is False


class TestRunnable:
    def test_absent_is_false(self):
        _write_raw({"slot": "default", "mode": "identity"})
        assert pub.published_entry("page")["runnable"] is False

    def test_it_can_be_turned_on_with_identity(self):
        pub.publish("page", mode=pub.MODE_IDENTITY, runnable=True)
        assert pub.published_entry("page")["runnable"] is True

    def test_public_mode_contradicts_it_and_loses(self):
        """Only reachable by hand-editing. A run happens for somebody, and a
        public page has nobody to run as."""
        _write_raw({"slot": "default", "mode": "public", "runnable": True})
        assert pub.published_entry("page")["runnable"] is False

    @pytest.mark.parametrize("truthy", ["true", "false", 1, "no", [1], {"a": 1}])
    def test_only_a_real_boolean_true_counts(self, truthy):
        """`"false"`, `1` and `"no"` are all truthy, and every one of them is a
        hand-edit that meant the opposite."""
        _write_raw({"slot": "default", "mode": "identity", "runnable": truthy})
        assert pub.published_entry("page")["runnable"] is False


class TestAllowsIsTheOnlyComparison:
    def test_a_public_page_is_not_opened_by_identity(self):
        """Not because such a page is closed — anonymous readability is a
        different branch's question entirely."""
        pub.publish("page", mode=pub.MODE_PUBLIC)
        assert pub.allows(pub.published_entry("page"), ZHANG) is False

    def test_no_identity_is_never_allowed(self):
        pub.publish("page", mode=pub.MODE_IDENTITY)
        entry = pub.published_entry("page")
        assert pub.allows(entry, None) is False
        assert pub.allows(entry, "") is False

    def test_an_absent_entry_is_never_allowed(self):
        assert pub.allows(None, ZHANG) is False

    def test_it_takes_a_raw_entry_as_happily_as_a_normalised_one(self):
        pub.publish("page", mode=pub.MODE_IDENTITY, allow=[ZHANG])
        raw = pub.load()["page"]
        assert pub.allows(raw, ZHANG) == pub.allows(pub.published_entry("page"), ZHANG)


class TestWhatPublishRefusesToWrite:
    def test_an_empty_allow_list_is_refused(self):
        """A page nobody may open is spelled `unexpose`, not an entry the next
        reader has to puzzle over."""
        with pytest.raises(ValueError, match="unexpose"):
            pub.publish("page", mode=pub.MODE_IDENTITY, allow=[])

    def test_an_allow_list_needs_identity_mode(self):
        with pytest.raises(ValueError, match="identity"):
            pub.publish("page", mode=pub.MODE_PUBLIC, allow=[ZHANG])

    def test_runnable_needs_identity_mode(self):
        with pytest.raises(ValueError, match="identity"):
            pub.publish("page", mode=pub.MODE_PUBLIC, runnable=True)

    @pytest.mark.parametrize("bad", ["zhang", [ZHANG, 7], [""], {"a": 1}])
    def test_a_malformed_allow_list_is_refused_at_the_door(self, bad):
        with pytest.raises(ValueError):
            pub.publish("page", mode=pub.MODE_IDENTITY, allow=bad)


class TestOldEntriesKeepWorking:
    def test_a_pre_field_public_entry_behaves_exactly_as_before(self):
        _write_raw({"slot": "default", "since": "2026-08-01T00:00:00+08:00"})
        entry = pub.published_entry("page")
        assert entry["mode"] == pub.MODE_PUBLIC
        assert pub.published_slot("page") == "default"
        assert entry["allow"] is None
        assert entry["runnable"] is False
