"""关键词 → 目录名的分层匹配。

钉的是每一层的判据边界，以及"松紧闸"那条：按序匹配必须挡得住
``video`` 撞上 ``voice-desktop-pet`` 这种跨度铺满全名的假命中。
"""

from frago.context.matcher import (
    MIN_SCORE,
    SCORE_ALL_TOKENS,
    SCORE_EXACT,
    SCORE_PREFIX,
    SCORE_SUBSEQUENCE,
    SCORE_SUBSTRING,
    match_names,
    normalize,
    score_name,
    strip_date_prefix,
    tokens,
)

REAL_NAMES = [
    "20260725-cxmt-ipo-video",
    "20260728-agent-session-workbench",
    "etf",
    "etf-dma-trading-plan",
    "hook_rules_dashboard",
    "gopro-采集-方案",
    "voice-desktop-pet",
    "video-corpus",
]


class TestNormalize:
    def test_lowercases_and_folds_separators(self):
        assert normalize("Hook_Rules Dashboard") == "hook-rules-dashboard"

    def test_collapses_runs_and_trims_edges(self):
        assert normalize("--foo__  bar--") == "foo-bar"

    def test_keeps_cjk(self):
        assert normalize("gopro-采集-方案") == "gopro-采集-方案"

    def test_strip_date_prefix_only_at_head(self):
        assert strip_date_prefix("20260725-cxmt-ipo") == "cxmt-ipo"
        assert strip_date_prefix("cxmt-20260725-ipo") == "cxmt-20260725-ipo"

    def test_tokens_drops_empties(self):
        assert tokens("a--b-c") == ["a", "b", "c"]


class TestLayers:
    def test_exact_name(self):
        assert score_name("etf", "etf").score == SCORE_EXACT

    def test_exact_after_stripping_date_prefix(self):
        """人记的是语义名，NEVER 是那串日期。"""
        got = score_name("cxmt-ipo-video", "20260725-cxmt-ipo-video")
        assert got.score == SCORE_EXACT

    def test_separator_style_does_not_matter(self):
        assert score_name("hook rules dashboard", "hook_rules_dashboard").score == SCORE_EXACT

    def test_prefix(self):
        assert score_name("etf-dma", "etf-dma-trading-plan").score == SCORE_PREFIX

    def test_prefix_ignores_date_prefix(self):
        assert score_name("cxmt", "20260725-cxmt-ipo-video").score == SCORE_PREFIX

    def test_substring(self):
        assert score_name("ipo", "20260725-cxmt-ipo-video").score == SCORE_SUBSTRING

    def test_all_tokens_out_of_order(self):
        got = score_name("workbench session", "20260728-agent-session-workbench")
        assert got.score == SCORE_ALL_TOKENS

    def test_subsequence_handles_abbreviation(self):
        got = score_name("sesswrkbench", "20260728-agent-session-workbench")
        assert got.score == SCORE_SUBSEQUENCE

    def test_similarity_handles_typo(self):
        got = score_name("cxmt-ipo-vidoe", "20260725-cxmt-ipo-video")
        assert got is not None
        assert MIN_SCORE <= got.score < SCORE_SUBSEQUENCE

    def test_unrelated_name_scores_nothing(self):
        assert score_name("kubernetes", "etf-dma-trading-plan") is None

    def test_empty_query_matches_nothing(self):
        assert score_name("   ", "etf") is None


class TestSubsequenceTightness:
    """裸的按序匹配几乎什么都能中，必须有跨度上限。"""

    def test_loose_scatter_is_rejected(self):
        # v-i-d-e-o 的确按序出现在 voicedesktoppet 里，但铺满了整个名字。
        assert score_name("video", "voice-desktop-pet") is None

    def test_tight_abbreviation_is_accepted(self):
        assert score_name("vidcorp", "video-corpus").score == SCORE_SUBSEQUENCE

    def test_two_char_query_never_uses_subsequence(self):
        # 太短的词按序匹配没有信息量，只能靠前面几层命中。
        got = score_name("vc", "video-corpus")
        assert got is None or got.score >= SCORE_ALL_TOKENS


class TestMatchNames:
    def test_sorted_by_score_then_name(self):
        got = match_names("etf", REAL_NAMES)
        assert [c.name for c in got[:2]] == ["etf", "etf-dma-trading-plan"]
        assert got[0].is_exact

    def test_filters_below_floor(self):
        assert all(c.score >= MIN_SCORE for c in match_names("video", REAL_NAMES))

    def test_no_match_returns_empty(self):
        assert match_names("kubernetes-operator", REAL_NAMES) == []

    def test_result_is_deterministic(self):
        assert match_names("video", REAL_NAMES) == match_names("video", list(reversed(REAL_NAMES)))
