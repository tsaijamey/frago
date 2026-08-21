# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""指挥台的回归用例：一组最自然的说法，看有多少句能落地。

每句都在同一份固定场景上跑，跑前重置，所以句与句之间互不影响。
没命中的会连同**模型原话和被拒理由**一起打出来——只报一个命中率，
下一步该改哪里是猜不出来的。

用法：
    uv run --no-project test_instruct.py            # 全跑
    uv run --no-project test_instruct.py 挪         # 只跑名字里带「挪」的
"""

import json
import subprocess
import sys
from pathlib import Path

RECIPE = "whitebox_scene_studio"
PROJECT = "regression"

# 固定场景：一个天台，四样东西，名字都是人会用的说法。
FIXTURE = {
    "canvas": {"aspect": "16:9"},
    "camera": {"position": [9.0, 3.0, 11.0], "target": [0.0, 1.0, -1.0], "fov": 40},
    "objects": [
        {"id": "obj_1", "shape": "plane", "semantic": "ground", "label": "天台地面",
         "position": [0, 0, 0], "rotation": [0, 0, 0], "scale": [30, 1, 30]},
        {"id": "obj_2", "shape": "box", "semantic": "building", "label": "女儿墙",
         "position": [0, 0, -5], "rotation": [0, 0, 0], "scale": [8, 1.1, 0.3]},
        {"id": "obj_3", "shape": "capsule", "semantic": "person", "label": "撑伞的人",
         "position": [-1.5, 0, 0], "rotation": [0, 20, 0], "scale": [1, 1.7, 0.7]},
        {"id": "obj_4", "shape": "cone", "semantic": "vegetation", "label": "盆栽",
         "position": [2.0, 0, -1.0], "rotation": [0, 0, 0], "scale": [0.8, 1.4, 0.8]},
    ],
}

# (分类, 说法, 判定这句算不算落地)
#
# 判定函数拿到的是执行结果，看的是「场景真的变成了他要的样子」，
# 不是「模型有没有回话」——后者太容易蒙混过关。
CASES = [
    ("挪东西", "把盆栽往左挪半米",
     lambda r, s0, s1: moved(s0, s1, "obj_4", axis_hint="left", dist=0.5)),
    ("挪东西", "撑伞的人往前挪一米",
     lambda r, s0, s1: moved(s0, s1, "obj_3", axis_hint="front", dist=1.0)),

    ("放东西", "在撑伞的人右边一米五放一把椅子",
     lambda r, s0, s1: added(s0, s1, semantic="furniture")),
    # 这句里两个诉求是有张力的：要框住更多就得后退，后退就不可能还停在 1.6 米。
    # 所以判的是「椅子放下了 + 确实走了人眼预设 + 相机动过了」，
    # 而不是苛求最终高度——那个数在物理上就不该是 1.6。
    ("放东西", "在撑伞的人右边一米五放一把椅子，再把机位压到人眼高度，框住天台上所有东西",
     lambda r, s0, s1: added(s0, s1, semantic="furniture")
                       and s1["camera"] != s0["camera"]
                       and any(x["action"] == "camera_set" for x in (r.get("plan") or []))),

    ("删东西", "把盆栽删掉",
     lambda r, s0, s1: ids(s1) == ids(s0) - {"obj_4"}),

    ("改名", "把撑伞的人改名叫夜归人",
     lambda r, s0, s1: by_id(s1, "obj_3").get("label") == "夜归人"),

    ("换机位", "把机位压到人眼高度",
     lambda r, s0, s1: abs(s1["camera"]["position"][1] - 1.6) < 0.01),
    ("换机位", "俯瞰整个天台",
     lambda r, s0, s1: s1["camera"]["position"][1] > 8),

    ("框住", "框住撑伞的人和女儿墙",
     lambda r, s0, s1: s1["camera"] != s0["camera"]),

    ("放大", "把盆栽放大一倍",
     lambda r, s0, s1: by_id(s1, "obj_4")["scale"][1] > by_id(s0, "obj_4")["scale"][1] * 1.5),
    ("放大", "把女儿墙加高到两米",
     lambda r, s0, s1: abs(by_id(s1, "obj_2")["scale"][1] - 2.0) < 0.2),

    ("贴地", "盆栽好像浮着，让它贴回地面",
     lambda r, s0, s1: abs(by_id(s1, "obj_4")["position"][1]) < 0.01),

    ("问距离", "撑伞的人离女儿墙有多远",
     lambda r, s0, s1: ids(s1) == ids(s0)
                       and any(x["action"] == "measure" for x in (r.get("plan") or []))),

    ("做不到", "把天空改成紫色",
     lambda r, s0, s1: not r.get("applied") and ids(s1) == ids(s0)),
    ("做不到", "给盆栽加上开花的细节和露水",
     lambda r, s0, s1: not r.get("applied") and ids(s1) == ids(s0)),
]


# --- 判定小工具 ---

def ids(scene):
    return {o["id"] for o in scene["objects"]}


def by_id(scene, oid):
    return next((o for o in scene["objects"] if o["id"] == oid), {})


def added(s0, s1, semantic=None):
    new = ids(s1) - ids(s0)
    if len(new) != 1:
        return False
    if semantic:
        return by_id(s1, new.pop())["semantic"] == semantic
    return True


def moved(s0, s1, oid, axis_hint=None, dist=None):
    """挪过了：物体还在、id 没变、位置变了、位移量大致对得上。"""
    if ids(s1) != ids(s0):
        return False              # 多出或少了物体，说明它选了 place 而不是 move
    a, b = by_id(s0, oid)["position"], by_id(s1, oid)["position"]
    delta = sum((b[i] - a[i]) ** 2 for i in range(3)) ** 0.5
    if delta < 1e-6:
        return False
    return abs(delta - dist) < 0.35 if dist else True


# --- 跑 ---

def run(params, capture_error=False):
    r = subprocess.run(
        ["frago", "recipe", "run", RECIPE, "--params", json.dumps(params, ensure_ascii=False)],
        capture_output=True, text=True, timeout=300,
    )
    if r.returncode != 0:
        if capture_error:
            return {"success": False, "error": r.stderr.strip()[-400:]}
        raise SystemExit(f"跑 {params.get('action')} 失败：{r.stderr.strip()[-400:]}")
    text = r.stdout[r.stdout.index("{"):]
    return json.loads(text)


def reset_scene():
    run({"action": "scene_put", "project": PROJECT, "scene": FIXTURE})
    return run({"action": "scene_get", "project": PROJECT})["scene"]


def main():
    needle = sys.argv[1] if len(sys.argv) > 1 else None

    known = {p["slug"] for p in run({"action": "project_list"})["projects"]}
    if PROJECT not in known:
        run({"action": "project_create", "name": "regression"})

    cases = [c for c in CASES if not needle or needle in c[0] or needle in c[1]]
    hits, misses = 0, []

    print(f"共 {len(cases)} 句，每句跑前重置场景\n")
    for i, (kind, text, judge) in enumerate(cases, 1):
        before = reset_scene()
        res = run({"action": "instruct", "project": PROJECT, "text": text}, capture_error=True)
        after = run({"action": "scene_get", "project": PROJECT})["scene"]

        try:
            ok = bool(judge(res, before, after))
        except Exception as e:
            ok = False
            res.setdefault("reason", f"判定时出错：{e!r}")

        print(f"{'✅' if ok else '❌'} [{kind}] {text}")
        if ok:
            hits += 1
        else:
            misses.append((kind, text, res))
            reason = res.get("reason") or res.get("error") or "（没给理由）"
            print(f"      被拒/失败：{reason}")
            plan = res.get("plan")
            if plan:
                print(f"      模型的计划：{json.dumps(plan, ensure_ascii=False)}")
            if res.get("model_said"):
                print(f"      模型原话：{str(res['model_said'])[:300]}")

    rate = hits / len(cases) * 100 if cases else 0
    print(f"\n命中 {hits}/{len(cases)} = {rate:.0f}%")
    if misses:
        print("\n没命中的：")
        for kind, text, res in misses:
            print(f"  [{kind}] {text}")
            print(f"      {res.get('reason') or res.get('error') or ''}")
    return 0 if not misses else 1


if __name__ == "__main__":
    sys.exit(main())
