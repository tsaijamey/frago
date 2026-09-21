"""frago recipe — 本机的配方文件夹。

文件夹是这台机器的主人自己摆的，像手机桌面：配方文件里一个字都不提自己属于哪个
文件夹，归属全记在这张表里。原因是 ``recipe.md`` 要发社区、要部署到服务器，它不该
记着「我在这台机器的哪个文件夹里」；界面上拖一下图标也不该改写一份要分发出去的
文件。

**不随包发默认清单。** 初装没有这张表，也就没有文件夹，界面跟从前一样平铺一屏
图标，直到主人亲手建第一个。事务分类可以带默认（家庭/工作/个人喜好/其他），是因
为事务能用来分类的角度就那么几个；配方接近 app，角度太多，任何一份默认清单都只是
替主人预设了一种他未必认同的看法。

表落在 ``~/.frago/recipes/folders.json``，跟配方做邻居。不放 ``config.json``：那份
文件在数据仓库的忽略清单里，放进去等于永远备份不到，而 ``recipes/`` 目录本身是入
库的，表跟着配方一起走。配方扫描只认 ``atomic/chrome``、``atomic/system``、
``workflows`` 三个子目录下带 ``recipe.md`` 的目录，顶层多这一个 JSON 不会被当成配方
读进来。

数组顺序就是桌面上的先后。**一张配方只能待在一个文件夹里**——手机上也是这样，同
一个图标不会同时出现在两个文件夹；归入新文件夹时先从原来那个里拿出来。没进任何名
单的配方就是未分类，表里不留痕：主人没管过的配方不该在这份文件里占一行。

名单里留着已经不存在的配方名（配方删了、还没装回来）不算错，原样留着：哪天配方装
回来，它自动回到原位。这一条照搬 ``frago todo category`` 删分类之后的做法。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

#: 一台机器最多摆多少个文件夹。比事务分类的 20 宽，因为配方能分的角度本来就多；
#: 留一个上限是为了挡住「每张配方一个文件夹」那种等于没分类的摆法。
MAX_FOLDERS = 40

#: 文件夹显示名支持的两门语言，与帮助手册的分类表同键。
LANGS = ("zh-CN", "en")

#: 「未分类」的保留字：命令行里 ``--into none`` 表示拿出来，它不能同时是某个文件夹
#: 的 id。
UNFILED = "none"

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")

#: 显示名的长度上限。文件夹名在网格里只有一行的位置，长了会被挤成省略号。
MAX_NAME = 24

SCHEMA_VERSION = 1


class FolderError(ValueError):
    """文件夹表操作失败。调用方直接把它的话转述给人看。"""


@dataclass
class Folder:
    id: str
    name: dict[str, str]
    icon: str = ""
    recipes: list[str] = field(default_factory=list)

    def label(self, lang: str = "zh-CN") -> str:
        """给这门语言看的名字；这门没写就用另一门，都没写就用 id。"""
        return self.name.get(lang) or next(
            (self.name[k] for k in LANGS if self.name.get(k)), self.id
        )

    def to_json(self) -> dict:
        out: dict = {"id": self.id, "name": dict(self.name)}
        if self.icon:
            out["icon"] = self.icon
        out["recipes"] = list(self.recipes)
        return out


def table_path() -> Path:
    """表的落点。调用时再算：测试夹具会改 HOME。"""
    return Path.home() / ".frago" / "recipes" / "folders.json"


# ── 读 ──────────────────────────────────────────────────────────────────


def list_folders() -> list[Folder]:
    """当前的文件夹，按摆放先后。

    文件不在就是一个文件夹都没有——初装的正常状态，不是错。文件读坏了也返回空
    表：文件夹只影响图标怎么摆，NEVER 因为它让整个配方列表打不开。坏在哪由
    :func:`diagnose` 去说。
    """
    try:
        return _parse(_read_raw())
    except (FolderError, OSError, json.JSONDecodeError):
        return []


def diagnose() -> str | None:
    """表有毛病时返回一句人话，好着或不存在时返回 ``None``。

    :func:`list_folders` 咽下去的错在这里说出来，供命令行和接口在列完之后补一
    句提示——静默吞掉比报错难查得多。
    """
    path = table_path()
    if not path.exists():
        return None
    try:
        _parse(_read_raw())
    except FolderError as e:
        return str(e)
    except json.JSONDecodeError as e:
        return f"{path} is not valid JSON: {e}"
    except OSError as e:
        return f"{path} unreadable: {e}"
    return None


def _read_raw() -> dict:
    path = table_path()
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise FolderError(f"{path} must hold a JSON object")
    return data


def _parse(data: dict) -> list[Folder]:
    if not data:
        return []
    section = data.get("folders", [])
    if not isinstance(section, list):
        raise FolderError("'folders' must be a list")
    out: list[Folder] = []
    for item in section:
        if not isinstance(item, dict):
            raise FolderError("each folder must be an object with id and name")
        name = item.get("name")
        if isinstance(name, str):
            # 早先手写的表可能只写了一个字符串，当中文名收下。
            name = {"zh-CN": name}
        elif not isinstance(name, dict):
            name = {}
        recipes = item.get("recipes", [])
        if not isinstance(recipes, list):
            raise FolderError(f"folder {item.get('id')!r}: 'recipes' must be a list")
        out.append(
            Folder(
                id=str(item.get("id", "")),
                name={k: str(v) for k, v in name.items() if k in LANGS and v},
                icon=str(item.get("icon", "") or ""),
                recipes=[str(r) for r in recipes],
            )
        )
    return validate(out)


# ── 校验 ────────────────────────────────────────────────────────────────


def validate(folders: list[Folder]) -> list[Folder]:
    """校验整张表，返回规整过（去掉首尾空白、去掉重复归属）的副本。"""
    if len(folders) > MAX_FOLDERS:
        raise FolderError(
            f"too many folders: {len(folders)} (at most {MAX_FOLDERS})"
        )
    seen_ids: set[str] = set()
    seen_recipes: set[str] = set()
    out: list[Folder] = []
    for f in folders:
        fid = f.id.strip()
        if fid == UNFILED:
            raise FolderError(f"folder id {UNFILED!r} is reserved for 'unfiled'")
        if not _ID_RE.match(fid):
            raise FolderError(
                f"invalid folder id {fid!r}: lowercase letters, digits, '-' or '_', "
                "starting with a letter or digit, at most 32 chars"
            )
        if fid in seen_ids:
            raise FolderError(f"duplicate folder id {fid!r}")
        seen_ids.add(fid)

        names = {k: v.strip() for k, v in f.name.items() if k in LANGS and v.strip()}
        if not names:
            raise FolderError(f"folder {fid!r} needs a display name")
        for lang, value in names.items():
            if len(value) > MAX_NAME:
                raise FolderError(
                    f"folder {fid!r} {lang} name too long: {len(value)} chars "
                    f"(at most {MAX_NAME})"
                )

        # 一张配方只待一个文件夹：同一个名字在后面的文件夹里再出现就丢掉，
        # 保留先出现的那个。手写表撞了也能自愈，不必让人回去改文件。
        recipes: list[str] = []
        for r in f.recipes:
            r = r.strip()
            if not r or r in seen_recipes:
                continue
            seen_recipes.add(r)
            recipes.append(r)

        out.append(Folder(fid, names, f.icon.strip(), recipes))
    return out


def require(folder_id: str, folders: list[Folder] | None = None) -> str:
    """确认这个 id 在表里，不在就报错并把现有的全列出来。

    这是「写了个表里没有的文件夹」那条路的唯一关卡。拒绝必须是硬的：放行一个没见过
    的 id，等于让系统替人凭空建一个文件夹，相差一字的两个文件夹就是这么来的。
    """
    folders = list_folders() if folders is None else folders
    if folder_id not in {f.id for f in folders}:
        raise FolderError(
            f"unknown folder {folder_id!r}; "
            f"{describe(folders)}. "
            f"To create it: frago recipe folder add {folder_id} <中文名>"
        )
    return folder_id


def describe(folders: list[Folder] | None = None) -> str:
    """报错时列出可选项：``market(行情研究), video(视频)``。"""
    folders = list_folders() if folders is None else folders
    if not folders:
        return "no folders exist yet"
    return "choose one of: " + ", ".join(f"{f.id}({f.label()})" for f in folders)


# ── 写 ──────────────────────────────────────────────────────────────────


def save_folders(folders: list[Folder]) -> list[Folder]:
    """整张表校验后落盘。

    先写同目录下的临时文件再改名顶上：写到一半断电，留下的是原来那张完整的表，
    不是半张。表空了就把文件删掉——「一个文件夹都没有」和「从没建过文件夹」对界面
    是同一件事，留一个空壳只会让人以为出过什么事。
    """
    cleaned = validate(folders)
    path = table_path()
    if not cleaned:
        path.unlink(missing_ok=True)
        return cleaned
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": SCHEMA_VERSION,
        "folders": [f.to_json() for f in cleaned],
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".folders-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return cleaned


def _index(folders: list[Folder], folder_id: str) -> int:
    for i, f in enumerate(folders):
        if f.id == folder_id:
            return i
    raise FolderError(f"no folder {folder_id!r}; {describe(folders)}")


def add_folder(
    folder_id: str,
    name_zh: str = "",
    name_en: str = "",
    *,
    icon: str = "",
    position: int | None = None,
) -> list[Folder]:
    """建一个文件夹。``position`` 从 1 数，缺省排到最后。

    两门名字给一门就行，另一门空着——界面会拿有的那门顶上。
    """
    folders = list_folders()
    if any(f.id == folder_id for f in folders):
        raise FolderError(f"folder {folder_id!r} already exists")
    if len(folders) >= MAX_FOLDERS:
        raise FolderError(
            f"already {len(folders)} folders (at most {MAX_FOLDERS}); "
            "remove one before adding another"
        )
    name = {k: v for k, v in (("zh-CN", name_zh), ("en", name_en)) if v}
    index = len(folders) if position is None else _clamp(position, len(folders) + 1)
    folders.insert(index, Folder(folder_id, name, icon))
    return save_folders(folders)


def rename_folder(
    folder_id: str, name_zh: str | None = None, name_en: str | None = None
) -> list[Folder]:
    """改显示名。id 和里面的配方一个都不动。"""
    folders = list_folders()
    target = folders[_index(folders, folder_id)]
    name = dict(target.name)
    for lang, value in (("zh-CN", name_zh), ("en", name_en)):
        if value is None:
            continue
        if value:
            name[lang] = value
        else:
            name.pop(lang, None)
    target.name = name
    return save_folders(folders)


def set_icon(folder_id: str, icon: str) -> list[Folder]:
    folders = list_folders()
    folders[_index(folders, folder_id)].icon = icon
    return save_folders(folders)


def move_folder(folder_id: str, position: int) -> list[Folder]:
    """挪到第 ``position`` 位（从 1 数；超出范围就贴到头或尾）。"""
    folders = list_folders()
    item = folders.pop(_index(folders, folder_id))
    folders.insert(_clamp(position, len(folders) + 1), item)
    return save_folders(folders)


def remove_folder(folder_id: str) -> list[Folder]:
    """拿掉一个文件夹。里面的配方回到未分类，配方本身一个都不删。"""
    folders = list_folders()
    folders.pop(_index(folders, folder_id))
    return save_folders(folders)


# ── 归属 ────────────────────────────────────────────────────────────────


def put(recipe_names: list[str], folder_id: str, *, position: int | None = None) -> list[Folder]:
    """把这几张配方放进一个已有的文件夹。

    先从原来待的文件夹里拿出来——一张配方只能待一个地方。目标文件夹必须已经存在：
    这里不替人建，建文件夹是一个单独的动作。
    """
    folders = list_folders()
    require(folder_id, folders)
    names = _clean_names(recipe_names)
    for f in folders:
        if f.id != folder_id:
            f.recipes = [r for r in f.recipes if r not in names]
    target = folders[_index(folders, folder_id)]
    staying = [r for r in target.recipes if r not in names]
    at = len(staying) if position is None else _clamp(position, len(staying) + 1)
    target.recipes = staying[:at] + names + staying[at:]
    return save_folders(folders)


def take(recipe_names: list[str]) -> list[Folder]:
    """把这几张配方从所在的文件夹里拿出来，回到未分类。"""
    folders = list_folders()
    names = _clean_names(recipe_names)
    for f in folders:
        f.recipes = [r for r in f.recipes if r not in names]
    return save_folders(folders)


def create_with(
    folder_id: str,
    recipe_names: list[str],
    name_zh: str = "",
    name_en: str = "",
    *,
    icon: str = "",
) -> list[Folder]:
    """建一个文件夹并当场把这几张配方放进去。

    界面上把一张卡拖到另一张卡上就是这个动作：手机上新文件夹就是这么诞生的，两件
    事之间不该出现一个空文件夹的中间状态。
    """
    add_folder(folder_id, name_zh, name_en, icon=icon)
    return put(recipe_names, folder_id)


def folder_of(recipe_name: str, folders: list[Folder] | None = None) -> str | None:
    """这张配方待在哪个文件夹；没进任何文件夹返回 ``None``。"""
    folders = list_folders() if folders is None else folders
    for f in folders:
        if recipe_name in f.recipes:
            return f.id
    return None


def assignments(folders: list[Folder] | None = None) -> dict[str, str]:
    """``{配方名: 文件夹 id}``，一次问清所有归属，免得逐张去查。"""
    folders = list_folders() if folders is None else folders
    return {r: f.id for f in folders for r in f.recipes}


def _clean_names(recipe_names: list[str]) -> list[str]:
    """去掉空白和重复，保留给进来的先后。"""
    out: list[str] = []
    seen: set[str] = set()
    for name in recipe_names:
        name = name.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    if not out:
        raise FolderError("no recipe names given")
    return out


def _clamp(position: int, size: int) -> int:
    """1 起数的位置换成下标，越界贴边。"""
    return max(0, min(position - 1, size - 1))
