// frago Knowledge Book — 渲染与交互。数据来自 data.js(全局 DATA)。
const esc = s => s.replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

function subTable(rows) {
  return `<table class="sub">${rows.map(([k,zh,en]) =>
    `<tr><td class="k">${esc(k)}</td><td class="v">${esc(zh)}<div class="ven">${esc(en)}</div></td></tr>`).join('')}</table>`;
}

function cmdCard(c) {
  let inner = '';
  if (c.subgroups) {
    inner = c.subgroups.map(g =>
      `<div class="subgroup-label">${esc(g.zh)} <span class="en">${esc(g.en)}</span></div>${subTable(g.items)}`).join('');
  } else if (c.sub) {
    inner = subTable(c.sub);
  }
  const subCount = c.sub ? c.sub.length : c.subgroups ? c.subgroups.reduce((n,g)=>n+g.items.length,0) : 0;
  const badge = subCount ? `<span class="badge">${subCount} 子命令</span>` : `<span class="badge">命令</span>`;
  const note = c.note ? `<p class="cmd-desc-en" style="font-family:var(--mono)">${esc(c.note)}</p>` : '';
  const blob = (c.name + ' ' + c.zh + ' ' + c.en + ' ' + (c.note||'') + ' ' +
    (c.sub ? c.sub.map(s=>s.join(' ')).join(' ') : '') + ' ' +
    (c.subgroups ? c.subgroups.map(g=>g.zh+' '+g.en+' '+g.items.map(i=>i.join(' ')).join(' ')).join(' ') : '')
    ).toLowerCase();
  return `<div class="cmd ${c.leaf ? 'cmd-leaf':''}" data-search="${esc(blob)}">
    <div class="cmd-head"><span class="cmd-name">frago ${esc(c.name)}</span>${badge}</div>
    <p class="cmd-desc">${esc(c.zh)}</p><p class="cmd-desc-en">${esc(c.en)}</p>${note}${inner}
  </div>`;
}

// 渲染内容
const content = document.getElementById('content');
let totalCmds = 0;
let html = '';
DATA.forEach(g => {
  totalCmds += g.cmds.length;
  html += `<section class="group" id="g-${g.id}" data-group="${g.id}">
    <h2>${g.zh} <span class="en">${g.en}</span></h2>
    ${g.cmds.map(cmdCard).join('')}
  </section>`;
});
// 动态领域(仅说明机制,不收录用户私有领域清单)
html += `<section class="group" id="g-domains" data-group="domains">
  <h2>动态领域命令 <span class="en">Dynamic Domains</span></h2>
  <p class="group-note">每个通过 <code style="font-family:var(--mono)">frago def add</code> 注册的知识领域,都会成为一个顶层命令,统一支持 <code style="font-family:var(--mono)">find / save / schema</code>。</p>
  <div class="cmd" data-search="frago domain 领域 find save schema def list">
    <div class="cmd-head"><span class="cmd-name">frago &lt;领域名&gt;</span><span class="badge">find / save / schema</span></div>
    <p class="cmd-desc">用法格式:<code style="font-family:var(--mono)">frago &lt;领域名&gt; find</code> · <code style="font-family:var(--mono)">frago &lt;领域名&gt; save</code> · <code style="font-family:var(--mono)">frago &lt;领域名&gt; schema</code></p>
    <p class="cmd-desc-en">具体领域名属用户本地私有数据(<code style="font-family:var(--mono)">~/.frago/books/</code>),不在本手册收录;本地用 <code style="font-family:var(--mono)">frago def list</code> 查看。<br>Domain names are user-local private data; run <code style="font-family:var(--mono)">frago def list</code> to view them locally.</p>
  </div>
</section>`;
content.innerHTML = html;

document.getElementById('cmdCountPill').innerHTML = `命令 <b>${totalCmds} 组</b>`;

// 构建侧边栏导航
const nav = document.getElementById('nav');
let navHtml = `<div class="nav-section"><div class="nav-head">CLI 参考 · Reference</div>`;
DATA.forEach(g => {
  navHtml += `<a href="#g-${g.id}" data-target="g-${g.id}">${g.zh}<span class="count">${g.cmds.length}</span></a>`;
});
navHtml += `<a href="#g-domains" data-target="g-domains">动态领域命令</a>`;
navHtml += `</div><div class="nav-foot">更多章节(核心概念 · Recipe 编写 · hook-rules · 场景路径)将陆续收录。</div>`;
nav.innerHTML = navHtml;

// 滚动高亮
const navLinks = [...nav.querySelectorAll('a')];
const sections = [...document.querySelectorAll('.group')];
const spy = new IntersectionObserver(entries => {
  entries.forEach(e => {
    if (e.isIntersecting) {
      const id = e.target.id;
      navLinks.forEach(a => a.classList.toggle('active', a.dataset.target === id));
    }
  });
}, { rootMargin: '-10% 0px -75% 0px' });
sections.forEach(s => spy.observe(s));

// 搜索过滤(中英文均可)
const search = document.getElementById('search');
const noResults = document.getElementById('noResults');
search.addEventListener('input', () => {
  const q = search.value.trim().toLowerCase();
  let anyVisible = false;
  document.querySelectorAll('.group').forEach(sec => {
    let groupVisible = false;
    sec.querySelectorAll('.cmd').forEach(card => {
      const hit = !q || card.dataset.search.includes(q);
      card.style.display = hit ? '' : 'none';
      if (hit) groupVisible = true;
    });
    sec.style.display = groupVisible ? '' : 'none';
    if (groupVisible) anyVisible = true;
  });
  noResults.style.display = anyVisible ? 'none' : 'block';
});

// 移动端菜单
const sidebar = document.getElementById('sidebar');
document.getElementById('menuBtn').addEventListener('click', () => sidebar.classList.toggle('open'));
nav.addEventListener('click', e => { if (e.target.closest('a')) sidebar.classList.remove('open'); });
