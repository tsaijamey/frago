# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""把「切了项目又被拽回去」这个 bug 钉死。

委托方看到的现象是：切到别的项目，过一会儿自己弹回默认项目，切一次弹一次。
根因是任何动作跑完都会把 state.json 的 active 写成**它自己操作的那个项目**。
慢动作（instruct 五六秒、generate 四十秒）在路上时人切走了，
动作跑完把 active 盖回去，页面看到 active 变了就整页切回——
而人只会觉得「切换按钮坏了」，根本想不到是几秒前那个请求在作祟。

这里用确定性的方式重演那个时序：不起后台进程、不靠 sleep 抢时间，
直接模拟「动作 A 拿着旧注册表、期间 active 被改、A 最后才写盘」。
手工跑一遍能碰上也能碰不上，这种 bug 必须钉住。
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recipe as R  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  — ' + detail) if detail else ''}")
    if not ok:
        fails.append(name)


def read(root, name):
    return json.loads((root / name).read_text(encoding="utf-8"))


def make_project(root, slug, name, objects=0):
    pdir = R.project_dir(root, slug)
    R.ensure_project(pdir)
    scene = json.loads(json.dumps(R.EMPTY_SCENE))
    scene["version"] = 1
    scene["objects"] = [
        {"id": f"obj_{i+1}", "shape": "box", "semantic": "prop",
         "position": [i, 0, 0], "rotation": [0, 0, 0], "scale": [1, 1, 1]}
        for i in range(objects)
    ]
    R.write_json_atomic(pdir / "scene.json", scene)
    return pdir


def main():
    root = Path(tempfile.mkdtemp(prefix="wss-state-"))
    try:
        # 两个项目：X（慢动作打在它上面）和 Y（人中途切过去）
        reg = {"rev": 1, "active": "X", "projects": [
            R.new_project_entry("X", "项目 X"),
            R.new_project_entry("Y", "项目 Y"),
        ]}
        R.write_json_atomic(root / "projects.json", reg)
        px = make_project(root, "X", "项目 X", objects=2)
        py = make_project(root, "Y", "项目 Y", objects=5)

        print("=== 1. 慢动作打在 X 上，它启动时读到的 active 是 X ===")
        stale_reg = R.load_registry(root)          # 动作 A 手里那份，此刻 active=X
        check("动作启动时看到的 active 是 X", stale_reg["active"] == "X")

        R.sync_project(root, stale_reg, "X", px)   # 假设 A 中途也同步过一次
        check("此时 state.active = X", read(root, "state.json")["active"] == "X")
        panel_rev_x = read(root, "state.json")["panel_rev"]

        print("\n=== 2. 动作还在路上，人切到 Y ===")
        switched = R.do_project_switch({"slug": "Y"}, root, R.load_registry(root))
        check("切换本身成功", switched.get("success"), switched.get("text", ""))
        check("注册表 active = Y", R.load_registry(root)["active"] == "Y")
        check("state.active = Y", read(root, "state.json")["active"] == "Y")
        panel_rev_y = read(root, "state.json")["panel_rev"]
        scene_ver_y = read(root, "state.json")["scene_version"]

        print("\n=== 3. 慢动作现在才跑完，拿着那份旧注册表写盘 ===")
        # 这就是 bug 的时刻：A 手里的 reg 仍然写着 active=X
        R.sync_project(root, stale_reg, "X", px)
        state = read(root, "state.json")

        check("state.active 仍然是 Y（没被慢动作拽回 X）", state["active"] == "Y",
              f"实得 {state['active']!r}")
        check("非活动项目的动作没有动 scene_version",
              state["scene_version"] == scene_ver_y,
              f"切换后 {scene_ver_y} → 现在 {state['scene_version']}")
        check("非活动项目的动作没有动 panel_rev",
              state["panel_rev"] == panel_rev_y,
              f"切换后 {panel_rev_y} → 现在 {state['panel_rev']}")

        print("\n=== 4. 打在活动项目上的动作照常更新 ===")
        before = read(root, "state.json")["panel_rev"]
        R.sync_project(root, R.load_registry(root), "Y", py)
        after = read(root, "state.json")
        check("活动项目的 panel_rev 会涨", after["panel_rev"] > before,
              f"{before} → {after['panel_rev']}")
        check("active 还是 Y", after["active"] == "Y")

        print("\n=== 5. X 那边的 panel.json 照样被刷新了（只是不进 state）===")
        # 非活动项目的产物该更新还得更新，否则切回去看到的是旧的
        check("X 的 panel.json 存在且 rev 在涨",
              read(px, "panel.json")["rev"] >= 2,
              f"rev={read(px, 'panel.json')['rev']}")

        print()
        print("FAILED:", fails if fails else "无")
        return 1 if fails else 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
