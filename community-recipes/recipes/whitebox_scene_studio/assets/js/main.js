/* 启动、布局、同步：把项目、视口、体块库、指挥台、生图台接在一起。
 *
 * 视口有两个实现，接口一模一样：有 GPU 走 editor3d（实时 WebGL），
 * 没有就走 preview2d（服务端渲染一张图）。选择只在 boot 里发生一次，
 * 下面所有代码都不知道自己拿到的是哪一个——「能不能用」不该取决于有没有显卡。
 *
 * **页面显示的一切，真值都在磁盘上。** 这是这一版的核心：
 * 场景在 projects/<slug>/scene.json，右栏在 panel.json，项目清单在 projects.json，
 * 而 state.json 是这四者的版本号快照。页面每 800ms 只读 state.json，
 * 哪个号变了就重拉哪一份。发布快照（config.public）只服务于调不通 action 的访客。
 *
 * 上一版的故障就出在这条规矩没立住：右栏三块只在 boot 里各读一次，
 * 而且优先读发布快照——于是终端里改了场景、出了图，页面还停在几小时前那一份。
 */

import * as api from './api.js';
import { createPalette } from './palette.js';
import { createGenPanel } from './genpanel.js';

const SAVE_DEBOUNCE_MS = 400;
const POLL_MS = 800;

const el = (id) => document.getElementById(id);

let view = null;        // editor3d 或 preview2d，接口相同
let palette = null;
let genpanel = null;
let catalog = null;

// 自己记的那份版本号。轮询靠它们判断「这次改动是不是别处做的」。
let activeProject = null;
let projects = [];
let knownProjectsRev = -1;
let knownPanelRev = -1;
let knownVersion = 0;

let saveTimer = null;
let saving = false;
let dirty = false;
let switching = false;   // 正在整页切项目，这期间别让轮询插进来

// --- 状态条 ---

function setStatus(text, kind) {
  const box = document.querySelector('.status');
  el('statusText').textContent = text;
  box.classList.toggle('is-live', kind !== 'error');
  box.classList.toggle('is-error', kind === 'error');
}

function setSaveState(text, kind) {
  const dd = el('wSave');
  dd.textContent = text;
  dd.classList.toggle('is-error', kind === 'error');
}

function refreshSceneReadout() {
  el('wScene').textContent = `v${knownVersion} · ${view ? view.objectCount() : 0} 个物体`;
}

function currentProjectName() {
  const p = projects.find((x) => x.slug === activeProject);
  return p ? p.name : activeProject || '—';
}

// --- 回写 ---

function scheduleSave() {
  dirty = true;
  setSaveState('待写入…');
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(flushSave, SAVE_DEBOUNCE_MS);
}

async function flushSave() {
  saveTimer = null;
  if (!dirty) return;
  if (saving) {
    // 上一次还在路上。不能并发发两份整场景——后到的那份不一定是后改的，
    // 版本号会打架。等它回来再排一次。
    scheduleSave();
    return;
  }

  dirty = false;
  saving = true;
  setSaveState('写入中…');
  try {
    const res = await api.run({
      action: 'scene_put',
      project: activeProject,
      scene: view.toScene({ version: knownVersion }),
    });
    knownVersion = res.scene_version;
    refreshSceneReadout();
    noteObjectCount(activeProject, view.objectCount());
    setSaveState(`已保存 v${knownVersion}`);
  } catch (e) {
    dirty = true;   // 没存上就还是脏的，下一次改动或轮询会再试
    setSaveState(`写入失败：${e.message}`, 'error');
    console.error('[whitebox] scene_put 失败', e);
  } finally {
    saving = false;
  }
}

/* 把待写入的改动立刻冲掉。
   snapshot / generate / camera_frame / instruct 读的都是磁盘上的场景，
   人刚拖完就点它们时，那份改动可能还压在 400ms 防抖里——
   不先冲掉，服务端算的是上一版。 */
async function ensureSaved() {
  if (saveTimer) {
    clearTimeout(saveTimer);
    saveTimer = null;
  }
  if (dirty || saving) await flushSave();
}

// 人正在拖东西或者刚改完还没落盘时，不能被外来的场景顶掉。
const busyEditing = () => dirty || saving || saveTimer || (view && view.isBusy());

// --- 轮询：一次看全局 ---

async function poll() {
  if (switching) return;
  let st;
  try {
    st = await api.fetchState();
  } catch (e) {
    // 轮询失败不该刷屏，也不该把人正在编辑的状态改掉。静默重试。
    console.warn('[whitebox] 轮询失败', e.message);
    return;
  }

  if (st.projects_rev !== knownProjectsRev) {
    knownProjectsRev = st.projects_rev;
    await reloadProjectList();
  }

  if (st.active && st.active !== activeProject) {
    await switchToProject(st.active, { announce: true });
    return;                      // 切项目已经把下面这些全刷过一遍了
  }

  if (st.panel_rev !== knownPanelRev) {
    knownPanelRev = st.panel_rev;
    await reloadPanel();
    await reloadAgentLog();
  }

  if (st.scene_version !== knownVersion) {
    if (busyEditing()) return;    // 手还在东西上，等他停下来再说
    try {
      const disk = await api.fetchScene(activeProject);
      knownVersion = disk.version || 0;
      view.loadScene(disk);
      syncControls();
      refreshSceneReadout();
      noteObjectCount(activeProject, view.objectCount());
      setStatus(`外部改动已载入（v${knownVersion} · ${view.objectCount()} 个物体）`);
    } catch (e) {
      console.warn('[whitebox] 重载场景失败', e.message);
    }
  }
}

async function reloadPanel() {
  try {
    genpanel.applyPanel(await api.fetchPanel(activeProject));
  } catch (e) {
    console.warn('[whitebox] 重拉右栏失败', e.message);
  }
}

// --- 项目 ---

async function reloadProjectList() {
  try {
    const reg = await api.fetchProjects();
    projects = reg.projects || [];
    knownProjectsRev = reg.rev;
    renderProjectSelect();
  } catch (e) {
    console.warn('[whitebox] 读项目清单失败', e.message);
  }
}

/* 下拉里的物体数就地更新，不为它多跑一次请求。
   服务端只在项目增删改名时推 projects_rev；物体数变化不推，
   否则人每挪一下东西就要重拉一次清单。但两处数字不能打架——
   页面上「下拉写 0 个、状态条写 3 个」比数字晚一点更让人不安。 */
function noteObjectCount(slug, count) {
  const p = projects.find((x) => x.slug === slug);
  if (p && p.object_count !== count) {
    p.object_count = count;
    renderProjectSelect();
  }
}

function renderProjectSelect() {
  const sel = el('projectSelect');
  sel.innerHTML = projects
    .map(
      (p) =>
        `<option value="${p.slug}"${p.slug === activeProject ? ' selected' : ''}>` +
        `${p.name}（${p.object_count || 0} 个物体）</option>`
    )
    .join('');
  el('wProject').textContent = `${currentProjectName()} · ${activeProject || '—'}`;
  el('projectDeleteBtn').disabled = projects.length <= 1;
}

/* 整页换项目：场景、右栏、指挥记录一起换。
   换到一半被轮询插一脚的话，会出现「视口是 A 的、右栏是 B 的」——
   那正是这次要根治的那类现象，所以整段用 switching 挡住。 */
async function switchToProject(slug, opts = {}) {
  switching = true;
  try {
    activeProject = slug;
    const scene = await api.fetchScene(slug);
    knownVersion = scene.version || 0;
    view.loadScene(scene);
    syncControls();

    let panel = null;
    try {
      panel = await api.fetchPanel(slug);
      knownPanelRev = panel.rev;
      genpanel.applyPanel(panel);
    } catch {
      knownPanelRev = -1;      // 还没同步过就下次轮询再说，不挡着人用
    }
    // 人写到一半的东西也归项目管：提示词、标签、图例、出图参数整套换过去。
    // 没有草稿的项目就是干净的空框，不是继承上一个项目的。
    await genpanel.loadDraft(panel);

    await reloadAgentLog();
    noteObjectCount(slug, view.objectCount());
    renderProjectSelect();
    refreshSceneReadout();
    if (opts.announce) {
      setStatus(`已切到项目「${currentProjectName()}」（${view.objectCount()} 个物体）`);
    }
  } finally {
    switching = false;
  }
}

function wireProjectBar() {
  el('projectSelect').addEventListener('change', async (e) => {
    const slug = e.target.value;
    try {
      await ensureSaved();
      await api.run({ action: 'project_switch', slug });
      await switchToProject(slug, { announce: true });
    } catch (err) {
      setStatus(`切项目失败：${err.message}`, 'error');
      renderProjectSelect();     // 切失败就把下拉复位，别让它显示一个没生效的选项
    }
  });

  el('projectNewBtn').addEventListener('click', async () => {
    const name = window.prompt('新项目叫什么？', '');
    if (!name || !name.trim()) return;
    try {
      await ensureSaved();
      const res = await api.run({ action: 'project_create', name: name.trim() });
      await reloadProjectList();
      await switchToProject(res.slug, { announce: false });
      setStatus(`已建项目「${name.trim()}」，空场景，可以开始摆了`);
    } catch (err) {
      setStatus(`建项目失败：${err.message}`, 'error');
    }
  });

  el('projectRenameBtn').addEventListener('click', async () => {
    const name = window.prompt('改成什么名字？', currentProjectName());
    if (!name || !name.trim()) return;
    try {
      await api.run({ action: 'project_rename', slug: activeProject, name: name.trim() });
      await reloadProjectList();
      renderProjectSelect();
      setStatus(`已改名为「${name.trim()}」`);
    } catch (err) {
      setStatus(`改名失败：${err.message}`, 'error');
    }
  });

  el('projectDeleteBtn').addEventListener('click', async () => {
    if (!window.confirm(`删除项目「${currentProjectName()}」？产物会移进 .trash，不物理删除。`)) return;
    try {
      const res = await api.run({ action: 'project_delete', slug: activeProject });
      await reloadProjectList();
      await switchToProject(res.active, { announce: false });
      setStatus(res.text);
    } catch (err) {
      setStatus(`删除失败：${err.message}`, 'error');
    }
  });
}

// --- 指挥 agent ---

function stepLine(r) {
  return `<li class="${r.success ? '' : 'is-bad'}">${escapeHtml(r.text || r.action)}</li>`;
}

function renderTurn(turn) {
  const said = escapeHtml(turn.instruction || '');
  const results = turn.results || [];
  const bad = turn.error || turn.applied === false;

  let body = '';
  if (results.length) {
    body += `<ul class="agent-steps">${results.map(stepLine).join('')}</ul>`;
  }
  if (turn.summary) body += `<p class="agent-said">${escapeHtml(turn.summary)}</p>`;
  if (turn.error || turn.reason) {
    body += `<p class="agent-reason">${escapeHtml(turn.error || turn.reason)}</p>`;
  }
  if (turn.model_said) {
    body += `<p class="agent-raw">模型原话：${escapeHtml(String(turn.model_said).slice(0, 400))}</p>`;
  }
  return `<div class="agent-turn${bad ? ' is-bad' : ''}">
            <p class="agent-said"><b>你说</b> ${said}</p>${body}
          </div>`;
}

async function reloadAgentLog() {
  const box = el('instructLog');
  try {
    const entries = await api.fetchAgentLog(activeProject, 8);
    if (!entries.length) {
      box.innerHTML = '<p class="agent-empty">还没指挥过。上面写一句试试。</p>';
      return;
    }
    box.innerHTML = entries.slice().reverse().map(renderTurn).join('');
  } catch {
    box.innerHTML = '<p class="agent-empty">还没指挥过。</p>';
  }
}

function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])
  );
}

const INSTRUCT_EXAMPLES = [
  '在车左边两米放个人',
  '把机位压到人眼高度，框住所有人',
  '在人后面四米放一棵树',
  '俯瞰整个场景',
];

function wireInstruct() {
  const btn = el('instructBtn');
  const box = el('instructText');

  // 只填进输入框，不直接发——人得有机会先改一改再让它去做。
  el('instructExamples').innerHTML = INSTRUCT_EXAMPLES
    .map((t) => `<button type="button" class="instruct-eg">${escapeHtml(t)}</button>`)
    .join('');
  for (const chip of el('instructExamples').querySelectorAll('.instruct-eg')) {
    chip.addEventListener('click', () => {
      box.value = chip.textContent;
      box.focus();
    });
  }

  async function send() {
    const text = box.value.trim();
    if (!text) {
      setStatus('先写一句要摆什么，比如「在车左边两米放个人」', 'error');
      box.focus();
      return;
    }

    btn.disabled = true;
    const label = btn.textContent;
    btn.textContent = 'agent 正在摆…';
    setStatus('agent 正在把这句话翻成动作…');
    try {
      await ensureSaved();
      const res = await api.run({ action: 'instruct', project: activeProject, text });

      // 执行完立刻主动拉一次，别干等 800ms 轮询——
      // 人按了按钮就该马上看到画面变，等一下才动会以为没生效又按一次。
      if (res.applied) {
        const disk = await api.fetchScene(activeProject);
        knownVersion = disk.version || 0;
        view.loadScene(disk);
        syncControls();
        refreshSceneReadout();
        box.value = '';
        setStatus(res.summary || '已按你说的调整了场景');
      } else {
        setStatus(res.reason || '这件事做不到', 'error');
      }
      await reloadAgentLog();
    } catch (err) {
      setStatus(`指挥失败：${err.message}`, 'error');
      el('instructLog').insertAdjacentHTML('afterbegin', renderTurn({
        instruction: text, error: err.message, applied: false,
      }));
    } finally {
      btn.disabled = false;
      btn.textContent = label;
    }
  }

  btn.addEventListener('click', send);
  // Cmd/Ctrl + Enter 发送。写完一句还要去够鼠标，节奏会断。
  box.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault();
      send();
    }
  });
}

// --- 控件与视口对齐 ---

function syncControls() {
  el('fovRange').value = String(Math.round(view.state.outFov));
  el('fovValue').textContent = `${Math.round(view.state.outFov)}°`;
  el('frameTag').textContent = view.state.aspect;
  for (const btn of el('aspectButtons').querySelectorAll('button')) {
    btn.classList.toggle('is-active', btn.dataset.aspect === view.state.aspect);
  }
}

function numRow(key, label, obj, step) {
  const v = obj[key];
  return `<div class="insp-vec"><span class="insp-key">${label}</span>${[0, 1, 2]
    .map(
      (i) =>
        `<input type="number" class="insp-num" data-key="${key}" data-axis="${i}"
           step="${step}" value="${Number(v[i]).toFixed(2)}">`
    )
    .join('')}</div>`;
}

function renderInspector(obj) {
  const box = el('inspector');
  if (!obj) {
    box.innerHTML = '<p class="inspector-empty">还没选中任何东西。点画面里的体块可以选中。</p>';
    return;
  }

  const semanticOptions = catalog.semantics
    .map((s) => `<option value="${s.key}"${s.key === obj.semantic ? ' selected' : ''}>${s.label}</option>`)
    .join('');

  box.innerHTML = `
    <div class="insp-row"><span class="insp-key">id</span><span class="insp-val">${obj.id}</span></div>
    <div class="insp-row"><span class="insp-key">形状</span><span class="insp-val">${obj.shape}</span></div>
    <label class="insp-field">
      <span class="insp-key">语义</span>
      <select id="inspSemantic">${semanticOptions}</select>
    </label>
    <label class="insp-field">
      <span class="insp-key">名字</span>
      <input type="text" id="inspLabel" placeholder="例如 打伞的女人"
             value="${(obj.label || '').replace(/"/g, '&quot;')}">
    </label>
    <p class="insp-note">名字会写进给模型的图例——「这块红色是谁」的答案。</p>
    ${numRow('position', '位置', obj, '0.1')}
    ${numRow('rotation', '旋转°', obj, '5')}
    ${numRow('scale', '缩放', obj, '0.1')}
  `;

  el('inspSemantic').addEventListener('change', (e) => {
    view.updateSelected({ semantic: e.target.value });
    renderInspector(view.selected());
  });
  el('inspLabel').addEventListener('input', (e) => {
    view.updateSelected({ label: e.target.value.trim() });
  });

  // 数字输入是两种模式下都在的那条变换通道。没有 gizmo 的时候它是唯一的路，
  // 有 gizmo 的时候它是能精确给数的那条路——agent 走的也是它。
  for (const input of box.querySelectorAll('.insp-num')) {
    input.addEventListener('change', () => {
      const current = view.selected();
      if (!current) return;
      const key = input.dataset.key;
      const axis = Number(input.dataset.axis);
      const next = current[key].slice();
      const parsed = Number(input.value);
      if (!Number.isFinite(parsed)) return;
      next[axis] = key === 'scale' ? Math.max(0.01, parsed) : parsed;
      view.updateSelected({ [key]: next });
    });
  }
}

function setArmBanner(text) {
  const banner = el('armBanner');
  if (!text) {
    banner.classList.add('hidden');
    return;
  }
  banner.textContent = text;
  banner.classList.remove('hidden');
}

// --- 工具条接线 ---

function wireToolbar() {
  const modes = el('gizmoModes');
  modes.addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-mode]');
    if (!btn) return;
    setMode(btn.dataset.mode);
  });

  el('duplicateBtn').addEventListener('click', () => {
    const copy = view.duplicateSelected();
    setStatus(copy ? `已复制出 ${copy.id}` : '先选中一个物体再复制');
  });

  el('deleteBtn').addEventListener('click', () => {
    const id = view.deleteSelected();
    setStatus(id ? `已删除 ${id}` : '先选中一个物体再删除');
  });

  el('clearBtn').addEventListener('click', () => {
    if (!view.objectCount()) return;
    if (!window.confirm(`确定清空「${currentProjectName()}」里的 ${view.objectCount()} 个物体？`)) return;
    view.clear();
    setStatus('场景已清空');
  });

  const groundBtn = el('snapGroundBtn');
  groundBtn.addEventListener('click', () => {
    const on = !groundBtn.classList.contains('is-active');
    groundBtn.classList.toggle('is-active', on);
    view.setSnapGround(on);
    setStatus(on ? '平移时贴住地面' : '可以离地摆放');
  });

  const gridBtn = el('snapGridBtn');
  gridBtn.addEventListener('click', () => {
    const on = !gridBtn.classList.contains('is-active');
    gridBtn.classList.toggle('is-active', on);
    view.setSnapGrid(on);
    setStatus(on ? '按 0.5m / 15° 吸附' : '自由摆放');
  });

  el('reloadBtn').addEventListener('click', async () => {
    await switchToProject(activeProject, { announce: false });
    setStatus(`已重新读取「${currentProjectName()}」v${knownVersion}`);
  });
}

function wireCameraBar() {
  const presetBox = el('cameraPresets');
  for (const p of catalog.cameraPresets) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'tool';
    btn.dataset.preset = p.key;
    btn.textContent = p.label;
    btn.addEventListener('click', () => {
      view.applyPreset(p.key);
      setStatus(`机位切到「${p.label}」`);
    });
    presetBox.appendChild(btn);
  }

  // 取景走服务端 action，前端不留第二份实现。它是一次性命令不是逐帧交互，
  // 一个来回的延迟无所谓，换来的是这份最容易算错的数学只有一个版本。
  el('frameAllBtn').addEventListener('click', async () => {
    try {
      await ensureSaved();
      const res = await api.run({ action: 'camera_frame', project: activeProject, margin: 0.15 });
      const disk = await api.fetchScene(activeProject);
      knownVersion = disk.version || 0;
      view.loadScene(disk);
      syncControls();
      refreshSceneReadout();
      setStatus(res.still_out_of_frame && res.still_out_of_frame.length
        ? `已取景，但还有装不下的：${res.still_out_of_frame.map((i) => i.message).join('；')}`
        : `已框住 ${res.targets.length} 个主体`);
    } catch (e) {
      setStatus(`取景失败：${e.message}`, 'error');
    }
  });

  const fov = el('fovRange');
  fov.addEventListener('input', () => {
    const v = Number(fov.value);
    el('fovValue').textContent = `${v}°`;
    view.setFov(v);
  });

  const aspectBox = el('aspectButtons');
  for (const a of catalog.aspects) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'tool';
    btn.dataset.aspect = a.key;
    btn.textContent = a.key;
    btn.title = `${a.width}×${a.height}`;
    btn.addEventListener('click', () => {
      view.setAspect(a.key);
      syncControls();
      setStatus(`画幅切到 ${a.key}（${a.width}×${a.height}）`);
    });
    aspectBox.appendChild(btn);
  }
}

function wireKeyboard() {
  window.addEventListener('keydown', (e) => {
    // 人正在输入框里打字，键盘就不归快捷键管。
    const t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT')) return;

    if (e.key === 'Delete' || e.key === 'Backspace') {
      const id = view.deleteSelected();
      if (id) {
        e.preventDefault();
        setStatus(`已删除 ${id}`);
      }
    } else if (e.key === 'Escape') {
      palette.disarm();
      view.select(null);
    } else if (e.key === 'g' || e.key === 'G') {
      setMode('translate');
    } else if (e.key === 'r' || e.key === 'R') {
      setMode('rotate');
    } else if (e.key === 's' || e.key === 'S') {
      setMode('scale');
    }
  });
}

function setMode(mode) {
  view.setGizmoMode(mode);
  for (const b of el('gizmoModes').querySelectorAll('button')) {
    b.classList.toggle('is-active', b.dataset.mode === mode);
  }
}

// --- 渲染通道 ---

/* WebGL 探测。无头浏览器（frago desktop 的演员标签就是一个）三个上下文名
   全返回 null，所以这里探到的「没有」是真的没有，不是暂时不可用。 */
function webglAvailable() {
  try {
    const c = document.createElement('canvas');
    return !!(c.getContext('webgl2') || c.getContext('webgl'));
  } catch {
    return false;
  }
}

async function makeView(useWebGL) {
  const common = {
    container: el('viewport'),
    frameEl: el('safeFrame'),
    catalog,
    onChange: scheduleSave,
    onSelect: renderInspector,
    onStatus: setStatus,
  };

  if (useWebGL) {
    const { createEditor } = await import('./editor3d.js');
    el('wRender').textContent = '浏览器 WebGL';
    return createEditor(common);
  }

  const { createPreview } = await import('./preview2d.js');
  el('wRender').textContent = '服务端光栅器';
  el('gizmoModes').classList.add('is-disabled');
  el('renderMode').classList.remove('hidden');
  el('renderMode').innerHTML =
    '这台浏览器没有 GPU，视口用的是<b>服务端渲染</b>：拖动转机位、松手出图，交互略慢但功能完整。<br>' +
    '放置、删除、机位、FOV、画幅、生图都照常可用；精确变换用左侧「选中物体」里的数字框。';
  return createPreview({
    ...common,
    // 场景直接随请求发过去，不等它落盘——否则预览永远慢防抖那一拍。
    requestPreview: (scene) => api.run({ action: 'preview', project: activeProject, scene }),
  });
}

// --- 启动 ---

async function boot() {
  const cfg = await api.loadConfig();

  el('wSlot').textContent = cfg.slot || 'default';
  el('wDataDir').textContent = cfg.dataDir || '（未发布）';

  // 词表正常随页面状态一起下发。页面从没被 view 发布过时它是空的，
  // 那就现向后端要一份——总比顶着一个空调色板开起来强。
  catalog = cfg.catalog;
  if (!catalog || !catalog.semantics) {
    const res = await api.run({ action: 'catalog' });
    catalog = res.catalog;
  }

  view = await makeView(webglAvailable());

  palette = createPalette({
    shapeEl: el('shapeGrid'),
    semanticEl: el('semanticGrid'),
    catalog,
    editor: view,
    onStatus: (text) => {
      setStatus(text);
      setArmBanner(palette && palette.isArmed() ? text : '');
    },
  });

  genpanel = createGenPanel({
    root: el('genPanel'),
    api,
    getScene: () => view.toScene({ version: knownVersion }),
    onStatus: setStatus,
    getProject: () => activeProject,
    catalog: () => catalog,
    ensureSaved,
  });

  const readOnly = genpanel.applyReadOnly();

  if (readOnly) {
    // 访客：调不通任何 action，也读不到项目结构。只认发布快照那一份。
    genpanel.applyPublished();
    setStatus('只读视图：可以看参考图、拉对比滑杆、下载原图');
  } else {
    await reloadProjectList();
    const st = await api.fetchState().catch(() => ({ active: cfg.activeProject }));
    knownProjectsRev = st.projects_rev ?? knownProjectsRev;
    await switchToProject(st.active || cfg.activeProject || projects[0]?.slug, { announce: false });

    wireProjectBar();
    wireInstruct();
    setInterval(poll, POLL_MS);
  }

  wireToolbar();
  wireCameraBar();
  wireKeyboard();

  setSaveState(`已同步 v${knownVersion}`);
  if (!readOnly) {
    setStatus(
      view.objectCount()
        ? `「${currentProjectName()}」已就位：${view.objectCount()} 个物体`
        : `「${currentProjectName()}」是空的——点体块库选一个再点地面，或在左下角说一句话让 agent 去摆`
    );
  }
}

boot().catch((err) => {
  setStatus(`接线断了：${err.message}`, 'error');
  console.error('[whitebox] 启动失败', err);
});
