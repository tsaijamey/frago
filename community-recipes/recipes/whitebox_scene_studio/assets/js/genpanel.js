/* 右侧生图台：参考图槽、提示词、图例、结果、对比滑杆。
 *
 * 这一侧的产品要点是**图例不能做成摆设**。白膜图告诉模型「这里立着一个东西」，
 * 只有图例告诉它「那个东西是人，而且是打伞的女人」。所以图例默认展开可见、
 * 可编辑，并且明说它会被拼在提示词前面——人得看得见自己在对模型说什么。
 */

import * as PD from './promptdraft.js';

export function createGenPanel(opts) {
  const { root, api, getScene, onStatus, ensureSaved, getProject, catalog } = opts;
  // 每个请求都带上页面此刻显示的那个项目，NEVER 让它落到服务端的 active 上——
  // 人切了项目而请求还在路上时，两者可以是不同的东西。
  const proj = () => (getProject ? getProject() : undefined);
  const flush = ensureSaved || (async () => {});

  const el = (id) => root.querySelector(`#${id}`);

  const state = {
    legend: '',
    legendEdited: false,
    busy: false,
    lastClay: null,
    results: [],
    compareUrl: null,
  };

  // --- 图例 ---

  /* 图例是从场景推出来的，场景一变就该跟着变——但人手改过就不能覆盖。
     所以改动来了不是二选一，而是第三种做法：照旧显示他写的那份，
     上面挂一条「场景已变，图例可能过时了」，点了才换。
     直接覆盖会把人写了半天的东西冲掉；完全不提示，他会拿着一份过时的图例去出图。 */
  function applyLegend(fresh, sceneVersion) {
    state.legend = fresh || '';
    // 图例是自动生成的，人得看得见它有多新、覆盖了什么——
    // 否则「页面上这段到底是不是当前场景的」只能靠猜，
    // 而猜错的代价是拿一份过时的图例去出图。
    const kinds = (state.legend.match(/#[0-9A-F]{6}/g) || []).length;
    el('legendMeta').textContent = state.legend
      ? `按场景 v${sceneVersion ?? '?'} 自动生成，覆盖 ${kinds} 类语义。会拼在提示词前面发给模型。`
      : '场景是空的，还没有图例。';
    const box = el('legendText');
    if (!state.legendEdited) {
      box.value = state.legend;
      el('legendStale').classList.add('hidden');
      return;
    }
    const stale = box.value.trim() !== state.legend.trim();
    el('legendStale').classList.toggle('hidden', !stale);
  }

  function adoptLegend() {
    el('legendText').value = state.legend;
    state.legendEdited = false;
    el('legendStale').classList.add('hidden');
    el('legendReset').classList.add('hidden');
  }

  el('legendRefresh').addEventListener('click', adoptLegend);

  async function refreshLegend(force) {
    if (state.legendEdited && !force) return;
    try {
      const res = await api.run({ action: 'legend', project: proj() });
      state.legend = res.legend || '';
      adoptLegend();
    } catch (e) {
      onStatus(`图例生成失败：${e.message}`, 'error');
    }
  }

  el('legendText').addEventListener('input', () => {
    state.legendEdited = true;
    el('legendReset').classList.remove('hidden');
    scheduleDraftSave();
  });

  el('legendReset').addEventListener('click', () => refreshLegend(true));

  el('legendToggle').addEventListener('click', () => {
    const box = el('legendBody');
    const hidden = box.classList.toggle('hidden');
    el('legendToggle').textContent = hidden ? '展开' : '收起';
  });

  // --- 参考图槽 ---

  function renderRefs(snapshot) {
    const box = el('refSlots');
    const stamp = (snapshot && snapshot.stamp) || '';
    const views = [
      { key: 'clay', label: '白膜图', hint: stamp ? `渲于 ${stamp}` : '交代体积与透视' },
      { key: 'seg', label: '分割图', hint: stamp ? `渲于 ${stamp}` : '交代哪块是什么' },
    ];
    box.innerHTML = views
      .map((v) => {
        const url = snapshot && snapshot[v.key];
        const body = url
          ? `<img src="${url}?t=${Date.now()}" alt="${v.label}">`
          : '<span class="ref-empty">按「预览参考图」生成</span>';
        return `<div class="ref-slot"><div class="ref-body">${body}</div>
                <div class="ref-meta"><b>${v.label}</b><span>${v.hint}</span></div></div>`;
      })
      .join('');
  }

  el('refreshRefsBtn').addEventListener('click', async () => {
    if (state.busy) return;
    setBusy(true, '正在渲染参考图…');
    try {
      await flush();
      const res = await api.run({ action: 'snapshot', project: proj(), views: ['clay', 'seg'] });
      const stamp = res.meta.stamp;
      state.lastClay = res.clay_rel;
      // snapshot 之后 panel_rev 会变，轮询会把这一格重刷一遍；
      // 这里先就地更新一次，人按了按钮不用等一轮轮询才看见。
      renderRefs({ clay: res.clay_rel, seg: res.seg_rel, stamp });
      onStatus(`参考图已渲染（${res.meta.width}×${res.meta.height}）`);
    } catch (e) {
      onStatus(`渲染参考图失败：${e.message}`, 'error');
    } finally {
      setBusy(false);
    }
  });

  // --- 生成 ---

  function setBusy(on, text) {
    state.busy = on;
    el('generateBtn').disabled = on;
    el('refreshRefsBtn').disabled = on;
    el('genStatus').textContent = text || '';
    el('genStatus').classList.toggle('hidden', !text);
  }



  // --- 草稿：人写到一半的东西属于项目，不属于页面 ---

  /* 提示词框原来不属于任何项目，只是页面上一个临时输入框。
     于是切项目时上一个项目的文字留在那儿——图例元信息写着 A 的场景版本、
     提示词却是 B 的内容，人看到的是一份自相矛盾的界面，而且看不出哪半边是错的。 */
  let draftTimer = null;
  let draftFrozen = false;      // 切项目期间冻住，否则 A 的草稿会被写进 B

  function currentDraft() {
    return {
      prompt: el('promptText').value,
      legend_text: el('legendText').value,
      legend_edited: state.legendEdited,
      size: el('sizeSelect').value,
      count: el('countSelect').value,
    };
  }

  function scheduleDraftSave() {
    if (draftFrozen) return;
    if (draftTimer) clearTimeout(draftTimer);
    draftTimer = setTimeout(async () => {
      draftTimer = null;
      if (draftFrozen) return;
      try {
        await api.run({ action: 'draft_put', project: proj(), draft: currentDraft() });
      } catch (e) {
        console.warn('[whitebox] 存草稿失败', e.message);
      }
    }, 600);
  }

  /* 切项目时整套换过去：正文、标签高亮、图例、出图参数，一个都不许留着上一个的。
     没有草稿的项目就是干净的空框，不是继承上一个项目的。 */
  async function loadDraft(panel) {
    draftFrozen = true;
    if (draftTimer) {
      clearTimeout(draftTimer);
      draftTimer = null;
    }
    try {
      let draft = {};
      try {
        draft = (await api.run({ action: 'draft_get', project: proj() })).draft || {};
      } catch {
        draft = {};
      }

      el('promptText').value = draft.prompt || '';
      el('sizeSelect').value = draft.size || '';
      el('countSelect').value = draft.count || '1';

      // 图例一律以这个项目的 panel 为准；人在这个项目里手改过才用他那份。
      state.legendEdited = Boolean(draft.legend_edited);
      state.legend = (panel && panel.legend) || '';
      el('legendText').value = state.legendEdited && draft.legend_text
        ? draft.legend_text
        : state.legend;
      applyLegend(state.legend, panel && panel.scene_version);

      syncPresetChips();
      el('expandNote').textContent = '';
    } finally {
      draftFrozen = false;
    }
  }

  el('promptText').addEventListener('input', () => {
    syncPresetChips();
    scheduleDraftSave();
  });
  for (const id of ['sizeSelect', 'countSelect']) {
    el(id).addEventListener('change', scheduleDraftSave);
  }

  // --- 帮人写提示词 ---

  /* 预设标签：追加、可取消、组内单选、状态从文本反推。
   *
   * 上一版只能点亮不能取消，人把七个风格全点亮了自己出不来——
   * 而「写实摄影 + 日式漫画 + 水彩 + 油画」拼在一句话里本身就是自相矛盾的。
   * 所以：同一组只能有一个（点第二个自动换掉第一个），再点一次取消，
   * 而且**取消只撤自己拼进去的那一段，NEVER 动他自己写的字**。
   */
  function presetItems() {
    return ((catalog() || {}).promptPresets || []).flatMap((g) =>
      g.items.map((it) => ({ ...it, group: g.group }))
    );
  }

  function togglePreset(item) {
    const box = el('promptText');
    const siblings = presetItems().filter((x) => x.group === item.group);
    box.value = PD.togglePresetText(box.value, item, siblings);
    syncPresetChips();
    scheduleDraftSave();
  }

  /* 高亮完全由正文反推，不另存一份状态。
     人手工把那段话删掉，标签就该自己灭——两份状态迟早对不上，
     而对不上的时候人只能信眼睛看到的那份，也就是正文。 */
  function syncPresetChips() {
    const text = el('promptText').value;
    let any = false;
    for (const chip of el('promptPresets').querySelectorAll('.preset-chip')) {
      const on = PD.hasSegment(text, chip.dataset.text);
      chip.classList.toggle('is-used', on);
      any = any || on;
    }
    el('presetClear').classList.toggle('hidden', !any);
  }

  function renderPresets() {
    const groups = (catalog() || {}).promptPresets || [];
    const box = el('promptPresets');
    box.innerHTML = groups
      .map(
        (g) =>
          `<div class="preset-row"><span class="preset-name">${g.group}</span>` +
          g.items
            .map((it) => `<button type="button" class="preset-chip" data-group="${escapeAttr(g.group)}" data-text="${escapeAttr(it.text)}">${escapeHtml(it.label)}</button>`)
            .join('') +
          '</div>'
      )
      .join('');
    for (const chip of box.querySelectorAll('.preset-chip')) {
      chip.addEventListener('click', () =>
        togglePreset({ group: chip.dataset.group, text: chip.dataset.text })
      );
    }
    syncPresetChips();
  }

  el('presetClear').addEventListener('click', () => {
    el('promptText').value = PD.clearPresetText(el('promptText').value, presetItems());
    syncPresetChips();
    scheduleDraftSave();
    onStatus('已撤掉所有标签拼进来的话，你自己写的字没动');
  });

  el('expandBtn').addEventListener('click', async () => {
    const seed = el('promptText').value.trim();
    if (!seed) {
      onStatus('先写一个题目，哪怕只有四个字——扩写是帮你起头，不是替你想', 'error');
      el('promptText').focus();
      return;
    }
    const btn = el('expandBtn');
    btn.disabled = true;
    const label = btn.textContent;
    btn.textContent = '扩写中…';
    try {
      await flush();
      const res = await api.run({ action: 'expand_prompt', project: proj(), text: seed });
      if (res.ok && res.draft) {
        el('promptText').value = res.draft;
        el('expandNote').textContent = res.note || '这是草稿，随便改';
        syncPresetChips();
        scheduleDraftSave();
        onStatus('已扩写成草稿，随便改');
      } else {
        onStatus(res.text || '扩写没成功', 'error');
      }
    } catch (e) {
      onStatus(`扩写失败：${e.message}`, 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = label;
    }
  });

  function escapeAttr(s) {
    return escapeHtml(s).replace(/'/g, '&#39;');
  }

  // --- 出图前体检 ---

  function renderPreflight(res) {
    const parts = [];
    if (res.geometry && res.geometry.length) {
      parts.push('<b>几何上有这些问题</b><ul>' +
        res.geometry.map((i) => `<li>${escapeHtml(i.message)}</li>`).join('') + '</ul>');
    }
    if (res.prompt_issues && res.prompt_issues.length) {
      parts.push('<b>提示词</b><ul>' +
        res.prompt_issues.map((i) => `<li>${escapeHtml(i.message)}</li>`).join('') + '</ul>');
    }
    el('preflightBody').innerHTML = parts.join('');
    const box = el('preflightBox');
    box.classList.remove('hidden');
    // 这是一个**在问人问题**的地方，而它出现在右栏很靠下的位置。
    // 不主动滚过去的话，人按了「生成」只会看到没反应——
    // 他既不知道被拦住了，也看不到那两个按钮。
    box.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  el('preflightCancel').addEventListener('click', () => {
    el('preflightBox').classList.add('hidden');
    setBusy(false);
  });

  el('generateBtn').addEventListener('click', async () => {
    const prompt = el('promptText').value.trim();
    if (!prompt) {
      onStatus('先写一句提示词——白膜只管构图，材质和细节靠它', 'error');
      el('promptText').focus();
      return;
    }
    const scene = getScene();
    if (!scene.objects.length) {
      onStatus('场景是空的，白膜图没有内容可参考', 'error');
      return;
    }

    // 先体检。上一次的教训很实在：场景整个浮空、提示词只有一个书名，
    // 工具全程一声不吭，四张图的钱花完才发现——而这两件事本来都查得出来。
    setBusy(true, '正在体检…');
    try {
      await flush();
      const pre = await api.run({ action: 'preflight', project: proj(), prompt });
      if (!pre.ok) {
        renderPreflight(pre);
        el('genStatus').textContent = '体检发现问题，选「我先去修」或「照样生成」';
        el('genStatus').classList.remove('hidden');
        el('generateBtn').disabled = false;   // 让他能改完再点
        return;
      }
    } catch (e) {
      // 体检本身挂了不该挡住出图——它是提醒，不是闸门。
      console.warn('[whitebox] 体检失败，跳过', e.message);
    }
    await doGenerate(prompt);
  });

  el('preflightGo').addEventListener('click', async () => {
    el('preflightBox').classList.add('hidden');
    await doGenerate(el('promptText').value.trim());
  });

  async function doGenerate(prompt) {
    setBusy(true, '正在渲染参考图并出图，通常十几秒…');
    try {
      await flush();
      const params = {
        action: 'generate',
        project: proj(),
        prompt,
        size: el('sizeSelect').value,
        n: Number(el('countSelect').value),
      };
      if (state.legendEdited) params.legend = el('legendText').value;

      const res = await api.run(params);
      state.results = res.rel_images || [];
      state.lastClay = res.rel_clay || state.lastClay;
      renderResults();
      onStatus(`出图 ${state.results.length} 张`);
      if (res.errors && res.errors.length) {
        onStatus(`出图 ${state.results.length} 张，另有 ${res.errors.length} 次失败`, 'error');
      }
    } catch (e) {
      onStatus(`生图失败：${e.message}`, 'error');
      el('genStatus').textContent = `失败：${e.message}`;
      el('genStatus').classList.remove('hidden');
      return;
    } finally {
      if (state.busy) setBusy(false);
    }
  }

  // --- 结果：预览 + 下载 ---

  /* 下载走 `<a download>` 直指 data/ 下那张图，**不经后端**。
     这样访客模式（frago recipe expose）下也能下载——访客没有跑 action 的权限，
     任何"点一下、后端打包一下再给你"的做法在那边都是死路。
     同源的静态文件加 download 属性，浏览器自己就存下来了。 */
  function downloadName(url) {
    // data/generated/20260821-040023/1.png → whitebox-20260821-040023-1.png
    const m = /generated\/([^/]+)\/([^/.]+)\.(\w+)$/.exec(url);
    return m ? `whitebox-${m[1]}-${m[2]}.${m[3]}` : `whitebox-${url.split('/').pop()}`;
  }

  function renderResults() {
    const grid = el('resultGrid');
    if (!state.results.length) {
      grid.innerHTML = '<p class="placeholder-hint">还没有出过图。</p>';
      el('compareBox').classList.add('hidden');
      return;
    }
    // 缓存串只加在预览的 img 上。download 的 href NEVER 带 ?t=——
    // 有些浏览器会把整个查询串塞进落盘文件名，存出来就是 1.png?t=1787…
    grid.innerHTML = state.results
      .map(
        (u, i) =>
          `<div class="result-cell">
             <button type="button" class="result-pick" data-url="${u}" title="点击放进下面的对比">
               <img src="${u}?t=${Date.now()}" alt="生成结果 ${i + 1}">
             </button>
             <a class="result-dl" href="${u}" download="${downloadName(u)}"
                title="下载原图 ${downloadName(u)}">下载</a>
           </div>`
      )
      .join('');

    for (const pick of grid.querySelectorAll('.result-pick')) {
      pick.addEventListener('click', () => showCompare(pick.dataset.url));
    }
    // 面板每次刷新都重渲这一格。人挑了第 3 张之后随手挪了个物体，
    // 不该被顶回第 1 张——他会以为自己点错了。
    const keep = state.results.includes(state.compareUrl) ? state.compareUrl : state.results[0];
    showCompare(keep);
  }

  /* 对比滑杆是这个工具的验收方式：生成图叠在白膜图上拉一下，
     构图有没有跟住一眼就看出来了，不用凭感觉说「挺像的」。 */
  function showCompare(url) {
    if (!state.lastClay) return;
    state.compareUrl = url;
    el('compareBox').classList.remove('hidden');
    el('compareBase').src = `${state.lastClay}?t=${Date.now()}`;
    el('compareTop').src = `${url}?t=${Date.now()}`;

    // 把文件名写进按钮文字：人点之前就知道会存下什么。
    const name = downloadName(url);
    const dl = el('compareDownload');
    dl.href = url;
    dl.download = name;
    dl.textContent = `⬇ 下载原图 ${name}`;
    dl.title = `保存到本地：${name}`;

    applyCompare();
  }

  function applyCompare() {
    const v = Number(el('compareRange').value);
    el('compareTopWrap').style.width = `${v}%`;
    el('compareValue').textContent = `${v}%`;
  }

  el('compareRange').addEventListener('input', applyCompare);

  // --- 历史 ---

  async function loadHistory() {
    try {
      const res = await api.run({ action: 'history', project: proj(), limit: 8 });
      const box = el('historyList');
      const entries = (res.entries || []).slice().reverse();
      if (!entries.length) {
        box.innerHTML = '<p class="placeholder-hint">还没有记录。</p>';
        return;
      }
      box.innerHTML = entries
        .map(
          (e) => `<button type="button" class="history-row" data-stamp="${e.stamp}">
            <span class="history-time">${e.created_at.slice(5, 16).replace('T', ' ')}</span>
            <span class="history-prompt">${escapeHtml(e.prompt).slice(0, 40)}</span>
            <span class="history-count">${(e.images || []).length} 张</span></button>`
        )
        .join('');
      for (const row of box.querySelectorAll('.history-row')) {
        row.addEventListener('click', () => {
          const entry = entries.find((x) => x.stamp === row.dataset.stamp);
          if (!entry) return;
          state.results = entry.rel_images || [];
          state.lastClay = `data/snapshots/${entry.snapshot_dir.split('/').pop()}/clay.png`;
          el('promptText').value = entry.prompt || '';
          renderResults();
        });
      }
    } catch (e) {
      onStatus(`读历史失败：${e.message}`, 'error');
    }
  }

  function escapeHtml(s) {
    return String(s || '').replace(/[&<>"]/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])
    );
  }

  el('historyBtn').addEventListener('click', loadHistory);

  /* 右栏的真值就是 panel.json。页面每 800ms 看一眼 state.json 的 panel_rev，
     变了就重拉这一份——所以终端里出的图、改的场景，右栏当场跟着换。

     这是委托方今早报的那个 bug 的修法：原来 restoreLast 优先读发布快照
     （`cfg.public.recent`），那是上一次有人跑 view 时顺手发布的东西，
     读到就 return，磁盘上的最新历史根本不会被看一眼。优先级现在反过来：
     主人侧一律读磁盘，发布快照只服务于调不通 action 的访客。 */
  function applyPanel(panel) {
    if (!panel) return;
    applyLegend(panel.legend, panel.scene_version);

    const snap = panel.snapshot || {};
    if (snap.clay || snap.seg) {
      renderRefs({ clay: snap.clay, seg: snap.seg, stamp: snap.stamp });
    } else {
      renderRefs(null);
    }

    const recent = panel.recent || {};
    if (recent.images && recent.images.length) {
      // NEVER 在这里回填提示词。提示词现在归草稿管，
      // 「只在框是空的时候填」正是上一个项目的文字赖着不走的原因。
      state.results = recent.images;
      state.lastClay = recent.clay || snap.clay || state.lastClay;
      renderResults();
    } else {
      state.results = [];
      renderResults();
    }
  }

  /* 访客侧才读发布快照——他拿不到 apiBase，也读不到项目里的 panel.json 之外的东西。
     顺序不能反，反过来就是今早那个故障。 */
  function applyPublished() {
    const pub = (api.config() || {}).public || {};
    applyLegend(pub.legend || '');
    const recent = pub.recent || {};
    if (recent.images && recent.images.length) {
      if (!el('promptText').value.trim()) el('promptText').value = recent.prompt || '';
      state.results = recent.images;
      state.lastClay = recent.clay;
      renderResults();
      renderRefs({ clay: recent.clay, seg: recent.seg });
    }
  }

  /* 访客模式：能看能下载，不能改。把改的入口收起来，
     而不是留在那里等人点了再报一句「apiBase 是 null」。 */
  function applyReadOnly() {
    const cfg = api.config() || {};
    if (cfg.apiBase && !cfg.readOnly) return false;
    root.classList.add('is-readonly');
    el('legendText').readOnly = true;
    el('promptText').readOnly = true;
    const note = document.createElement('p');
    note.className = 'readonly-note';
    note.textContent = '这是分享出来的只读视图：可以看参考图、拉对比滑杆、下载原图，但不能改场景或重新生成。';
    el('genStatus').insertAdjacentElement('afterend', note);
    return true;
  }

  renderPresets();
  renderRefs(null);
  renderResults();

  return {
    state,
    refreshLegend,
    loadHistory,
    applyPanel,
    applyPublished,
    loadDraft,
    applyReadOnly,
  };
}
