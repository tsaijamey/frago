/**
 * frago 的 mermaid 图统一样式（B「卡片」）。WebUI、`frago view`、`frago apps use mermaid`
 * 三处画图都读这一份，NEVER 在别处另抄一套。
 *
 * 用法：页面先加载 mermaid，再加载本文件，然后
 *   mermaid.initialize(fragoMermaid.config('dark' | 'light'));
 *   ……渲染出 svg 之后……
 *   fragoMermaid.postProcess(svgElement);
 *
 * 分工：**代理只写语义，颜色由这里定。** 代理在图里写 `:::done / :::doing / :::todo /
 * :::blocked` 标节点状态，决策图里选中的路写 `==>`、放弃的路写 `-.->`、最终落点加
 * `:::pick`；它 NEVER 写 `classDef` 或 `style` 定颜色——那样每张图一个样，和界面打架。
 *
 * 颜色分两路进图：
 * - 主题变量（themeVariables）：mermaid 用它推算派生色，**只认字面色值**，写 `var(--x)`
 *   整张图渲染失败。深浅各给一份实色，半透明色压成对应表面上的实色。
 * - 注入样式（themeCSS）：会被加上本图的 id 前缀，只作用于本图。颜色一律写成
 *   `var(--界面变量, 兜底色)`：图内联在 WebUI 里时跟着界面主题走；在 `frago view` 的
 *   页面上、或者导出成独立 SVG 文件时，界面变量不存在，落到兜底色。兜底色抄自
 *   WebUI 的 globals.css 两套主题。
 *
 * 样式来历：~/.frago/data/frago-dev/20260918-mermaid-business-style/（三套候选的对比与实测）。
 * 本文件是普通脚本，不是模块：`frago view` 与 `frago apps` 用 <script> 直接加载它。
 */
(function () {
  var FONT =
    "'Geist Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif";

  // 主题变量只认字面色：WebUI 的半透明色在这里压成对应表面上的实色。
  var SOLID = {
    dark: { bg: '#1a1a1a', card: '#242424', text: '#ebebeb', text2: '#a3a3a3', muted: '#7a7a7a', border: '#3a3a3a', note: '#262626' },
    light: { bg: '#f7f7f7', card: '#ffffff', text: '#1a1a1a', text2: '#666666', muted: '#8c8c8c', border: '#d6d6d6', note: '#f0f0f0' },
  };

  // 界面变量的兜底色，与 globals.css 的 :root / [data-theme='light'] 一一对应。
  var FALLBACK = {
    dark: {
      'bg-card': '#242424',
      'bg-tertiary': '#262626',
      'text-primary': 'rgba(255, 255, 255, 0.92)',
      'text-secondary': 'rgba(255, 255, 255, 0.62)',
      'text-muted': 'rgba(255, 255, 255, 0.42)',
      'text-dim': 'rgba(255, 255, 255, 0.3)',
      'border-color': 'rgba(255, 255, 255, 0.09)',
      'border-strong': 'rgba(255, 255, 255, 0.16)',
      'accent-primary': '#15b34d',
      'accent-primary-10': 'rgba(21, 179, 77, 0.12)',
      'accent-primary-20': 'rgba(21, 179, 77, 0.22)',
      'accent-error': '#f0596b',
      'accent-error-10': 'rgba(240, 89, 107, 0.14)',
      'accent-info': '#6ba3d6',
      'accent-info-10': 'rgba(107, 163, 214, 0.14)',
    },
    light: {
      'bg-card': '#FFFFFF',
      'bg-tertiary': '#F0F0F0',
      'text-primary': 'rgba(0, 0, 0, 0.9)',
      'text-secondary': 'rgba(0, 0, 0, 0.6)',
      'text-muted': 'rgba(0, 0, 0, 0.45)',
      'text-dim': 'rgba(0, 0, 0, 0.32)',
      'border-color': 'rgba(0, 0, 0, 0.09)',
      'border-strong': 'rgba(0, 0, 0, 0.16)',
      'accent-primary': '#0a8f33',
      'accent-primary-10': 'rgba(10, 143, 51, 0.1)',
      'accent-primary-20': 'rgba(10, 143, 51, 0.2)',
      'accent-error': '#c42b45',
      'accent-error-10': 'rgba(196, 43, 69, 0.1)',
      'accent-info': '#2e6da8',
      'accent-info-10': 'rgba(46, 109, 168, 0.1)',
    },
  };

  // 深色底上投影看不见，界面自己的规矩也是深色不用投影；浅色给一层很轻的卡片影。
  var CARD_SHADOW = {
    dark: 'none',
    light: 'drop-shadow(0 1px 2px rgba(0,0,0,.06)) drop-shadow(0 3px 8px rgba(0,0,0,.05))',
  };

  function modeOf(mode) {
    return mode === 'light' ? 'light' : 'dark';
  }

  function themeVariables(mode) {
    var t = SOLID[mode];
    return {
      darkMode: mode === 'dark',
      background: t.bg,
      fontFamily: FONT,
      fontSize: '14px',
      primaryColor: t.card,
      primaryTextColor: t.text,
      primaryBorderColor: t.border,
      secondaryColor: t.note,
      tertiaryColor: t.note,
      lineColor: t.muted,
      textColor: t.text,
      mainBkg: t.card,
      nodeBorder: t.border,
      clusterBkg: t.note,
      clusterBorder: t.border,
      edgeLabelBackground: t.card,
      nodeTextColor: t.text,
      titleColor: t.text,
      actorBkg: t.card,
      actorBorder: t.border,
      actorTextColor: t.text,
      actorLineColor: t.border,
      signalColor: t.text2,
      signalTextColor: t.text,
      labelBoxBkgColor: t.card,
      labelBoxBorderColor: t.border,
      labelTextColor: t.text,
      loopTextColor: t.text2,
      noteBkgColor: t.note,
      noteTextColor: t.text2,
      noteBorderColor: t.note,
      activationBkgColor: t.note,
      activationBorderColor: t.border,
      sequenceNumberColor: t.bg,
    };
  }

  function themeCSS(mode) {
    var fb = FALLBACK[mode];
    function v(name) {
      return 'var(--' + name + ', ' + fb[name] + ')';
    }
    var shadow = CARD_SHADOW[mode];
    return [
      '.label, .nodeLabel, .edgeLabel, text.actor, .messageText, .noteText, .labelText, .loopText { font-family: ' + FONT + ' !important; }',
      '.nodeLabel, .label { color: ' + v('text-primary') + ' !important; }',
      '.edgeLabel foreignObject, .label foreignObject { overflow: visible; }',
      /* 标签是 HTML 段落，图又常嵌在别人的正文里：正文的段落外边距和行高会漏进来，
         把连线标签撑成一根竖条、把判断菱形撑得老大。量尺寸和显示时都按这里的来。 */
      '.label p, .nodeLabel p, .edgeLabel p { margin: 0 !important; line-height: 1.5 !important; }',
      '.labelBkg { background: transparent !important; }',
      /* 没写标签的连线也会生成一个空标签，胶囊样式会把它画成一个空框 */
      '.edgeLabel span.edgeLabel:empty, .edgeLabel p:empty { display: none !important; }',

      '.node rect, .node polygon, .node circle, .node path { fill: ' + v('bg-card') + ' !important; stroke: ' + v('border-color') + ' !important; stroke-width: 1px !important; filter: ' + shadow + '; }',
      '.node rect { rx: 8px; ry: 8px; }',
      '.node .nodeLabel { font-weight: 500; }',
      '.flowchart-link { stroke: ' + v('border-strong') + ' !important; stroke-width: 1.5px !important; }',
      '.marker, marker path { fill: ' + v('text-dim') + ' !important; stroke: ' + v('text-dim') + ' !important; }',
      '.edgeLabel { background: transparent !important; }',
      /* 胶囊只画在最里层的段落上；外面那层 span 也画的话，胶囊上下会各多出一截 */
      '.edgeLabel span.edgeLabel { background: transparent !important; }',
      '.edgeLabel p { background: ' + v('bg-card') + ' !important; color: ' + v('text-secondary') + ' !important; font-size: 11.5px; padding: 1px 8px; border-radius: 999px; box-shadow: 0 0 0 1px ' + v('border-color') + '; }',

      /* 状态只换颜色不换字重：节点尺寸按常规字重量出来，加粗后长名字会被折成两行。
         前缀记号挂在段落上而不是标签外层，否则标签里包着的块级段落会把记号挤到单独一行；
         记号悬在文字左侧、占节点内距，不占文字宽度，同样是为了不把名字折行。 */
      '.node.done .nodeLabel p, .node.doing .nodeLabel p, .node.blocked .nodeLabel p { position: relative; display: inline-block; }',
      '.node.done .nodeLabel p::before, .node.doing .nodeLabel p::before, .node.blocked .nodeLabel p::before { position: absolute; right: 100%; padding-right: 3px; }',
      '.node.done rect { fill: ' + v('bg-tertiary') + ' !important; stroke: transparent !important; filter: none; }',
      '.node.done .nodeLabel, .node.done .nodeLabel p { color: ' + v('text-secondary') + ' !important; }',
      ".node.done .nodeLabel p::before { content: '✓'; }",
      '.node.doing rect { fill: ' + v('accent-primary-10') + ' !important; stroke: ' + v('accent-primary-20') + ' !important; }',
      '.node.doing .nodeLabel, .node.doing .nodeLabel p { color: ' + v('accent-primary') + ' !important; }',
      ".node.doing .nodeLabel p::before { content: '●'; font-size: 9px; line-height: 2; }",
      '.node.todo rect { fill: transparent !important; stroke: ' + v('border-strong') + ' !important; stroke-dasharray: 4 3; filter: none; }',
      '.node.todo .nodeLabel, .node.todo .nodeLabel p { color: ' + v('text-muted') + ' !important; }',
      '.node.blocked rect { fill: ' + v('accent-error-10') + ' !important; stroke: transparent !important; filter: none; }',
      '.node.blocked .nodeLabel, .node.blocked .nodeLabel p { color: ' + v('accent-error') + ' !important; }',
      ".node.blocked .nodeLabel p::before { content: '!'; font-weight: 700; }",

      /* 决策：选中的路 = 粗线变绿，放弃的路 = 淡虚线，落点 = 绿框 */
      '.flowchart-link.edge-thickness-thick { stroke: ' + v('accent-primary') + ' !important; stroke-width: 2px !important; }',
      '.flowchart-link.edge-pattern-dotted { stroke: ' + v('border-strong') + ' !important; stroke-dasharray: 2 4 !important; }',
      '.node.pick rect { fill: ' + v('accent-primary-10') + ' !important; stroke: ' + v('accent-primary') + ' !important; stroke-width: 1.5px !important; }',
      '.node.pick .nodeLabel, .node.pick .nodeLabel p { color: ' + v('accent-primary') + ' !important; }',

      /* 时序图 */
      'rect.actor { fill: ' + v('bg-card') + ' !important; stroke: ' + v('border-color') + ' !important; rx: 8px; ry: 8px; filter: ' + shadow + '; }',
      'text.actor, text.actor > tspan { fill: ' + v('text-primary') + ' !important; font-weight: 500; }',
      '.actor-man line, .actor-man circle { stroke: ' + v('text-secondary') + ' !important; fill: ' + v('bg-card') + ' !important; }',
      '.actor-line { stroke: ' + v('border-color') + ' !important; stroke-width: 1.5px; }',
      '.messageLine0, .messageLine1 { stroke: ' + v('text-dim') + ' !important; stroke-width: 1.5px !important; }',
      '.messageText { fill: ' + v('text-primary') + ' !important; font-size: 13px !important; }',
      'rect.note { fill: ' + v('accent-info-10') + ' !important; stroke: none !important; rx: 8px; ry: 8px; }',
      '.noteText, .noteText > tspan { fill: ' + v('accent-info') + ' !important; }',
      '.activation0 { fill: ' + v('accent-primary-20') + ' !important; stroke: none !important; rx: 3px; }',
      /* v12 给分组框自带一层浅灰投影，深色底上整块发灰，关掉 */
      '.seq-box { fill: ' + v('bg-card') + ' !important; stroke: ' + v('border-color') + ' !important; rx: 12px; ry: 12px; fill-opacity: .55; filter: none !important; }',
      '.seq-box-label { fill: ' + v('text-secondary') + ' !important; font-size: 12px !important; font-weight: 600; }',
    ].join('\n');
  }

  /**
   * 交给 `mermaid.initialize` 的整份配置。
   *
   * `look: 'classic'` 与 `theme: 'base'` 必须显式写：v12 默认是 neo 外观（黑粗边加硬投影），
   * 不关掉的话上面的样式压不住。布局用 v12 默认的 ELK，走线比 dagre 整齐。
   */
  function config(mode) {
    var m = modeOf(mode);
    return {
      startOnLoad: false,
      securityLevel: 'strict',
      theme: 'base',
      look: 'classic',
      themeVariables: themeVariables(m),
      themeCSS: themeCSS(m),
      flowchart: { htmlLabels: true, useMaxWidth: false, curve: 'basis', padding: 12, nodeSpacing: 44, rankSpacing: 52 },
      sequence: {
        useMaxWidth: false,
        mirrorActors: false,
        actorMargin: 60,
        boxMargin: 10,
        noteMargin: 12,
        messageMargin: 36,
        boxTextMargin: 8,
      },
    };
  }

  /**
   * 渲染完成后补一刀：时序图的参与方分组框没有类名，样式选不中它。按形状认出来补上：
   * 分组框是直接挂在图根下、比参与方卡片高得多的矩形，紧跟着的那段文字是它的标题。
   */
  function postProcess(svg) {
    if (!svg || svg.getAttribute('aria-roledescription') !== 'sequence') return;
    var i = 0;
    svg.querySelectorAll(':scope > g > rect, :scope > rect').forEach(function (rect) {
      if (rect.classList.contains('actor') || rect.classList.contains('note')) return;
      if (Number(rect.getAttribute('height')) <= 100) return;
      rect.classList.add('seq-box', 'seq-box-' + i++);
      var label = rect.nextElementSibling;
      if (label && label.tagName === 'text') label.classList.add('seq-box-label');
    });
  }

  globalThis.fragoMermaid = { config: config, postProcess: postProcess };
})();
