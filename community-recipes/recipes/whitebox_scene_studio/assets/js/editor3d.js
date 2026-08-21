/* three.js 白膜编辑器：场景、体块、gizmo、相机、取景框。
 *
 * 两条贯穿全文件的约定，改之前先读懂：
 *
 * 1) 每种形状都是一个「单位体」：x/z 落在 ±0.5 以内、y 从 0 到 1，底面中心就是原点。
 *    所以 scene.json 里的 position 直接是贴地点，把 y 设成 0 就是站在地上，
 *    不用再按各自的高度去补一个偏移。代价是 scale 变成倍数而不是米数
 *    ——胶囊天生比方块窄，硬要让 scale 等于米数，同一个数字在不同形状上就是不同的宽度。
 *
 * 2) 相机有两个 FOV，别混。`outFov` 是出图用的，存进 scene.json、也是取景框内的真实视野；
 *    three 相机上挂的那个是渲染用的，比 outFov 大，大出来的部分正好是取景框外面
 *    那圈能看见的余量。取景框一变，渲染 FOV 就得跟着重算，否则框里显示的
 *    不等于将来出的图——这个工具的全部价值就在这个等号上。
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { TransformControls } from 'three/addons/controls/TransformControls.js';
import * as SM from './scenemath.js';

// 取景框占视口的比例。留出的这一圈余量是给人看「画面外还有什么」的，
// 太满就失去了安全框的意义，太空则浪费屏幕。
const FRAME_FILL = 0.86;

const GRID_STEP = 0.5;               // 网格吸附步长，米
const ROTATE_STEP = Math.PI / 12;    // 旋转吸附步长，15°
const SCALE_STEP = 0.1;
const CLICK_SLOP = 4;                // 按下到抬起挪动超过这个像素数就算拖动视角，不算点选

const DEG = Math.PI / 180;

/* --- 单位几何体 -------------------------------------------------------
   都归一到 y ∈ [0,1]、底面中心在原点。建一次复用，别每放一个物体新建一份。 */

export function unitGeometry(shape) {
  switch (shape) {
    case 'box':
      return new THREE.BoxGeometry(1, 1, 1).translate(0, 0.5, 0);
    case 'sphere':
      return new THREE.SphereGeometry(0.5, 32, 16).translate(0, 0.5, 0);
    case 'cylinder':
      return new THREE.CylinderGeometry(0.5, 0.5, 1, 32).translate(0, 0.5, 0);
    case 'cone':
      return new THREE.ConeGeometry(0.5, 1, 32).translate(0, 0.5, 0);
    case 'capsule':
      // 半径 0.25 + 柱身 0.5 = 总高 1。比方块窄，这是胶囊该有的样子。
      return new THREE.CapsuleGeometry(0.25, 0.5, 8, 16).translate(0, 0.5, 0);
    case 'plane':
      // 用薄板而不是 PlaneGeometry：将来 seg / depth 通道要它有厚度才不会被剔掉。
      return new THREE.BoxGeometry(1, 0.02, 1).translate(0, 0.01, 0);
    case 'stairs':
      return stairsGeometry();
    default:
      return new THREE.BoxGeometry(1, 1, 1).translate(0, 0.5, 0);
  }
}

/* 楼梯用挤出的阶梯剖面做，得到的是单一 Mesh。
   拿几个方块拼成 Group 也能看，但后面换材质、拾取、算包围盒都要分头处理。 */
function stairsGeometry() {
  const steps = 5;
  const profile = new THREE.Shape();
  profile.moveTo(0, 0);
  for (let i = 0; i < steps; i++) {
    profile.lineTo(i / steps, (i + 1) / steps);
    profile.lineTo((i + 1) / steps, (i + 1) / steps);
  }
  profile.lineTo(1, 0);
  profile.closePath();
  const geo = new THREE.ExtrudeGeometry(profile, { depth: 1, bevelEnabled: false });
  geo.translate(-0.5, 0, -0.5);
  geo.computeVertexNormals();
  return geo;
}

export function createEditor(opts) {
  const { container, frameEl, catalog, onChange, onSelect, onStatus } = opts;

  const semanticColor = {};
  for (const s of catalog.semantics) semanticColor[s.key] = s.color;

  const geometries = {};
  for (const s of catalog.shapes) geometries[s.key] = unitGeometry(s.key);

  const materials = {};
  function materialFor(semantic) {
    if (!materials[semantic]) {
      materials[semantic] = new THREE.MeshStandardMaterial({
        color: new THREE.Color(semanticColor[semantic] || '#cccccc'),
        roughness: 0.75,
        metalness: 0.0,
      });
    }
    return materials[semantic];
  }

  // --- 场景骨架 ---

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x1b1e24);

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  container.appendChild(renderer.domElement);

  const camera = new THREE.PerspectiveCamera(40, 1, 0.05, 2000);
  camera.position.set(6, 4, 8);

  const orbit = new OrbitControls(camera, renderer.domElement);
  orbit.enableDamping = true;
  orbit.dampingFactor = 0.08;
  orbit.target.set(0, 0.8, 0);

  scene.add(new THREE.HemisphereLight(0xffffff, 0x33383f, 2.0));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(8, 14, 6);
  scene.add(sun);

  const grid = new THREE.GridHelper(120, 240, 0x4a5160, 0x2c313a);
  scene.add(grid);

  // 地面只用来做射线求交，不需要真的存在一块 mesh。
  const groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);

  const objectGroup = new THREE.Group();
  scene.add(objectGroup);

  const selectionBox = new THREE.BoxHelper(undefined, 0x4da3ff);
  selectionBox.visible = false;
  scene.add(selectionBox);

  const gizmo = new TransformControls(camera, renderer.domElement);
  gizmo.setSize(0.9);
  scene.add(gizmo);

  // --- 状态 ---

  const state = {
    aspect: '16:9',
    outFov: 40,
    snapGrid: false,
    snapGround: true,
    selectedId: null,
    idCounter: 0,
    dragging: false,   // gizmo 正在被拖；轮询期间不能把场景换掉
    armed: null,       // 点选放置：{ shape, semantic }
  };

  const meshById = new Map();

  // --- 取景框与两个 FOV ---

  function aspectRatio() {
    const preset = catalog.aspects.find((a) => a.key === state.aspect) || catalog.aspects[0];
    return preset.width / preset.height;
  }

  function layout() {
    const w = container.clientWidth;
    const h = container.clientHeight;
    if (!w || !h) return;

    renderer.setSize(w, h, false);

    // 取景框：按出图画幅在视口里做 contain 适配，再缩到 FRAME_FILL 留出余量。
    const ratio = aspectRatio();
    let fw = w;
    let fh = w / ratio;
    if (fh > h) {
      fh = h;
      fw = h * ratio;
    }
    fw *= FRAME_FILL;
    fh *= FRAME_FILL;

    frameEl.style.width = `${Math.round(fw)}px`;
    frameEl.style.height = `${Math.round(fh)}px`;

    // 渲染 FOV 反推：让取景框内的竖直视野正好等于 outFov。
    // 推导见文件头第 2 条；横向会自动跟着对上，因为两边用的是同一个视口宽高比。
    camera.aspect = w / h;
    const heightFrac = fh / h;
    const renderFov = 2 * Math.atan(Math.tan((state.outFov * DEG) / 2) / heightFrac) / DEG;
    camera.fov = Math.min(179, renderFov);
    camera.updateProjectionMatrix();
  }

  // --- 物体增删改 ---

  function nextId() {
    state.idCounter += 1;
    let id = `obj_${state.idCounter}`;
    while (meshById.has(id)) {
      state.idCounter += 1;
      id = `obj_${state.idCounter}`;
    }
    return id;
  }

  function defaultScale(shape, semantic) {
    const combo = catalog.comboScale[`${semantic}:${shape}`];
    if (combo) return combo.slice();
    const base = catalog.shapeScale[shape];
    return base ? base.slice() : [1, 1, 1];
  }

  function buildMesh(obj) {
    const mesh = new THREE.Mesh(geometries[obj.shape], materialFor(obj.semantic));
    mesh.userData.obj = obj;
    applyToMesh(mesh, obj);
    return mesh;
  }

  function applyToMesh(mesh, obj) {
    mesh.position.fromArray(obj.position);
    // scene.json 里的角度是度数，不是弧度：agent 说「转 90 度」比说 1.5708 顺手得多。
    mesh.rotation.set(obj.rotation[0] * DEG, obj.rotation[1] * DEG, obj.rotation[2] * DEG);
    mesh.scale.fromArray(obj.scale);
  }

  function readFromMesh(mesh) {
    const obj = mesh.userData.obj;
    obj.position = [mesh.position.x, mesh.position.y, mesh.position.z];
    obj.rotation = [mesh.rotation.x / DEG, mesh.rotation.y / DEG, mesh.rotation.z / DEG];
    obj.scale = [
      Math.max(0.01, mesh.scale.x),
      Math.max(0.01, mesh.scale.y),
      Math.max(0.01, mesh.scale.z),
    ];
  }

  function addObject(spec) {
    const shape = spec.shape;
    const semantic = spec.semantic;
    const obj = {
      id: spec.id || nextId(),
      shape,
      semantic,
      position: (spec.position || [0, 0, 0]).slice(),
      rotation: (spec.rotation || [0, 0, 0]).slice(),
      scale: (spec.scale || defaultScale(shape, semantic)).slice(),
    };
    if (spec.label) obj.label = spec.label;

    const mesh = buildMesh(obj);
    objectGroup.add(mesh);
    meshById.set(obj.id, mesh);
    return obj;
  }

  function removeObject(id) {
    const mesh = meshById.get(id);
    if (!mesh) return false;
    if (gizmo.object === mesh) gizmo.detach();
    objectGroup.remove(mesh);
    meshById.delete(id);
    if (state.selectedId === id) select(null);
    return true;
  }

  function clearObjects() {
    gizmo.detach();
    for (const mesh of meshById.values()) objectGroup.remove(mesh);
    meshById.clear();
    select(null);
  }

  // --- 选中 ---

  function select(id) {
    state.selectedId = id;
    const mesh = id ? meshById.get(id) : null;
    if (mesh) {
      gizmo.attach(mesh);
      selectionBox.setFromObject(mesh);
      selectionBox.visible = true;
    } else {
      gizmo.detach();
      selectionBox.visible = false;
    }
    if (onSelect) onSelect(mesh ? mesh.userData.obj : null);
  }

  function refreshSelectionBox() {
    const mesh = state.selectedId ? meshById.get(state.selectedId) : null;
    if (mesh) selectionBox.setFromObject(mesh);
  }

  // --- 指针 ---

  function pointerNDC(event) {
    const rect = renderer.domElement.getBoundingClientRect();
    return new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1
    );
  }

  const raycaster = new THREE.Raycaster();

  function groundPointAt(event) {
    raycaster.setFromCamera(pointerNDC(event), camera);
    const hit = new THREE.Vector3();
    if (!raycaster.ray.intersectPlane(groundPlane, hit)) return null;
    if (state.snapGrid) {
      hit.x = Math.round(hit.x / GRID_STEP) * GRID_STEP;
      hit.z = Math.round(hit.z / GRID_STEP) * GRID_STEP;
    }
    hit.y = 0;
    return hit;
  }

  function pickObject(event) {
    raycaster.setFromCamera(pointerNDC(event), camera);
    const hits = raycaster.intersectObjects(objectGroup.children, false);
    return hits.length ? hits[0].object : null;
  }

  function placeAt(spec, point) {
    if (!point) return null;
    const obj = addObject({ ...spec, position: [point.x, 0, point.z] });
    select(obj.id);
    emitChange();
    return obj;
  }

  // --- 事件 ---

  let downAt = null;

  renderer.domElement.addEventListener('pointerdown', (e) => {
    downAt = { x: e.clientX, y: e.clientY };
  });

  renderer.domElement.addEventListener('pointerup', (e) => {
    if (!downAt) return;
    const moved = Math.hypot(e.clientX - downAt.x, e.clientY - downAt.y);
    downAt = null;
    // 转视角的时候顺手抬起，不该被当成点选。
    if (moved > CLICK_SLOP) return;
    if (state.dragging) return;

    // armed 状态下点地面就是落位——这是给只会点、不会拖的调用方准备的路径。
    if (state.armed) {
      const obj = placeAt(state.armed, groundPointAt(e));
      if (obj && onStatus) onStatus(`已放置 ${obj.id}（仍可继续点地面放置，Esc 退出）`);
      return;
    }

    const mesh = pickObject(e);
    select(mesh ? mesh.userData.obj.id : null);
  });

  gizmo.addEventListener('dragging-changed', (e) => {
    state.dragging = e.value;
    orbit.enabled = !e.value;
    if (!e.value) emitChange();
  });

  gizmo.addEventListener('objectChange', () => {
    const mesh = gizmo.object;
    if (!mesh) return;
    if (state.snapGround && gizmo.getMode() === 'translate') mesh.position.y = 0;
    readFromMesh(mesh);
    refreshSelectionBox();
    if (onSelect) onSelect(mesh.userData.obj);
  });

  // 拖放放置。dragover 必须 preventDefault，否则浏览器根本不会派发 drop。
  container.addEventListener('dragover', (e) => {
    if (!e.dataTransfer) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
  });

  container.addEventListener('drop', (e) => {
    e.preventDefault();
    let spec;
    try {
      spec = JSON.parse(e.dataTransfer.getData('application/json') || 'null');
    } catch {
      spec = null;
    }
    if (!spec || !spec.shape || !spec.semantic) return;
    const obj = placeAt(spec, groundPointAt(e));
    if (obj && onStatus) onStatus(`已放置 ${obj.id}`);
  });

  const resizeObserver = new ResizeObserver(layout);
  resizeObserver.observe(container);

  // --- 渲染循环 ---

  function tick() {
    orbit.update();
    renderer.render(scene, camera);
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);

  // --- 相机 ---

  /* 机位解算走 scenemath 那一份，跟服务端预览通道共用。
     两条通道各写一套的话，同一个「人眼 1.6m」在有没有 GPU 的机器上会站在不同位置，
     而这个工具的全部意义就是机位可复现。 */
  function applyPreset(key) {
    const preset = catalog.cameraPresets.find((p) => p.key === key);
    if (!preset) return;

    const objects = [...meshById.values()].map((m) => m.userData.obj);
    const pose = SM.presetPose(preset, SM.framingBounds(objects), {
      position: [camera.position.x, camera.position.y, camera.position.z],
      target: [orbit.target.x, orbit.target.y, orbit.target.z],
      fov: state.outFov,
    });

    camera.position.fromArray(pose.position);
    orbit.target.fromArray(pose.target);
    orbit.update();
    emitChange();
  }

  // --- 序列化 ---

  function toScene(base) {
    const objects = [];
    for (const mesh of meshById.values()) {
      const o = mesh.userData.obj;
      const out = {
        id: o.id,
        shape: o.shape,
        semantic: o.semantic,
        position: o.position.map((n) => round(n)),
        rotation: o.rotation.map((n) => round(n)),
        scale: o.scale.map((n) => round(n)),
      };
      if (o.label) out.label = o.label;
      objects.push(out);
    }
    const preset = catalog.aspects.find((a) => a.key === state.aspect) || catalog.aspects[0];
    return {
      version: (base && base.version) || 0,
      canvas: { aspect: state.aspect, width: preset.width, height: preset.height },
      camera: {
        position: [round(camera.position.x), round(camera.position.y), round(camera.position.z)],
        target: [round(orbit.target.x), round(orbit.target.y), round(orbit.target.z)],
        fov: round(state.outFov),
      },
      objects,
    };
  }

  function round(n) {
    return Math.round(n * 1000) / 1000;
  }

  function loadScene(scene_) {
    clearObjects();
    let maxId = 0;
    for (const o of scene_.objects || []) {
      addObject(o);
      const m = /^obj_(\d+)$/.exec(o.id || '');
      if (m) maxId = Math.max(maxId, Number(m[1]));
    }
    state.idCounter = maxId;

    const cam = scene_.camera || {};
    if (Array.isArray(cam.position)) camera.position.fromArray(cam.position);
    if (Array.isArray(cam.target)) orbit.target.fromArray(cam.target);
    if (typeof cam.fov === 'number') state.outFov = cam.fov;

    const aspect = (scene_.canvas || {}).aspect;
    if (aspect && catalog.aspects.some((a) => a.key === aspect)) state.aspect = aspect;

    orbit.update();
    layout();
    select(null);
  }

  // --- 对外 ---

  let changeHandle = null;
  function emitChange() {
    if (!onChange) return;
    if (changeHandle) return;   // 一帧内多次改动合成一次通知，防抖交给上层
    changeHandle = requestAnimationFrame(() => {
      changeHandle = null;
      onChange();
    });
  }

  // 相机是人一直在动的东西，每一帧回写会把后端打爆；
  // 交给 OrbitControls 的 end 事件，松手才算一次改动。
  orbit.addEventListener('end', emitChange);

  return {
    state,
    loadScene,
    toScene,
    addObject: (spec) => {
      const obj = addObject(spec);
      emitChange();
      return obj;
    },
    getObject: (id) => {
      const mesh = meshById.get(id);
      return mesh ? mesh.userData.obj : null;
    },
    updateSelected(patch) {
      const mesh = state.selectedId ? meshById.get(state.selectedId) : null;
      if (!mesh) return null;
      const obj = mesh.userData.obj;
      if (patch.label !== undefined) {
        if (patch.label) obj.label = patch.label;
        else delete obj.label;
      }
      if (patch.semantic && patch.semantic !== obj.semantic) {
        obj.semantic = patch.semantic;
        mesh.material = materialFor(patch.semantic);
      }
      emitChange();
      return obj;
    },
    deleteSelected() {
      if (!state.selectedId) return false;
      const id = state.selectedId;
      removeObject(id);
      emitChange();
      return id;
    },
    duplicateSelected() {
      const mesh = state.selectedId ? meshById.get(state.selectedId) : null;
      if (!mesh) return null;
      const src = mesh.userData.obj;
      const copy = addObject({
        shape: src.shape,
        semantic: src.semantic,
        label: src.label,
        position: [src.position[0] + 1, src.position[1], src.position[2]],
        rotation: src.rotation,
        scale: src.scale,
      });
      select(copy.id);
      emitChange();
      return copy;
    },
    select,
    selected: () => {
      const mesh = state.selectedId ? meshById.get(state.selectedId) : null;
      return mesh ? mesh.userData.obj : null;
    },
    clear() {
      clearObjects();
      emitChange();
    },
    setGizmoMode(mode) {
      gizmo.setMode(mode);
    },
    gizmoMode: () => gizmo.getMode(),
    setAspect(key) {
      state.aspect = key;
      layout();
      emitChange();
    },
    setFov(value) {
      state.outFov = value;
      layout();
      emitChange();
    },
    setSnapGrid(on) {
      state.snapGrid = on;
      gizmo.setTranslationSnap(on ? GRID_STEP : null);
      gizmo.setRotationSnap(on ? ROTATE_STEP : null);
      gizmo.setScaleSnap(on ? SCALE_STEP : null);
    },
    setSnapGround(on) {
      state.snapGround = on;
    },
    arm(spec) {
      state.armed = spec;
    },
    disarm() {
      state.armed = null;
    },
    applyPreset,
    objectCount: () => meshById.size,
    isBusy: () => state.dragging,
  };
}
