/* 没有 WebGL 时的视口：服务端渲染一张图，前端只负责显示、点选和框选标记。
 *
 * 它对外的接口跟 editor3d.js 逐个方法对齐，main.js 拿到哪一个都一样用。
 * 差别只在「画」这一步：那边是每帧实时，这边是每次改动后向服务端要一张图。
 *
 * 关键点是**点得准**：人点在图上某处，落位必须落在他以为的地方。
 * 这靠的是前端的反投影跟服务端的投影用同一套公式——都在 scenemath.js 里，
 * 两边各写一套的话，画面看着都对，只有落点会差半米，而且极难查。
 */

import * as SM from './scenemath.js';

const PREVIEW_DEBOUNCE_MS = 220;
const CLICK_SLOP = 4;
const ORBIT_SPEED = 0.35;      // 每像素转多少度
const MIN_ELEV = -80;
const MAX_ELEV = 88;

export function createPreview(opts) {
  const { container, frameEl, catalog, onChange, onSelect, onStatus, requestPreview } = opts;

  const semanticById = {};
  for (const s of catalog.semantics) semanticById[s.key] = s;

  const img = document.createElement('img');
  img.className = 'preview-img';
  img.alt = '服务端渲染的场景预览';
  img.draggable = false;
  container.appendChild(img);

  // 选中框画在 2D canvas 上——2D 上下文不需要 GPU，这台浏览器给得起。
  const overlay = document.createElement('canvas');
  overlay.className = 'preview-overlay';
  container.appendChild(overlay);

  const state = {
    aspect: '16:9',
    outFov: 40,
    snapGrid: false,
    snapGround: true,
    selectedId: null,
    idCounter: 0,
    dragging: false,
    armed: null,
    camera: { position: [6, 4, 8], target: [0, 0.8, 0], fov: 40 },
    objects: [],
    busy: false,
  };

  function aspectPreset() {
    return catalog.aspects.find((a) => a.key === state.aspect) || catalog.aspects[0];
  }

  function aspectRatio() {
    const p = aspectPreset();
    return p.width / p.height;
  }

  function camera() {
    return { position: state.camera.position, target: state.camera.target, fov: state.outFov };
  }

  // --- 布局：图片按画幅比 contain 进容器，overlay 严丝合缝盖在图片上 ---

  function layout() {
    const w = container.clientWidth;
    const h = container.clientHeight;
    if (!w || !h) return;

    const ratio = aspectRatio();
    let fw = w;
    let fh = w / ratio;
    if (fh > h) {
      fh = h;
      fw = h * ratio;
    }
    fw = Math.round(fw * 0.94);
    fh = Math.round(fh * 0.94);

    for (const el of [img, overlay]) {
      el.style.width = `${fw}px`;
      el.style.height = `${fh}px`;
    }
    overlay.width = fw;
    overlay.height = fh;

    // 退化模式下整张图就是出图画幅本身，所以安全框正好贴着图片边缘。
    frameEl.style.width = `${fw}px`;
    frameEl.style.height = `${fh}px`;
    drawOverlay();
  }

  // --- 向服务端要图 ---

  let previewTimer = null;
  let previewInFlight = false;
  let previewAgain = false;

  function schedulePreview() {
    if (previewTimer) clearTimeout(previewTimer);
    previewTimer = setTimeout(runPreview, PREVIEW_DEBOUNCE_MS);
  }

  async function runPreview() {
    previewTimer = null;
    if (previewInFlight) {
      // 上一张还在路上。记一笔，等它回来再补一张，别并发发两个渲染请求。
      previewAgain = true;
      return;
    }
    previewInFlight = true;
    state.busy = true;
    container.classList.add('is-rendering');
    try {
      const res = await requestPreview(toScene({ version: 0 }));
      if (res && res.rel_url) {
        await loadImage(`${res.rel_url}?t=${Date.now()}`);
      }
    } catch (e) {
      if (onStatus) onStatus(`预览渲染失败：${e.message}`, 'error');
    } finally {
      previewInFlight = false;
      state.busy = false;
      container.classList.remove('is-rendering');
      drawOverlay();
      if (previewAgain) {
        previewAgain = false;
        schedulePreview();
      }
    }
  }

  function loadImage(src) {
    return new Promise((resolve) => {
      img.onload = () => resolve(true);
      img.onerror = () => resolve(false);
      img.src = src;
    });
  }

  // --- 选中框 ---

  function drawOverlay() {
    const ctx = overlay.getContext('2d');
    ctx.clearRect(0, 0, overlay.width, overlay.height);
    const obj = selected();
    if (!obj) return;

    const box = SM.objectAABB(obj);
    const cam = camera();
    const ratio = aspectRatio();
    const pts = [];
    for (let i = 0; i < 8; i++) {
      const p = SM.projectPoint(
        [
          i & 1 ? box.max[0] : box.min[0],
          i & 2 ? box.max[1] : box.min[1],
          i & 4 ? box.max[2] : box.min[2],
        ],
        cam,
        ratio
      );
      if (p) pts.push(p);
    }
    if (!pts.length) return;

    const xs = pts.map((p) => ((p[0] * 0.5 + 0.5) * overlay.width));
    const ys = pts.map((p) => ((0.5 - p[1] * 0.5) * overlay.height));
    const x0 = Math.min(...xs), x1 = Math.max(...xs);
    const y0 = Math.min(...ys), y1 = Math.max(...ys);

    ctx.strokeStyle = '#4da3ff';
    ctx.lineWidth = 2;
    ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
    ctx.fillStyle = 'rgba(77,163,255,0.14)';
    ctx.fillRect(x0, y0, x1 - x0, y1 - y0);

    const tag = obj.label || obj.id;
    ctx.font = '12px -apple-system, sans-serif';
    const tw = ctx.measureText(tag).width + 10;
    ctx.fillStyle = '#4da3ff';
    ctx.fillRect(x0, Math.max(0, y0 - 18), tw, 17);
    ctx.fillStyle = '#0b1119';
    ctx.fillText(tag, x0 + 5, Math.max(11, y0 - 5));
  }

  // --- 指针 ---

  function ndcAt(event) {
    const rect = img.getBoundingClientRect();
    if (rect.width < 1 || rect.height < 1) return null;
    return [
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1,
    ];
  }

  function groundAt(event) {
    const ndc = ndcAt(event);
    if (!ndc) return null;
    const hit = SM.groundHit(ndc[0], ndc[1], camera(), aspectRatio());
    if (!hit) return null;
    if (state.snapGrid) {
      hit[0] = Math.round(hit[0] / 0.5) * 0.5;
      hit[2] = Math.round(hit[2] / 0.5) * 0.5;
    }
    return [hit[0], 0, hit[2]];
  }

  /* 拾取：把每个物体的包围盒投到屏幕，看点落在谁里面，取离相机最近的那个。
     比逐三角形求交糙，但在体块场景里够用，而且不用把网格搬到前端来。 */
  function pickAt(event) {
    const ndc = ndcAt(event);
    if (!ndc) return null;
    const cam = camera();
    const ratio = aspectRatio();
    let best = null;
    let bestDist = Infinity;

    for (const obj of state.objects) {
      const box = SM.objectAABB(obj);
      const xs = [], ys = [];
      for (let i = 0; i < 8; i++) {
        const p = SM.projectPoint(
          [
            i & 1 ? box.max[0] : box.min[0],
            i & 2 ? box.max[1] : box.min[1],
            i & 4 ? box.max[2] : box.min[2],
          ],
          cam,
          ratio
        );
        if (p) { xs.push(p[0]); ys.push(p[1]); }
      }
      if (!xs.length) continue;
      if (ndc[0] < Math.min(...xs) || ndc[0] > Math.max(...xs)) continue;
      if (ndc[1] < Math.min(...ys) || ndc[1] > Math.max(...ys)) continue;

      const c = SM.boundsCenter(box);
      const d = Math.hypot(
        c[0] - cam.position[0], c[1] - cam.position[1], c[2] - cam.position[2]
      );
      if (d < bestDist) { bestDist = d; best = obj; }
    }
    return best;
  }

  // --- 轨道：拖的时候不重绘，松手才向服务端要新图 ---

  let downAt = null;
  let orbitFrom = null;

  container.addEventListener('pointerdown', (e) => {
    downAt = { x: e.clientX, y: e.clientY };
    orbitFrom = {
      position: state.camera.position.slice(),
      target: state.camera.target.slice(),
      azimuth: 0,
      elevation: 0,
    };
    container.setPointerCapture(e.pointerId);
  });

  container.addEventListener('pointermove', (e) => {
    if (!downAt || !orbitFrom) return;
    const dx = e.clientX - downAt.x;
    const dy = e.clientY - downAt.y;
    if (Math.hypot(dx, dy) <= CLICK_SLOP) return;

    state.dragging = true;
    orbitFrom.azimuth = -dx * ORBIT_SPEED;
    orbitFrom.elevation = -dy * ORBIT_SPEED;
    container.classList.add('is-orbiting');
    if (onStatus) {
      onStatus(`转动机位 ${Math.round(orbitFrom.azimuth)}° / ${Math.round(orbitFrom.elevation)}°——松手后重绘`);
    }
  });

  container.addEventListener('pointerup', (e) => {
    if (!downAt) return;
    const moved = Math.hypot(e.clientX - downAt.x, e.clientY - downAt.y);
    const orbit = orbitFrom;
    downAt = null;
    orbitFrom = null;
    container.classList.remove('is-orbiting');

    if (moved > CLICK_SLOP && state.dragging) {
      state.dragging = false;
      applyOrbit(orbit.azimuth, orbit.elevation);
      return;
    }
    state.dragging = false;

    if (state.armed) {
      const point = groundAt(e);
      if (!point) {
        // 低机位时画面中心在地平线以上，射线朝天上跑，永远打不到地面。
        // 说清楚该往哪个方向调，别让人以为是点歪了。
        if (onStatus) onStatus('这里在地平线以上，落不到地面——往画面下半部分点，或换个俯视一点的机位', 'error');
        return;
      }
      const obj = addObject({ ...state.armed, position: point });
      select(obj.id);
      emitChange();
      if (onStatus) onStatus(`已放置 ${obj.id}（仍可继续点地面放置，Esc 取消）`);
      return;
    }

    const hit = pickAt(e);
    select(hit ? hit.id : null);
  });

  container.addEventListener('wheel', (e) => {
    e.preventDefault();
    const cam = state.camera;
    const dir = [
      cam.position[0] - cam.target[0],
      cam.position[1] - cam.target[1],
      cam.position[2] - cam.target[2],
    ];
    const factor = e.deltaY > 0 ? 1.12 : 1 / 1.12;
    state.camera.position = [
      cam.target[0] + dir[0] * factor,
      Math.max(0.05, cam.target[1] + dir[1] * factor),
      cam.target[2] + dir[2] * factor,
    ];
    emitChange();
    schedulePreview();
  }, { passive: false });

  function applyOrbit(azimuthDeg, elevationDeg) {
    const cam = state.camera;
    const dx = cam.position[0] - cam.target[0];
    const dy = cam.position[1] - cam.target[1];
    const dz = cam.position[2] - cam.target[2];
    const radius = Math.hypot(dx, dy, dz) || 1;

    let theta = Math.atan2(dx, dz) * (180 / Math.PI) + azimuthDeg;
    let phi = Math.asin(Math.max(-1, Math.min(1, dy / radius))) * (180 / Math.PI) + elevationDeg;
    phi = Math.max(MIN_ELEV, Math.min(MAX_ELEV, phi));

    const t = theta * (Math.PI / 180);
    const p = phi * (Math.PI / 180);
    state.camera.position = [
      cam.target[0] + radius * Math.cos(p) * Math.sin(t),
      cam.target[1] + radius * Math.sin(p),
      cam.target[2] + radius * Math.cos(p) * Math.cos(t),
    ];
    emitChange();
    schedulePreview();
  }

  // 拖放放置：跟点选走同一条落位路径，行为必须一致。
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
    const point = groundAt(e);
    if (!point) return;
    const obj = addObject({ ...spec, position: point });
    select(obj.id);
    emitChange();
    if (onStatus) onStatus(`已放置 ${obj.id}`);
  });

  new ResizeObserver(layout).observe(container);

  // --- 物体 ---

  function nextId() {
    state.idCounter += 1;
    let id = `obj_${state.idCounter}`;
    while (state.objects.some((o) => o.id === id)) {
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

  function addObject(spec) {
    const obj = {
      id: spec.id || nextId(),
      shape: spec.shape,
      semantic: spec.semantic,
      position: (spec.position || [0, 0, 0]).slice(),
      rotation: (spec.rotation || [0, 0, 0]).slice(),
      scale: (spec.scale || defaultScale(spec.shape, spec.semantic)).slice(),
    };
    if (spec.label) obj.label = spec.label;
    state.objects.push(obj);
    return obj;
  }

  function selected() {
    return state.objects.find((o) => o.id === state.selectedId) || null;
  }

  function select(id) {
    state.selectedId = id;
    drawOverlay();
    if (onSelect) onSelect(selected());
  }

  function emitChange() {
    if (onChange) onChange();
    schedulePreview();
    drawOverlay();
  }

  function toScene(base) {
    const preset = aspectPreset();
    return {
      version: (base && base.version) || 0,
      canvas: { aspect: state.aspect, width: preset.width, height: preset.height },
      camera: {
        position: state.camera.position.map(round),
        target: state.camera.target.map(round),
        fov: round(state.outFov),
      },
      objects: state.objects.map((o) => {
        const out = {
          id: o.id,
          shape: o.shape,
          semantic: o.semantic,
          position: o.position.map(round),
          rotation: o.rotation.map(round),
          scale: o.scale.map(round),
        };
        if (o.label) out.label = o.label;
        return out;
      }),
    };
  }

  function round(n) {
    return Math.round(n * 1000) / 1000;
  }

  function loadScene(scene) {
    state.objects = (scene.objects || []).map((o) => ({
      id: o.id,
      shape: o.shape,
      semantic: o.semantic,
      label: o.label,
      position: (o.position || [0, 0, 0]).slice(),
      rotation: (o.rotation || [0, 0, 0]).slice(),
      scale: (o.scale || [1, 1, 1]).slice(),
    }));

    let maxId = 0;
    for (const o of state.objects) {
      const m = /^obj_(\d+)$/.exec(o.id || '');
      if (m) maxId = Math.max(maxId, Number(m[1]));
    }
    state.idCounter = maxId;

    const cam = scene.camera || {};
    if (Array.isArray(cam.position)) state.camera.position = cam.position.slice();
    if (Array.isArray(cam.target)) state.camera.target = cam.target.slice();
    if (typeof cam.fov === 'number') state.outFov = cam.fov;

    const aspect = (scene.canvas || {}).aspect;
    if (aspect && catalog.aspects.some((a) => a.key === aspect)) state.aspect = aspect;

    state.selectedId = null;
    layout();
    schedulePreview();
    if (onSelect) onSelect(null);
  }

  return {
    state,
    mode: 'server',
    loadScene,
    toScene,
    addObject: (spec) => {
      const obj = addObject(spec);
      emitChange();
      return obj;
    },
    getObject: (id) => state.objects.find((o) => o.id === id) || null,
    updateSelected(patch) {
      const obj = selected();
      if (!obj) return null;
      if (patch.label !== undefined) {
        if (patch.label) obj.label = patch.label;
        else delete obj.label;
      }
      if (patch.semantic) obj.semantic = patch.semantic;
      for (const key of ['position', 'rotation', 'scale']) {
        if (Array.isArray(patch[key])) obj[key] = patch[key].slice();
      }
      emitChange();
      return obj;
    },
    deleteSelected() {
      const obj = selected();
      if (!obj) return false;
      state.objects = state.objects.filter((o) => o.id !== obj.id);
      select(null);
      emitChange();
      return obj.id;
    },
    duplicateSelected() {
      const src = selected();
      if (!src) return null;
      const copy = addObject({
        ...src,
        id: null,
        position: [src.position[0] + 1, src.position[1], src.position[2]],
      });
      select(copy.id);
      emitChange();
      return copy;
    },
    select,
    selected,
    clear() {
      state.objects = [];
      select(null);
      emitChange();
    },
    setGizmoMode() {
      // 服务端预览没有 gizmo。变换走检查器里的数字输入框——
      // 那条路在两种模式下都在，agent 用的也是它。
    },
    gizmoMode: () => 'translate',
    setAspect(key) {
      state.aspect = key;
      layout();
      emitChange();
    },
    setFov(value) {
      state.outFov = value;
      emitChange();
    },
    setSnapGrid(on) {
      state.snapGrid = on;
    },
    setSnapGround(on) {
      state.snapGround = on;
    },
    arm(spec) {
      state.armed = spec;
      container.classList.add('is-armed');
    },
    disarm() {
      state.armed = null;
      container.classList.remove('is-armed');
    },
    applyPreset(key) {
      const preset = catalog.cameraPresets.find((p) => p.key === key);
      if (!preset) return;
      const pose = SM.presetPose(preset, SM.framingBounds(state.objects), camera());
      state.camera.position = pose.position;
      state.camera.target = pose.target;
      emitChange();
    },
    refresh: schedulePreview,
    objectCount: () => state.objects.length,
    isBusy: () => state.busy || state.dragging,
  };
}
