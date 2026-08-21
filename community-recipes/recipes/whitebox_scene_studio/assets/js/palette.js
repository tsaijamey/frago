/* 体块库与语义色卡。管两件事：选什么、怎么落到地上。
 *
 * 落位有两条路，缺一不可：
 *   拖 —— 人的手感最好，从体块库直接甩到地面上想要的位置。
 *   点 —— 先点体块选中，再点地面落位。这条是给 agent 走的：
 *         驱动页面的一方只会点，不会拖，没有这条路它就用不了这个工具。
 * 两条路最后都汇到 editor.addObject，行为必须一致。
 */

export function createPalette(opts) {
  const { shapeEl, semanticEl, catalog, editor, onStatus } = opts;

  const state = {
    semantic: 'person',
    armedShape: null,
  };

  const semanticById = {};
  for (const s of catalog.semantics) semanticById[s.key] = s;

  // --- 语义色卡 ---

  const semanticButtons = new Map();
  for (const s of catalog.semantics) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'swatch';
    btn.dataset.semantic = s.key;
    btn.title = `${s.label} ${s.color} · ${s.hint}`;
    btn.innerHTML =
      `<span class="swatch-chip" style="background:${s.color}"></span>` +
      `<span class="swatch-label">${s.label}</span>`;
    btn.addEventListener('click', () => {
      setSemantic(s.key);
      // 点了「人物」就该能直接去点地面，不必再想「人该用哪个形状」。
      armShape(catalog.semanticShape[s.key] || 'box');
    });
    semanticEl.appendChild(btn);
    semanticButtons.set(s.key, btn);
  }

  // --- 体块库 ---

  const shapeButtons = new Map();
  for (const sh of catalog.shapes) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'block';
    btn.dataset.shape = sh.key;
    btn.draggable = true;
    btn.title = `${sh.label}：拖到地面，或点这里再点地面`;
    btn.innerHTML =
      `<span class="block-glyph">${sh.glyph}</span>` +
      `<span class="block-label">${sh.label}</span>`;

    btn.addEventListener('click', () => {
      // 再点一次同一个就是取消——armed 是个持续状态，必须给得掉。
      if (state.armedShape === sh.key) disarm();
      else armShape(sh.key);
    });

    btn.addEventListener('dragstart', (e) => {
      e.dataTransfer.effectAllowed = 'copy';
      e.dataTransfer.setData(
        'application/json',
        JSON.stringify({ shape: sh.key, semantic: state.semantic })
      );
    });

    shapeEl.appendChild(btn);
    shapeButtons.set(sh.key, btn);
  }

  // --- 状态迁移 ---

  function paintShapeColors() {
    const color = (semanticById[state.semantic] || {}).color || '#cccccc';
    for (const btn of shapeButtons.values()) {
      btn.style.setProperty('--block-color', color);
    }
  }

  function setSemantic(key) {
    if (!semanticById[key]) return;
    state.semantic = key;
    for (const [k, btn] of semanticButtons) {
      btn.classList.toggle('is-active', k === key);
    }
    paintShapeColors();
  }

  function armShape(shape) {
    state.armedShape = shape;
    for (const [k, btn] of shapeButtons) {
      btn.classList.toggle('is-armed', k === shape);
    }
    editor.arm({ shape, semantic: state.semantic });
    const label = (catalog.shapes.find((s) => s.key === shape) || {}).label || shape;
    const sem = (semanticById[state.semantic] || {}).label || state.semantic;
    if (onStatus) onStatus(`已选中「${sem}·${label}」——点地面落位，Esc 取消`);
  }

  function disarm() {
    state.armedShape = null;
    for (const btn of shapeButtons.values()) btn.classList.remove('is-armed');
    editor.disarm();
    if (onStatus) onStatus('放置已取消');
  }

  setSemantic(state.semantic);

  return {
    state,
    setSemantic,
    armShape,
    disarm,
    isArmed: () => state.armedShape !== null,
    currentSemantic: () => state.semantic,
  };
}
