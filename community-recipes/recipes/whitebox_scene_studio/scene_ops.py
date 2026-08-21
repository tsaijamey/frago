"""场景真值的世界空间几何。纯函数、无第三方依赖、可单测。

这个文件是 agent 接口的地基：`place` / `measure` / `validate` / `camera_frame`
说到底都是同一批几何问题——包围盒、相机基、投影、支撑长度。散在 action 里各写一遍，
迟早有一处跟另外几处算得不一样，而且极难发现：每个 action 单看都"有道理"。

三条与前端和 render.py 逐位对齐的约定，改任何一处都要三边一起改：
1. 单位体：y ∈ [0,1]、x/z 在 ±0.5 以内、底面中心即原点（胶囊天生窄一半）。
2. 欧拉角是**度数**，序是 three.js 默认 XYZ，等价 R = Rx·Ry·Rz。
3. 相机 fov 是**竖直**视角，画幅比取 canvas.width / canvas.height。

对应实现：assets/js/editor3d.js 的 unitGeometry、assets/js/scenemath.js、render.py 的 unit_mesh。
"""

import math

DEG = math.pi / 180.0

# --- 单位体 -------------------------------------------------------------

UNIT_BOUNDS = {
    "box": ((-0.5, 0.0, -0.5), (0.5, 1.0, 0.5)),
    "sphere": ((-0.5, 0.0, -0.5), (0.5, 1.0, 0.5)),
    "cylinder": ((-0.5, 0.0, -0.5), (0.5, 1.0, 0.5)),
    "cone": ((-0.5, 0.0, -0.5), (0.5, 1.0, 0.5)),
    "capsule": ((-0.25, 0.0, -0.25), (0.25, 1.0, 0.25)),
    "plane": ((-0.5, 0.0, -0.5), (0.5, 0.02, 0.5)),
    "stairs": ((-0.5, 0.0, -0.5), (0.5, 1.0, 0.5)),
}

# 定机位时要排除的"面"。地面板动辄 40×40 米，算进包围盒会把相机推到几十米外，
# 画面里人和车缩成两个点。取景框的是主体，不是脚下那块地。
SURFACE_SEMANTICS = {"ground", "water"}

# 相机的地面下限。低机位是创作手法，钻到地下不是。
MIN_CAMERA_Y = 0.3


def unit_extent(shape):
    """单位体在三个轴上的跨度。dims ÷ 它 = scale。"""
    lo, hi = UNIT_BOUNDS.get(shape, UNIT_BOUNDS["box"])
    return [hi[i] - lo[i] for i in range(3)]


def dims_to_scale(shape, dims):
    """真实米数 → scale 倍数。

    这层换算是必须的，因为 scale 是倍数不是米数：胶囊的单位体只有 0.5 宽，
    给它 scale.x=0.5 得到的是 0.25 米宽的人，而不是 0.5 米宽的人。
    默认尺寸按米数写、临用时换算，就不会在这上面栽跟头。
    """
    ext = unit_extent(shape)
    return [float(dims[i]) / ext[i] if ext[i] else 1.0 for i in range(3)]


def scale_to_dims(shape, scale):
    """scale 倍数 → 真实米数。报给人和 agent 看的一律用这个。"""
    ext = unit_extent(shape)
    return [float(scale[i]) * ext[i] for i in range(3)]


# --- 向量 ---------------------------------------------------------------


def sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def add(a, b):
    return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]


def mul(a, s):
    return [a[0] * s, a[1] * s, a[2] * s]


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def length(a):
    return math.sqrt(dot(a, a))


def normalize(a, fallback=(0.0, 0.0, 1.0)):
    n = length(a)
    return mul(a, 1.0 / n) if n > 1e-9 else list(fallback)


def euler_matrix(rx, ry, rz):
    """three.js 默认 XYZ 序：R = Rx·Ry·Rz。入参是度数。"""
    a, b = math.cos(rx * DEG), math.sin(rx * DEG)
    c, d = math.cos(ry * DEG), math.sin(ry * DEG)
    e, f = math.cos(rz * DEG), math.sin(rz * DEG)
    return [
        [c * e, -c * f, d],
        [a * f + b * e * d, a * e - b * f * d, -b * c],
        [b * f - a * e * d, b * e + a * f * d, a * c],
    ]


def apply_matrix(m, v):
    return [
        m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
        m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
        m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
    ]


# --- 包围盒 -------------------------------------------------------------


def object_aabb(obj):
    """物体的世界轴对齐包围盒：单位体八个角点缩放、旋转、平移后取极值。

    旋转过的物体这么算比真实包围盒松一点。定机位和判穿模都宁可松——
    松了顶多多留一点余量，紧了会漏判。
    """
    lo, hi = UNIT_BOUNDS.get(obj.get("shape"), UNIT_BOUNDS["box"])
    scale = obj.get("scale") or [1, 1, 1]
    rot = obj.get("rotation") or [0, 0, 0]
    pos = obj.get("position") or [0, 0, 0]
    m = euler_matrix(*rot)

    mins = [float("inf")] * 3
    maxs = [float("-inf")] * 3
    for i in range(8):
        corner = [
            (hi[0] if i & 1 else lo[0]) * scale[0],
            (hi[1] if i & 2 else lo[1]) * scale[1],
            (hi[2] if i & 4 else lo[2]) * scale[2],
        ]
        w = add(apply_matrix(m, corner), pos)
        for k in range(3):
            mins[k] = min(mins[k], w[k])
            maxs[k] = max(maxs[k], w[k])
    return {"min": mins, "max": maxs}


def aabb_center(box):
    return [(box["min"][k] + box["max"][k]) / 2 for k in range(3)]


def aabb_size(box):
    return [box["max"][k] - box["min"][k] for k in range(3)]


def aabb_union(boxes):
    mins = [float("inf")] * 3
    maxs = [float("-inf")] * 3
    for b in boxes:
        for k in range(3):
            mins[k] = min(mins[k], b["min"][k])
            maxs[k] = max(maxs[k], b["max"][k])
    return {"min": mins, "max": maxs}


def aabb_overlap(a, b):
    """三轴上的重叠长度。任何一轴 ≤ 0 就是不相交。"""
    return [
        min(a["max"][k], b["max"][k]) - max(a["min"][k], b["min"][k]) for k in range(3)
    ]


def support_half(box, direction):
    """包围盒沿某方向的"半径"：把三个半跨度投到该方向上取绝对值之和。

    place 用它算两个物体之间的净空——不这么算就只能按中心距离摆，
    而"把人放在车左边 2 米"，人想要的是 2 米空地，不是中心距 2 米
    （车半长 2.3 米，那样人会站在车里）。
    """
    half = [aabb_size(box)[k] / 2 for k in range(3)]
    return sum(abs(direction[k]) * half[k] for k in range(3))


def scene_aabb(objects):
    boxes = [object_aabb(o) for o in objects or []]
    if not boxes:
        return {"min": [-2.0, 0.0, -2.0], "max": [2.0, 1.8, 2.0]}
    return aabb_union(boxes)


def framing_aabb(objects):
    subjects = [o for o in objects or [] if o.get("semantic") not in SURFACE_SEMANTICS]
    return scene_aabb(subjects if subjects else objects)


def bounds_radius(box):
    return max(2.0, length(aabb_size(box)) / 2)


# --- 相机 ---------------------------------------------------------------


def camera_basis(camera):
    """相机的三根轴。与 render.py 的 look_at 同一份推导，含同一条退化保护。"""
    eye = list(camera.get("position") or [6, 4, 8])
    target = list(camera.get("target") or [0, 0.8, 0])
    fwd = normalize(sub(target, eye), (0.0, 0.0, -1.0))

    up = [0.0, 1.0, 0.0]
    side = cross(fwd, up)
    if length(side) < 1e-6:
        # 正俯视：视线与 up 共线，叉积退化。换一根参考轴，画面照样正。
        up = [0.0, 0.0, -1.0]
        side = cross(fwd, up)
    side = normalize(side, (1.0, 0.0, 0.0))
    return eye, fwd, side, cross(side, fwd)


def ground_direction(name, camera):
    """把"左/右/前/后"翻译成世界向量——**按相机此刻的朝向**。

    这是 place 最要紧的一条：人说"放在车左边"，说的是他在画面里看到的左边，
    不是世界坐标的 -X。相机一转，同一句话指的就是另一个方向。
    """
    _eye, fwd, side, _up = camera_basis(camera)
    flat_fwd = normalize([fwd[0], 0.0, fwd[2]], (0.0, 0.0, -1.0))
    flat_side = normalize([side[0], 0.0, side[2]], (1.0, 0.0, 0.0))

    return {
        "right": flat_side,
        "left": mul(flat_side, -1),
        "back": flat_fwd,                  # 更远离相机
        "front": mul(flat_fwd, -1),        # 更靠近相机
        "above": [0.0, 1.0, 0.0],
        "below": [0.0, -1.0, 0.0],
    }.get(name)


def project_point(world, camera, aspect, near=0.05):
    """世界点 → NDC。相机背后返回 None：不判这一下，身后的东西会以镜像位置出现在画面里。"""
    eye, fwd, side, up = camera_basis(camera)
    rel = sub(world, eye)
    zv = -dot(rel, fwd)
    if zv > -near:
        return None
    fscale = 1.0 / math.tan(float(camera.get("fov") or 40) * DEG / 2)
    return [(fscale / aspect) * dot(rel, side) / -zv, fscale * dot(rel, up) / -zv]


def aabb_screen_rect(box, camera, aspect):
    """包围盒投到屏幕上的矩形。返回 (rect, 可见角点数)；一个角点都投不出来时 rect 为 None。"""
    xs, ys, seen = [], [], 0
    for i in range(8):
        p = project_point(
            [
                box["max"][0] if i & 1 else box["min"][0],
                box["max"][1] if i & 2 else box["min"][1],
                box["max"][2] if i & 4 else box["min"][2],
            ],
            camera,
            aspect,
        )
        if p is None:
            continue
        seen += 1
        xs.append(p[0])
        ys.append(p[1])
    if not xs:
        return None, 0
    return (min(xs), min(ys), max(xs), max(ys)), seen


# --- 机位解算 -----------------------------------------------------------


def solve_preset(preset, bounds, camera):
    """预设机位。换的是机位，不是把视角推倒重来——除俯瞰外都保持当前方位角。"""
    center = aabb_center(bounds)
    radius = bounds_radius(bounds)

    if preset.get("key") == "top_down":
        return {
            # 正上方看下去时视线与 up 共线。往 z 上挪一丁点，画面看不出来，
            # look_at 和轨道控制都不会翻。
            "position": [center[0], max(12.0, radius * 2.6), center[2] + 0.01],
            "target": [center[0], 0.0, center[2]],
        }

    pos = camera.get("position") or [6, 4, 8]
    tgt = camera.get("target") or [0, 0.8, 0]
    d = [pos[0] - tgt[0], 0.0, pos[2] - tgt[2]]
    if dot(d, d) < 1e-6:
        d = [0.0, 0.0, 1.0]
    d = normalize(d)
    dist = max(3.5, radius * 2.4)
    return {
        "position": [center[0] + d[0] * dist, float(preset["height"]), center[2] + d[2] * dist],
        "target": [center[0], min(4.0, max(0.3, center[1])), center[2]],
    }


def solve_frame(bounds, camera, aspect, margin=0.12):
    """解出能把 bounds 全框住的机位：保持当前朝向，沿视线后退到刚好装下。

    按包围盒在**相机三根轴上的实际投影**算，不按包围球算。
    包围球对横向铺开的场景太浪费：一条 14 米宽、13 米深、只有 5 米高的街景，
    球半径被宽和深撑到 10 米，于是相机退到 38 米外，主体在画面里缩成一小块。
    真正决定要退多远的是"横向占多宽、纵向占多高"这两件事，各自跟对应的视角比。

    fov 不动。人挑镜头（35mm 还是 85mm）是创作决定，取景不该替他改掉——
    要框更多东西就退后，不是偷偷换个广角。
    """
    center = aabb_center(bounds)

    pos = camera.get("position") or [6, 4, 8]
    away = sub(pos, center)                 # 从中心指向相机的方向，保持人当前的朝向
    if length(away) < 1e-6:
        away = [0.0, 0.4, 1.0]
    away = normalize(away)

    v_fov = float(camera.get("fov") or 40) * DEG
    h_fov = 2 * math.atan(math.tan(v_fov / 2) * aspect)

    def distance_for(direction):
        fwd = mul(direction, -1)
        up0 = [0.0, 1.0, 0.0]
        s = cross(fwd, up0)
        if length(s) < 1e-6:
            up0 = [0.0, 0.0, -1.0]
            s = cross(fwd, up0)
        s = normalize(s, (1.0, 0.0, 0.0))
        u = cross(s, fwd)

        # 逐个角点解「要退多远它才进画框」，取最大值。
        #
        # 不能用「最宽的半跨度」加「最深的半跨度」——那是把最宽的角点和最近的角点
        # 当成同一个点在算，双重保守，结果是主体只占半个画面。
        # 一个角点越靠近相机就越大，所以它自己的深度要从所需距离里减掉。
        need = 1.0
        for i in range(8):
            corner = [
                bounds["max"][0] if i & 1 else bounds["min"][0],
                bounds["max"][1] if i & 2 else bounds["min"][1],
                bounds["max"][2] if i & 4 else bounds["min"][2],
            ]
            rel = sub(corner, center)
            want = max(
                abs(dot(rel, s)) * (1 + margin) / math.tan(h_fov / 2),
                abs(dot(rel, u)) * (1 + margin) / math.tan(v_fov / 2),
            )
            need = max(need, want - dot(rel, fwd))
        return need

    # 相机不能退到地底下。主体越高（一排楼）、人原来的机位越低，
    # 沿原方向退得越远就扎得越深——退到 y=-26 时画面是从地下往上看，
    # 荒谬且不可能是人想要的。压到地面以上，横向朝向保持不变。
    dist = distance_for(away)
    for _ in range(2):
        if center[1] + away[1] * dist >= MIN_CAMERA_Y:
            break
        need_y = max(-0.95, min(0.95, (MIN_CAMERA_Y - center[1]) / dist))
        flat = normalize([away[0], 0.0, away[2]], (0.0, 0.0, 1.0))
        horiz = math.sqrt(max(0.0, 1.0 - need_y * need_y))
        away = normalize([flat[0] * horiz, need_y, flat[2] * horiz])
        dist = distance_for(away)

    position = add(center, mul(away, dist))
    position[1] = max(position[1], MIN_CAMERA_Y)
    return {"position": position, "target": center}


# --- place --------------------------------------------------------------


def solve_placement(ref, proto, direction_name, distance, align, camera):
    """解出新物体的落点。

    proto 是一个 position 在原点的候选物体，用来量它自己的包围盒——
    旋转过的物体包围盒不一定以原点为中心，所以最后要把这个偏移减掉，
    否则"贴着车左边放"会贴歪半个身位。
    """
    d = ground_direction(direction_name, camera)
    if d is None:
        return None, f"不认识的方向：{direction_name}"

    ref_box = object_aabb(ref)
    new_box = object_aabb(proto)
    ref_c = aabb_center(ref_box)
    new_c = aabb_center(new_box)          # proto 在原点时，这就是包围盒中心相对 position 的偏移

    if direction_name in ("above", "below"):
        gap = float(distance)
        note = None
        if direction_name == "above":
            bottom = ref_box["max"][1] + gap
        else:
            bottom = ref_box["min"][1] - gap - aabb_size(new_box)[1]
            # 参照物站在地上时，它下面就是地。照字面算会把东西整个埋进去，
            # 而且埋了看不见——白模上什么都没有，人只会觉得"怎么少了一样东西"。
            # 说「放在他下面」的人，多半想说的是「在他脚边」。落到地面上，并说一声。
            if bottom < 0 and align != "center":
                bottom = 0.0
                note = "参照物是站在地上的，它下面就是地；已把这个东西放到地面上"
        return {
            "position": [
                ref_c[0] - new_c[0],
                bottom - new_box["min"][1],
                ref_c[2] - new_c[2],
            ],
            "gap": gap,
            "note": note,
        }, None

    # 水平方向：按两个包围盒沿该方向的半径 + 净空求中心距，
    # 这样 distance 就是实打实的空地宽度，跟物体多大无关。
    span = support_half(ref_box, d) + float(distance) + support_half(new_box, d)
    target_c = [ref_c[0] + d[0] * span, 0.0, ref_c[2] + d[2] * span]

    if align == "center":
        y = ref_c[1] - new_c[1]
    else:
        y = -new_box["min"][1]            # 最低点贴地；旋转过的物体也照样贴住

    return {
        "position": [target_c[0] - new_c[0], y, target_c[2] - new_c[2]],
        "gap": float(distance),
        "center_distance": span,
    }, None


# --- measure ------------------------------------------------------------


def describe_direction(a_box, b_box, camera, tolerance=0.25):
    """a 相对 b 在哪边——按相机朝向说人话，不说 ±X。

    人问"人在车的哪边"，想听的是"在车的左前方"，不是"Δx = -2.3"。
    坐标是相机一转就变意思的东西，方位词才是他脑子里的那个模型。
    """
    _eye, fwd, side, _up = camera_basis(camera)
    flat_fwd = normalize([fwd[0], 0.0, fwd[2]], (0.0, 0.0, -1.0))
    flat_side = normalize([side[0], 0.0, side[2]], (1.0, 0.0, 0.0))

    delta = sub(aabb_center(a_box), aabb_center(b_box))
    lateral = dot(delta, flat_side)
    depth = dot(delta, flat_fwd)
    vertical = delta[1]

    parts = []
    lr = "aligned"
    if abs(lateral) > tolerance:
        lr = "right" if lateral > 0 else "left"
        parts.append("右" if lateral > 0 else "左")

    fb = "aligned"
    if abs(depth) > tolerance:
        fb = "back" if depth > 0 else "front"
        parts.append("后" if depth > 0 else "前")

    ud = "aligned"
    if abs(vertical) > tolerance:
        ud = "above" if vertical > 0 else "below"

    if parts:
        text = "".join(parts) + "方"
    else:
        text = "几乎重合"
    if ud == "above":
        text += "偏上"
    elif ud == "below":
        text += "偏下"

    return {
        "left_right": lr,
        "front_back": fb,
        "up_down": ud,
        "lateral_m": round(lateral, 3),
        "depth_m": round(depth, 3),
        "vertical_m": round(vertical, 3),
        "text": text,
    }


def surface_gap(a_box, b_box):
    """两个包围盒之间的净空。相交时为负，绝对值是嵌进去多深。"""
    overlap = aabb_overlap(a_box, b_box)
    if all(o > 0 for o in overlap):
        return -min(overlap)
    gaps = [-o for o in overlap if o <= 0]
    return math.sqrt(sum(g * g for g in gaps))


# --- validate -----------------------------------------------------------


def label_of(obj):
    return obj.get("label") or obj.get("id")


def find_issues(scene, aspect, intersect_tolerance=0.05, float_tolerance=0.05):
    """三类问题：穿模、悬空、出画。每条都带 id 和一句人话。

    容差不是可有可无的：贴着放的两个物体本来就会共面，零容差会把每一次
    "把椅子推到桌子边上"都报成穿模，报告一长人就不看了。
    """
    objects = scene.get("objects") or []
    camera = scene.get("camera") or {}
    issues = []

    boxes = {o["id"]: object_aabb(o) for o in objects if o.get("id")}
    by_id = {o["id"]: o for o in objects if o.get("id")}

    # 穿模。地面和水面跳过——所有东西都站在地上，跟它重叠是常态不是问题。
    ids = [o["id"] for o in objects if o.get("id")]
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            if by_id[a].get("semantic") in SURFACE_SEMANTICS:
                continue
            if by_id[b].get("semantic") in SURFACE_SEMANTICS:
                continue
            overlap = aabb_overlap(boxes[a], boxes[b])
            depth = min(overlap)
            if depth > intersect_tolerance:
                issues.append({
                    "kind": "intersect",
                    "ids": [a, b],
                    "depth_m": round(depth, 3),
                    "message": (
                        f"「{label_of(by_id[a])}」和「{label_of(by_id[b])}」穿模了，"
                        f"最浅的一轴也嵌进去 {depth:.2f} 米"
                    ),
                })

    # 悬空：底面离地，且下方没有别的物体托着。
    # 陷地：底面在地平面以下。
    for o in objects:
        oid = o.get("id")
        if not oid or o.get("semantic") in SURFACE_SEMANTICS:
            continue
        box = boxes[oid]
        bottom = box["min"][1]

        # 陷地要单独先判。这一条曾经写在悬空那段的**里面**，
        # 于是永远不可能触发：底面在地下就先被上面那个 continue 拦掉了。
        # 表现是一只埋了半米的行李箱，体检照样报「通过」。
        if bottom < -float_tolerance:
            issues.append({
                "kind": "sunken",
                "ids": [oid],
                "depth_m": round(-bottom, 3),
                "message": f"「{label_of(o)}」陷进地里 {-bottom:.2f} 米，只露出上面一截",
            })
            continue

        if bottom <= float_tolerance:
            continue
        supported = False
        for other in objects:
            if other.get("id") == oid or not other.get("id"):
                continue
            ob = boxes[other["id"]]
            horizontal = (
                min(box["max"][0], ob["max"][0]) > max(box["min"][0], ob["min"][0])
                and min(box["max"][2], ob["max"][2]) > max(box["min"][2], ob["min"][2])
            )
            if horizontal and abs(ob["max"][1] - bottom) <= 0.12:
                supported = True
                break
        if not supported:
            issues.append({
                "kind": "floating",
                "ids": [oid],
                "height_m": round(bottom, 3),
                "message": f"「{label_of(o)}」悬在离地 {bottom:.2f} 米的空中，下面没有东西托着",
            })


    # 出画：包围盒投到屏幕上，跟 [-1,1] 的画框比。
    for o in objects:
        oid = o.get("id")
        if not oid or o.get("semantic") in SURFACE_SEMANTICS:
            continue
        rect, seen = aabb_screen_rect(boxes[oid], camera, aspect)
        if rect is None:
            issues.append({
                "kind": "out_of_frame",
                "ids": [oid],
                "visible_ratio": 0.0,
                "message": f"「{label_of(o)}」整个在相机背后，画面里根本没有它",
            })
            continue
        x0, y0, x1, y1 = rect
        inter_w = max(0.0, min(x1, 1.0) - max(x0, -1.0))
        inter_h = max(0.0, min(y1, 1.0) - max(y0, -1.0))
        area = max((x1 - x0) * (y1 - y0), 1e-9)
        ratio = (inter_w * inter_h) / area
        if ratio <= 0.001:
            issues.append({
                "kind": "out_of_frame",
                "ids": [oid],
                "visible_ratio": 0.0,
                "message": f"「{label_of(o)}」完全在画面外",
            })
        elif ratio < 0.9 or seen < 8:
            issues.append({
                "kind": "partly_out_of_frame",
                "ids": [oid],
                "visible_ratio": round(ratio, 3),
                "message": f"「{label_of(o)}」有 {(1 - ratio) * 100:.0f}% 被画框切掉了",
            })

    return issues
