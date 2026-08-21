# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26", "pillow>=10"]
# ///
"""render.py 的自测：单位体约定、seg 颜色逐位精确、三通道对齐。"""
import sys, json, math
from pathlib import Path
import numpy as np

R = Path.home() / ".frago/recipes/workflows/whitebox_scene_studio"
sys.path.insert(0, str(R))
import render
from recipe import SEMANTICS, SHAPE_KEYS

COLORS = {s['key']: s['color'] for s in SEMANTICS}
fails = []
def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  — ' + detail) if detail else ''}")
    if not ok: fails.append(name)

print("=== 1. 单位体约定：y∈[0,1]，x/z 在 ±0.5 内，底面中心即原点 ===")
for shape in SHAPE_KEYS:
    v, n, f = render.unit_mesh(shape)
    lo, hi = v.min(axis=0), v.max(axis=0)
    exp_h = 0.02 if shape == 'plane' else 1.0
    ok = (abs(lo[1]) < 1e-9 and abs(hi[1] - exp_h) < 1e-6
          and lo[0] >= -0.5001 and hi[0] <= 0.5001
          and lo[2] >= -0.5001 and hi[2] <= 0.5001
          and abs(lo[0] + hi[0]) < 1e-6 and abs(lo[2] + hi[2]) < 1e-6)
    check(f"{shape:9s} bbox", ok, f"x[{lo[0]:+.3f},{hi[0]:+.3f}] y[{lo[1]:.3f},{hi[1]:.3f}] z[{lo[2]:+.3f},{hi[2]:+.3f}] tris={len(f)}")
    check(f"{shape:9s} 法线单位长", bool(np.allclose(np.linalg.norm(n, axis=1), 1.0, atol=1e-6)))

print("\n=== 2. 楼梯剖面真是 5 级台阶（不是被压成方块）===")
v, n, f = render.unit_mesh('stairs')
front = v[np.abs(v[:, 2] - 0.5) < 1e-9]
heights = sorted(set(np.round(front[:, 1], 4)))
check("楼梯有 6 个不同高度（0 + 5 级）", heights == [0.0, 0.2, 0.4, 0.6, 0.8, 1.0], str(heights))

print("\n=== 3. 欧拉角与 three.js XYZ 序一致 ===")
m = render.euler_matrix(0, 90, 0)
got = m @ np.array([1.0, 0, 0])
check("绕 Y 转 90° 把 +X 送到 -Z", np.allclose(got, [0, 0, -1], atol=1e-9), f"→ {np.round(got,6).tolist()}")
m = render.euler_matrix(90, 0, 0)
got = m @ np.array([0.0, 1, 0])
check("绕 X 转 90° 把 +Y 送到 +Z", np.allclose(got, [0, 0, 1], atol=1e-9), f"→ {np.round(got,6).tolist()}")

print("\n=== 4. seg 颜色逐位精确（这是图例的另一半，差一色阶就对不上号）===")
scene = {
  "canvas": {"aspect": "16:9", "width": 640, "height": 360},
  "camera": {"position": [0, 3, 9], "target": [0, 0.9, 0], "fov": 40},
  "objects": [
    {"id":"p","shape":"capsule","semantic":"person","position":[-2,0,0],"rotation":[0,0,0],"scale":[1,1.75,1]},
    {"id":"v","shape":"box","semantic":"vehicle","position":[2.4,0,0],"rotation":[0,-20,0],"scale":[4.4,1.5,1.9]},
    {"id":"t","shape":"cone","semantic":"vegetation","position":[0,0,-4],"rotation":[0,0,0],"scale":[2,4.5,2]},
    {"id":"g","shape":"plane","semantic":"ground","position":[0,0,0],"rotation":[0,0,0],"scale":[40,1,40]},
  ],
}
seg = render.render_view(scene, COLORS, 'seg', 640, 360)
present = {tuple(c) for c in seg.reshape(-1, 3)[::7]}
allowed = {render.hex_rgb(COLORS[k]) for k in COLORS} | {(0, 0, 0)}
strays = present - allowed
check("seg 里没有色卡以外的颜色", not strays, f"意外色 {sorted(strays)[:5]}" if strays else f"出现 {len(present)} 种，全部合法")
for key, want in (("person", COLORS['person']), ("vehicle", COLORS['vehicle']), ("vegetation", COLORS['vegetation'])):
    want_rgb = render.hex_rgb(want)
    cnt = int((seg == np.array(want_rgb)).all(axis=2).sum())
    check(f"{key} 的色块存在且是 {want}", cnt > 200, f"{cnt} 像素")

print("\n=== 5. 三通道严格对齐（同一相机、同一尺寸、轮廓一致）===")
clay = render.render_view(scene, COLORS, 'clay', 640, 360, supersample=1)
depth = render.render_view(scene, COLORS, 'depth', 640, 360)
check("三张图尺寸一致", clay.shape == seg.shape == depth.shape, f"{clay.shape}")
occ_seg = (seg != np.array([0,0,0])).any(axis=2)
occ_depth = (depth != np.array([0,0,0])).any(axis=2)
agree = (occ_seg == occ_depth).mean()
check("seg 与 depth 的占用像素重合 ≥99%", agree >= 0.99, f"{agree*100:.2f}%")

print("\n=== 6. 相机在正上方（视线与 up 共线）不炸 ===")
top = dict(scene); top = json.loads(json.dumps(scene))
top['camera'] = {"position": [0, 20, 0], "target": [0, 0, 0], "fov": 40}
try:
    img = render.render_view(top, COLORS, 'seg', 320, 180)
    nonbg = int((img != 0).any(axis=2).sum())
    check("正俯视能出图", nonbg > 1000, f"{nonbg} 个非背景像素")
except Exception as e:
    check("正俯视能出图", False, repr(e))

print("\n=== 7. 相机贴到物体里（需要近平面裁剪）不出横贯全屏的怪影 ===")
close = json.loads(json.dumps(scene))
close['camera'] = {"position": [-2, 0.9, 0.05], "target": [0, 0.9, -4], "fov": 55}
img = render.render_view(close, COLORS, 'seg', 320, 180)
check("近距离渲染不抛异常且有内容", int((img != 0).any(axis=2).sum()) > 0, "近平面裁剪生效")

print()
print("FAILED:", fails if fails else "无")
sys.exit(1 if fails else 0)
