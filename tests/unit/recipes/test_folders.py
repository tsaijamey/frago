"""配方文件夹：主人在本机怎么摆图标。

这里盯着的是四件事，每一件都是「不这样就会乱」的那种：

1. 初装没有文件夹，而且这不是错——不带默认清单是一条决定，不是还没做完。
2. 写了一个表里没有的文件夹，当场拒绝并列出现有的。放行的话，系统就替人凭空建了
   一个文件夹，相差一字的两个文件夹全是这么来的。
3. 一张配方只待一个文件夹。换个地方就得从原处消失，不然一个图标在两处出现。
4. 删掉文件夹不碰配方，里面那几张回到未分类。
"""

import json

import pytest

from frago.recipes import folders as F


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    """每个用例一台干净的机器。"""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return tmp_path


class TestAnUntouchedMachine:
    def test_no_folders_and_no_file(self):
        # 初装：一个文件夹都没有，表这个文件压根不存在。界面据此跟从前一样平铺。
        assert F.list_folders() == []
        assert not F.table_path().exists()

    def test_nothing_is_wrong(self):
        # 「没有文件夹」不是坏状态，不该报出任何毛病。
        assert F.diagnose() is None

    def test_the_table_lives_next_to_the_recipes(self):
        # 落点是约定的一部分：放 config.json 的话它在数据仓库的忽略清单里，
        # 主人摆了一下午的桌面永远备份不到。
        assert F.table_path().parts[-2:] == ("recipes", "folders.json")


class TestNamingAFolder:
    def test_both_languages_are_kept(self):
        F.add_folder("market", "行情研究", "Market Research")
        folder = F.list_folders()[0]
        assert folder.label("zh-CN") == "行情研究"
        assert folder.label("en") == "Market Research"

    def test_one_language_is_enough(self):
        # 只写中文名：英文那门回落到中文，不逼人当场翻译一个还没想好的名字。
        F.add_folder("market", "行情研究")
        assert F.list_folders()[0].label("en") == "行情研究"

    def test_a_folder_needs_some_name(self):
        with pytest.raises(F.FolderError, match="needs a display name"):
            F.add_folder("market")

    def test_renaming_leaves_the_recipes_alone(self):
        F.add_folder("market", "行情研究")
        F.put(["board", "dashboard"], "market")
        F.rename_folder("market", "行情")
        folder = F.list_folders()[0]
        assert folder.label() == "行情"
        assert folder.recipes == ["board", "dashboard"]

    def test_an_id_is_not_a_free_for_all(self):
        with pytest.raises(F.FolderError, match="invalid folder id"):
            F.add_folder("Market Research", "行情")

    def test_none_is_spoken_for(self):
        # `--into none` 表示拿出来，所以它不能同时是某个文件夹的 id。
        with pytest.raises(F.FolderError, match="reserved"):
            F.add_folder("none", "未分类")


class TestAFolderThatIsNotThere:
    """相差一字的两个文件夹，是从「随手写一个没见过的名字」来的。堵掉这个入口。"""

    def test_putting_into_an_unknown_folder_is_refused(self):
        F.add_folder("market", "行情研究")
        with pytest.raises(F.FolderError, match="unknown folder 'markets'"):
            F.put(["board"], "markets")

    def test_the_refusal_lists_what_does_exist(self):
        F.add_folder("market", "行情研究")
        with pytest.raises(F.FolderError) as caught:
            F.put(["board"], "markets")
        # 光说「没有这个」会把人打发去翻文档。现有的摆在眼前，他改一个字就过了。
        assert "market(行情研究)" in str(caught.value)

    def test_the_refusal_says_how_to_create_it(self):
        with pytest.raises(F.FolderError, match="frago recipe folder add"):
            F.put(["board"], "market")

    def test_nothing_is_created_behind_the_scenes(self):
        with pytest.raises(F.FolderError):
            F.put(["board"], "market")
        assert F.list_folders() == []


class TestOneRecipeOneFolder:
    def test_moving_takes_it_out_of_the_old_one(self):
        F.add_folder("market", "行情研究")
        F.add_folder("video", "视频")
        F.put(["board"], "market")
        F.put(["board"], "video")
        assert F.folder_of("board") == "video"
        assert F.list_folders()[0].recipes == []

    def test_taking_out_leaves_it_unfiled(self):
        F.add_folder("market", "行情研究")
        F.put(["board"], "market")
        F.take(["board"])
        assert F.folder_of("board") is None
        # 未分类的配方在表里不留痕：主人没管过的东西不该在这份文件里占一行。
        assert F.list_folders()[0].recipes == []

    def test_a_duplicate_written_by_hand_heals_itself(self, home):
        # 手写的表里同一张配方出现在两个文件夹里：留先出现的那个，别让人回去改文件。
        path = F.table_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "version": 1,
            "folders": [
                {"id": "market", "name": {"zh-CN": "行情"}, "recipes": ["board"]},
                {"id": "video", "name": {"zh-CN": "视频"}, "recipes": ["board"]},
            ],
        }, ensure_ascii=False), encoding="utf-8")
        assert F.folder_of("board") == "market"
        assert F.list_folders()[1].recipes == []


class TestRemovingAFolder:
    def test_the_recipes_survive(self):
        F.add_folder("market", "行情研究")
        F.put(["board", "dashboard"], "market")
        F.remove_folder("market")
        assert F.list_folders() == []
        assert F.folder_of("board") is None

    def test_the_file_goes_away_when_the_last_one_does(self):
        # 「一个文件夹都没有」和「从没建过」对界面是同一件事，留个空壳只会让人
        # 以为出过什么事。
        F.add_folder("market", "行情研究")
        F.remove_folder("market")
        assert not F.table_path().exists()


class TestOrderOnTheGrid:
    def test_the_array_order_is_the_grid_order(self):
        F.add_folder("a", "甲")
        F.add_folder("b", "乙")
        F.add_folder("c", "丙")
        assert [f.id for f in F.list_folders()] == ["a", "b", "c"]

    def test_moving_to_the_front(self):
        F.add_folder("a", "甲")
        F.add_folder("b", "乙")
        F.move_folder("b", 1)
        assert [f.id for f in F.list_folders()] == ["b", "a"]

    def test_out_of_range_sticks_to_an_end(self):
        F.add_folder("a", "甲")
        F.add_folder("b", "乙")
        F.move_folder("a", 99)
        assert [f.id for f in F.list_folders()] == ["b", "a"]


class TestCreatingWithRecipesInHand:
    """界面上把一张卡拖到另一张上：新文件夹就该当场装着这两张，不经过空文件夹。"""

    def test_the_folder_arrives_already_holding_them(self):
        F.create_with("market", ["board", "dashboard"], "行情研究")
        assert F.list_folders()[0].recipes == ["board", "dashboard"]


class TestABrokenTable:
    def test_a_broken_table_does_not_take_the_page_down(self, home):
        path = F.table_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ not json", encoding="utf-8")
        # 文件夹只管图标怎么摆，坏了也不该让整个配方列表打不开。
        assert F.list_folders() == []

    def test_but_it_says_so_out_loud(self, home):
        path = F.table_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ not json", encoding="utf-8")
        # 不吭声的话，人看到的是「我的文件夹全没了」，查不到任何线索。
        assert "not valid JSON" in (F.diagnose() or "")

    def test_a_write_never_leaves_half_a_table(self, home):
        F.add_folder("market", "行情研究")
        before = F.table_path().read_text(encoding="utf-8")
        with pytest.raises(F.FolderError):
            F.add_folder("Bad Id", "坏")
        assert F.table_path().read_text(encoding="utf-8") == before
