"""配方的标题：给人看的那个名字。

`name` 一直在当两样东西用——标识（进目录名、进命令行、进依赖声明）和标题（界面上
把下划线换成空格显示）。两个用途要求相反：标识改了等于换一张配方，标题要能随时改、
要能写中文。`title` 把标题拿出来单过。

存量 86 张配方一张都没写这个字段，所以这里第一件要盯的就是：不写照旧。
"""

import pytest

from frago.recipes.exceptions import RecipeValidationError
from frago.recipes.metadata import (
    MAX_TITLE,
    RecipeMetadata,
    display_title,
    parse_metadata_file,
    validate_metadata,
)


def make(**over) -> RecipeMetadata:
    base = dict(
        name="a_stock_dma_signal_board",
        type="atomic",
        runtime="python",
        version="1.0.0",
        description="d",
        use_cases=["u"],
        output_targets=["stdout"],
    )
    base.update(over)
    return RecipeMetadata(**base)


def write_recipe(tmp_path, frontmatter: str):
    path = tmp_path / "recipe.md"
    path.write_text(f"---\n{frontmatter}\n---\n\n# x\n", encoding="utf-8")
    return path


class TestARecipeThatNeverGotAName:
    def test_it_looks_exactly_like_before(self):
        # 没写 title：下划线换空格，跟这个字段出现之前一模一样。
        assert display_title(make()) == "a stock dma signal board"

    def test_and_it_still_validates(self):
        validate_metadata(make())


class TestARecipeWithAName:
    def test_the_chinese_name_wins_for_a_chinese_reader(self):
        meta = make(title={"zh-CN": "A股 DMA 信号盘", "en": "DMA Signal Board"})
        assert display_title(meta, "zh-CN") == "A股 DMA 信号盘"

    def test_the_english_name_wins_for_an_english_reader(self):
        meta = make(title={"zh-CN": "A股 DMA 信号盘", "en": "DMA Signal Board"})
        assert display_title(meta, "en") == "DMA Signal Board"

    def test_one_language_covers_the_other(self):
        # 只写了一门，另一门用它顶上——总比退回 name 那个机器标识强。
        meta = make(title={"zh-CN": "A股 DMA 信号盘"})
        assert display_title(meta, "en") == "A股 DMA 信号盘"

    def test_the_identifier_is_untouched(self):
        meta = make(title={"zh-CN": "A股 DMA 信号盘"})
        assert meta.name == "a_stock_dma_signal_board"


class TestWritingItWrong:
    def test_an_unknown_language_is_refused(self):
        # 填在 `zh` 下面的标题，界面按 `zh-CN` 去取永远取不到，表现为「这张配方没
        # 改过名」——没有任何一处会报错。所以这里必须是 error 而不是随它去。
        with pytest.raises(RecipeValidationError) as caught:
            validate_metadata(make(title={"zh": "行情盘"}))
        assert "zh" in str(caught.value)

    def test_an_empty_title_is_refused(self):
        with pytest.raises(RecipeValidationError, match="title.zh-CN"):
            validate_metadata(make(title={"zh-CN": ""}))

    def test_a_title_that_would_be_cut_off_is_refused(self):
        # 卡片上标题只有一两行的位置。在这里挡住，好过让人在界面上才发现写长了。
        with pytest.raises(RecipeValidationError, match="太长"):
            validate_metadata(make(title={"zh-CN": "名" * (MAX_TITLE + 1)}))


class TestReadingItFromTheFile:
    def test_a_map_comes_through(self, tmp_path):
        path = write_recipe(tmp_path, "\n".join([
            "name: demo",
            "type: atomic",
            "runtime: python",
            'version: "1.0.0"',
            "description: d",
            "use_cases: [u]",
            "output_targets: [stdout]",
            "title:",
            '  zh-CN: "行情盘"',
            '  en: "Signal Board"',
        ]))
        meta = parse_metadata_file(path)
        assert meta.title == {"zh-CN": "行情盘", "en": "Signal Board"}

    def test_a_bare_string_is_taken_as_the_chinese_name(self, tmp_path):
        # 有人会直接写 `title: 行情盘`。那是他的意思，拒绝它教不会任何东西。
        path = write_recipe(tmp_path, "\n".join([
            "name: demo",
            "type: atomic",
            "runtime: python",
            'version: "1.0.0"',
            "description: d",
            "use_cases: [u]",
            "output_targets: [stdout]",
            'title: "行情盘"',
        ]))
        assert parse_metadata_file(path).title == {"zh-CN": "行情盘"}

    def test_leaving_it_out_is_fine(self, tmp_path):
        path = write_recipe(tmp_path, "\n".join([
            "name: demo",
            "type: atomic",
            "runtime: python",
            'version: "1.0.0"',
            "description: d",
            "use_cases: [u]",
            "output_targets: [stdout]",
        ]))
        meta = parse_metadata_file(path)
        assert meta.title == {}
        validate_metadata(meta)
