/* 前端与服务端共用的那套几何约定，用纯函数写一遍。
 *
 * 这个文件存在的理由：同一套投影现在有三个消费者——WebGL 视口、服务端光栅器、
 * 以及退化模式下「点图上一个点，算出它落在地上哪里」。三处各写一套，
 * 迟早会有一处算出来的位置跟另外两处差半米，而且极难查：画面看着都对，
 * 只有落点不对。所以投影、反投影、包围盒、机位预设都只在这里写一次。
 *
 * 与 render.py 的对应关系是逐行的：look_at / 透视除法 / fov 是竖直角，
 * 改这里必须同步改那里，反之亦然。
 */

const DEG = Math.PI / 180;

/* 每种形状的单位体包围盒，与 editor3d.js 的 unitGeometry、render.py 的
   unit_mesh 三处一致：y 从 0 到 1，底面中心即原点。胶囊天生窄一圈。 */
export const UNIT_BOUNDS = {
  box: { min: [-0.5, 0, -0.5], max: [0.5, 1, 0.5] },
  sphere: { min: [-0.5, 0, -0.5], max: [0.5, 1, 0.5] },
  cylinder: { min: [-0.5, 0, -0.5], max: [0.5, 1, 0.5] },
  cone: { min: [-0.5, 0, -0.5], max: [0.5, 1, 0.5] },
  capsule: { min: [-0.25, 0, -0.25], max: [0.25, 1, 0.25] },
  plane: { min: [-0.5, 0, -0.5], max: [0.5, 0.02, 0.5] },
  stairs: { min: [-0.5, 0, -0.5], max: [0.5, 1, 0.5] },
};

// --- 向量小工具 ---

const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const mul = (a, s) => [a[0] * s, a[1] * s, a[2] * s];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
];
const len = (a) => Math.hypot(a[0], a[1], a[2]);
function norm(a) {
  const l = len(a);
  return l > 1e-9 ? mul(a, 1 / l) : [0, 0, 1];
}

/* three.js 默认 XYZ 欧拉序：R = Rx·Ry·Rz。入参是度数，跟 scene.json 一致。 */
export function eulerMatrix(rxDeg, ryDeg, rzDeg) {
  const a = Math.cos(rxDeg * DEG), b = Math.sin(rxDeg * DEG);
  const c = Math.cos(ryDeg * DEG), d = Math.sin(ryDeg * DEG);
  const e = Math.cos(rzDeg * DEG), f = Math.sin(rzDeg * DEG);
  return [
    [c * e, -c * f, d],
    [a * f + b * e * d, a * e - b * f * d, -b * c],
    [b * f - a * e * d, b * e + a * f * d, a * c],
  ];
}

const applyM = (m, v) => [
  m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
  m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
  m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
];

/* 一个物体的世界包围盒：把单位体的 8 个角点缩放、旋转、平移后取极值。
   旋转过的物体这么算会比真实包围盒松一点，用来定机位足够，也不会把东西框漏。 */
export function objectAABB(obj) {
  const u = UNIT_BOUNDS[obj.shape] || UNIT_BOUNDS.box;
  const s = obj.scale || [1, 1, 1];
  const m = eulerMatrix(...(obj.rotation || [0, 0, 0]));
  const p = obj.position || [0, 0, 0];

  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < 8; i++) {
    const corner = [
      (i & 1 ? u.max[0] : u.min[0]) * s[0],
      (i & 2 ? u.max[1] : u.min[1]) * s[1],
      (i & 4 ? u.max[2] : u.min[2]) * s[2],
    ];
    const w = add(applyM(m, corner), p);
    for (let k = 0; k < 3; k++) {
      if (w[k] < min[k]) min[k] = w[k];
      if (w[k] > max[k]) max[k] = w[k];
    }
  }
  return { min, max };
}

/* 整个场景的包围盒。空场景给一个人站在原点大小的默认框，
   免得后面除以 0，也免得预设机位把相机放到无穷远。 */
export function sceneBounds(objects) {
  if (!objects || !objects.length) {
    return { min: [-2, 0, -2], max: [2, 1.8, 2] };
  }
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  for (const o of objects) {
    const b = objectAABB(o);
    for (let k = 0; k < 3; k++) {
      if (b.min[k] < min[k]) min[k] = b.min[k];
      if (b.max[k] > max[k]) max[k] = b.max[k];
    }
  }
  return { min, max };
}

/* 定机位用的包围盒：把地面和水面排除在外。
   它们动辄铺 40×40 米，算进去会把包围盒半径撑到几十米，
   机位于是退到几十米开外——画面里人和车缩成两个点，看着像相机坏了。
   取景要框的是主体，不是脚下那块地。全是地面时才退回按全部算。 */
const SURFACE_SEMANTICS = new Set(['ground', 'water']);

export function framingBounds(objects) {
  const subjects = (objects || []).filter((o) => !SURFACE_SEMANTICS.has(o.semantic));
  return sceneBounds(subjects.length ? subjects : objects);
}

export function boundsCenter(b) {
  return [(b.min[0] + b.max[0]) / 2, (b.min[1] + b.max[1]) / 2, (b.min[2] + b.max[2]) / 2];
}

export function boundsRadius(b) {
  const size = sub(b.max, b.min);
  return Math.max(2, len(size) / 2);
}

/* 相机基向量。与 render.py 的 look_at 同一份推导，包括那条退化保护：
   正俯视时视线与 up 共线，叉积为零，得换一根参考轴，否则画面会翻。 */
export function cameraBasis(camera) {
  const eye = camera.position;
  const fwd = norm(sub(camera.target, eye));
  let up = [0, 1, 0];
  let side = cross(fwd, up);
  if (len(side) < 1e-6) {
    up = [0, 0, -1];
    side = cross(fwd, up);
  }
  side = norm(side);
  const trueUp = cross(side, fwd);
  return { eye, fwd, side, trueUp };
}

/* 屏幕上的一点打到地面 y=0 上的世界坐标。
   ndc 是 [-1,1]，右手为 +x、上为 +y。打不到（射线朝上或平行）时返回 null。 */
export function groundHit(ndcX, ndcY, camera, aspect) {
  const { eye, fwd, side, trueUp } = cameraBasis(camera);
  const fscale = 1 / Math.tan((camera.fov * DEG) / 2);
  const dir = norm(
    add(add(mul(side, (ndcX * aspect) / fscale), mul(trueUp, ndcY / fscale)), fwd)
  );
  if (Math.abs(dir[1]) < 1e-6) return null;
  const t = -eye[1] / dir[1];
  if (t <= 0) return null;
  return add(eye, mul(dir, t));
}

/* 世界点投到 ndc。相机背后的点返回 null——不判这一下，
   身后的东西会以镜像的位置出现在画面里。 */
export function projectPoint(world, camera, aspect, near = 0.05) {
  const { eye, fwd, side, trueUp } = cameraBasis(camera);
  const rel = sub(world, eye);
  const zv = -dot(rel, fwd);
  if (zv > -near) return null;
  const fscale = 1 / Math.tan((camera.fov * DEG) / 2);
  return [
    ((fscale / aspect) * dot(rel, side)) / -zv,
    (fscale * dot(rel, trueUp)) / -zv,
  ];
}

/* 机位预设。换的是机位，不是把视角推倒重来——所以除俯瞰外都保持人当前
   转到的方位角，只改高度和距离。 */
export function presetPose(preset, bounds, camera) {
  const center = boundsCenter(bounds);
  const radius = boundsRadius(bounds);

  if (preset.key === 'top_down') {
    return {
      // 正上方看下去时视线与 up 共线。往 z 上挪一丁点，画面看不出来，
      // 轨道控制和 look_at 都不会翻。
      position: [center[0], Math.max(12, radius * 2.6), center[2] + 0.01],
      target: [center[0], 0, center[2]],
    };
  }

  let dir = [camera.position[0] - camera.target[0], 0, camera.position[2] - camera.target[2]];
  if (dot(dir, dir) < 1e-6) dir = [0, 0, 1];
  dir = norm(dir);
  const dist = Math.max(3.5, radius * 2.4);
  return {
    position: [center[0] + dir[0] * dist, preset.height, center[2] + dir[2] * dist],
    target: [center[0], Math.min(4, Math.max(0.3, center[1])), center[2]],
  };
}

/* 取景（camera_frame）**不在这里实现**。
   它是一次性命令而不是逐帧交互，走服务端 action 就够快，
   于是这份最容易算错的数学只有 scene_ops.py 一个版本——
   前后端各留一份、哪天只改了一边，是这种工具最典型的慢性 bug。 */
