# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26", "pillow>=10"]
# ///
"""服务端软件光栅器：读 scene.json，出 clay / seg / depth 三张严格对齐的 PNG。

**为什么服务端要自己会渲染。** 3D 本来只活在浏览器里，服务端要图就得请页面代劳。
可无头浏览器没有 GPU（实测 webgl2 / webgl / experimental-webgl 三个上下文全是 null），
于是「页面开着」成了出图的前提——agent 不开页面就出不了图，端到端测试也跑不通。
所以渲染在这里重做一遍：服务端是主路径，浏览器 WebGL 只是加速路径。

**跟前端必须逐位对齐的三件事**，改任何一处都要两边一起改：
1. 单位体约定：每种形状 y ∈ [0,1]、x/z 在 ±0.5 以内、底面中心即原点。
   与 assets/js/editor3d.js 的 unitGeometry 一一对应。
2. 欧拉角：scene.json 存的是**度数**，旋转序是 three.js 的默认 XYZ，
   等价于 R = Rx·Ry·Rz（已对着 three r165 的 makeRotationFromEuler 逐元素核对）。
3. 相机 fov 是**竖直**视角，画幅比取 canvas.width / canvas.height。
   这就是页面上那个安全框里的视野——所见即所得的等号建立在这一条上。

**seg 通道的颜色必须逐位精确**：它是图例文字「红色=人物」的另一半，
差一个色阶，模型就对不上号。所以 seg 不做光照、不做色调映射、不做超采样，
色值直接按字节写进缓冲区。这条在代码里有强制点，别绕过去。
"""

import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

NEAR = 0.05
DEG = math.pi / 180.0

BG_CLAY = (0xF2, 0xF2, 0xF2)
BG_SEG = (0x00, 0x00, 0x00)
BG_DEPTH = (0x00, 0x00, 0x00)

GRID_COLOR = (0xB4, 0xBC, 0xC6)
GRID_HALF = 20        # 网格向四周各铺多少米
GRID_WIDTH = 0.015    # 线条在世界里的宽度，米
# 网格得浮在地面板**上方**。plane 的单位厚度是 0.02，压在下面就整片看不见了
# ——那正好是最需要参照的场景（人铺了一块地，然后不知道自己在往哪儿点）。
GRID_Y = 0.03


# --- 单位体网格 ---------------------------------------------------------
# 每个构造函数返回 (verts Nx3, normals Nx3, faces Mx3)。
# 法线是按形状解析给的而不是求平均：球和柱要圆滑，方块和楼梯要硬边，
# 平均法线两头都讨不了好——球面出棱、方块的角被抹圆。


def _quad(verts, normals, faces, p0, p1, p2, p3, n):
    base = len(verts)
    verts.extend([p0, p1, p2, p3])
    normals.extend([n, n, n, n])
    faces.append((base, base + 1, base + 2))
    faces.append((base, base + 2, base + 3))


def mesh_box(w=1.0, h=1.0, d=1.0, y0=0.0):
    """轴对齐盒子，底面贴 y0，x/z 居中。"""
    hx, hz = w / 2, d / 2
    y1 = y0 + h
    v, n, f = [], [], []
    _quad(v, n, f, (-hx, y0, hz), (hx, y0, hz), (hx, y1, hz), (-hx, y1, hz), (0, 0, 1))
    _quad(v, n, f, (hx, y0, -hz), (-hx, y0, -hz), (-hx, y1, -hz), (hx, y1, -hz), (0, 0, -1))
    _quad(v, n, f, (hx, y0, hz), (hx, y0, -hz), (hx, y1, -hz), (hx, y1, hz), (1, 0, 0))
    _quad(v, n, f, (-hx, y0, -hz), (-hx, y0, hz), (-hx, y1, hz), (-hx, y1, -hz), (-1, 0, 0))
    _quad(v, n, f, (-hx, y1, hz), (hx, y1, hz), (hx, y1, -hz), (-hx, y1, -hz), (0, 1, 0))
    _quad(v, n, f, (-hx, y0, -hz), (hx, y0, -hz), (hx, y0, hz), (-hx, y0, hz), (0, -1, 0))
    return np.array(v, np.float64), np.array(n, np.float64), np.array(f, np.int32)


def mesh_sphere(radius=0.5, cy=0.5, seg=28, rings=14):
    v, n, f = [], [], []
    for i in range(rings + 1):
        phi = math.pi * i / rings
        for j in range(seg + 1):
            theta = 2 * math.pi * j / seg
            nx = math.sin(phi) * math.cos(theta)
            ny = math.cos(phi)
            nz = math.sin(phi) * math.sin(theta)
            n.append((nx, ny, nz))
            v.append((radius * nx, cy + radius * ny, radius * nz))
    row = seg + 1
    for i in range(rings):
        for j in range(seg):
            a = i * row + j
            f.append((a, a + row, a + row + 1))
            f.append((a, a + row + 1, a + 1))
    return np.array(v, np.float64), np.array(n, np.float64), np.array(f, np.int32)


def mesh_cylinder(radius=0.5, height=1.0, y0=0.0, seg=28):
    v, n, f = [], [], []
    y1 = y0 + height
    for j in range(seg + 1):
        t = 2 * math.pi * j / seg
        cx, cz = math.cos(t), math.sin(t)
        v.append((radius * cx, y0, radius * cz))
        n.append((cx, 0, cz))
        v.append((radius * cx, y1, radius * cz))
        n.append((cx, 0, cz))
    for j in range(seg):
        a = j * 2
        f.append((a, a + 2, a + 3))
        f.append((a, a + 3, a + 1))
    for y, ny, flip in ((y1, 1.0, False), (y0, -1.0, True)):
        c = len(v)
        v.append((0, y, 0))
        n.append((0, ny, 0))
        ring = len(v)
        for j in range(seg + 1):
            t = 2 * math.pi * j / seg
            v.append((radius * math.cos(t), y, radius * math.sin(t)))
            n.append((0, ny, 0))
        for j in range(seg):
            a, b = ring + j, ring + j + 1
            f.append((c, b, a) if flip else (c, a, b))
    return np.array(v, np.float64), np.array(n, np.float64), np.array(f, np.int32)


def mesh_cone(radius=0.5, height=1.0, y0=0.0, seg=28):
    v, n, f = [], [], []
    apex = y0 + height
    slope = radius / math.hypot(radius, height)
    ny = radius and (height / math.hypot(radius, height)) or 1.0
    for j in range(seg + 1):
        t = 2 * math.pi * j / seg
        cx, cz = math.cos(t), math.sin(t)
        # 侧面法线：水平分量沿半径，竖直分量由母线斜率给
        nrm = (cx * ny, slope, cz * ny)
        v.append((radius * cx, y0, radius * cz))
        n.append(nrm)
        v.append((0.0, apex, 0.0))
        n.append(nrm)
    for j in range(seg):
        a = j * 2
        f.append((a, a + 2, a + 1))
    c = len(v)
    v.append((0, y0, 0))
    n.append((0, -1, 0))
    ring = len(v)
    for j in range(seg + 1):
        t = 2 * math.pi * j / seg
        v.append((radius * math.cos(t), y0, radius * math.sin(t)))
        n.append((0, -1, 0))
    for j in range(seg):
        f.append((c, ring + j + 1, ring + j))
    return np.array(v, np.float64), np.array(n, np.float64), np.array(f, np.int32)


def mesh_capsule(radius=0.25, length=0.5, seg=24, rings=8):
    """总高 = length + 2*radius。默认 0.5 + 0.5 = 1，与前端胶囊一致。"""
    v, n, f = [], [], []
    cy_low, cy_high = radius, radius + length
    rows = []
    for i in range(rings + 1):            # 上半球
        phi = (math.pi / 2) * i / rings
        rows.append((math.sin(phi), math.cos(phi), cy_high))
    for i in range(rings + 1):            # 下半球
        phi = (math.pi / 2) * i / rings
        rows.append((math.cos(phi), -math.sin(phi), cy_low))
    for sr, sy, cy in rows:
        for j in range(seg + 1):
            t = 2 * math.pi * j / seg
            nx, nz = sr * math.cos(t), sr * math.sin(t)
            n.append((nx, sy, nz))
            v.append((radius * nx, cy + radius * sy, radius * nz))
    row = seg + 1
    for i in range(len(rows) - 1):
        for j in range(seg):
            a = i * row + j
            f.append((a, a + row, a + row + 1))
            f.append((a, a + row + 1, a + 1))
    return np.array(v, np.float64), np.array(n, np.float64), np.array(f, np.int32)


def mesh_extrude(profile, depth=1.0):
    """把 XY 剖面沿 +Z 挤出。楼梯用它，跟前端的 ExtrudeGeometry 同形。

    剖面必须相对最后一个顶点是星形的（从它能直视到每一点），楼梯剖面满足，
    所以前后盖用扇形三角化就够，不必上通用多边形剖分。
    """
    v, n, f = [], [], []
    pts = list(profile)
    k = len(pts)

    for z, nz in ((depth, 1.0), (0.0, -1.0)):
        base = len(v)
        for x, y in pts:
            v.append((x, y, z))
            n.append((0, 0, nz))
        anchor = base + k - 1
        for i in range(k - 2):
            if nz > 0:
                f.append((anchor, base + i, base + i + 1))
            else:
                f.append((anchor, base + i + 1, base + i))

    for i in range(k):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % k]
        ex, ey = x1 - x0, y1 - y0
        ln = math.hypot(ex, ey)
        if ln < 1e-12:
            continue
        nrm = (ey / ln, -ex / ln, 0.0)
        _quad(v, n, f, (x0, y0, 0.0), (x1, y1, 0.0), (x1, y1, depth), (x0, y0, depth), nrm)

    return np.array(v, np.float64), np.array(n, np.float64), np.array(f, np.int32)


def mesh_stairs(steps=5):
    """与前端同一份剖面：左低右高的阶梯，下方实心。"""
    pts = [(0.0, 0.0)]
    for i in range(steps):
        pts.append((i / steps, (i + 1) / steps))
        pts.append(((i + 1) / steps, (i + 1) / steps))
    pts.append((1.0, 0.0))
    v, n, f = mesh_extrude(pts, 1.0)
    v = v - np.array([0.5, 0.0, 0.5])
    return v, n, f


_MESH_CACHE = {}


def unit_mesh(shape):
    if shape in _MESH_CACHE:
        return _MESH_CACHE[shape]
    if shape == 'box':
        m = mesh_box()
    elif shape == 'sphere':
        m = mesh_sphere()
    elif shape == 'cylinder':
        m = mesh_cylinder()
    elif shape == 'cone':
        m = mesh_cone()
    elif shape == 'capsule':
        m = mesh_capsule()
    elif shape == 'plane':
        m = mesh_box(1.0, 0.02, 1.0)
    elif shape == 'stairs':
        m = mesh_stairs()
    else:
        m = mesh_box()
    _MESH_CACHE[shape] = m
    return m


# --- 变换 ---------------------------------------------------------------


def euler_matrix(rx, ry, rz):
    """three.js 默认 XYZ 序：R = Rx·Ry·Rz。入参是度数。"""
    a, b = math.cos(rx * DEG), math.sin(rx * DEG)
    c, d = math.cos(ry * DEG), math.sin(ry * DEG)
    e, ff = math.cos(rz * DEG), math.sin(rz * DEG)
    return np.array([
        [c * e, -c * ff, d],
        [a * ff + b * e * d, a * e - b * ff * d, -b * c],
        [b * ff - a * e * d, b * e + a * ff * d, a * c],
    ], np.float64)


def look_at(eye, target, up=(0.0, 1.0, 0.0)):
    eye = np.asarray(eye, np.float64)
    target = np.asarray(target, np.float64)
    fwd = target - eye
    ln = np.linalg.norm(fwd)
    fwd = fwd / ln if ln > 1e-9 else np.array([0.0, 0.0, -1.0])

    up = np.asarray(up, np.float64)
    side = np.cross(fwd, up)
    if np.linalg.norm(side) < 1e-6:
        # 正俯视：视线与 up 共线，叉积退化。换一根参考轴，画面照样正。
        up = np.array([0.0, 0.0, -1.0])
        side = np.cross(fwd, up)
    side /= np.linalg.norm(side)
    trueup = np.cross(side, fwd)

    m = np.eye(4)
    m[0, :3], m[1, :3], m[2, :3] = side, trueup, -fwd
    m[0, 3] = -side @ eye
    m[1, 3] = -trueup @ eye
    m[2, 3] = fwd @ eye
    return m


# --- 三角形收集 ---------------------------------------------------------


def hex_rgb(text, fallback=(0xCC, 0xCC, 0xCC)):
    t = (text or '').lstrip('#')
    if len(t) != 6:
        return fallback
    try:
        return tuple(int(t[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return fallback


def collect_triangles(scene, semantic_colors):
    """把场景摊平成一堆世界空间三角形。返回 (pos, nrm, color)。

    pos (T,3,3)、nrm (T,3,3)、color (T,3) —— 颜色是 seg 用的语义色，
    一个物体的所有三角形共用一个，所以 seg 出来是干净的纯色块。
    """
    pos_parts, nrm_parts, col_parts = [], [], []

    for obj in scene.get('objects') or []:
        shape = obj.get('shape')
        verts, normals, faces = unit_mesh(shape)

        scale = np.asarray(obj.get('scale') or [1, 1, 1], np.float64)
        rot = obj.get('rotation') or [0, 0, 0]
        trans = np.asarray(obj.get('position') or [0, 0, 0], np.float64)
        rm = euler_matrix(*rot)

        world = (rm @ (verts * scale).T).T + trans

        # 法线要走逆转置，否则非等比缩放会让它歪掉——胶囊被压扁时最明显。
        inv_scale = 1.0 / np.where(np.abs(scale) < 1e-9, 1e-9, scale)
        wn = (rm @ (normals * inv_scale).T).T
        ln = np.linalg.norm(wn, axis=1, keepdims=True)
        wn = wn / np.where(ln < 1e-12, 1.0, ln)

        color = hex_rgb(semantic_colors.get(obj.get('semantic')))
        pos_parts.append(world[faces])
        nrm_parts.append(wn[faces])
        col_parts.append(np.tile(color, (len(faces), 1)))

    if not pos_parts:
        empty3 = np.zeros((0, 3, 3), np.float64)
        return empty3, empty3, np.zeros((0, 3), np.float64)

    return (
        np.concatenate(pos_parts).astype(np.float64),
        np.concatenate(nrm_parts).astype(np.float64),
        np.concatenate(col_parts).astype(np.float64),
    )


def grid_triangles(half=GRID_HALF, step=1.0, width=GRID_WIDTH, y=GRID_Y):
    """地面网格。只给预览用——它不是场景的一部分，NEVER 混进 clay / seg 快照。"""
    pos, nrm = [], []
    hw = width / 2
    n = int(half / step)
    for i in range(-n, n + 1):
        c = i * step
        for a, b, c0, c1 in (
            ((-half, y, c - hw), (half, y, c - hw), (half, y, c + hw), (-half, y, c + hw)),
            ((c - hw, y, -half), (c - hw, y, half), (c + hw, y, half), (c + hw, y, -half)),
        ):
            pos.append([a, b, c0])
            pos.append([a, c0, c1])
            nrm.append([(0, 1, 0)] * 3)
            nrm.append([(0, 1, 0)] * 3)
    return np.array(pos, np.float64), np.array(nrm, np.float64)


# --- 光栅化 -------------------------------------------------------------


class Target:
    """颜色 + 深度缓冲。深度存 1/z（近大远小），因为只有 1/z 在屏幕空间线性。"""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.color = np.zeros((h, w, 3), np.float64)
        self.invz = np.zeros((h, w), np.float64)


def clip_near(tri_pos_view, tri_nrm):
    """按近平面裁剪一个三角形，返回若干个三角形。

    不裁的话，相机后面的顶点做透视除法会把三角形甩到画面另一头，
    出来是一条横贯全屏的怪影——人退后一步就会看到，必须处理。
    """
    inside = [i for i in range(3) if tri_pos_view[i][2] <= -NEAR]
    if len(inside) == 3:
        return [(tri_pos_view, tri_nrm)]
    if not inside:
        return []

    poly_p, poly_n = [], []
    for i in range(3):
        j = (i + 1) % 3
        pi, pj = tri_pos_view[i], tri_pos_view[j]
        ni, nj = tri_nrm[i], tri_nrm[j]
        in_i, in_j = pi[2] <= -NEAR, pj[2] <= -NEAR
        if in_i:
            poly_p.append(pi)
            poly_n.append(ni)
        if in_i != in_j:
            t = (-NEAR - pi[2]) / (pj[2] - pi[2])
            poly_p.append(pi + t * (pj - pi))
            poly_n.append(ni + t * (nj - ni))

    out = []
    for i in range(1, len(poly_p) - 1):
        out.append((
            np.array([poly_p[0], poly_p[i], poly_p[i + 1]]),
            np.array([poly_n[0], poly_n[i], poly_n[i + 1]]),
        ))
    return out


def raster(target, tris_view, tris_nrm, shade, fov_deg, ss=1):
    """把视图空间的三角形画进缓冲。shade(normals, count) 返回 (count,3) 的 0-1 颜色。"""
    w, h = target.w, target.h
    aspect = w / h
    fscale = 1.0 / math.tan(fov_deg * DEG / 2)

    for tp, tn in zip(tris_view, tris_nrm):
        for cp, cn in clip_near(tp, tn):
            z = -cp[:, 2]
            invz = 1.0 / z
            ndc_x = (fscale / aspect) * cp[:, 0] * invz
            ndc_y = fscale * cp[:, 1] * invz
            sx = (ndc_x * 0.5 + 0.5) * w
            sy = (0.5 - ndc_y * 0.5) * h

            x0 = max(int(math.floor(sx.min())), 0)
            x1 = min(int(math.ceil(sx.max())) + 1, w)
            y0 = max(int(math.floor(sy.min())), 0)
            y1 = min(int(math.ceil(sy.max())) + 1, h)
            if x0 >= x1 or y0 >= y1:
                continue

            area = (sx[1] - sx[0]) * (sy[2] - sy[0]) - (sx[2] - sx[0]) * (sy[1] - sy[0])
            if abs(area) < 1e-12:
                continue

            px = np.arange(x0, x1, dtype=np.float64)[None, :] + 0.5
            py = np.arange(y0, y1, dtype=np.float64)[:, None] + 0.5

            w0 = ((sx[1] - sx[0]) * (py - sy[0]) - (px - sx[0]) * (sy[1] - sy[0])) / area
            w1 = ((px - sx[0]) * (sy[2] - sy[0]) - (sx[2] - sx[0]) * (py - sy[0])) / area
            l0 = 1.0 - w0 - w1
            l1, l2 = w1, w0

            inside = (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
            if not inside.any():
                continue

            invz_p = l0 * invz[0] + l1 * invz[1] + l2 * invz[2]
            tile = target.invz[y0:y1, x0:x1]
            mask = inside & (invz_p > tile)
            if not mask.any():
                continue

            idx = np.nonzero(mask)
            iz = invz_p[idx]
            tile[idx] = iz

            # 法线要做透视校正：先按 n/z 插值再除回来，否则斜面上的明暗会歪。
            nrm = (
                l0[idx][:, None] * cn[0] * invz[0]
                + l1[idx][:, None] * cn[1] * invz[1]
                + l2[idx][:, None] * cn[2] * invz[2]
            ) / iz[:, None]
            ln = np.linalg.norm(nrm, axis=1, keepdims=True)
            nrm = nrm / np.where(ln < 1e-12, 1.0, ln)

            sub = target.color[y0:y1, x0:x1]
            sub[idx] = shade(nrm, len(iz))


# --- 三个通道 -----------------------------------------------------------


SUN_DIR = np.array([0.45, 0.82, 0.36])
SUN_DIR = SUN_DIR / np.linalg.norm(SUN_DIR)

# 半球光的天与地。地这一头**不能压太暗**：白膜要的是柔光下的形体，
# 背光面一旦掉进近黑，模型读到的就不是「这里是个盒子的侧面」而是「这里有个黑洞」。
SKY = np.array([1.00, 1.00, 1.00])
GROUND = np.array([0.55, 0.56, 0.60])
AMBIENT_GAIN = 0.55
SUN_GAIN = 0.50


def clay_shader():
    """白色 Lambert + 半球光 + 一盏主方向光。交代形体和透视，不交代材质。

    法线走的是**世界空间**，光也定义在世界空间——半球光的上下必须跟着世界的上下，
    跟着相机走的话，人转一圈机位，物体的明暗会跟着转，形体反而读不出来了。
    """

    def shade(nrm, count):
        hemi = 0.5 * nrm[:, 1:2] + 0.5
        ambient = GROUND + (SKY - GROUND) * hemi
        diffuse = np.clip(nrm @ SUN_DIR, 0.0, 1.0)[:, None]
        return np.clip(AMBIENT_GAIN * ambient + SUN_GAIN * diffuse, 0.0, 1.0)

    return shade


def face_forward(pos_view, nrm_world, view_matrix):
    """把背朝相机的三角形法线翻过来。

    薄板（地面、墙）只有一层皮，从背面看过去若不翻，整块会掉成背光的死色。
    判定放在三角形这一级：视图空间里从三角形指向相机的方向，与它的法线同向即为正面。
    """
    if len(pos_view) == 0:
        return nrm_world
    rot = view_matrix[:3, :3]
    nrm_view = nrm_world @ rot.T
    to_eye = -pos_view.mean(axis=1)                 # 相机在视图空间的原点
    facing = (nrm_view.mean(axis=1) * to_eye).sum(axis=1) >= 0
    return np.where(facing[:, None, None], nrm_world, -nrm_world)


def flat_shader(rgb01):
    def shade(nrm, count):
        return np.tile(rgb01, (count, 1))
    return shade


def encode(target, bg):
    img = target.color.copy()
    img[target.invz <= 0] = np.asarray(bg, np.float64) / 255.0
    return np.rint(np.clip(img, 0, 1) * 255).astype(np.uint8)


def depth_image(target):
    hit = target.invz > 0
    out = np.zeros((target.h, target.w), np.float64)
    if hit.any():
        dist = np.zeros_like(out)
        dist[hit] = 1.0 / target.invz[hit]
        lo, hi = dist[hit].min(), dist[hit].max()
        span = max(hi - lo, 1e-6)
        out[hit] = 1.0 - (dist[hit] - lo) / span      # 近白远黑
    rgb = np.repeat((out * 255).astype(np.uint8)[:, :, None], 3, axis=2)
    rgb[~hit] = np.asarray(BG_DEPTH, np.uint8)
    return rgb


def to_view(tris, view_matrix):
    if len(tris) == 0:
        return tris
    flat = tris.reshape(-1, 3)
    homo = np.concatenate([flat, np.ones((len(flat), 1))], axis=1)
    return (homo @ view_matrix.T)[:, :3].reshape(tris.shape)


def render_view(scene, semantic_colors, view, width, height, supersample=1):
    """渲染一张图，返回 HxWx3 的 uint8。"""
    cam = scene.get('camera') or {}
    eye = cam.get('position') or [6, 4, 8]
    target_pt = cam.get('target') or [0, 0.8, 0]
    fov = float(cam.get('fov') or 40)

    # seg 一旦超采样，边缘就会混出色卡上没有的中间色，图例里那句
    # 「#E74C3C 红色 = 人物」立刻失真。这里强制关掉，别改。
    ss = 1 if view == 'seg' else max(1, int(supersample))
    w, h = width * ss, height * ss

    vm = look_at(eye, target_pt)
    pos, nrm, col = collect_triangles(scene, semantic_colors)
    pos_v = to_view(pos, vm)
    nrm = face_forward(pos_v, nrm, vm)

    tgt = Target(w, h)

    if view == 'preview':
        gpos, gnrm = grid_triangles()
        raster(tgt, to_view(gpos, vm), gnrm, flat_shader(np.asarray(GRID_COLOR) / 255.0), fov)

    if view == 'seg':
        # 按物体分组画，每组一个纯色。颜色直接按 /255 给，取整回来是逐位原值。
        start = 0
        while start < len(pos_v):
            end = start
            while end < len(pos_v) and np.array_equal(col[end], col[start]):
                end += 1
            raster(tgt, pos_v[start:end], nrm[start:end], flat_shader(col[start] / 255.0), fov)
            start = end
    else:
        raster(tgt, pos_v, nrm, clay_shader(), fov)

    if view == 'depth':
        img = depth_image(tgt)
    elif view == 'seg':
        img = encode(tgt, BG_SEG)
    else:
        img = encode(tgt, BG_CLAY)

    if ss > 1:
        img = np.asarray(
            Image.fromarray(img).resize((width, height), Image.LANCZOS), np.uint8
        )
    return img


def render_to_file(scene, semantic_colors, view, width, height, path, supersample=1):
    img = render_view(scene, semantic_colors, view, width, height, supersample)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img).save(path)
    return path


def main():
    """独立跑：render.py <scene.json> <view> <out.png> [width] [height]"""
    if len(sys.argv) < 4:
        print('用法: render.py <scene.json> <clay|seg|depth|preview> <out.png> [宽] [高]')
        sys.exit(1)

    scene = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    view = sys.argv[2]
    out = sys.argv[3]
    canvas = scene.get('canvas') or {}
    width = int(sys.argv[4]) if len(sys.argv) > 4 else int(canvas.get('width') or 1280)
    height = int(sys.argv[5]) if len(sys.argv) > 5 else int(canvas.get('height') or 720)

    # 色卡的唯一真值在 recipe.py。这里 import 过来而不是抄一份，
    # 抄出来的那份一旦漂移，seg 图和图例文字就会各说各话。
    sys.path.insert(0, str(Path(__file__).parent))
    from recipe import SEMANTICS
    colors = {s['key']: s['color'] for s in SEMANTICS}

    render_to_file(scene, colors, view, width, height, out, supersample=2)
    print(json.dumps({'success': True, 'path': out, 'view': view,
                      'width': width, 'height': height}, ensure_ascii=False))


if __name__ == '__main__':
    main()
