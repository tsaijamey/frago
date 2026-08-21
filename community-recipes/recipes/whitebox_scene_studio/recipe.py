# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26", "pillow>=10"]
# ///
"""whitebox_scene_studio — 白膜场景生图工作台。

v0.5.0：项目化 + 页面实时同步 + UI 指挥 agent。
每个项目一份独立的场景与产物；页面显示的一切真值都在磁盘上，
发布快照只服务于访客只读视图。
渲染是双通道：服务端软件光栅器（render.py）是主路径，
浏览器 WebGL 只是加速路径。所以 agent 不开页面也能出图，
没有 GPU 的浏览器也能完整使用这个工具。

架构上有三条不能绕的约定，改这个文件前先确认没违反：
1. 配方 NEVER 自己起 HTTP 服务。页面由 frago server（固定 8093）从 assets/ 直接发。
2. NEVER `import frago`——PEP 723 隔离环境里 import 不到。要用 frago 的能力就 subprocess。
3. 数据目录由平台交代（FRAGO_RECIPE_DATA_DIR），缺省才回落到硬编码路径。

语义色卡是这个配方的共同真值：seg 图靠它上色、图例文字靠它写「红色=人物」、
前端调色板靠它显示。所以它定义在这里一份，随页面状态下发给前端，
NEVER 让前端自己抄一份——抄出来的那份一旦漂移，出图颜色和图例就对不上了。
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scene_ops  # noqa: E402  —— 世界空间几何，纯函数无依赖

RECIPE_NAME = "whitebox_scene_studio"

DEFAULT_DATA_DIR = Path.home() / ".frago/data/image/recipe-caches" / RECIPE_NAME

# ARCH 第四节的契约现在全部落地了，没有「规划中」的动作了。
LIVE_ACTIONS = (
    "view", "scene_get", "scene_put", "catalog",
    "project_list", "project_create", "project_switch", "project_rename", "project_delete",
    "object_add", "object_update", "object_delete", "scene_clear", "place", "move",
    "measure", "validate",
    "camera_set", "camera_frame",
    "snapshot", "preview", "legend", "generate", "critique", "history",
    "instruct", "preflight", "expand_prompt", "draft_get", "draft_put",
)

SNAPSHOT_VIEWS = ("clay", "seg", "depth")

# 预览是给人一边摆一边看的，要的是快而不是精。长边压到这个数，
# 再大就跟不上人点下一个物体的节奏了。
PREVIEW_LONG_EDGE = 720

SEEDREAM_RECIPE = "doubao_seedream_image"

# --- 语义色卡 ---------------------------------------------------------
# key 是存进 scene.json 的值，color 是 seg 图上这一类的纯色块，
# label 是写进图例给模型看的中文词。三者一动全动。

SEMANTICS = [
    {"key": "ground", "label": "地面", "color": "#4A4A4A", "hint": "地板、路面", "color_name": "深灰"},
    {"key": "building", "label": "建筑", "color": "#B03A2E", "hint": "楼房、墙体块", "color_name": "砖红"},
    {"key": "wall", "label": "墙面", "color": "#95A5A6", "hint": "隔断、围墙", "color_name": "灰白"},
    {"key": "person", "label": "人物", "color": "#E74C3C", "hint": "胶囊立人", "color_name": "红色"},
    {"key": "vehicle", "label": "车辆", "color": "#2980B9", "hint": "轿车、卡车方块", "color_name": "蓝色"},
    {"key": "vegetation", "label": "植被", "color": "#27AE60", "hint": "树、草丛", "color_name": "绿色"},
    {"key": "furniture", "label": "家具", "color": "#F39C12", "hint": "桌椅柜", "color_name": "橙色"},
    {"key": "prop", "label": "道具", "color": "#8E44AD", "hint": "杂物", "color_name": "紫色"},
    {"key": "water", "label": "水面", "color": "#1ABC9C", "hint": "河、池", "color_name": "青色"},
    {"key": "light", "label": "光源", "color": "#F1C40F", "hint": "灯、窗", "color_name": "黄色"},
]
SEMANTIC_KEYS = tuple(s["key"] for s in SEMANTICS)

# --- 体块库 -----------------------------------------------------------
# 每种形状在前端都是一个「单位体」：x/z 在 ±0.5 以内、y 从 0 到 1，
# 底面中心就是原点。所以 scene.json 里的 position 直接是贴地点，
# scale 是倍数而不是米数——胶囊天生比方块窄，硬要用米数会到处对不齐。

SHAPES = [
    {"key": "box", "label": "方块", "glyph": "◼"},
    {"key": "sphere", "label": "球", "glyph": "●"},
    {"key": "cylinder", "label": "圆柱", "glyph": "⬤"},
    {"key": "cone", "label": "圆锥", "glyph": "▲"},
    {"key": "capsule", "label": "胶囊", "glyph": "⬮"},
    {"key": "plane", "label": "平面", "glyph": "▬"},
    {"key": "stairs", "label": "楼梯块", "glyph": "◺"},
]
SHAPE_KEYS = tuple(s["key"] for s in SHAPES)

# 默认尺寸一律按**真实世界米数**写：宽 × 高 × 深。
#
# 为什么不直接写 scale：scale 是倍数，而各形状的单位体跨度不一样——胶囊只有 0.5 宽，
# 别的都是 1 宽。同一个 scale.x=0.5 在方块上是半米、在胶囊上是四分之一米。
# 用米数写、临用时换算，就不会出现"人只有半米高"这种事。
# 而白膜的尺度一旦错了，模型看到的比例关系全跟着错，出图就不是你摆的那个世界。
SEMANTIC_DIMS = {
    "person": [0.5, 1.7, 0.35],
    "vehicle": [4.6, 1.5, 1.9],
    "vegetation": [3.0, 5.0, 3.0],
    "building": [8.0, 12.0, 8.0],
    "furniture": [1.2, 0.75, 0.6],
    "wall": [4.0, 2.8, 0.2],
    "ground": [40.0, 0.02, 40.0],
    "water": [10.0, 0.02, 10.0],
    "prop": [0.4, 0.4, 0.4],
    "light": [0.3, 0.3, 0.3],
}

# 语义尺寸套到某些形状上不合身，这几个单独给。
# 树的语义尺寸是 3 宽 5 高（针叶树的样子），换成球形树冠就该是 3×3×3。
COMBO_DIMS = {
    "vegetation:sphere": [3.0, 3.0, 3.0],
    "vegetation:cylinder": [0.35, 5.0, 0.35],
    "vegetation:box": [1.2, 0.8, 1.2],
    "person:cylinder": [0.5, 1.7, 0.5],
    "light:cylinder": [0.12, 4.0, 0.12],
    "light:box": [0.6, 1.2, 0.15],
    "building:cylinder": [6.0, 12.0, 6.0],
}

# 语义没覆盖到的形状，按形状本身给一个不至于离谱的默认。
SHAPE_DIMS = {
    "box": [1.0, 1.0, 1.0],
    "sphere": [1.0, 1.0, 1.0],
    "cylinder": [1.0, 1.0, 1.0],
    "cone": [1.0, 1.0, 1.0],
    "capsule": [0.5, 1.7, 0.35],
    "plane": [4.0, 0.02, 4.0],
    "stairs": [2.0, 1.0, 1.5],
}


def default_dims(shape: str, semantic: str) -> list:
    """某个「语义 + 形状」该有多大，单位米。"""
    combo = COMBO_DIMS.get(f"{semantic}:{shape}")
    if combo:
        return list(combo)
    if semantic in SEMANTIC_DIMS and shape != "plane":
        return list(SEMANTIC_DIMS[semantic])
    if shape == "plane" and semantic in SEMANTIC_DIMS:
        return list(SEMANTIC_DIMS[semantic])
    return list(SHAPE_DIMS.get(shape, [1.0, 1.0, 1.0]))


def default_scale(shape: str, semantic: str) -> list:
    return [round(v, 4) for v in scene_ops.dims_to_scale(shape, default_dims(shape, semantic))]


# 前端拿的还是倍数（它按倍数缩放网格），所以在这里换算好再下发。
# 页面因此完全不必知道米数这回事，catalog 的结构也没变。
SHAPE_SCALE = {s: default_scale(s, "") for s in SHAPE_KEYS}
COMBO_SCALE = {
    f"{sem}:{shape}": default_scale(shape, sem)
    for sem in SEMANTIC_KEYS
    for shape in SHAPE_KEYS
}

# 点一下语义色卡就该能直接落一个像样的东西，不必再想「人该用哪个形状」。
SEMANTIC_SHAPE = {
    "ground": "plane",
    "building": "box",
    "wall": "box",
    "person": "capsule",
    "vehicle": "box",
    "vegetation": "cone",
    "furniture": "box",
    "prop": "box",
    "water": "plane",
    "light": "sphere",
}

ASPECTS = [
    {"key": "16:9", "width": 1280, "height": 720},
    {"key": "1:1", "width": 1024, "height": 1024},
    {"key": "9:16", "width": 720, "height": 1280},
    {"key": "4:3", "width": 1152, "height": 864},
]
ASPECT_KEYS = tuple(a["key"] for a in ASPECTS)

# 机位预设：高度是相机离地多少米。top_down 单独处理，其余保持当前方位角只换高度。
CAMERA_PRESETS = [
    {"key": "eye_level", "label": "人眼 1.6m", "height": 1.6},
    {"key": "low", "label": "低机位 0.4m", "height": 0.4},
    {"key": "high", "label": "高机位 3m", "height": 3.0},
    {"key": "top_down", "label": "俯瞰", "height": None},
]

# 场景初值。相机站在人眼高度斜看向原点，画幅 16:9——
# 打开页面第一眼就该是一个能用的机位，而不是黑屏或者相机埋在地里。
EMPTY_SCENE = {
    "version": 0,
    "updated_at": None,
    "canvas": {"aspect": "16:9", "width": 1280, "height": 720},
    "camera": {"position": [6.0, 4.0, 8.0], "target": [0.0, 0.8, 0.0], "fov": 40},
    "objects": [],
}

EMPTY_COMMANDS = {"seq": 0, "pending": []}


def frago_argv() -> list:
    """找系统级 frago，绝不回落源码 checkout 版。

    checkout 版有一道「拒绝从源码运行」的守卫，会直接 exit 1，
    而它常常就排在 PATH 前面（开发时 venv 激活着）。认错了这里
    每一次 subprocess 都会失败，且错误信息跟真正的问题毫无关系。
    """

    def is_checkout(path_str: str) -> bool:
        try:
            p = Path(path_str).resolve()
        except OSError:
            return False
        if p.parent.name == "bin" and p.parent.parent.name == ".venv":
            root = p.parent.parent.parent
            if (root / "pyproject.toml").exists() and (root / "src" / "frago").is_dir():
                return True
        return False

    candidates = [str(Path(d) / "frago") for d in os.environ.get("PATH", "").split(os.pathsep) if d]
    candidates += [
        str(Path.home() / ".local" / "bin" / "frago"),
        "/opt/homebrew/bin/frago",
        "/usr/local/bin/frago",
    ]

    seen = set()
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        if os.path.isfile(c) and os.access(c, os.X_OK) and not is_checkout(c):
            return [c]

    print(
        "⚠️ 找不到系统级 frago（只有源码 checkout 版或未安装），"
        "发布页面状态会失败；请把 frago 装到系统位置（如 ~/.local/bin）",
        file=sys.stderr,
    )
    return ["frago"]


def resolve_data_dir() -> Path:
    """数据目录以平台交代的为准。"""
    env = os.environ.get("FRAGO_RECIPE_DATA_DIR")
    return Path(env).expanduser() if env else DEFAULT_DATA_DIR


def read_json(path: Path, fallback: dict) -> dict:
    """读一份 JSON。缺失或读坏都按初值处理，不让页面开不起来。"""
    if not path.exists():
        return json.loads(json.dumps(fallback))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return json.loads(json.dumps(fallback))
    return data if isinstance(data, dict) else json.loads(json.dumps(fallback))


def write_json_atomic(path: Path, data: dict) -> None:
    """先写临时文件再改名。

    页面每 800ms 就读一次 scene.json，直接覆写会让它读到写了一半的内容
    —— 表现是编辑器毫无征兆地闪回空场景，而且不可复现。
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# --- 项目 ---------------------------------------------------------------
# 一个项目 = 一份独立的场景与它全部的产物。磁盘上就是 projects/<slug>/ 一个目录，
# 里面自成一套：scene.json、panel.json、agent_log.jsonl、history.jsonl、
# snapshots/、generated/、preview/。项目之间不共享任何东西——串台比丢东西更难查：
# 人会以为是模型不稳，其实是他看的那份不是他改的那份。

PROJECT_FILES = ("scene.json", "history.jsonl", "commands.json")
PROJECT_DIRS = ("snapshots", "generated", "preview")

DEFAULT_PROJECT_NAME = "街角"
DEFAULT_PROJECT_SLUG = "street-corner"


def slugify(name: str, taken=()) -> str:
    """项目名 → 目录名。

    中文名取不出拉丁 slug 时退回 project-N，不硬转拼音——拼音转出来的
    「manhuaduizhan」既不好认也不稳定，还不如一个带序号的中性名字。
    人看到的一直是 name（下拉里、页脚上都是它），slug 只是磁盘目录名。
    """
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")[:40]
    if not base:
        base = f"project-{len(taken) + 1}"
    if base not in taken:
        return base
    i = 2
    while f"{base}-{i}" in taken:
        i += 1
    return f"{base}-{i}"


def project_dir(data_root: Path, slug: str) -> Path:
    return data_root / "projects" / slug


def load_registry(data_root: Path) -> dict:
    reg = read_json(data_root / "projects.json", {"rev": 0, "active": None, "projects": []})
    reg.setdefault("rev", 0)
    reg.setdefault("projects", [])
    return reg


def save_registry(data_root: Path, reg: dict) -> None:
    """清单有增删改名时才走这里——它会推 rev，页面据此重拉项目列表。"""
    reg["rev"] = int(reg.get("rev") or 0) + 1
    write_json_atomic(data_root / "projects.json", reg)


def touch_registry(data_root: Path, slug: str, count: int) -> None:
    """只更新某个项目的物体数。**临写前重新读盘**，不要用进程启动时那份。

    这里曾经直接把内存里那份整份写回去，而那份是进程一启动就读好的。
    问题在于一个动作可能跑很久——`generate` 要四十秒，期间页面每 800ms
    触发一次动作、每次都是一个新进程。这四十秒里任何人新建或删掉了项目，
    都会被这份四十秒前的副本覆盖掉：新建的项目凭空消失，而且谁也说不清是怎么没的。

    重读之后窗口从「整个动作的时长」缩到「几微秒」。要彻底消除还得上文件锁，
    但对「一个人 + 一个页面」这个用法，这一步已经把实际风险拿掉了。
    """
    fresh = load_registry(data_root)
    entry = next((p for p in fresh["projects"] if p["slug"] == slug), None)
    if entry is None or entry.get("object_count") == count:
        return
    entry["object_count"] = count
    entry["updated_at"] = datetime.now().isoformat(timespec="seconds")
    write_json_atomic(data_root / "projects.json", fresh)


def new_project_entry(slug: str, name: str) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    return {
        "slug": slug, "name": name, "created_at": now, "updated_at": now,
        "object_count": 0, "cover": f"projects/{slug}/preview/latest.png",
    }


def migrate_to_projects(data_root: Path) -> dict:
    """把根目录下的老结构整体搬进 projects/street-corner/。

    幂等：projects.json 在就直接返回。**搬而不是复制**——留一份在原地的话，
    以后每个 bug 都得先花十分钟确认「我改的到底是哪一份」。
    """
    if (data_root / "projects.json").exists():
        return load_registry(data_root)

    legacy = [n for n in PROJECT_FILES + PROJECT_DIRS if (data_root / n).exists()]
    has_scene = (data_root / "scene.json").exists()

    slug = DEFAULT_PROJECT_SLUG if has_scene else "untitled"
    name = DEFAULT_PROJECT_NAME if has_scene else "未命名"
    pdir = project_dir(data_root, slug)
    pdir.mkdir(parents=True, exist_ok=True)

    moved = []
    for item in legacy:
        src, dst = data_root / item, pdir / item
        if dst.exists():
            continue
        src.rename(dst)
        moved.append(item)

    reg = {"rev": 0, "active": slug, "projects": [new_project_entry(slug, name)]}
    save_registry(data_root, reg)

    if moved:
        lines = "".join(f"- `{m}`\n" for m in moved)
        (data_root / "MIGRATED.md").write_text(
            "# 已迁移到项目结构\n\n"
            f"时间：{datetime.now().isoformat(timespec='seconds')}\n\n"
            "原来这些东西直接躺在数据目录根上，现在整体搬进了 "
            f"`projects/{slug}/`（项目名「{name}」）：\n\n" + lines +
            "\n是**搬**不是复制，根目录不再有第二份——两份真值比没有真值更糟。\n"
            "从此每个项目一份独立的场景与产物，互不串台。\n",
            encoding="utf-8",
        )
    return reg


def ensure_projects(data_root: Path) -> dict:
    """保证注册表在、active 指向一个真实存在的项目。"""
    data_root.mkdir(parents=True, exist_ok=True)
    reg = migrate_to_projects(data_root)

    if not reg["projects"]:
        slug = DEFAULT_PROJECT_SLUG
        project_dir(data_root, slug).mkdir(parents=True, exist_ok=True)
        reg["projects"] = [new_project_entry(slug, DEFAULT_PROJECT_NAME)]
        reg["active"] = slug
        save_registry(data_root, reg)

    known = {p["slug"] for p in reg["projects"]}
    if reg.get("active") not in known:
        reg["active"] = reg["projects"][0]["slug"]
        save_registry(data_root, reg)
    return reg


def resolve_project(params: dict, reg: dict) -> tuple:
    """`project` 缺省就是当前 active。

    给了但不存在必须报错，NEVER 静默落回 active——那会让 agent 以为自己改的是 A、
    其实改的是 B，而且两边看起来都「成功了」。
    """
    wanted = params.get("project")
    if not wanted:
        return reg["active"], None
    known = [p["slug"] for p in reg["projects"]]
    if wanted in known:
        return wanted, None
    return None, f"项目 {wanted!r} 不存在。现有：{', '.join(known)}"


# --- 右栏真值与轮询锚点 --------------------------------------------------


def rel_to_data(data_root: Path, path: Path) -> str:
    """绝对路径 → 页面能直接用的 data/ 相对路径。"""
    try:
        return "data/" + path.resolve().relative_to(data_root.resolve()).as_posix()
    except (ValueError, OSError):
        return str(path)


def latest_snapshot_info(data_root: Path, pdir: Path) -> dict:
    snap = latest_snapshot(pdir)
    if not snap:
        return {}
    out = {"stamp": snap.name}
    for view in SNAPSHOT_VIEWS:
        f = snap / f"{view}.png"
        out[view] = rel_to_data(data_root, f) if f.exists() else None
    return out


def write_panel(data_root: Path, pdir: Path, scene: dict) -> dict:
    """重写右栏的真值。

    右栏显示的参考图、图例、结果，全都是从磁盘推出来的。页面每 800ms 看一眼
    state.json 里的 panel_rev，变了就重拉这一份——所以「终端里出了张图、
    页面右栏当场跟着换」不需要任何推送机制，也不会再出现页面停在几小时前那一份。
    """
    old = read_json(pdir / "panel.json", {})
    panel = {
        "rev": int(old.get("rev") or 0) + 1,
        "scene_version": scene.get("version", 0),
        "legend": build_legend(scene),
        "snapshot": latest_snapshot_info(data_root, pdir),
        "recent": recent_results(data_root, pdir),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    write_json_atomic(pdir / "panel.json", panel)
    return panel


def write_state(data_root: Path, reg: dict, slug: str, panel: dict, scene: dict) -> None:
    """页面每 800ms 只读这一个小文件，从这里判断别处有没有动过东西。

    一次轮询看全局，而不是让页面对四五个文件各轮一遍：轮询次数会翻倍，
    而且几份东西到达的时机不同，页面会在半秒内闪过几种自相矛盾的状态。
    """
    previous = read_json(data_root / "state.json", {})

    # active **只能**来自注册表。写成「这次动作操作的是哪个项目」会出大事：
    # 一个慢动作打在 A 上、人中途切到 B，动作跑完把 active 盖回 A，
    # 页面看到 active 变了就整页切回 A——人切一次被拽回一次，
    # 而且怎么看都像是「切换按钮坏了」，根本想不到是几秒前那个请求在作祟。
    # 「人现在在看哪个项目」这件事，只有 project_switch / create / delete 有权改。
    active = reg.get("active")

    # panel_rev 和 scene_version 说的是「活动项目现在什么样」。
    # 动作打在非活动项目上时不许动它们，否则页面会为了一个它根本没在看的项目
    # 白重拉一遍右栏，人正在写的东西也跟着被刷掉。
    on_active = slug == active
    write_json_atomic(data_root / "state.json", {
        "active": active,
        "projects_rev": int(reg.get("rev") or 0),
        "panel_rev": int(panel.get("rev") or 0) if on_active else previous.get("panel_rev", 0),
        "scene_version": (scene.get("version", 0) if on_active
                          else previous.get("scene_version", 0)),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    })


def sync_project(data_root: Path, reg: dict, slug: str, pdir: Path) -> dict:
    """一次动作做完，把派生出来的东西全部对齐。

    放在 main() 一个地方做，而不是散在十几个 action 里各写一遍——
    散着写迟早有一个忘了刷新，表现是「别的都实时，唯独这个动作之后页面不动」，
    而这种毛病从现象根本猜不到是漏了哪一行。
    """
    scene = read_json(pdir / "scene.json", EMPTY_SCENE)
    panel = write_panel(data_root, pdir, scene)

    # 只改计数不推 rev：清单本身没有增删，页面不必重拉列表。
    touch_registry(data_root, slug, len(scene.get("objects") or []))

    # state.json 里的 projects_rev 也要用盘上的现值，不能用手里这份旧的——
    # 用旧的会让页面以为清单没变，于是新建的项目在页面上一直不出现。
    write_state(data_root, load_registry(data_root), slug, panel, scene)
    return panel


def ensure_project(pdir: Path) -> dict:
    """保证项目目录和它的真值文件都在。返回当前场景。

    页面一加载就会去拉这个项目的 scene.json / panel.json，
    文件不存在会是一条 404 —— 与其让前端去分辨「404 等于空场景」，
    不如在这里把空文件写出来，前端只处理一种情况。
    """
    pdir.mkdir(parents=True, exist_ok=True)
    for sub in PROJECT_DIRS:
        (pdir / sub).mkdir(exist_ok=True)

    scene_path = pdir / "scene.json"
    scene = read_json(scene_path, EMPTY_SCENE)
    if not scene_path.exists():
        scene["updated_at"] = datetime.now().isoformat(timespec="seconds")
        write_json_atomic(scene_path, scene)

    commands_path = pdir / "commands.json"
    if not commands_path.exists():
        write_json_atomic(commands_path, EMPTY_COMMANDS)

    return scene


# --- 校验 -------------------------------------------------------------


def as_vec3(value, field: str, errors: list, default=None):
    if value is None and default is not None:
        return list(default)
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        errors.append(f"{field} 要是三个数字，收到 {value!r}")
        return list(default) if default else [0.0, 0.0, 0.0]
    out = []
    for i, v in enumerate(value):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            errors.append(f"{field}[{i}] 不是数字：{v!r}")
            out.append(0.0)
        else:
            out.append(float(v))
    return out


def clean_object(raw, index: int, seen: set, errors: list) -> dict | None:
    if not isinstance(raw, dict):
        errors.append(f"第 {index + 1} 个物体不是对象")
        return None

    oid = str(raw.get("id") or "").strip()
    if not oid:
        errors.append(f"第 {index + 1} 个物体缺 id")
        return None
    if oid in seen:
        errors.append(f"物体 id 重复：{oid}")
        return None
    seen.add(oid)

    shape = raw.get("shape")
    if shape not in SHAPE_KEYS:
        errors.append(f"{oid} 的形状非法：{shape!r}，可用 {', '.join(SHAPE_KEYS)}")
        return None

    semantic = raw.get("semantic")
    if semantic not in SEMANTIC_KEYS:
        errors.append(f"{oid} 的语义非法：{semantic!r}，可用 {', '.join(SEMANTIC_KEYS)}")
        return None

    obj = {
        "id": oid,
        "shape": shape,
        "semantic": semantic,
        "position": as_vec3(raw.get("position"), f"{oid}.position", errors, [0, 0, 0]),
        "rotation": as_vec3(raw.get("rotation"), f"{oid}.rotation", errors, [0, 0, 0]),
        "scale": as_vec3(raw.get("scale"), f"{oid}.scale", errors, [1, 1, 1]),
    }
    label = raw.get("label")
    if label:
        obj["label"] = str(label)
    return obj


def clean_scene(raw, previous: dict, errors: list) -> dict:
    """把页面回写的整份场景洗干净。版本号只认服务端这一份，页面报什么都不算。"""
    if not isinstance(raw, dict):
        errors.append("scene 要是一个对象")
        return previous

    canvas_raw = raw.get("canvas") or {}
    aspect = canvas_raw.get("aspect")
    if aspect not in ASPECT_KEYS:
        errors.append(f"画幅非法：{aspect!r}，可用 {', '.join(ASPECT_KEYS)}")
        aspect = previous.get("canvas", {}).get("aspect", "16:9")
    preset = next(a for a in ASPECTS if a["key"] == aspect)

    camera_raw = raw.get("camera") or {}
    fov = camera_raw.get("fov", 40)
    if isinstance(fov, bool) or not isinstance(fov, (int, float)) or not 5 <= fov <= 120:
        errors.append(f"FOV 要在 5–120 之间，收到 {fov!r}")
        fov = 40

    seen: set = set()
    objects = []
    for i, raw_obj in enumerate(raw.get("objects") or []):
        obj = clean_object(raw_obj, i, seen, errors)
        if obj:
            objects.append(obj)

    return {
        "version": int(previous.get("version") or 0) + 1,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "canvas": {"aspect": aspect, "width": preset["width"], "height": preset["height"]},
        "camera": {
            "position": as_vec3(camera_raw.get("position"), "camera.position", errors, [6, 4, 8]),
            "target": as_vec3(camera_raw.get("target"), "camera.target", errors, [0, 0.8, 0]),
            "fov": float(fov),
        },
        "objects": objects,
    }


# --- action ------------------------------------------------------------


def catalog() -> dict:
    """体块库、色卡、画幅、机位预设——前端要显示的全部词表。"""
    return {
        "semantics": SEMANTICS,
        "shapes": SHAPES,
        "shapeScale": SHAPE_SCALE,
        "comboScale": COMBO_SCALE,
        "semanticShape": SEMANTIC_SHAPE,
        "aspects": ASPECTS,
        "cameraPresets": CAMERA_PRESETS,
        "promptPresets": PROMPT_PRESETS,
    }


def publish_page(state: dict, slot: str) -> str:
    """发布页面该显示的东西，返回页面地址。

    html/css/js 留在配方目录里由服务端直接发，这里只发状态。
    """
    r = subprocess.run(
        [*frago_argv(), "recipe", "publish", RECIPE_NAME, "--slot", slot],
        input=json.dumps(state, ensure_ascii=False),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if r.returncode != 0:
        raise RuntimeError(f"发布页面状态失败: {r.stderr.strip()[:300]}")
    return r.stdout.strip()


def recent_results(data_root: Path, pdir: Path) -> dict:
    """最近一次生成，写成页面直接能用的 data/ 相对路径。

    两个消费者：panel.json（主人侧每 800ms 同步的真值）和发布快照的 public 块
    （访客侧唯一拿得到的那份——他调不通任何 action，清单不随状态发布的话，
    看到的就是一个空网格加一排下载按钮，按钮在、没东西可下）。
    """
    path = pdir / "history.jsonl"
    if not path.exists():
        return {}
    last = None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("images"):
            last = entry
    if not last:
        return {}

    stamp = last["stamp"]
    snap_dir = pdir / "snapshots" / Path(last.get("snapshot_dir") or "").name
    return {
        "stamp": stamp,
        "prompt": last.get("prompt", ""),
        "images": [
            rel_to_data(data_root, pdir / "generated" / stamp / Path(p).name)
            for p in last["images"]
        ],
        "clay": rel_to_data(data_root, snap_dir / "clay.png"),
        "seg": rel_to_data(data_root, snap_dir / "seg.png"),
    }


def do_view(params: dict, data_root: Path, reg: dict, slug: str, pdir: Path, scene: dict) -> dict:
    """发布页面状态并返回地址。

    dataDir 指的是**数据根**而不是项目目录：页面拿到的一切路径都写成
    `data/projects/<slug>/…`，切项目时只是换一段路径，不必重新发布一次状态。
    """
    slot = str(params.get("slot") or "default")
    entry = next((p for p in reg["projects"] if p["slug"] == slug), {})
    state = {
        "dataDir": str(data_root),
        "activeProject": slug,
        "projectName": entry.get("name", slug),
        "sceneVersion": scene.get("version", 0),
        "objectCount": len(scene.get("objects") or []),
        "canvas": scene.get("canvas") or EMPTY_SCENE["canvas"],
        "stage": "dual",
        "catalog": catalog(),
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        # public 是访客唯一拿得到的那一块（见 frago book recipe-expose）。
        # 访客调不通任何 action，所以他要看的东西必须在这里备一份。
        "public": {
            "title": "白膜场景生图工作台",
            "projectName": entry.get("name", slug),
            "canvas": scene.get("canvas") or EMPTY_SCENE["canvas"],
            "legend": build_legend(scene),
            "recent": recent_results(data_root, pdir),
        },
    }
    url = publish_page(state, slot)

    result = {
        "success": True,
        "text": (
            f"白膜工作台：{url}\n"
            f"当前项目「{entry.get('name', slug)}」（{slug}），"
            f"{len(scene.get('objects') or [])} 个物体"
        ),
        "url": url,
        "slot": slot,
        "project": slug,
        "data_dir": str(data_root),
        "project_dir": str(pdir),
        "scene_version": state["sceneVersion"],
        "object_count": state["objectCount"],
    }
    # 打不开浏览器不算失败——地址照样吐出来，人可以自己粘。
    if not params.get("no_open"):
        result["open_url"] = url
    return result


def do_scene_get(scene: dict) -> dict:
    objects = scene.get("objects") or []
    return {
        "success": True,
        "text": f"场景 v{scene.get('version', 0)}，{len(objects)} 个物体",
        "scene": scene,
        "scene_version": scene.get("version", 0),
        "object_count": len(objects),
    }


def do_scene_put(params: dict, pdir: Path, previous: dict) -> dict:
    """页面整体回写。校验不过就整份拒绝，NEVER 半份落盘。

    半份落盘比拒绝更糟：人看到编辑器里东西还在，磁盘上已经少了几个，
    下一次轮询又把少掉的那份灌回编辑器，等于凭空删物体。
    """
    errors: list = []
    cleaned = clean_scene(params.get("scene"), previous, errors)
    if errors:
        return {
            "success": False,
            "error": "场景数据有问题，没有落盘：" + "；".join(errors[:8]),
            "issues": errors,
            "scene_version": previous.get("version", 0),
        }

    write_json_atomic(pdir / "scene.json", cleaned)
    return {
        "success": True,
        "text": f"场景已保存 v{cleaned['version']}，{len(cleaned['objects'])} 个物体",
        "scene_version": cleaned["version"],
        "object_count": len(cleaned["objects"]),
        "updated_at": cleaned["updated_at"],
    }


# --- 渲染 ---------------------------------------------------------------


def semantic_colors() -> dict:
    return {s["key"]: s["color"] for s in SEMANTICS}


def load_renderer():
    """光栅器按需 import。

    numpy 一进来就是一百多毫秒，而 view / scene_get / scene_put 这些高频动作
    一个像素都不画——页面每次拖动都要走 scene_put，让它们陪着付这份钱不值得。
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import render

    return render


def canvas_size(scene: dict, params: dict) -> tuple:
    canvas = scene.get("canvas") or {}
    width = int(params.get("width") or canvas.get("width") or 1280)
    height = int(params.get("height") or canvas.get("height") or 720)
    return max(16, width), max(16, height)


def do_snapshot(params: dict, data_root: Path, pdir: Path, scene: dict) -> dict:
    """出 clay / seg / depth。**不走页面握手**——服务端自己会画。

    这是双通道决定里最实的一条：以前必须先请人把页面打开，
    现在 agent 直接就能拿到图，端到端测试也才跑得通。
    """
    views = params.get("views") or ["clay", "seg"]
    bad = [v for v in views if v not in SNAPSHOT_VIEWS]
    if bad:
        return {
            "success": False,
            "error": f"不认识的通道：{', '.join(bad)}。可用 {', '.join(SNAPSHOT_VIEWS)}",
        }
    if not scene.get("objects"):
        return {"success": False, "error": "场景是空的，没有东西可渲染。先放几个体块。"}

    render = load_renderer()
    width, height = canvas_size(scene, params)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = pdir / "snapshots" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    colors = semantic_colors()
    paths = {}
    for view in views:
        # clay 超采样两倍再降下来，边缘才不毛躁；seg 在 render.py 里被强制
        # 关掉超采样——混出来的中间色会让「红色=人物」这句话失真。
        target = out_dir / f"{view}.png"
        render.render_to_file(scene, colors, view, width, height, target, supersample=2)
        paths[view] = str(target)

    meta = {
        "stamp": stamp,
        "views": list(views),
        "width": width,
        "height": height,
        "scene_version": scene.get("version", 0),
        "camera": scene.get("camera"),
        "canvas": scene.get("canvas"),
        "legend": build_legend(scene),
        "rendered_by": "server",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    write_json_atomic(out_dir / "meta.json", meta)

    return {
        "success": True,
        "text": f"已渲染 {len(paths)} 张 {width}×{height}：{'、'.join(paths)}",
        "dir": str(out_dir),
        "paths": paths,
        # 页面要的是相对 data/ 的路径，直接给它算好，别让前端去拼绝对路径
        "clay_rel": rel_to_data(data_root, out_dir / "clay.png") if "clay" in paths else None,
        "seg_rel": rel_to_data(data_root, out_dir / "seg.png") if "seg" in paths else None,
        **{v: paths.get(v) for v in SNAPSHOT_VIEWS},
        "meta": meta,
    }


def do_preview(params: dict, data_root: Path, pdir: Path, scene: dict) -> dict:
    """给页面的低分辨率预览。没有 WebGL 的浏览器靠它当视口。

    可以直接把要看的场景传进来，不必先落盘。页面的改动是防抖 400ms 才回写的，
    而预览 220ms 就要一张——不给这条路，预览永远比手上的动作慢一拍，
    人点下一个物体时看到的还是上一个物体没出现的画面。
    """
    if isinstance(params.get("scene"), dict):
        errors: list = []
        scene = clean_scene(params["scene"], {"version": scene.get("version", 0)}, errors)
        if errors:
            return {"success": False, "error": "预览的场景数据有问题：" + "；".join(errors[:5])}

    render = load_renderer()
    width, height = canvas_size(scene, params)
    scale = PREVIEW_LONG_EDGE / max(width, height)
    if scale < 1:
        width, height = max(16, int(width * scale)), max(16, int(height * scale))

    out_dir = pdir / "preview"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "latest.png"
    # 临时名也得以 .png 收尾：Pillow 是按扩展名推格式的，给它 .tmp 会直接抛
    # ValueError: unknown file extension。
    tmp = out_dir / "latest-writing.png"

    view = params.get("view") or "preview"
    render.render_to_file(scene, semantic_colors(), view, width, height, tmp, supersample=1)
    # 页面每次都在读这一个文件名，直接覆写会读到写了一半的 PNG。
    tmp.replace(target)

    return {
        "success": True,
        "text": f"预览已更新 {width}×{height}",
        "path": str(target),
        "rel_url": rel_to_data(data_root, target),
        "width": width,
        "height": height,
        "scene_version": scene.get("version", 0),
    }


# --- 图例 ---------------------------------------------------------------


def build_legend(scene: dict) -> str:
    """按当前场景拼一段中文图例，默认放在用户提示词前面。

    这段不是装饰，是这个工具的产品核心：白膜图告诉模型「哪里有个立着的东西」，
    图例才告诉它「那个东西是人，而且是打伞的女人」。

    **写法上有一个致命的坑，实测踩过：**
    原来写的是「#8E44AD 紫色 = 道具（1 个：行李箱）」，模型读成了「行李箱是紫色的」——
    出的四张图里人是纯红、箱子是紫、树是绿，五个颜色跟色卡一一对应，
    连分割图的黑色背景都被当成黑夜空画了出来。提示词弱的时候没有别的信息压住它，
    这个误读就会整个暴露。

    所以现在必须把三件事讲死：这些颜色只是**标记区域归属的记号**、
    成片里 NEVER 出现这些颜色、黑色区域是「那里没东西」而不是黑夜。
    色块的中文颜色名也去掉了——「紫色 = 道具」这种写法本身就是在教它上色。
    """
    objects = scene.get("objects") or []
    if not objects:
        return ""

    by_semantic = {}
    for obj in objects:
        by_semantic.setdefault(obj.get("semantic"), []).append(obj)

    parts = []
    for s in SEMANTICS:                       # 按色卡顺序输出，每次都一致
        group = by_semantic.get(s["key"])
        if not group:
            continue
        labels = [o["label"] for o in group if o.get("label")]
        quoted = "、".join(f'"{t}"' for t in labels)
        if not labels:
            detail = f"{len(group)} 个"
        elif len(labels) == len(group):
            detail = f"{len(group)} 个：{quoted}"
        else:
            detail = f"{len(group)} 个，其中 {quoted}"
        parts.append(f'{s["color"]} 的区域是{s["label"]}（{detail}）')

    return (
        "参考图 1 是三维体块的白模渲染，参考图 2 是同一机位的语义分割图。\n"
        "请严格遵循这两张图里的相机角度、透视关系、各物体的位置与遮挡次序。\n"
        "\n"
        "关于参考图 2，有三件事必须先说清楚：\n"
        "1. 图上的颜色只是**用来标出哪块区域属于哪个东西的记号**，"
        "不是物体的颜色，也不是这幅画的配色方案。\n"
        "2. 成片里 NEVER 出现这些颜色。每个物体该是什么颜色、什么材质，"
        "由下面的描述和生活常识决定。\n"
        "3. 图上的**黑色区域表示那里没有物体**（是空白），"
        "不是黑夜、不是黑色背景板、不是深色的天空。\n"
        "\n"
        "各区域的归属：" + "；".join(parts) + "。\n"
        "\n"
        "白模只表示体积和位置，不表示材质、颜色与细节。这些以下面的描述为准：\n"
    )


# --- 生图 ---------------------------------------------------------------

# 方舟对出图尺寸有两条硬约束，都是实测撞出来的 400：
#   1. size 只认 'WIDTHxHEIGHT' 或 2k/3k/4k —— 传 '1K' 直接 InvalidParameter。
#   2. 面积至少 3,686,400 像素（正好 2560×1440）—— 画幅尺寸 1280×720 只有它的四分之一。
SEEDREAM_MIN_PIXELS = 3_686_400


def seedream_size(canvas: dict) -> str:
    """把画幅比放大到方舟的面积下限，比例一点不变。

    比例必须守住：人在左边锁了 9:16、右边却出一张方图的话，
    「构图有没有跟住白膜」就无从谈起了——参考图和出图得是同一个画幅。
    """
    width = int(canvas.get("width") or 1280)
    height = int(canvas.get("height") or 720)
    ratio = width / height

    def up16(x: float) -> int:
        return int(-(-x // 16) * 16)      # 向上取整到 16 的倍数

    h = up16((SEEDREAM_MIN_PIXELS / ratio) ** 0.5)
    w = up16(h * ratio)
    while w * h < SEEDREAM_MIN_PIXELS:    # 取整可能把面积抹掉一点，补回来
        h += 16
        w = up16(h * ratio)
    return f"{w}x{h}"


def do_generate(params: dict, data_root: Path, pdir: Path, scene: dict) -> dict:
    """拼图例 + 白膜图 + 分割图，交给 Seedream。

    凭证不在这里读：subprocess 调子配方，runner 按子配方名注入。
    """
    prompt = (params.get("prompt") or "").strip()
    if not prompt:
        return {"success": False, "error": "generate 需要 prompt——白膜只管构图，材质和细节得靠它"}
    if not scene.get("objects"):
        return {"success": False, "error": "场景是空的。先摆几个体块，白膜图才有内容可参考。"}

    snap = do_snapshot(
        {"views": params.get("use_views") or ["clay", "seg"]}, data_root, pdir, scene
    )
    if not snap.get("success"):
        return snap

    legend = build_legend(scene)
    if params.get("legend") is not None:
        legend = str(params["legend"])
    full_prompt = f"{legend}\n{prompt}" if legend else prompt

    images = [p for p in snap["paths"].values()]
    for extra in params.get("extra_images") or []:
        if Path(extra).expanduser().exists():
            images.append(str(Path(extra).expanduser()))

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = pdir / "generated" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    size = params.get("size") or seedream_size(scene.get("canvas") or {})

    count = max(1, min(int(params.get("n") or 1), 4))
    results, errors = [], []
    for i in range(count):
        # 子配方一次出一张，要几张就叫几次。
        child = {
            "prompt": full_prompt,
            "image": images,
            "size": size,
            "output_dir": str(out_dir),
            "filename": f"{i + 1}",
        }
        if params.get("model"):
            child["model"] = params["model"]

        r = subprocess.run(
            [*frago_argv(), "recipe", "run", SEEDREAM_RECIPE, "--params",
             json.dumps(child, ensure_ascii=False)],
            capture_output=True, text=True, timeout=300,
        )
        if r.returncode != 0:
            errors.append(r.stderr.strip()[:300] or r.stdout.strip()[:300])
            continue
        path = out_dir / f"{i + 1}.png"
        if path.exists():
            results.append(str(path))
        else:
            found = sorted(p for p in out_dir.glob(f"{i + 1}.*") if p.suffix != ".json")
            if found:
                results.append(str(found[0]))

    entry = {
        "stamp": stamp,
        "scene_version": scene.get("version", 0),
        "prompt": prompt,
        "legend": legend,
        "full_prompt": full_prompt,
        "reference_images": images,
        "snapshot_dir": snap["dir"],
        "images": results,
        "errors": errors,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    write_json_atomic(out_dir / "request.json", entry)
    with (pdir / "history.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    if not results:
        return {
            "success": False,
            "error": "一张都没出来：" + ("；".join(errors) if errors else "子配方没报错也没落图"),
            "history_id": stamp,
            "snapshot_dir": snap["dir"],
        }

    return {
        "success": True,
        "text": f"出图 {len(results)} 张，参考图 {len(images)} 张",
        "images": results,
        "rel_images": [rel_to_data(data_root, Path(p)) for p in results],
        "history_id": stamp,
        "snapshot_dir": snap["dir"],
        "clay": snap["paths"].get("clay"),
        "rel_clay": rel_to_data(data_root, Path(snap["paths"]["clay"])) if snap["paths"].get("clay") else None,
        "legend": legend,
        "errors": errors,
    }


def do_history(data_root: Path, pdir: Path, limit: int = 20) -> dict:
    path = pdir / "history.jsonl"
    if not path.exists():
        return {"success": True, "entries": [], "text": "还没生成过"}
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    entries = entries[-limit:]
    for e in entries:
        e["rel_images"] = [
            rel_to_data(data_root, Path(p)) for p in e.get("images") or []
        ]
    return {"success": True, "entries": entries, "text": f"{len(entries)} 条生成记录"}


# --- agent 接口：场景编辑 ------------------------------------------------


def r3(value: float) -> float:
    """保留三位小数，并把 -0.0 归成 0.0。

    -0.0 在 JSON 里原样打出来，读的人会以为是算错了符号——它其实等于 0。
    """
    return round(float(value), 3) + 0.0


def canvas_aspect(scene: dict) -> float:
    canvas = scene.get("canvas") or {}
    return float(canvas.get("width") or 1280) / float(canvas.get("height") or 720)


def persist(pdir: Path, previous: dict, new_scene: dict) -> tuple:
    """所有服务端改动的唯一落盘口。

    一律过一遍 clean_scene：agent 传进来的东西跟页面传进来的一样不可信，
    而且这样版本号只有一个地方在涨，不会出现两条路径各涨各的。
    """
    errors: list = []
    cleaned = clean_scene(new_scene, previous, errors)
    if errors:
        return None, "场景数据有问题，没有落盘：" + "；".join(errors[:6])
    write_json_atomic(pdir / "scene.json", cleaned)
    return cleaned, None


def object_choices(objects: list) -> str:
    """报错时列出现有物体，id 和名字一起给——只报 id 的话人对不上号。"""
    if not objects:
        return "（场景是空的）"
    return "、".join(
        f'{o["id"]}「{o.get("label")}」' if o.get("label") else o["id"] for o in objects
    )


def resolve_ref(ref, objects: list, field: str = "id") -> tuple:
    """把一个物体引用解析成 id。id 和**名字**都认。

    人说「把盆栽往左挪」，agent 也会顺着说「盆栽」——而它在放下一个新物体之前
    根本无从知道服务端会分配哪个 id，所以「用名字引用刚放下的东西」是唯一合理的写法。
    只认 id 的契约等于逼调用方去猜一个还不存在的编号。

    重名和找不到都要说清楚：含糊地挑一个，人会以为改的是 A、其实改的是 B。
    """
    if ref is None or ref == "":
        return None, f"{field} 没给"
    ref = str(ref)

    if any(o.get("id") == ref for o in objects):
        return ref, None

    exact = [o["id"] for o in objects if (o.get("label") or "") == ref]
    if len(exact) == 1:
        return exact[0], None
    if len(exact) > 1:
        return None, f"有 {len(exact)} 个物体都叫「{ref}」（{', '.join(exact)}），请直接用 id 指名"

    loose = [o["id"] for o in objects if ref in (o.get("label") or "")]
    if len(loose) == 1:
        return loose[0], None
    if len(loose) > 1:
        return None, f"「{ref}」对得上好几个物体（{', '.join(loose)}），请直接用 id 指名"

    return None, f"{field} 找不到 {ref!r}。现有：{object_choices(objects)}"


def next_object_id(objects: list) -> str:
    used = {str(o.get("id")) for o in objects}
    biggest = 0
    for o in objects:
        oid = str(o.get("id") or "")
        if oid.startswith("obj_") and oid[4:].isdigit():
            biggest = max(biggest, int(oid[4:]))
    while True:
        biggest += 1
        candidate = f"obj_{biggest}"
        if candidate not in used:
            return candidate


def build_object(params: dict, objects: list, position=None) -> tuple:
    """按 agent 给的参数造一个物体。尺寸可以给 dims（米）也可以给 scale（倍数）。

    dims 那条路是给 agent 走的：说「4.6 米长的车」比说「scale 4.6」自然，
    也不用去记胶囊的单位体比别的窄一半这件事。
    """
    semantic = params.get("semantic")
    if semantic not in SEMANTIC_KEYS:
        return None, f"语义非法：{semantic!r}，可用 {', '.join(SEMANTIC_KEYS)}"

    # shape 可以不给：语义已经蕴含了一个合理的形状（人=胶囊、车=方块、树=圆锥）。
    # 因为少写一个字段就整批拒绝，对调用方太苛刻——「放一把椅子」里
    # 「椅子」这个信息已经足够了，非要它再说一遍「用方块」是多余的。
    shape = params.get("shape") or SEMANTIC_SHAPE.get(semantic)
    if shape not in SHAPE_KEYS:
        return None, f"形状非法：{params.get('shape')!r}，可用 {', '.join(SHAPE_KEYS)}"

    if params.get("dims"):
        dims = params["dims"]
        if not isinstance(dims, (list, tuple)) or len(dims) != 3:
            return None, "dims 要是三个数字：宽 高 深，单位米"
        scale = scene_ops.dims_to_scale(shape, dims)
    elif params.get("scale"):
        scale = list(params["scale"])
    else:
        scale = default_scale(shape, semantic)

    obj = {
        "id": params.get("id") or next_object_id(objects),
        "shape": shape,
        "semantic": semantic,
        "position": list(position if position is not None else (params.get("position") or [0, 0, 0])),
        "rotation": list(params.get("rotation") or [0, 0, 0]),
        "scale": [round(float(v), 4) for v in scale],
    }
    if params.get("label"):
        obj["label"] = str(params["label"])
    return obj, None


def describe_object(obj: dict) -> dict:
    """报给 agent 看的物体。带上米数——倍数它读不出「这有多大」。"""
    dims = scene_ops.scale_to_dims(obj["shape"], obj["scale"])
    return {
        "id": obj["id"],
        "shape": obj["shape"],
        "semantic": obj["semantic"],
        "label": obj.get("label"),
        "position": obj["position"],
        "rotation": obj["rotation"],
        "scale": obj["scale"],
        "dims_m": [round(v, 3) for v in dims],
    }


def do_object_add(params: dict, pdir: Path, scene: dict) -> dict:
    objects = list(scene.get("objects") or [])
    obj, err = build_object(params, objects)
    if err:
        return {"success": False, "error": err}

    objects.append(obj)
    cleaned, err = persist(pdir, scene, {**scene, "objects": objects})
    if err:
        return {"success": False, "error": err}

    dims = [round(v, 2) for v in scene_ops.scale_to_dims(obj["shape"], obj["scale"])]
    return {
        "success": True,
        "text": f"已放入 {obj['id']}（{obj['semantic']} · {obj['shape']}，{dims[0]}×{dims[1]}×{dims[2]} 米）",
        "id": obj["id"],
        "object": describe_object(obj),
        "scene_version": cleaned["version"],
    }


def do_object_update(params: dict, pdir: Path, scene: dict) -> dict:
    objects = [dict(o) for o in scene.get("objects") or []]
    oid, err = resolve_ref(params.get("id"), objects, "id")
    if err:
        return {"success": False, "error": err}
    target = next(o for o in objects if o["id"] == oid)

    changed = []
    if params.get("dims"):
        dims = params["dims"]
        if not isinstance(dims, (list, tuple)) or len(dims) != 3:
            return {"success": False, "error": "dims 要是三个数字：宽 高 深，单位米"}
        target["scale"] = [
            round(v, 4) for v in scene_ops.dims_to_scale(target["shape"], dims)
        ]
        changed.append("dims")

    for key in ("position", "rotation", "scale"):
        if params.get(key) is not None and not (key == "scale" and "dims" in changed):
            target[key] = list(params[key])
            changed.append(key)

    for key in ("shape", "semantic", "label"):
        if params.get(key) is not None:
            target[key] = params[key]
            changed.append(key)

    if not changed:
        return {
            "success": False,
            "error": "没给要改的字段。可改：position / rotation / scale / dims / shape / semantic / label",
        }

    cleaned, err = persist(pdir, scene, {**scene, "objects": objects})
    if err:
        return {"success": False, "error": err}

    updated = next(o for o in cleaned["objects"] if o["id"] == oid)
    return {
        "success": True,
        "text": f"{oid} 已改：{', '.join(changed)}",
        "changed": changed,
        "object": describe_object(updated),
        "scene_version": cleaned["version"],
    }


def do_object_delete(params: dict, pdir: Path, scene: dict) -> dict:
    objects = list(scene.get("objects") or [])
    oid, err = resolve_ref(params.get("id"), objects, "id")
    if err:
        return {"success": False, "error": err}
    label = scene_ops.label_of(next(o for o in objects if o["id"] == oid))
    remaining = [o for o in objects if o.get("id") != oid]

    cleaned, err = persist(pdir, scene, {**scene, "objects": remaining})
    if err:
        return {"success": False, "error": err}
    return {
        "success": True,
        "text": f"已删除 {oid}「{label}」，还剩 {len(remaining)} 个物体",
        "id": oid,
        "scene_version": cleaned["version"],
    }


def do_scene_clear(pdir: Path, scene: dict) -> dict:
    count = len(scene.get("objects") or [])
    cleaned, err = persist(pdir, scene, {**scene, "objects": []})
    if err:
        return {"success": False, "error": err}
    return {
        "success": True,
        "text": f"场景已清空，删掉了 {count} 个物体（相机和画幅没动）",
        "removed": count,
        "scene_version": cleaned["version"],
    }


def do_place(params: dict, pdir: Path, scene: dict) -> dict:
    """按语义放置：挨着谁、在哪边、隔多远。

    这是 agent 摆场景最该走的一条路。让它自己算世界坐标，等于要求它
    在脑子里同时装着相机朝向和每个物体的包围盒——算错了还不自知，
    出图才发现人站在车里。
    """
    objects = list(scene.get("objects") or [])
    ref_id, err = resolve_ref(params.get("relative_to"), objects, "relative_to")
    if err:
        return {"success": False, "error": err}
    ref = next(o for o in objects if o["id"] == ref_id)

    direction = params.get("direction") or "right"
    if direction not in ("front", "back", "left", "right", "above", "below"):
        return {
            "success": False,
            "error": f"方向 {direction!r} 不认识。可用 front / back / left / right / above / below",
        }

    try:
        distance = float(params.get("distance", 1.0))
    except (TypeError, ValueError):
        return {"success": False, "error": f"distance 要是数字，收到 {params.get('distance')!r}"}
    if distance < 0:
        return {"success": False, "error": "distance 不能是负数——换个方向而不是给负距离"}

    # align 是可选的精调项，只有 ground / center 两种。给错了退回默认并在回话里说一声，
    # 不因为一个可选字段写错就把整句话拒掉——那正是「最自然的说法反而失败」的来源。
    align = params.get("align") or "ground"
    align_note = ""
    if align not in ("ground", "center"):
        align_note = f"（align={align!r} 不认识，按 ground 处理）"
        align = "ground"

    proto, err = build_object(params, objects, position=[0.0, 0.0, 0.0])
    if err:
        return {"success": False, "error": err}

    solved, err = scene_ops.solve_placement(
        ref, proto, direction, distance, align, scene.get("camera") or {}
    )
    if err:
        return {"success": False, "error": err}

    proto["position"] = [r3(v) for v in solved["position"]]
    objects.append(proto)
    cleaned, err = persist(pdir, scene, {**scene, "objects": objects})
    if err:
        return {"success": False, "error": err}

    words = {
        "front": "前面（更靠近相机）", "back": "后面（更远离相机）",
        "left": "左边", "right": "右边", "above": "上方", "below": "下方",
    }[direction]
    if solved.get("note"):
        align_note += f"（{solved['note']}）"
    return {
        "success": True,
        "text": (
            f"已把 {proto['id']} 放在「{scene_ops.label_of(ref)}」的{words}，"
            f"净空 {distance} 米，落点 {proto['position']}{align_note}"
        ),
        "id": proto["id"],
        "position": proto["position"],
        "object": describe_object(proto),
        "relative_to": ref_id,
        "direction": direction,
        "gap_m": distance,
        "scene_version": cleaned["version"],
    }


def do_move(params: dict, pdir: Path, scene: dict) -> dict:
    """把已有物体沿某个方向挪一段距离。方向按相机朝向解释。

    这是「往左挪半米」的对应动作。以前没有它，调用方只能硬套 place——
    而 place 是**放新的**，套上去要么多出一个物体，要么因为缺 shape 整批被拒。
    一句最自然的话没有对应动作，怪不到说话的人头上。

    跟 place 的区别就一句：place 的 distance 是两个物体之间的净空，
    move 的 distance 是这个物体自己挪了多远。
    """
    objects = [dict(o) for o in scene.get("objects") or []]
    oid, err = resolve_ref(params.get("id"), objects, "id")
    if err:
        return {"success": False, "error": err}
    target = next(o for o in objects if o["id"] == oid)

    direction = params.get("direction")
    vec = scene_ops.ground_direction(direction, scene.get("camera") or {})
    if vec is None:
        return {
            "success": False,
            "error": f"方向 {direction!r} 不认识。可用 front / back / left / right / above / below",
        }

    try:
        distance = float(params.get("distance", 0.5))
    except (TypeError, ValueError):
        return {"success": False, "error": f"distance 要是数字，收到 {params.get('distance')!r}"}

    before = list(target["position"])
    target["position"] = [r3(before[i] + vec[i] * distance) for i in range(3)]

    # 贴地物体横向挪动不该被浮点误差抬离地面；真要抬高就用 above。
    if direction not in ("above", "below") and abs(before[1]) < 1e-6:
        target["position"][1] = 0.0

    cleaned, err = persist(pdir, scene, {**scene, "objects": objects})
    if err:
        return {"success": False, "error": err}

    words = {"front": "靠近相机", "back": "远离相机", "left": "左", "right": "右",
             "above": "上", "below": "下"}[direction]
    return {
        "success": True,
        "text": (
            f"「{scene_ops.label_of(target)}」往{words}挪了 {distance} 米："
            f"{[round(v, 2) for v in before]} → {target['position']}"
        ),
        "id": oid,
        "from": before,
        "position": target["position"],
        "object": describe_object(target),
        "scene_version": cleaned["version"],
    }


# --- agent 接口：测量与体检 ---------------------------------------------


def do_measure(params: dict, scene: dict) -> dict:
    objects = scene.get("objects") or []
    by_id = {o["id"]: o for o in objects if o.get("id")}
    a_id, err = resolve_ref(params.get("a"), objects, "a")
    if err:
        return {"success": False, "error": err}
    b_id, err = resolve_ref(params.get("b"), objects, "b")
    if err:
        return {"success": False, "error": err}

    a_box = scene_ops.object_aabb(by_id[a_id])
    b_box = scene_ops.object_aabb(by_id[b_id])
    camera = scene.get("camera") or {}

    center_dist = scene_ops.length(
        scene_ops.sub(scene_ops.aabb_center(a_box), scene_ops.aabb_center(b_box))
    )
    gap = scene_ops.surface_gap(a_box, b_box)
    overlap = scene_ops.aabb_overlap(a_box, b_box)
    intersecting = all(o > 0 for o in overlap)
    heading = scene_ops.describe_direction(a_box, b_box, camera)

    a_label = scene_ops.label_of(by_id[a_id])
    b_label = scene_ops.label_of(by_id[b_id])
    if intersecting:
        gap_text = f"两者穿模，最浅的一轴嵌进去 {min(overlap):.2f} 米"
    else:
        gap_text = f"表面之间还有 {gap:.2f} 米空地"

    return {
        "success": True,
        "text": f"「{a_label}」在「{b_label}」的{heading['text']}，中心距 {center_dist:.2f} 米；{gap_text}",
        "a": a_id,
        "b": b_id,
        "distance": round(center_dist, 3),
        "surface_gap": round(gap, 3),
        "direction": heading,
        "aabb_overlap": intersecting,
        "overlap_m": [round(v, 3) for v in overlap],
    }


def do_validate(scene: dict) -> dict:
    """场景体检。报三类问题，每条都带 id 和一句人话。"""
    issues = scene_ops.find_issues(scene, canvas_aspect(scene))
    if not issues:
        return {
            "success": True,
            "text": f"体检通过：{len(scene.get('objects') or [])} 个物体，没有穿模、悬空或出画",
            "issues": [],
            "ok": True,
        }

    by_kind: dict = {}
    for issue in issues:
        by_kind.setdefault(issue["kind"], []).append(issue)
    summary = "、".join(
        f"{len(v)} 处{ {'intersect': '穿模', 'floating': '悬空', 'sunken': '陷地',
                        'out_of_frame': '出画', 'partly_out_of_frame': '部分出画'}[k] }"
        for k, v in by_kind.items()
    )
    lines = [f"体检发现 {len(issues)} 个问题（{summary}）："]
    lines += [f"  · {i['message']}" for i in issues]

    return {
        "success": True,     # 查出问题不等于这次调用失败
        "text": "\n".join(lines),
        "issues": issues,
        "ok": False,
    }


# --- agent 接口：相机 ----------------------------------------------------


def do_camera_set(params: dict, pdir: Path, scene: dict) -> dict:
    camera = dict(scene.get("camera") or {})
    objects = scene.get("objects") or []
    preset_key = params.get("preset")

    if preset_key:
        preset = next((p for p in CAMERA_PRESETS if p["key"] == preset_key), None)
        if not preset:
            keys = ", ".join(p["key"] for p in CAMERA_PRESETS)
            return {"success": False, "error": f"没有预设 {preset_key!r}。可用：{keys}"}

        target_id = params.get("target_id")
        if target_id:
            target_id, err = resolve_ref(target_id, objects, "target_id")
            if err:
                return {"success": False, "error": err}
            bounds = scene_ops.object_aabb(next(o for o in objects if o["id"] == target_id))
        else:
            bounds = scene_ops.framing_aabb(objects)

        pose = scene_ops.solve_preset(preset, bounds, camera)
        camera["position"] = [r3(v) for v in pose["position"]]
        camera["target"] = [r3(v) for v in pose["target"]]
        note = f"机位切到「{preset['label']}」"
        if target_id:
            note += f"，对着 {target_id}"
    else:
        given = [k for k in ("position", "target", "fov") if params.get(k) is not None]
        if not given:
            return {
                "success": False,
                "error": "camera_set 要么给 position / target / fov，要么给 preset（可选配 target_id）",
            }
        for key in ("position", "target"):
            if params.get(key) is not None:
                camera[key] = list(params[key])
        note = "相机已按给定位姿设置"

    if params.get("fov") is not None:
        camera["fov"] = params["fov"]

    cleaned, err = persist(pdir, scene, {**scene, "camera": camera})
    if err:
        return {"success": False, "error": err}

    cam = cleaned["camera"]
    return {
        "success": True,
        "text": (
            f"{note}：位置 {cam['position']}，看向 {cam['target']}，FOV {cam['fov']}°"
        ),
        "camera": cam,
        "scene_version": cleaned["version"],
    }


def do_camera_frame(params: dict, pdir: Path, scene: dict) -> dict:
    """解出能把指定物体全框住的机位。fov 不动——换镜头是创作决定，取景不该替人做。"""
    objects = scene.get("objects") or []
    if not objects:
        return {"success": False, "error": "场景是空的，没有东西可框"}

    by_id = {o["id"]: o for o in objects if o.get("id")}
    targets = params.get("targets")
    if targets:
        if isinstance(targets, str):
            targets = [targets]
        resolved, bad = [], []
        for t in targets:
            rid, err = resolve_ref(t, objects, "targets")
            (bad if err else resolved).append(err or rid)
        if bad:
            return {"success": False, "error": "；".join(bad)}
        targets = list(dict.fromkeys(resolved))     # 名字和 id 混着给可能指向同一个

        # 显式点名的地面/水面也要剔掉。人说「框住天台上所有东西」，
        # 地面确实是场景里的一个物体，照字面算进去就要框住一块 30×30 米的地板——
        # 相机被推到几十米外，主体缩成几个点，而他要的恰恰是看清那些主体。
        # 只有当点名的全是面时才照办：那种情况下他是真想看那块地。
        subjects = [t for t in targets
                    if by_id[t].get("semantic") not in scene_ops.SURFACE_SEMANTICS]
        dropped = [by_id[t] for t in targets if t not in subjects]
        if subjects:
            targets = subjects
        bounds = scene_ops.aabb_union([scene_ops.object_aabb(by_id[t]) for t in targets])
    else:
        # 不指定就框全部主体。地面不算——它铺 40 米，算进去相机会退到几十米外。
        targets = [o["id"] for o in objects
                   if o.get("id") and o.get("semantic") not in scene_ops.SURFACE_SEMANTICS]
        dropped = []
        bounds = scene_ops.framing_aabb(objects)

    try:
        margin = float(params.get("margin", 0.12))
    except (TypeError, ValueError):
        return {"success": False, "error": f"margin 要是数字，收到 {params.get('margin')!r}"}

    camera = dict(scene.get("camera") or {})
    pose = scene_ops.solve_frame(bounds, camera, canvas_aspect(scene), margin)
    camera["position"] = [r3(v) for v in pose["position"]]
    camera["target"] = [r3(v) for v in pose["target"]]

    cleaned, err = persist(pdir, scene, {**scene, "camera": camera})
    if err:
        return {"success": False, "error": err}

    # 解完自查一次：说「都框住了」之前，先按新机位算一遍谁还在画外。
    check = scene_ops.find_issues(cleaned, canvas_aspect(cleaned))
    out = [i for i in check if i["kind"] in ("out_of_frame", "partly_out_of_frame")
           and set(i["ids"]) & set(targets)]

    cam = cleaned["camera"]
    text = f"已框住 {len(targets)} 个目标：位置 {cam['position']}，看向 {cam['target']}，FOV {cam['fov']}°"
    if dropped:
        names = "、".join(f"「{scene_ops.label_of(o)}」" for o in dropped)
        text += f"\n（{names}是铺开的面，算进去会把相机推到很远，已从取景里排除）"
    if out:
        text += "\n⚠ 但还有没装下的：" + "；".join(i["message"] for i in out)

    return {
        "success": True,
        "text": text,
        "camera": cam,
        "targets": targets,
        "margin": margin,
        "still_out_of_frame": out,
        "scene_version": cleaned["version"],
    }


# --- agent 接口：看图评价 ------------------------------------------------


CRITIQUE_SCHEMA = (
    '{"verdict": "good|acceptable|bad", "summary": "一句话总体判断", '
    '"issues": [{"what": "问题是什么", "where": "画面里哪个位置", "severity": "high|medium|low"}], '
    '"suggestions": [{"action": "该怎么改", "why": "为什么"}]}'
)


def latest_snapshot(pdir: Path) -> Path | None:
    root = pdir / "snapshots"
    if not root.exists():
        return None
    dirs = sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: d.name)
    return dirs[-1] if dirs else None


def do_critique(params: dict, pdir: Path, scene: dict) -> dict:
    """把快照交给多模态模型，回结构化判断。

    几何能查的（穿模、悬空、出画）已经由 validate 查过了，一并喂给模型当已知事实——
    否则它会把注意力花在重新发现这些上，而它恰恰不擅长；
    真正只有眼睛能判断的是构图、留白、遮挡关系读不读得懂。
    """
    snap_dir = Path(params["snapshot_dir"]).expanduser() if params.get("snapshot_dir") else latest_snapshot(pdir)
    if not snap_dir or not snap_dir.exists():
        return {
            "success": False,
            "error": "没有可评价的快照。先跑 action=snapshot 渲一张，或用 snapshot_dir 指定目录。",
        }

    images = [str(snap_dir / n) for n in ("clay.png", "seg.png") if (snap_dir / n).exists()]
    if not images:
        return {"success": False, "error": f"{snap_dir} 里没有 clay.png / seg.png"}

    meta = read_json(snap_dir / "meta.json", {})
    geometry = scene_ops.find_issues(scene, canvas_aspect(scene))
    known = "；".join(i["message"] for i in geometry) or "无"

    question = params.get("question") or "这个构图有什么问题？"
    prompt = (
        "你在看一个三维白膜场景的两张渲染图：第一张是白模（只有体积和位置，不表示材质），"
        "第二张是同一机位的语义分割图。它们将作为图生图的构图参考。\n"
        f"分割图配色对应：{meta.get('legend') or '（无图例）'}\n"
        f"几何自检已经查出的问题（不必重复指出）：{known}\n"
        f"人的问题：{question}\n"
        "请只评价眼睛才能判断的事：构图是否成立、主体是否突出、留白与平衡、"
        "遮挡关系读不读得懂、机位高度与透视是否服务于这个画面。\n"
        f"只输出 JSON，格式：{CRITIQUE_SCHEMA}"
    )

    r = subprocess.run(
        [*frago_argv(), "recipe", "run", "openrouter_vision_classify", "--params",
         json.dumps({
             "prompt": prompt,
             "image_input": images,
             "response_format": "json",
             "model": params.get("model") or "google/gemini-2.5-flash",
             "max_tokens": 1200,
             "reasoning_enabled": False,
         }, ensure_ascii=False)],
        capture_output=True, text=True, timeout=180,
    )
    if r.returncode != 0:
        return {
            "success": False,
            "error": f"视觉模型调用失败：{(r.stderr or r.stdout).strip()[:300]}",
            "snapshot_dir": str(snap_dir),
        }

    payload = extract_child_json(r.stdout)
    verdict_obj = (payload or {}).get("parsed_json")
    if not isinstance(verdict_obj, dict):
        return {
            "success": False,
            "error": "视觉模型没回可解析的 JSON，拿不到结构化判断",
            "raw_text": (payload or {}).get("raw_text", "")[:500],
            "snapshot_dir": str(snap_dir),
        }

    issues = verdict_obj.get("issues") or []
    suggestions = verdict_obj.get("suggestions") or []
    lines = [f"判断：{verdict_obj.get('verdict', '?')} —— {verdict_obj.get('summary', '')}"]
    if issues:
        lines.append("看出来的问题：")
        lines += [f"  · [{i.get('severity', '?')}] {i.get('what', '')}（{i.get('where', '')}）" for i in issues]
    if suggestions:
        lines.append("建议：")
        lines += [f"  · {s.get('action', '')}——{s.get('why', '')}" for s in suggestions]
    if geometry:
        lines.append("几何自检另外查出：")
        lines += [f"  · {i['message']}" for i in geometry]

    return {
        "success": True,
        "text": "\n".join(lines),
        "verdict": verdict_obj.get("verdict"),
        "summary": verdict_obj.get("summary"),
        "issues": issues,
        "suggestions": suggestions,
        "geometry_issues": geometry,
        "snapshot_dir": str(snap_dir),
        "model": (payload or {}).get("model"),
    }


def extract_child_json(stdout: str) -> dict | None:
    """从子配方的 stdout 里挖出那份 JSON。

    runner 会在前面加一行 `[recipe] ... | OK | 1.2s` 之类的执行记录，
    直接 json.loads 整个 stdout 会炸在第一个字符上。
    """
    text = (stdout or "").strip()
    start = text.find("{")
    if start < 0:
        return None
    try:
        return json.loads(text[start:])
    except json.JSONDecodeError:
        return None


# --- agent 接口：项目 ----------------------------------------------------


def describe_projects(reg: dict) -> str:
    lines = [f"共 {len(reg['projects'])} 个项目，当前是「{project_name(reg, reg['active'])}」："]
    for p in reg["projects"]:
        mark = "▸" if p["slug"] == reg["active"] else " "
        lines.append(f"  {mark} {p['name']}（{p['slug']}）· {p.get('object_count', 0)} 个物体")
    return "\n".join(lines)


def project_name(reg: dict, slug: str) -> str:
    return next((p["name"] for p in reg["projects"] if p["slug"] == slug), slug)


def do_project_list(reg: dict) -> dict:
    return {
        "success": True,
        "text": describe_projects(reg),
        "active": reg["active"],
        "projects": reg["projects"],
        "projects_rev": reg.get("rev", 0),
    }


def do_project_create(params: dict, data_root: Path, reg: dict) -> dict:
    name = str(params.get("name") or "").strip()
    if not name:
        return {"success": False, "error": "project_create 需要 name——项目得有个人能叫得出的名字"}

    taken = {p["slug"] for p in reg["projects"]}
    slug = slugify(name, taken)
    pdir = project_dir(data_root, slug)
    ensure_project(pdir)

    reg["projects"].append(new_project_entry(slug, name))
    reg["active"] = slug          # 新建即切过去：人建它就是要用它
    save_registry(data_root, reg)
    sync_project(data_root, reg, slug, pdir)

    return {
        "success": True,
        "text": f"已建项目「{name}」（{slug}）并切过去，空场景",
        "slug": slug,
        "name": name,
        "active": slug,
        "projects_rev": reg.get("rev", 0),
    }


def do_project_switch(params: dict, data_root: Path, reg: dict) -> dict:
    slug = params.get("slug")
    known = [p["slug"] for p in reg["projects"]]
    if slug not in known:
        return {"success": False, "error": f"项目 {slug!r} 不存在。现有：{', '.join(known)}"}
    if reg["active"] == slug:
        return {
            "success": True,
            "text": f"当前已经是「{project_name(reg, slug)}」了",
            "active": slug,
        }

    reg["active"] = slug
    save_registry(data_root, reg)
    pdir = project_dir(data_root, slug)
    ensure_project(pdir)
    sync_project(data_root, reg, slug, pdir)

    return {
        "success": True,
        "text": f"已切到「{project_name(reg, slug)}」（{slug}）",
        "active": slug,
        "projects_rev": reg.get("rev", 0),
    }


def do_project_rename(params: dict, data_root: Path, reg: dict) -> dict:
    slug = params.get("slug") or reg["active"]
    name = str(params.get("name") or "").strip()
    if not name:
        return {"success": False, "error": "project_rename 需要 name"}

    entry = next((p for p in reg["projects"] if p["slug"] == slug), None)
    if not entry:
        known = ", ".join(p["slug"] for p in reg["projects"])
        return {"success": False, "error": f"项目 {slug!r} 不存在。现有：{known}"}

    old_name = entry["name"]
    entry["name"] = name
    entry["updated_at"] = datetime.now().isoformat(timespec="seconds")
    save_registry(data_root, reg)

    # slug 不动。它是磁盘目录名，改了等于把所有已发布的图片地址一起改掉。
    return {
        "success": True,
        "text": f"「{old_name}」改名为「{name}」（目录名 {slug} 不动）",
        "slug": slug,
        "name": name,
        "projects_rev": reg.get("rev", 0),
    }


def do_project_delete(params: dict, data_root: Path, reg: dict) -> dict:
    slug = params.get("slug")
    known = [p["slug"] for p in reg["projects"]]
    if slug not in known:
        return {"success": False, "error": f"项目 {slug!r} 不存在。现有：{', '.join(known)}"}
    if len(reg["projects"]) <= 1:
        return {
            "success": False,
            "error": (
                f"「{project_name(reg, slug)}」是最后一个项目，删了这个页面就没有可显示的场景了。"
                "先建一个新项目再删它。"
            ),
        }

    name = project_name(reg, slug)
    reg["projects"] = [p for p in reg["projects"] if p["slug"] != slug]
    if reg["active"] == slug:
        reg["active"] = reg["projects"][0]["slug"]
    save_registry(data_root, reg)

    # 目录挪进 .trash/ 而不是删掉：出图是花过钱的，误删一个项目不该不可挽回。
    pdir = project_dir(data_root, slug)
    trashed = None
    if pdir.exists():
        trash = data_root / ".trash"
        trash.mkdir(exist_ok=True)
        dest = trash / f"{slug}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        pdir.rename(dest)
        trashed = str(dest)

    active_dir = project_dir(data_root, reg["active"])
    ensure_project(active_dir)
    sync_project(data_root, reg, reg["active"], active_dir)

    return {
        "success": True,
        "text": (
            f"已删除项目「{name}」，当前切到「{project_name(reg, reg['active'])}」。"
            + (f"产物移到 {trashed}，没有物理删除。" if trashed else "")
        ),
        "deleted": slug,
        "active": reg["active"],
        "trashed_to": trashed,
        "projects_rev": reg.get("rev", 0),
    }


# --- UI 指挥 agent -------------------------------------------------------

# 自然语言能触发的动作，白名单。
#
# 刻意不含 generate：一句「摆个街角然后出图」会直接花掉主人的钱，
# 而人说这句话时未必意识到自己在下单。出图必须是他自己按那个按钮。
# 也不含 project_* 与 scene_put：结构性/整份覆盖的动作不该由一句话触发。
INSTRUCT_ACTIONS = (
    "object_add", "object_update", "object_delete", "scene_clear",
    "place", "move", "camera_set", "camera_frame", "measure", "validate",
)

INSTRUCT_MAX_STEPS = 12


def instruct_context(reg: dict, slug: str, scene: dict) -> str:
    """喂给模型的现场情况。给它 id、语义、名字、尺寸和相机——它要按这些说话。"""
    objects = scene.get("objects") or []
    lines = [f'当前项目：「{project_name(reg, slug)}」，{len(objects)} 个物体。']
    if objects:
        lines.append("场景里现有的物体（这两列任选一个都能用来引用它）：")
        lines.append("  id | 名字 | 语义·形状 | 位置 | 尺寸米(宽高深)")
        for o in objects:
            dims = [round(v, 2) for v in scene_ops.scale_to_dims(o["shape"], o["scale"])]
            lines.append(
                f'  {o["id"]} | {o.get("label") or "（无名）"} | '
                f'{o["semantic"]}·{o["shape"]} | '
                f'{[round(v, 2) for v in o["position"]]} | {dims}'
            )
    else:
        lines.append("场景是空的。")

    cam = scene.get("camera") or {}
    lines.append(
        f'相机：位置 {[round(v, 2) for v in cam.get("position", [])]}，'
        f'看向 {[round(v, 2) for v in cam.get("target", [])]}，FOV {cam.get("fov")}°'
    )
    lines.append(f'画幅：{(scene.get("canvas") or {}).get("aspect")}')
    lines.append("可用语义：" + "、".join(f'{s["key"]}({s["label"]})' for s in SEMANTICS))
    lines.append("可用形状：" + "、".join(f'{s["key"]}({s["label"]})' for s in SHAPES))
    return "\n".join(lines)


INSTRUCT_CONTRACT = """先分清这句话是**改已有的东西**还是**放新的东西**，两者用的动作完全不同：

【改已有的】
- move {id, direction, distance}
    把已有物体挪一段距离。「往左挪半米」「往前一点」用它。
    distance 是这个物体自己挪了多远。
- object_update {id, dims?|rotation?|label?|semantic?|position?}
    改尺寸（dims 是真实米数 [宽,高,深]）、转角、名字、语义。
    「放大一倍」「加高到两米」「改名叫 X」用它。
- object_delete {id}
- scene_clear {}

【放新的】
- place {semantic, label?, relative_to, direction, distance, align?}
    挨着某个已有物体放一个**新**物体。distance 是两者表面之间的净空米数。
    align 只有两个值：ground（贴地，默认）或 center（与参照物中心等高）。
- object_add {semantic, label?, dims?, position?, rotation?}
    直接放一个新物体，不参照别人。

  两者的 shape 都可以不写，按语义自动取（人=胶囊、车=方块、树=圆锥、家具=方块……）；
  要特别指定才写 shape。

【相机】
- camera_set {preset}  preset ∈ eye_level(人眼1.6m) / low(0.4m) / high(3m) / top_down(俯瞰)
    可加 target_id 让相机对着某个物体。
- camera_frame {targets?, margin?}
    退到刚好装下。**「框住所有东西」就不要写 targets**，留空即是全部主体。
    只框某几个才写 targets，而且 NEVER 把地面、水面这类铺开的面写进去——
    它们动辄几十米，会把相机推得很远。

【只看不改】
- measure {a, b}   量两个物体的距离与方位
- validate {}      体检：穿模 / 悬空 / 出画

【position 的含义 —— 最容易搞错的一条】
position 是物体的**底面中心贴地点**，不是几何中心。
所以放在地上的东西，**y 一律给 0**，不管它多高。
  ✓ 一个 8 米高的图书馆放在地上：position 的 y = 0
  ✗ 写成 4（半高）会让整栋楼悬在 4 米高的空中
只有真要让它浮空（吊灯、飞鸟）才给非零 y，而且要在 summary 里说明「我让它浮空了」。
拿不准就不要写 position——不写的话工具自己会把它贴在地上。

引用物体时，**id 和名字都可以**：写 "obj_3" 或写 "撑伞的人" 都指得着。
你在同一批动作里刚放下的东西，用你给它起的 label 去指它就行。

direction 一律是 front(更靠近相机) / back / left / right / above / below，
**是相机看到的方向**，不是世界坐标轴。"""


def parse_instruct_plan(payload: dict) -> tuple:
    """从模型返回里挖出动作数组。它可能给数组，也可能包一层。"""
    if not isinstance(payload, dict):
        return None, "模型没回 JSON"
    for key in ("plan", "actions", "steps"):
        if isinstance(payload.get(key), list):
            return payload[key], None
    if isinstance(payload.get("result"), list):
        return payload["result"], None
    return None, "模型回的 JSON 里没有 plan 数组"


def validate_plan(plan: list, scene: dict) -> tuple:
    """执行前先把整批过一遍。

    过不了就整批拒绝：做一半的结果最难收拾——人看着场景变了一部分，
    既不知道哪几条生效了，也不敢直接重来一遍。

    校验时要跟着推演**引用**：第 2 条用第 1 条刚放下的东西是正常写法，
    而调用方那时还不知道服务端会分配哪个 id，只能用自己起的名字去指它。
    所以这里跟踪的是「能指得着的引用」——id 和名字都算。
    """
    if not isinstance(plan, list) or not plan:
        return None, ["模型没给出任何动作"]
    if len(plan) > INSTRUCT_MAX_STEPS:
        return None, [f"一次最多 {INSTRUCT_MAX_STEPS} 个动作，模型给了 {len(plan)} 个"]

    objects = scene.get("objects") or []
    live = {o["id"] for o in objects} | {o["label"] for o in objects if o.get("label")}
    counter = 0
    for o in objects:
        oid = str(o.get("id") or "")
        if oid.startswith("obj_") and oid[4:].isdigit():
            counter = max(counter, int(oid[4:]))

    errors = []
    cleaned = []
    for i, step in enumerate(plan, 1):
        if not isinstance(step, dict):
            errors.append(f"第 {i} 条不是对象")
            continue
        action = step.get("action")
        if action not in INSTRUCT_ACTIONS:
            errors.append(
                f"第 {i} 条的动作 {action!r} 用不了。能用的：{', '.join(INSTRUCT_ACTIONS)}"
            )
            continue

        args = {k: v for k, v in step.items() if k != "action"}

        def need_ref(value, field):
            """引用只要指得着就行，id 或名字都算。"""
            if value in live:
                return
            errors.append(
                f"第 {i} 条的 {field} 指向 {value!r}，场景里没有这个物体。"
                f"能指的：{'、'.join(sorted(live)) or '（场景是空的）'}"
            )

        if action in ("object_add", "place"):
            if args.get("semantic") not in SEMANTIC_KEYS:
                errors.append(f"第 {i} 条的语义 {args.get('semantic')!r} 不认识")
            # shape 允许省略，服务端按语义取默认形状
            if args.get("shape") is not None and args.get("shape") not in SHAPE_KEYS:
                errors.append(f"第 {i} 条的形状 {args.get('shape')!r} 不认识")

        if action == "place":
            need_ref(args.get("relative_to"), "relative_to")

        if action in ("place", "move"):
            if args.get("direction") not in ("front", "back", "left", "right", "above", "below"):
                errors.append(f"第 {i} 条的方向 {args.get('direction')!r} 不认识")
            try:
                if float(args.get("distance", 1)) < 0:
                    errors.append(f"第 {i} 条的距离是负数")
            except (TypeError, ValueError):
                errors.append(f"第 {i} 条的距离不是数字")

        if action in ("object_update", "object_delete", "move"):
            need_ref(args.get("id"), "id")

        if action == "camera_set":
            preset = args.get("preset")
            if preset and preset not in [p["key"] for p in CAMERA_PRESETS]:
                errors.append(f"第 {i} 条的机位预设 {preset!r} 不认识")
            if not preset and not any(args.get(k) is not None for k in ("position", "target", "fov")):
                errors.append(f"第 {i} 条的 camera_set 既没给 preset 也没给位姿")
            if args.get("target_id"):
                need_ref(args["target_id"], "target_id")

        if action == "camera_frame":
            for t in (args.get("targets") or []):
                need_ref(t, "targets")

        if action == "measure":
            for k in ("a", "b"):
                need_ref(args.get(k), k)

        # 推演这一条对后面的影响，好让下一条引用得上刚放下的东西
        if action in ("object_add", "place"):
            counter += 1
            live.add(f"obj_{counter}")
            if args.get("label"):
                live.add(str(args["label"]))
        elif action == "object_delete":
            live.discard(args.get("id"))
        elif action == "object_update" and args.get("label"):
            live.add(str(args["label"]))
        elif action == "scene_clear":
            live.clear()

        cleaned.append({"action": action, "args": args})

    return (None, errors) if errors else (cleaned, [])


def run_plan_step(step: dict, data_root: Path, reg: dict, slug: str, pdir: Path) -> dict:
    """按现有 dispatcher 的那套语义跑一条。**不另发明一套执行路径**——
    另写一套的话，命令行验过的东西在 UI 上未必成立，两边会慢慢长歪。"""
    action, args = step["action"], step["args"]
    scene = read_json(pdir / "scene.json", EMPTY_SCENE)

    if action == "object_add":
        return do_object_add(args, pdir, scene)
    if action == "object_update":
        return do_object_update(args, pdir, scene)
    if action == "object_delete":
        return do_object_delete(args, pdir, scene)
    if action == "scene_clear":
        return do_scene_clear(pdir, scene)
    if action == "place":
        return do_place(args, pdir, scene)
    if action == "move":
        return do_move(args, pdir, scene)
    if action == "camera_set":
        return do_camera_set(args, pdir, scene)
    if action == "camera_frame":
        return do_camera_frame(args, pdir, scene)
    if action == "measure":
        return do_measure(args, scene)
    if action == "validate":
        return do_validate(scene)
    return {"success": False, "error": f"执行器不认识 {action!r}"}


def planned_height(args: dict, action: str, objects: list) -> float | None:
    """这一步要放/要改的那个物体有多高，单位米。算不出来就返回 None。"""
    if args.get("dims") and isinstance(args["dims"], (list, tuple)) and len(args["dims"]) == 3:
        try:
            return float(args["dims"][1])
        except (TypeError, ValueError):
            return None

    if action == "object_update":
        current = next((o for o in objects if o.get("id") == args.get("id")
                        or (o.get("label") and o["label"] == args.get("id"))), None)
        if not current:
            return None
        if args.get("scale"):
            return scene_ops.scale_to_dims(current["shape"], args["scale"])[1]
        return scene_ops.scale_to_dims(current["shape"], current["scale"])[1]

    semantic = args.get("semantic")
    shape = args.get("shape") or SEMANTIC_SHAPE.get(semantic)
    if args.get("scale") and shape:
        try:
            return scene_ops.scale_to_dims(shape, args["scale"])[1]
        except (TypeError, ValueError, IndexError):
            return None
    if shape and semantic:
        return default_dims(shape, semantic)[1]
    return None


def ground_correct_plan(plan: list, scene: dict) -> tuple:
    """把「按中心点摆」的写法就地纠正成贴地。

    实测过一整轮：五个物体里四个的 y 恰好等于自身高度的一半，
    图书馆因此悬在 4 米高的空中，白模忠实地画了出来，出的四张图全废。
    这是「position 是几何中心」这个再自然不过的误解——多数三维工具确实是那样。

    提示词里已经写死了约定，但**不能因为写了就省掉这道兜底**：
    提示词是劝说，兜底是保证。而这个错的代价是整批出图作废，且人未必看得出来
    ——白模里一栋浮空的楼，乍看只像是构图有点怪。

    正负都要认：薄板给 -h/2 是同一个误解（把中心对到了地面）。
    """
    objects = scene.get("objects") or []
    notes = []
    for step in plan:
        if step["action"] not in ("object_add", "object_update"):
            continue
        args = step["args"]
        pos = args.get("position")
        if not isinstance(pos, (list, tuple)) or len(pos) != 3:
            continue
        try:
            y = float(pos[1])
        except (TypeError, ValueError):
            continue
        if abs(y) < 1e-9:
            continue

        height = planned_height(args, step["action"], objects)
        if not height or height <= 0:
            continue

        # 容差取「半高的 1%」，再给一个绝对下限，免得薄板永远匹配不上
        if abs(abs(y) - height / 2) <= max(1e-4, height * 0.01):
            args["position"] = [pos[0], 0.0, pos[2]]
            name = args.get("label") or args.get("id") or args.get("semantic") or "这个物体"
            notes.append(
                f"「{name}」原本给的 y={y:g} 正好是它自身高度（{height:g} 米）的一半，"
                f"那是按几何中心摆的写法；已把它落回地面"
            )
    return plan, notes


def context_image(data_root: Path, pdir: Path, scene: dict) -> tuple:
    """给模型看的那张当前画面。先现渲一张预览，不行就退回最近一次快照。

    返回 (路径, 说不出来时的人话理由)。两条路都断了才认输——
    指挥台是这个页面最常用的入口之一，不该因为渲染抖一下就整个不能用。
    """
    try:
        preview = do_preview({"view": "preview"}, data_root, pdir, scene)
        if preview.get("success") and Path(preview["path"]).exists():
            return preview["path"], None
        why = preview.get("error") or "预览渲染没出图"
    except Exception as e:      # noqa: BLE001 —— 渲染栈里什么都可能抛，这里只负责兜住
        why = f"预览渲染出错：{e}"

    snap = latest_snapshot(pdir)
    if snap:
        for name in ("clay.png", "preview.png", "seg.png"):
            f = snap / name
            if f.exists():
                return str(f), None

    return None, f"{why}，也没有可用的历史快照"


def do_instruct(params: dict, data_root: Path, reg: dict, slug: str, pdir: Path, scene: dict) -> dict:
    """把一句人话翻成一串本配方的动作，校验通过后按顺序执行。

    要点是**不发明新 DSL**：让模型直接吐本配方已有的 action 调用，
    这样命令行验过的每一条契约在 UI 上原样成立，出错信息也是同一套人话。
    """
    text = str(params.get("text") or "").strip()
    if not text:
        return {"success": False, "error": "instruct 需要 text——告诉我要摆什么"}

    # 顺手渲一张预览当视觉上下文。走的是 critique 那条通道（它要图），
    # 而模型多看一眼当前画面，「再往左挪一点」这类话才有参照。
    image, why = context_image(data_root, pdir, scene)
    if not image:
        # 没图就别硬调：子配方会抛一句「Missing required parameter: image_input」，
        # 那是个用户从没听说过的配方的内部细节，解释不了任何事。
        return {
            "success": True,
            "applied": False,
            "text": f"看不到当前画面，这一轮没敢动场景：{why}",
            "reason": why,
            "instruction": text,
            "scene_version": scene.get("version", 0),
        }

    prompt = (
        "你在指挥一个三维白膜场景编辑器。用户说了一句话，你要把它翻成一串动作调用。\n\n"
        f"{instruct_context(reg, slug, scene)}\n\n"
        f"{INSTRUCT_CONTRACT}\n\n"
        f"用户说：{text}\n\n"
        "只输出 JSON，格式：\n"
        '{"plan": [{"action": "...", "参数名": 值}], "summary": "一句话说明你打算做什么", '
        '"refused": null}\n'
        "做不到的部分（比如改天空颜色、改材质、加光影——这个编辑器只管体块位置和机位）"
        "就把 plan 留空，refused 里用人话写清楚为什么做不到、以及这里能做什么。"
        "NEVER 为了凑数去改场景里别的东西。"
    )

    child = {
        "prompt": prompt,
        "image_input": [image] if image else [],
        "response_format": "json",
        "model": params.get("model") or "google/gemini-2.5-flash",
        "max_tokens": 1500,
        "reasoning_enabled": False,
    }
    if not image:
        child.pop("image_input")

    r = subprocess.run(
        [*frago_argv(), "recipe", "run", "openrouter_vision_classify",
         "--params", json.dumps(child, ensure_ascii=False)],
        capture_output=True, text=True, timeout=180,
    )
    if r.returncode != 0:
        return {
            "success": False,
            "error": f"模型调用失败：{(r.stderr or r.stdout).strip()[:300]}",
            "instruction": text,
        }

    payload = extract_child_json(r.stdout) or {}
    verdict = payload.get("parsed_json")
    raw_text = payload.get("raw_text", "")
    if not isinstance(verdict, dict):
        return {
            "success": False,
            "error": "模型没回可解析的 JSON，这一轮什么都没做",
            "model_said": raw_text[:600],
            "instruction": text,
        }

    refused = verdict.get("refused")
    plan_raw, perr = parse_instruct_plan(verdict)

    if refused or not plan_raw:
        reason = refused or perr or "模型没给出可执行的动作"
        log_instruct(pdir, text, [], [], reason, raw_text)
        # 返回 success=True 是刻意的：配方跑通了，只是这件事做不到。
        # 报 False 的话服务端只会回一句 {"detail": "..."}，模型原话、被拒理由
        # 全部丢掉，页面就只能显示「失败了」——那正是说明书里禁止的那种反馈。
        return {
            "success": True,
            "applied": False,
            "text": f"这件事做不到：{reason}",
            "refused": True,
            "reason": reason,
            "model_said": verdict.get("summary") or raw_text[:600],
            "instruction": text,
            "scene_version": scene.get("version", 0),
        }

    plan, errors = validate_plan(plan_raw, scene)
    if errors:
        log_instruct(pdir, text, plan_raw, [], "；".join(errors), raw_text)
        return {
            "success": True,
            "applied": False,
            "text": "模型给的动作没通过校验，整批都没执行：" + "；".join(errors[:6]),
            "reason": "；".join(errors[:6]),
            "issues": errors,
            "plan": plan_raw,
            "model_said": verdict.get("summary") or "",
            "instruction": text,
            "scene_version": scene.get("version", 0),
        }

    plan, ground_notes = ground_correct_plan(plan, scene)

    # 执行前把整份场景留一手。任何一条炸了就整份回滚——
    # 「NEVER 执行一半」不能只靠预检说了算，预检覆盖不到的情况总会有。
    rollback = read_json(pdir / "scene.json", EMPTY_SCENE)

    results, failed = [], None
    for step in plan:
        res = run_plan_step(step, data_root, reg, slug, pdir)
        results.append({
            "action": step["action"],
            "args": step["args"],
            "success": bool(res.get("success")),
            "text": res.get("text") or res.get("error"),
        })
        if not res.get("success"):
            failed = res.get("error")
            break

    if failed:
        write_json_atomic(pdir / "scene.json", rollback)
        log_instruct(pdir, text, plan, results, f"执行中失败并已回滚：{failed}", raw_text)
        return {
            "success": True,
            "applied": False,
            "text": f"执行到第 {len(results)} 条时失败，场景已整份回滚：{failed}",
            "reason": failed,
            "plan": plan,
            "results": results,
            "instruction": text,
            "scene_version": rollback.get("version", 0),
        }

    fresh = read_json(pdir / "scene.json", EMPTY_SCENE)
    summary = verdict.get("summary") or "已按你说的调整了场景"
    if ground_notes:
        # 纠正过什么必须说出来。人得知道最终落地的跟他/模型说的那一版有出入。
        summary += "（" + "；".join(ground_notes) + "）"
    log_instruct(pdir, text, plan, results, None, raw_text)

    return {
        "success": True,
        "applied": True,
        "text": summary + "\n" + "\n".join(f"  · {r['text']}" for r in results),
        "summary": summary,
        "ground_corrections": ground_notes,
        "plan": plan,
        "results": results,
        "instruction": text,
        "scene_version": fresh.get("version", 0),
        "object_count": len(fresh.get("objects") or []),
    }


def log_instruct(pdir: Path, text: str, plan, results, error, raw: str) -> None:
    """一轮一行。人回头看得见自己说了什么、agent 做了哪几条、结果如何。"""
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "instruction": text,
        "plan": plan,
        "results": results,
        "error": error,
    }
    if error:
        entry["model_said"] = (raw or "")[:600]
    with (pdir / "agent_log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# --- 草稿：人正在写的东西也是项目的一部分 -------------------------------

DRAFT_FIELDS = ("prompt", "presets", "legend_text", "legend_edited", "size", "count")


def do_draft_get(pdir: Path) -> dict:
    draft = read_json(pdir / "draft.json", {})
    return {"success": True, "draft": draft, "text": "草稿已读取"}


def do_draft_put(params: dict, pdir: Path) -> dict:
    """页面把人写到一半的东西存进这个项目。

    提示词框原来不属于任何项目——它只是页面上一个临时输入框。
    于是切项目时上一个项目的文字留在那儿，图例元信息写着 A 的场景版本、
    提示词却是 B 的内容，两边来自两个项目，人看到的是一份自相矛盾的界面。
    把它当成项目的一部分存起来，切换时整套换过去，这类串台才断得干净。
    """
    incoming = params.get("draft")
    if not isinstance(incoming, dict):
        return {"success": False, "error": "draft_put 需要一个 draft 对象"}

    draft = {k: incoming[k] for k in DRAFT_FIELDS if k in incoming}
    draft["updated_at"] = datetime.now().isoformat(timespec="seconds")
    write_json_atomic(pdir / "draft.json", draft)
    return {"success": True, "draft": draft, "text": "草稿已保存"}


# --- 出图前体检 ---------------------------------------------------------

# 一段能用的提示词至少要说到材质、光线、氛围里的一两样。只写一个题目
# （「海边的卡夫卡」）模型只能自由发挥，而人恰恰是冲着"构图可控"来的。
PROMPT_HINT_WORDS = {
    "材质": ("材质", "质感", "皮肤", "布料", "金属", "木", "石", "混凝土", "玻璃",
             "砖", "锈", "潮湿", "湿", "干燥", "粗糙", "光滑", "斑驳"),
    "光线": ("光", "逆光", "顶光", "侧光", "阴影", "高光", "霓虹", "烛", "日出",
             "日落", "阳光", "月光", "灯"),
    "氛围": ("氛围", "安静", "喧闹", "孤独", "温暖", "冷", "压抑", "空旷", "雾",
             "雨", "雪", "阴天", "晴", "黄昏", "清晨", "夜", "正午"),
    "风格": ("写实", "摄影", "电影感", "漫画", "水彩", "油画", "版画", "三渲二",
             "插画", "胶片", "mm", "镜头", "景深"),
}

MIN_PROMPT_CHARS = 16


def check_prompt(prompt: str, scene: dict) -> list:
    """看这段提示词够不够撑起一张图。返回若干条人话。

    这不是打分，是把「它少了什么」说出来。人有权照样生成——
    超现实、极简的画面本来就不需要说满，替他决定不是工具该干的事。
    """
    text = (prompt or "").strip()
    issues = []

    if not text:
        return [{
            "kind": "prompt_empty",
            "message": "提示词是空的。白模只管构图，材质、光线、氛围得靠它。",
        }]

    if len(text) < MIN_PROMPT_CHARS:
        issues.append({
            "kind": "prompt_short",
            "message": (
                f"提示词只有 {len(text)} 个字，基本只是个题目。"
                "白模已经把构图定死了，剩下的材质、光线、氛围全靠这段话——"
                "写得太短，模型只能自由发挥。"
            ),
        })

    missing = [k for k, words in PROMPT_HINT_WORDS.items()
               if not any(w in text for w in words)]
    if len(missing) >= 3:
        issues.append({
            "kind": "prompt_thin",
            "message": f"没提到{('、'.join(missing))}。下面的预设标签点几个就能补上。",
        })

    labels = [o["label"] for o in (scene.get("objects") or []) if o.get("label")]
    if labels and not any(lb in text for lb in labels):
        issues.append({
            "kind": "prompt_no_echo",
            "message": (
                f"场景里有 {'、'.join(f'「{lb}」' for lb in labels[:4])}"
                f"{'等' if len(labels) > 4 else ''}，提示词里一个都没提到。"
                "点一下「扩写」可以把它们写进去。"
            ),
        })

    return issues


def do_preflight(params: dict, pdir: Path, scene: dict) -> dict:
    """按「生成」之前先查一遍，把问题摆出来让人自己决定。

    缺的这一环代价很实在：委托方那次，场景整个浮空、提示词只有一个书名，
    工具全程一声不吭，四张图的钱花完才发现。这两件事**工具本来都查得出来**。

    但一条都不强制拦：浮空在超现实场景里可能正是他要的，
    提示词简陋也可能是故意的。工具的位置是"说出来"，不是"替他决定"。
    """
    geometry = scene_ops.find_issues(scene, canvas_aspect(scene))
    prompt_issues = check_prompt(params.get("prompt", ""), scene)

    lines = []
    if geometry:
        lines.append(f"几何上有 {len(geometry)} 处：")
        lines += [f"  · {i['message']}" for i in geometry]
    if prompt_issues:
        lines.append("提示词：")
        lines += [f"  · {i['message']}" for i in prompt_issues]

    ok = not geometry and not prompt_issues
    return {
        "success": True,
        "ok": ok,
        "text": "出图前体检通过，可以生成" if ok else "\n".join(lines),
        "geometry": geometry,
        "prompt_issues": prompt_issues,
        "counts": {"geometry": len(geometry), "prompt": len(prompt_issues)},
    }


# --- 帮人写提示词 --------------------------------------------------------

# 「提示词我没有心情写」不是懒——场景里已经有物体名、机位、画幅、语义，
# 够拼出一段像样的描述了，是工具没接这一棒。
# 预设是**拼进去**不是替换掉：人写的那部分一个字都不能动。
PROMPT_PRESETS = [
    {"group": "风格", "items": [
        {"label": "写实摄影", "text": "写实摄影质感，35mm 镜头，浅景深"},
        {"label": "电影感", "text": "电影感画面，宽银幕调色，颗粒质感"},
        {"label": "日式漫画", "text": "日式漫画风格，清晰线条，网点阴影"},
        {"label": "水彩", "text": "水彩手绘，湿画法晕染，纸纹可见"},
        {"label": "三渲二", "text": "三渲二风格，干净的色块与描边"},
        {"label": "版画", "text": "版画质感，高对比黑白，刀刻纹理"},
        {"label": "油画", "text": "油画质感，厚涂笔触，颜料堆叠"},
    ]},
    {"group": "时间", "items": [
        {"label": "清晨", "text": "清晨，空气清冷通透"},
        {"label": "正午", "text": "正午，光线强烈，影子短而硬"},
        {"label": "黄昏", "text": "黄昏，暖金色的斜光"},
        {"label": "夜", "text": "夜晚，暗部占大面积"},
    ]},
    {"group": "天气", "items": [
        {"label": "晴", "text": "晴朗，天空干净"},
        {"label": "阴", "text": "阴天，光线平均柔和"},
        {"label": "雨", "text": "下雨，地面湿漉漉地反光"},
        {"label": "雾", "text": "有雾，远处的东西被雾气吃掉一层"},
        {"label": "雪", "text": "下雪，物体边缘积着薄雪"},
    ]},
    {"group": "光线", "items": [
        {"label": "自然光", "text": "自然光"},
        {"label": "逆光", "text": "逆光，主体边缘有一圈光"},
        {"label": "顶光", "text": "顶光，眼窝与下方形成阴影"},
        {"label": "霓虹", "text": "霓虹灯光，冷暖色在湿面上交错"},
        {"label": "烛光", "text": "烛光，暖黄的小范围光源"},
    ]},
]


def do_expand_prompt(params: dict, data_root: Path, reg: dict, slug: str,
                     pdir: Path, scene: dict) -> dict:
    """把一个题目扩写成一段完整的画面描述草稿。

    交给模型的不只是那个题目，还有场景里的物体名、机位、画幅——
    扩写出来的东西才会跟他摆的这个世界对得上，而不是另起一个画面。
    出来的是**草稿**，明说可以改：替人做决定和帮人起头是两回事。
    """
    seed = str(params.get("text") or "").strip()
    if not seed:
        return {"success": False, "error": "扩写需要一个起头——哪怕只是个题目"}

    image, why = context_image(data_root, pdir, scene)
    cam = scene.get("camera") or {}
    labels = [o["label"] for o in (scene.get("objects") or []) if o.get("label")]

    prompt = (
        "你在帮人把一个简短的题目扩写成图生图用的画面描述。\\n\\n"
        f"他写的题目：{seed}\\n\\n"
        f"这个画面里已经摆好的东西：{'、'.join(labels) or '（还没起名字）'}\\n"
        f"相机在 {[round(v, 1) for v in cam.get('position', [])]}，"
        f"看向 {[round(v, 1) for v in cam.get('target', [])]}，"
        f"画幅 {(scene.get('canvas') or {}).get('aspect')}\\n"
        "（附图是这个场景当前的白模预览，构图已经定死了）\\n\\n"
        "请写一段 80-150 字的中文画面描述，要求：\\n"
        "- **只写材质、光线、天气、氛围、风格**这些白模表达不了的东西\\n"
        "- 把上面那些物体的名字自然地织进去\\n"
        "- NEVER 描述物体的位置、大小、朝向、遮挡关系——那些白模已经定死了，"
        "你再说一遍只会跟它打架\\n"
        "- 不要分点，写成连贯的一段话\\n\\n"
        '只输出 JSON：{"draft": "……"}'
    )

    child = {
        "prompt": prompt,
        "response_format": "json",
        "model": params.get("model") or "google/gemini-2.5-flash",
        "max_tokens": 800,
        "reasoning_enabled": False,
    }
    if image:
        child["image_input"] = [image]
    else:
        return {
            "success": True,
            "ok": False,
            "text": f"渲不出当前画面，扩写这一步暂时用不了：{why}",
            "reason": why,
        }

    r = subprocess.run(
        [*frago_argv(), "recipe", "run", "openrouter_vision_classify",
         "--params", json.dumps(child, ensure_ascii=False)],
        capture_output=True, text=True, timeout=180,
    )
    if r.returncode != 0:
        return {"success": False, "error": f"模型调用失败：{(r.stderr or r.stdout).strip()[:300]}"}

    payload = extract_child_json(r.stdout) or {}
    parsed = payload.get("parsed_json")
    draft = (parsed or {}).get("draft") if isinstance(parsed, dict) else None
    if not draft:
        return {
            "success": True,
            "ok": False,
            "text": "模型没回可用的草稿",
            "model_said": (payload.get("raw_text") or "")[:400],
        }

    return {
        "success": True,
        "ok": True,
        "text": draft,
        "draft": draft,
        "seed": seed,
        "note": "这是草稿，随便改——它只补材质光线氛围，构图仍然由白膜说了算",
    }


def main() -> None:
    if len(sys.argv) < 2:
        params = {}
    else:
        try:
            params = json.loads(sys.argv[1])
        except json.JSONDecodeError as e:
            print(json.dumps({"success": False, "error": f"参数解析失败: {e}"}, ensure_ascii=False))
            sys.exit(1)

    action = params.get("action") or "view"
    data_root = resolve_data_dir()

    try:
        reg = ensure_projects(data_root)
    except OSError as e:
        print(json.dumps({"success": False, "error": f"数据目录不可用 {data_root}：{e}"}, ensure_ascii=False))
        sys.exit(1)

    # 项目级动作只碰注册表，不需要先解出某个项目目录。
    if action in ("project_list", "project_create", "project_switch",
                  "project_rename", "project_delete"):
        handler = {
            "project_list": lambda: do_project_list(reg),
            "project_create": lambda: do_project_create(params, data_root, reg),
            "project_switch": lambda: do_project_switch(params, data_root, reg),
            "project_rename": lambda: do_project_rename(params, data_root, reg),
            "project_delete": lambda: do_project_delete(params, data_root, reg),
        }[action]
        result = handler()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result.get("success") else 1)

    slug, perr = resolve_project(params, reg)
    if perr:
        print(json.dumps({"success": False, "error": perr}, ensure_ascii=False, indent=2))
        sys.exit(1)

    pdir = project_dir(data_root, slug)
    try:
        scene = ensure_project(pdir)
    except OSError as e:
        print(json.dumps({"success": False, "error": f"项目目录不可用 {pdir}：{e}"}, ensure_ascii=False))
        sys.exit(1)

    if action == "view":
        try:
            result = do_view(params, data_root, reg, slug, pdir, scene)
        except (RuntimeError, subprocess.SubprocessError) as e:
            result = {"success": False, "error": str(e)}
    elif action == "scene_get":
        result = do_scene_get(scene)
    elif action == "scene_put":
        try:
            result = do_scene_put(params, pdir, scene)
        except OSError as e:
            result = {"success": False, "error": f"写 scene.json 失败：{e}"}
    elif action == "catalog":
        result = {"success": True, "catalog": catalog()}
    elif action == "snapshot":
        result = do_snapshot(params, data_root, pdir, scene)
    elif action == "preview":
        result = do_preview(params, data_root, pdir, scene)
    elif action == "legend":
        legend = build_legend(scene)
        result = {"success": True, "legend": legend, "text": legend or "场景是空的，没有图例"}
    elif action == "generate":
        result = do_generate(params, data_root, pdir, scene)
    elif action == "history":
        result = do_history(data_root, pdir, int(params.get("limit") or 20))
    elif action == "instruct":
        result = do_instruct(params, data_root, reg, slug, pdir, scene)
    elif action == "preflight":
        result = do_preflight(params, pdir, scene)
    elif action == "draft_get":
        result = do_draft_get(pdir)
    elif action == "draft_put":
        result = do_draft_put(params, pdir)
    elif action == "expand_prompt":
        result = do_expand_prompt(params, data_root, reg, slug, pdir, scene)
    elif action == "object_add":
        result = do_object_add(params, pdir, scene)
    elif action == "object_update":
        result = do_object_update(params, pdir, scene)
    elif action == "object_delete":
        result = do_object_delete(params, pdir, scene)
    elif action == "scene_clear":
        result = do_scene_clear(pdir, scene)
    elif action == "place":
        result = do_place(params, pdir, scene)
    elif action == "move":
        result = do_move(params, pdir, scene)
    elif action == "measure":
        result = do_measure(params, scene)
    elif action == "validate":
        result = do_validate(scene)
    elif action == "camera_set":
        result = do_camera_set(params, pdir, scene)
    elif action == "camera_frame":
        result = do_camera_frame(params, pdir, scene)
    elif action == "critique":
        result = do_critique(params, pdir, scene)
    else:
        result = {
            "success": False,
            "error": f"未知 action: {action}。当前可用：{', '.join(LIVE_ACTIONS)}",
        }

    # 派生真值统一在这里对齐：panel.json（右栏看的东西）和 state.json（页面轮询的锚点）。
    # 放一个地方做而不是散在各 action 里，是因为散着写迟早漏一个，
    # 表现是「别的都实时，唯独这个动作之后页面不动」——从现象猜不到漏了哪行。
    # draft_put 是页面在存自己写到一半的东西，不该推 panel_rev——
    # 推了页面就会为自己刚敲的字重拉一遍右栏，光标和滚动位置全乱。
    if result.get("success") and action != "draft_put":
        try:
            sync_project(data_root, reg, slug, pdir)
        except OSError as e:
            result.setdefault("warnings", []).append(f"同步页面真值失败：{e}")

    result.setdefault("project", slug)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
