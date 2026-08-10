"""The group contract: one agent, one tab group, five tabs, its own tabs only.

What these tests protect, in order of how much it costs when it breaks:

1. A group's commands land on *its* current tab — never on whatever tab
   the browser is showing, which may be the page a person is reading.
2. A group can only see and touch its own tabs. Reaching another group's
   page is the failure the whole design exists to prevent.
3. Hitting the tab ceiling fails loudly and says what is in the way.
   Silently closing the oldest tab leaves the agent believing a page is
   still open, and nothing anywhere contradicts it.

Chrome IO is mocked; only the bookkeeping is under test here. The live
browser path is covered end to end by the worker run.
"""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

import frago.browser.cdp.tab_group_manager as tgm_mod
from frago.browser.cdp.tab_group_manager import (
    DEFAULT_MAX_TABS_PER_GROUP,
    GROUP_TIMEOUT_SECONDS,
    ChromeCommandError,
    TabGroupManager,
)


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    """Redirect group state/lock files to tmp and silence landing-page push."""
    monkeypatch.setattr(tgm_mod, "STATE_FILE", tmp_path / "tab_groups.json")
    monkeypatch.setattr(tgm_mod, "LOCK_FILE", tmp_path / "tab_groups.lock")
    monkeypatch.setattr(
        TabGroupManager, "_push_to_landing_page", lambda *_a, **_kw: None
    )
    return tmp_path / "tab_groups.json"


class _FakeBrowser:
    """Enough of a browser to hand out and take back tab ids."""

    def __init__(self):
        self.tabs: list[str] = []
        self._n = 0

    def create(self, url, background=True):  # noqa: ARG002
        self._n += 1
        tid = f"tab{self._n:02d}"
        self.tabs.append(tid)
        return tid

    def close(self, tid):
        if tid in self.tabs:
            self.tabs.remove(tid)
        return True

    def session(self):
        s = MagicMock()
        s.target.create_target.side_effect = self.create
        s.target.close_target.side_effect = self.close
        return s


@pytest.fixture
def browser():
    return _FakeBrowser()


@pytest.fixture
def tgm(isolated_state, browser, monkeypatch):  # noqa: ARG001
    """A manager whose idea of "live tabs" is the fake browser's."""
    monkeypatch.setattr(
        TabGroupManager, "_get_live_target_ids", lambda *_a: set(browser.tabs)
    )
    return TabGroupManager()


# ─────────────── navigate: reuse by default, --new on request ───────────────


def test_navigate_reuses_the_groups_current_tab(tgm, browser):
    first = tgm.get_or_create_tab("https://a.example", "g1", browser.session())
    second = tgm.get_or_create_tab("https://b.example", "g1", browser.session())
    assert second == first, "navigate without --new must not open a tab"
    assert len(browser.tabs) == 1
    assert tgm.get_group("g1").tabs[first].url == "https://b.example"


def test_navigate_new_opens_another_tab_in_the_same_group(tgm, browser):
    first = tgm.get_or_create_tab("https://a.example", "g1", browser.session())
    second = tgm.get_or_create_tab("https://b.example", "g1",
                                   browser.session(), new=True)
    assert second != first
    assert len(browser.tabs) == 2
    group = tgm.get_group("g1")
    assert set(group.tabs) == {first, second}
    # The new tab becomes the one commands land on.
    assert group.current_target_id == second


def test_navigate_reuses_current_not_most_recently_created(tgm, browser):
    """After switch-tab, plain navigate replaces *that* tab.

    The distinction matters: "the group's current tab" is wherever the
    agent last pointed itself, not the newest tab and not the tab the
    browser happens to be showing.
    """
    first = tgm.get_or_create_tab("https://a.example", "g1", browser.session())
    tgm.get_or_create_tab("https://b.example", "g1", browser.session(),
                          new=True)
    tgm.switch_tab("g1", first)
    landed = tgm.get_or_create_tab("https://c.example", "g1",
                                   browser.session())
    assert landed == first
    assert len(browser.tabs) == 2


# ─────────────── the ceiling: refuse, and say what is in the way ───────────


def test_group_refuses_a_sixth_tab_and_names_the_five(tgm, browser):
    for i in range(DEFAULT_MAX_TABS_PER_GROUP):
        tgm.get_or_create_tab(f"https://{i}.example", "g1",
                              browser.session(), new=True)
    assert len(browser.tabs) == DEFAULT_MAX_TABS_PER_GROUP

    with pytest.raises(ChromeCommandError) as exc:
        tgm.get_or_create_tab("https://over.example", "g1",
                              browser.session(), new=True)

    err = exc.value
    assert err.code == "GROUP_TAB_LIMIT"
    assert len(err.context["tabs"]) == DEFAULT_MAX_TABS_PER_GROUP
    assert err.context["limit"] == DEFAULT_MAX_TABS_PER_GROUP
    # The way out has to be in the error, or the agent is simply stuck.
    assert any("close-tab" in r for r in err.context["remedies"])
    # And nothing was closed behind the agent's back.
    assert len(browser.tabs) == DEFAULT_MAX_TABS_PER_GROUP


def test_full_group_still_accepts_a_plain_navigate(tgm, browser):
    """The ceiling limits how many tabs a group holds, not what it can do."""
    for i in range(DEFAULT_MAX_TABS_PER_GROUP):
        tgm.get_or_create_tab(f"https://{i}.example", "g1",
                              browser.session(), new=True)
    reused = tgm.get_or_create_tab("https://replace.example", "g1",
                                   browser.session())
    assert reused in browser.tabs
    assert len(browser.tabs) == DEFAULT_MAX_TABS_PER_GROUP


def test_closing_a_tab_makes_room_again(tgm, browser):
    ids = [tgm.get_or_create_tab(f"https://{i}.example", "g1",
                                 browser.session(), new=True)
           for i in range(DEFAULT_MAX_TABS_PER_GROUP)]
    tgm.close_tab("g1", ids[0], browser.session())
    fresh = tgm.get_or_create_tab("https://new.example", "g1",
                                  browser.session(), new=True)
    assert fresh in browser.tabs
    assert len(tgm.get_group("g1").tabs) == DEFAULT_MAX_TABS_PER_GROUP


# ─────────────── isolation: a group only reaches its own tabs ───────────────


def test_a_group_cannot_switch_to_another_groups_tab(tgm, browser):
    mine = tgm.get_or_create_tab("https://mine.example", "g1",
                                 browser.session())
    theirs = tgm.get_or_create_tab("https://theirs.example", "g2",
                                   browser.session())

    with pytest.raises(ChromeCommandError) as exc:
        tgm.switch_tab("g1", theirs)
    assert exc.value.code == "TAB_NOT_IN_GROUP"
    # g1's own pointer is untouched.
    assert tgm.get_group("g1").current_target_id == mine


def test_a_group_cannot_close_another_groups_tab(tgm, browser):
    tgm.get_or_create_tab("https://mine.example", "g1", browser.session())
    theirs = tgm.get_or_create_tab("https://theirs.example", "g2",
                                   browser.session())

    with pytest.raises(ChromeCommandError) as exc:
        tgm.close_tab("g1", theirs, browser.session())
    assert exc.value.code == "TAB_NOT_IN_GROUP"
    assert theirs in browser.tabs, "the other group's page must survive"


def test_two_groups_keep_separate_current_tabs(tgm, browser):
    a = tgm.get_or_create_tab("https://a.example", "g1", browser.session())
    b = tgm.get_or_create_tab("https://b.example", "g2", browser.session())
    tgm.get_or_create_tab("https://a2.example", "g1", browser.session())
    assert tgm.get_current_target("g1") == a
    assert tgm.get_current_target("g2") == b


def test_tab_id_prefix_resolves_within_the_group(tgm, browser):
    full = tgm.get_or_create_tab("https://a.example", "g1", browser.session())
    assert tgm.switch_tab("g1", full[:4]) == full


# ─────────────── closing a tab: the pointer must not dangle ───────────────


def test_closing_the_current_tab_repoints_the_group(tgm, browser):
    first = tgm.get_or_create_tab("https://a.example", "g1", browser.session())
    second = tgm.get_or_create_tab("https://b.example", "g1",
                                   browser.session(), new=True)
    assert tgm.get_current_target("g1") == second

    tgm.close_tab("g1", second, browser.session())
    assert tgm.get_current_target("g1") == first
    assert second not in browser.tabs


def test_closing_the_last_tab_leaves_no_current(tgm, browser):
    only = tgm.get_or_create_tab("https://a.example", "g1", browser.session())
    tgm.close_tab("g1", only, browser.session())
    assert tgm.get_current_target("g1") is None


def test_a_tab_closed_by_hand_is_dropped_not_handed_out(tgm, browser):
    """A person closing an agent's tab must not poison the next command."""
    first = tgm.get_or_create_tab("https://a.example", "g1", browser.session())
    second = tgm.get_or_create_tab("https://b.example", "g1",
                                   browser.session(), new=True)
    browser.close(second)  # person clicks the ×; nobody tells the bookkeeping

    landed = tgm.get_or_create_tab("https://c.example", "g1",
                                   browser.session())
    assert landed == first
    assert second not in tgm.get_group("g1").tabs


# ─────────────── lifecycle: use resets the clock, silence closes ───────────


def test_any_command_on_a_group_resets_its_idle_clock(tgm, browser):
    tgm.get_or_create_tab("https://a.example", "g1", browser.session())
    group = tgm.get_group("g1")
    group.last_activity = time.time() - GROUP_TIMEOUT_SECONDS + 30
    stale = group.last_activity

    tgm.touch_group("g1")
    assert tgm.get_group("g1").last_activity > stale
    assert tgm._expired_group_names(time.time()) == []


def test_a_group_left_alone_past_the_timeout_expires(tgm, browser):
    tgm.get_or_create_tab("https://a.example", "g1", browser.session())
    tgm.get_or_create_tab("https://b.example", "g2", browser.session())
    tgm.get_group("g1").last_activity = time.time() - GROUP_TIMEOUT_SECONDS - 1
    tgm._save_state()

    assert tgm._expired_group_names(time.time()) == ["g1"]
    with patch.object(tgm_mod, "cdp_get"):
        assert tgm.cleanup_expired_groups_http() == 1
    assert set(tgm.list_groups()) == {"g2"}


def test_group_close_takes_every_tab_with_it(tgm, browser):
    for i in range(3):
        tgm.get_or_create_tab(f"https://{i}.example", "g1",
                              browser.session(), new=True)
    survivor = tgm.get_or_create_tab("https://other.example", "g2",
                                     browser.session())

    assert tgm.close_group("g1", browser.session()) is True
    assert browser.tabs == [survivor]
    assert "g1" not in tgm.list_groups()


# ─────────────── the two backends must not drift apart ───────────────


def test_service_worker_ceiling_matches_the_python_one():
    """The agent must not have to learn two different limits.

    The extension backend enforces the ceiling inside the browser, in
    JavaScript; the CDP backend enforces it in Python. Two numbers, one
    contract — if they drift, the same command succeeds or fails
    depending on which backend happens to be up.
    """
    import re
    from pathlib import Path

    import frago
    sw = (Path(frago.__file__).parent / "_resources" / "extension_bundle"
          / "background" / "service-worker-v11.js").read_text(encoding="utf-8")

    limit = re.search(r"const MAX_TABS_PER_GROUP\s*=\s*(\d+)", sw)
    assert limit, "service worker no longer declares MAX_TABS_PER_GROUP"
    assert int(limit.group(1)) == DEFAULT_MAX_TABS_PER_GROUP

    idle = re.search(r"const GROUP_IDLE_MS\s*=\s*([0-9_*\s]+);", sw)
    assert idle, "service worker no longer declares GROUP_IDLE_MS"
    assert eval(idle.group(1).replace("_", "")) == GROUP_TIMEOUT_SECONDS * 1000


def test_group_errors_are_reported_by_name_with_a_usable_way_out():
    """An error an agent cannot act on is a dead end.

    Two things went wrong here before and both are worth a test. The
    bridge reported bare numbers (`-32003`) while the books documented
    `TAB_NOT_IN_GROUP`, so an agent matching what the docs promised
    never matched anything. And every bridge error carried the hint
    "run: frago browser start" — advice that, for a tab-in-the-wrong-
    group error, tears down the browser and closes every other group's
    pages to fix nothing.
    """
    from click.testing import CliRunner

    from frago.browser.backends.extension import ExtensionBackendError
    from frago.cli import browser_commands as cc

    class _Exploding:
        def list_tabs(self, group):
            raise ExtensionBackendError(
                -32003,
                f"TAB_NOT_IN_GROUP: tab 7 is not in group '{group}'",
                {"code": "TAB_NOT_IN_GROUP", "group": group,
                 "remedies": [f"frago browser list-tabs --group {group}"]},
            )

    runner = CliRunner()
    with patch.object(cc, "_ext_backend", lambda: _Exploding()):
        r = runner.invoke(
            cc.browser_group,
            ["--backend", "extension", "list-tabs", "--group", "g1"],
            env={"FRAGO_CURRENT_RUN": "", "FRAGO_BROWSER_BACKEND": ""},
        )

    assert r.exit_code != 0
    payload = json.loads(r.output)
    assert payload["code"] == "TAB_NOT_IN_GROUP", \
        "the named code is what the books document; a bare number is unusable"
    assert "-32003" not in payload["error"], \
        "the transport number does not belong in the agent-facing message"
    assert payload["hint"] == ["frago browser list-tabs --group g1"]
    assert "frago browser start" not in json.dumps(payload), \
        "the bridge answered, so restarting the browser fixes nothing " \
        "and closes everyone else's tabs"


def test_bridge_down_still_says_to_start_the_browser():
    """The restart hint is right exactly once: when nothing answered."""
    from click.testing import CliRunner

    from frago.cli import browser_commands as cc

    class _Unreachable:
        def list_tabs(self, group):
            raise ConnectionRefusedError("no socket")

    runner = CliRunner()
    with patch.object(cc, "_ext_backend", lambda: _Unreachable()):
        r = runner.invoke(
            cc.browser_group,
            ["--backend", "extension", "list-tabs", "--group", "g1"],
            env={"FRAGO_CURRENT_RUN": "", "FRAGO_BROWSER_BACKEND": ""},
        )

    assert r.exit_code != 0
    assert "frago browser start" in json.loads(r.output)["hint"]


def test_service_worker_names_every_group_error():
    """The bridge's group errors must all carry a documented name.

    Kept as a source check because these throws live in the browser and
    no Python test can reach them.
    """
    import re
    from pathlib import Path

    import frago
    sw = (Path(frago.__file__).parent / "_resources" / "extension_bundle"
          / "background" / "service-worker-v11.js").read_text(encoding="utf-8")

    named = set(re.findall(r'groupError\(\s*-?\d+,\s*"([A-Z_]+)"', sw))
    assert {"NO_GROUP", "GROUP_TAB_LIMIT", "TAB_NOT_IN_GROUP",
            "NO_TAB_IN_GROUP"} <= named, f"unnamed group errors remain: {named}"

    from frago.browser.cdp.tab_group_manager import CHROME_ERRORS
    unknown = named - set(CHROME_ERRORS)
    assert not unknown, (
        f"{unknown} is reported by the extension backend but unknown to the "
        f"CDP backend — one vocabulary, or agents learn two")


def test_extension_manifest_grants_what_groups_need():
    """Tab groups need `tabGroups`; the 30-minute timer needs `alarms`.

    A service worker is killed at will, so the timer cannot be a
    setTimeout — without the alarms permission, groups would simply
    never expire and nobody would see an error saying so.
    """
    from pathlib import Path

    import frago
    manifest = json.loads(
        (Path(frago.__file__).parent / "_resources" / "extension_bundle"
         / "manifest.json").read_text(encoding="utf-8"))
    for perm in ("tabGroups", "alarms", "tabs", "storage"):
        assert perm in manifest["permissions"], f"missing permission: {perm}"
