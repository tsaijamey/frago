# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""scene_ops 的自测：包围盒、相机相对方向、place 的净空、体检的三类问题。

这些东西错了在画面上看不出来——物体照样画得出来，只是位置不对。
所以必须用断言钉住，不能靠眼睛验。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scene_ops as so  # noqa: E402
import recipe as R  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  — ' + detail) if detail else ''}")
    if not ok:
        fails.append(name)


def close(a, b, tol=1e-6):
    return abs(a - b) <= tol


def obj(oid, shape, semantic, pos, rot=None, dims=None, label=None):
    o = {
        "id": oid, "shape": shape, "semantic": semantic,
        "position": list(pos), "rotation": list(rot or [0, 0, 0]),
        "scale": so.dims_to_scale(shape, dims) if dims else R.default_scale(shape, semantic),
    }
    if label:
        o["label"] = label
    return o


print("=== 1. 默认尺寸就是真实米数（人不是半米高，车不是巴士）===")
for sem, shape, want in [
    ("person", "capsule", [0.5, 1.7, 0.35]),
    ("vehicle", "box", [4.6, 1.5, 1.9]),
    ("vegetation", "cone", [3.0, 5.0, 3.0]),
    ("building", "box", [8.0, 12.0, 8.0]),
    ("furniture", "box", [1.2, 0.75, 0.6]),
    ("wall", "box", [4.0, 2.8, 0.2]),
]:
    got = so.scale_to_dims(shape, R.default_scale(shape, sem))
    check(f"{sem:11s}{shape:8s} 默认 {want}", all(close(a, b, 1e-3) for a, b in zip(got, want)),
          f"实得 {[round(v,3) for v in got]}")

person = obj("p", "capsule", "person", [0, 0, 0])
box = so.object_aabb(person)
h = box["max"][1] - box["min"][1]
check("人站在地上，头顶正好 1.7 米", close(h, 1.7, 1e-6) and close(box["min"][1], 0.0),
      f"高 {h:.3f}，底 {box['min'][1]:.3f}")

print("\n=== 2. 包围盒：缩放与旋转 ===")
b = so.object_aabb(obj("b", "box", "prop", [0, 0, 0], dims=[2, 3, 4]))
check("2×3×4 的方块贴地居中", b["min"] == [-1.0, 0.0, -2.0] and b["max"] == [1.0, 3.0, 2.0], str(b))

b = so.object_aabb(obj("b", "box", "prop", [0, 0, 0], rot=[0, 90, 0], dims=[4, 1, 2]))
size = so.aabb_size(b)
check("绕 Y 转 90° 后长宽对调", close(size[0], 2, 1e-6) and close(size[2], 4, 1e-6),
      f"尺寸 {[round(v,3) for v in size]}")

print("\n=== 3. 方向是「相机看到的方向」，不是世界轴 ===")
cam_z = {"position": [0, 2, 10], "target": [0, 1, 0], "fov": 40}
right = so.ground_direction("right", cam_z)
front = so.ground_direction("front", cam_z)
check("相机在 +Z 时，右 = +X", close(right[0], 1, 1e-6) and close(right[2], 0, 1e-6), str([round(v,3) for v in right]))
check("相机在 +Z 时，前（靠近相机）= +Z", close(front[2], 1, 1e-6), str([round(v,3) for v in front]))

cam_x = {"position": [10, 2, 0], "target": [0, 1, 0], "fov": 40}
right_x = so.ground_direction("right", cam_x)
check("相机转到 +X 时，同一句「右」变成 -Z", close(right_x[2], -1, 1e-6),
      str([round(v, 3) for v in right_x]))

print("\n=== 4. place 的 distance 是净空，不是中心距 ===")
car = obj("car", "box", "vehicle", [0, 0, 0], label="车")
proto = obj("new", "capsule", "person", [0, 0, 0])
solved, err = so.solve_placement(car, proto, "left", 2.0, "ground", cam_z)
check("解算没报错", err is None, str(err))
if solved:
    pos = solved["position"]
    car_box, p_box = so.object_aabb(car), so.object_aabb({**proto, "position": pos})
    gap = car_box["min"][0] - p_box["max"][0]
    check("人在车左边，两者表面净空正好 2 米", close(gap, 2.0, 1e-6), f"净空 {gap:.4f} 米")
    check("人贴在地上", close(p_box["min"][1], 0.0, 1e-9), f"底 {p_box['min'][1]:.4f}")
    check("不穿模", any(o <= 0 for o in so.aabb_overlap(car_box, p_box)), "")

solved_a, _ = so.solve_placement(car, proto, "above", 0.5, "ground", cam_z)
p_box = so.object_aabb({**proto, "position": solved_a["position"]})
car_box = so.object_aabb(car)
check("above：底面离车顶正好 0.5 米", close(p_box["min"][1] - car_box["max"][1], 0.5, 1e-6),
      f"{p_box['min'][1] - car_box['max'][1]:.4f}")

# 旋转过的物体，包围盒不以原点为中心，落点要把这个偏移减掉
tilted = obj("t", "box", "prop", [0, 0, 0], rot=[0, 45, 0], dims=[4, 1, 1])
solved_t, _ = so.solve_placement(car, tilted, "right", 1.0, "ground", cam_z)
t_box = so.object_aabb({**tilted, "position": solved_t["position"]})
gap_t = t_box["min"][0] - so.object_aabb(car)["max"][0]
check("转过 45° 的物体也贴得准", close(gap_t, 1.0, 1e-6), f"净空 {gap_t:.4f} 米")

print("\n=== 5. measure 说人话 ===")
scene_cam = cam_z
a_box = so.object_aabb(obj("a", "capsule", "person", [-3, 0, 2]))
b_box = so.object_aabb(car)
d = so.describe_direction(a_box, b_box, scene_cam)
check("人在车的左前方", d["left_right"] == "left" and d["front_back"] == "front", d["text"])
check("横向距离 3 米", close(abs(d["lateral_m"]), 3.0, 1e-6), str(d["lateral_m"]))

print("\n=== 6. 体检：穿模 / 悬空 / 出画 ===")
scene = {
    "canvas": {"aspect": "16:9", "width": 1280, "height": 720},
    "camera": {"position": [0, 2, 14], "target": [0, 1, 0], "fov": 40},
    "objects": [
        obj("ground", "plane", "ground", [0, 0, 0]),
        obj("car", "box", "vehicle", [0, 0, 0], label="车"),
        obj("man", "capsule", "person", [0, 0, 0], label="站在车里的人"),   # 故意穿模
        obj("lamp", "sphere", "light", [4, 3, 0], label="悬空的灯"),        # 故意悬空
        obj("far", "cone", "vegetation", [80, 0, 0], label="画外的树"),     # 故意出画
    ],
}
issues = so.find_issues(scene, 1280 / 720)
kinds = {}
for i in issues:
    kinds.setdefault(i["kind"], []).append(i)

check("查出穿模", "intersect" in kinds,
      kinds.get("intersect", [{}])[0].get("message", ""))
check("穿模没把「站在地上」误报", all("ground" not in i["ids"] for i in kinds.get("intersect", [])),
      f"共 {len(kinds.get('intersect', []))} 对")
check("查出悬空", any("lamp" in i["ids"] for i in kinds.get("floating", [])),
      kinds.get("floating", [{}])[0].get("message", ""))
check("查出出画", any("far" in i["ids"] for i in kinds.get("out_of_frame", []) + kinds.get("partly_out_of_frame", [])),
      next((i["message"] for i in issues if "far" in i["ids"]), ""))
check("每条问题都带 id 和人话", all(i.get("ids") and i.get("message") for i in issues),
      f"共 {len(issues)} 条")

clean_scene = {
    "canvas": scene["canvas"],
    "camera": {"position": [0, 2, 16], "target": [0, 1, 0], "fov": 45},
    "objects": [
        obj("ground", "plane", "ground", [0, 0, 0]),
        obj("car", "box", "vehicle", [0, 0, 0]),
        obj("man", "capsule", "person", [-4, 0, 0]),
    ],
}
check("干净场景不误报", so.find_issues(clean_scene, 1280 / 720) == [],
      str([i["message"] for i in so.find_issues(clean_scene, 1280 / 720)]))

print("\n=== 7. camera_frame 解出来的机位真能框住目标 ===")
wide = {
    "canvas": {"aspect": "16:9", "width": 1280, "height": 720},
    "camera": {"position": [3, 2, 6], "target": [0, 1, 0], "fov": 40},
    "objects": [
        obj("ground", "plane", "ground", [0, 0, 0]),
        obj("a", "box", "building", [-20, 0, -10]),
        obj("b", "box", "building", [22, 0, 8]),
        obj("c", "capsule", "person", [0, 0, 0]),
    ],
}
aspect = 1280 / 720
bounds = so.framing_aabb(wide["objects"])
pose = so.solve_frame(bounds, wide["camera"], aspect, 0.12)
framed = {**wide["camera"], **pose}
inside = True
for o in wide["objects"]:
    if o["semantic"] in so.SURFACE_SEMANTICS:
        continue
    rect, seen = so.aabb_screen_rect(so.object_aabb(o), framed, aspect)
    if rect is None or seen < 8 or rect[0] < -1 or rect[2] > 1 or rect[1] < -1 or rect[3] > 1:
        inside = False
check("框完之后所有主体都在画框内", inside, f"相机退到 {[round(v,1) for v in pose['position']]}")

# 只"装得下"不够——包围球式的解法也装得下，只是主体缩成一小块。
# 所以还要求主体真的占满画面：横向或纵向至少填到 60%。
rects = [so.aabb_screen_rect(so.object_aabb(o), framed, aspect)[0]
         for o in wide["objects"] if o["semantic"] not in so.SURFACE_SEMANTICS]
rects = [r for r in rects if r]
fill_w = (max(r[2] for r in rects) - min(r[0] for r in rects)) / 2
fill_h = (max(r[3] for r in rects) - min(r[1] for r in rects)) / 2
check("取景够紧，主体填满画面而不是缩成一小块",
      max(fill_w, fill_h) >= 0.6,
      f"横向填充 {fill_w*100:.0f}%，纵向 {fill_h*100:.0f}%")
check("fov 没被偷偷改掉", "fov" not in pose, "取景只动机位，换镜头是人的创作决定")
check("相机没被解到地底下", pose["position"][1] >= so.MIN_CAMERA_Y,
      f"相机高度 {pose['position'][1]:.2f} 米")

print("\n=== 8. 俯瞰机位不炸（视线与 up 共线）===")
try:
    top = so.solve_preset({"key": "top_down", "height": None}, bounds, wide["camera"])
    ok = top["position"][1] > 10 and so.project_point([0, 0, 0], {**framed, **top}, aspect) is not None
    check("俯瞰能解出机位且能投影", ok, str([round(v, 1) for v in top["position"]]))
except Exception as e:
    check("俯瞰能解出机位且能投影", False, repr(e))

print("\n=== 9. 中心点摆法的兜底校正（实测踩过：整个场景浮空，四张图作废）===")
plan = [
    {"action": "object_add", "args": {"semantic": "building", "label": "图书馆",
                                      "dims": [10, 8, 10], "position": [0, 4.0, 0]}},
    {"action": "object_add", "args": {"semantic": "person", "label": "卡夫卡",
                                      "position": [1, 0.85, 0]}},
    {"action": "object_add", "args": {"semantic": "prop", "label": "行李箱",
                                      "dims": [0.6, 0.5, 0.4], "position": [2, -0.25, 0]}},
    {"action": "object_add", "args": {"semantic": "light", "label": "真的吊灯",
                                      "dims": [0.3, 0.3, 0.3], "position": [3, 2.5, 0]}},
]
fixed, notes = R.ground_correct_plan(plan, {"objects": []})
ys = [st["args"]["position"][1] for st in fixed]
check("半高的 y 被归零（图书馆 4.0 → 0）", close(ys[0], 0.0), f"实得 {ys[0]}")
check("默认尺寸也算得出半高（卡夫卡 0.85 → 0）", close(ys[1], 0.0), f"实得 {ys[1]}")
check("负的半高同样纠正（行李箱 -0.25 → 0）", close(ys[2], 0.0), f"实得 {ys[2]}")
check("真正想浮空的不动（吊灯 2.5 不是半高 0.15）", close(ys[3], 2.5), f"实得 {ys[3]}")
check("纠正了什么要说出来", len(notes) == 3 and all("落回地面" in n for n in notes),
      f"{len(notes)} 条：{notes[0] if notes else ''}")

print()
print("FAILED:", fails if fails else "无")
sys.exit(1 if fails else 0)
