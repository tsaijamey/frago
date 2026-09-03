/* desktop stage —— 只读显示器。所有画面变化只来自 broker 消息。 */
(function () {
  "use strict";

  // contentId / instanceId 由 config.json 下发，是这块荧幕的归属证明。
  // 端口不属于身份，任何一个旧实例遗留的标签都连得上后来的 broker，
  // 所以每次握手都要自报家门，由 broker 判断该不该收下这块荧幕的几何。
  var CONFIG = {
    brokerWs: "ws://127.0.0.1:8770/stream",
    desktop: { w: 1920, h: 1080 },
    contentId: null,
    instanceId: null
  };

  // dock 距屏幕底边的留白，与 style.css 里 #dock 的 bottom 保持一致。
  var DOCK_MARGIN = 10;

  var els = {};
  var state = {
    ws: null,
    wsOpen: false,
    focus: "term",
    // 桌面坐标系下的窗口几何（win 消息的目标值，layout 上报以此为准）
    geom: {
      term: { x: 120, y: 90, w: 900, h: 560 },
      browser: { x: 620, y: 210, w: 1080, h: 700 },
      image: { x: 760, y: 250, w: 480, h: 360 }
    },
    viewport: null,       // 舞台视口尺寸，hello 时下发
    pendingFrame: null,   // 只保留最新一帧待绘
    drawing: false,
    firstFrameSent: false,
    // 连上之后到 broker 把整份现状补发完之间，这块荧幕手上还是出厂状态，
    // 这期间一个字都不许往回报（见 sendLayout）。
    syncing: true,
    captionTimer: null,
    appNames: { term: "Terminal", browser: "Chrome", image: "Preview" },
    minimized: { term: false, browser: false, image: false },
    prevGeom: {},          // min/max 前的几何，restore 用
    // 程序在不在桌面上。与 minimized 是两件事：收起的程序还在跑（dock 亮着灯、
    // 窗口飞进了 dock），关掉的程序不在了（灯灭、窗口不存在）。两者共用一个
    // 标志的话，画面上就分不出"收起来了"和"退出了"，而这正是要能演出来的区别。
    // 图片浏览器开机不在桌面上——它是被 image open 叫起来的。
    open: { term: true, browser: true, image: false },
    // 终端缓冲区：历史 + 当前屏，broker 按增量推过来，这里存着并画出来。
    // base 是"broker 已经从头部丢掉多少行"，lines 的下标加上它才是缓冲区行号，
    // 两边靠这个数对齐。stuck = 视口贴着底：贴底时新输出跟着走（真实终端就是
    // 这样），人一往回滚就松开，否则回看到一半会被新输出拽回底部。
    term: { base: 0, lines: [], stuck: true, top: 0 }
  };

  function $(id) { return document.getElementById(id); }

  // 窗口元素按名字取。三扇窗共用同一套定位/焦点/收展逻辑，写死 term/browser
  // 三元会让第三扇窗进来时每个函数都要改一遍，且漏一处就在画面上静静失效。
  function winEl(win) {
    return { term: els.winTerm, browser: els.winBrowser, image: els.winImage }[win];
  }
  function dockEl(win) {
    return { term: els.dockTerm, browser: els.dockBrowser, image: els.dockImage }[win];
  }
  function winHeaderH(win) {
    return { term: els.termHeaderH, browser: els.browserHeaderH, image: els.imageHeaderH }[win];
  }

  /* ── 底座：缩放适配 ── */
  function fitStage() {
    var dw = CONFIG.desktop.w, dh = CONFIG.desktop.h;
    els.stage.style.width = dw + "px";
    els.stage.style.height = dh + "px";
    var scale = Math.min(window.innerWidth / dw, window.innerHeight / dh);
    els.stage.style.transform =
      "translate(-50%, -50%) scale(" + scale + ")";
  }

  /* ── 时钟 ── */
  function tickClock() {
    var d = new Date();
    var days = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
    var hh = String(d.getHours()).padStart(2, "0");
    var mm = String(d.getMinutes()).padStart(2, "0");
    els.clock.textContent = days[d.getDay()] + " " + hh + ":" + mm;
  }

  /* ── 窗口几何与焦点 ── */

  // 浏览器窗口的几何不再由这里决定：broker 读演员标签天然的视口，按它的宽高比
  // 算出这扇窗该多大，然后当成一条普通的 win 消息发下来，这里照单执行。
  // 曾经反过来——窗口是主、视口是从，broker 把演员视口覆写成窗口内容区的尺寸；
  // 那份覆写会被导航、刷新、debugger 重附着悄悄抹掉，于是要重放、要对账帧尺寸。
  // 现在没有覆写，也就没有可丢的东西。这块荧幕是纯显示器。

  function applyGeom(win, g, ms) {
    var el = winEl(win);
    var dur = (typeof ms === "number" ? ms : 300) + "ms";
    el.style.transitionDuration = dur;
    el.style.left = g.x + "px";
    el.style.top = g.y + "px";
    el.style.width = g.w + "px";
    el.style.height = g.h + "px";
    if (win === "browser") trackFit(typeof ms === "number" ? ms : 300);
  }

  // win 可以是 null：桌面上一个程序都没开着时就是这个状态，菜单栏退回 Finder，
  // 三扇窗口谁也不在前台。不接受 null 的话，关掉最后一个程序会让菜单栏一直
  // 挂着那个已经不存在的程序名。
  function applyFocus(win) {
    if (win && !state.open[win]) openWin(win, 0);  // 点名一个关掉的程序 = 启动它
    if (win && state.minimized[win]) restoreWin(win); // 点名一个收起的窗口 = 召回它
    state.focus = win;
    ["term", "browser", "image"].forEach(function (w) {
      winEl(w).classList.toggle("focused", win === w);
      dockEl(w).classList.toggle("active", win === w);
    });
    els.mbApp.textContent = win ? (state.appNames[win] || win) : "Finder";
  }

  /* ── layout 上报：内容区矩形（桌面坐标），broker 靠它换算点击坐标 ── */
  function contentRect(win) {
    // 关掉的和收起的窗口都不占桌面：上报零矩形，点击永远落不进去
    if (!state.open[win] || state.minimized[win]) {
      return { x: -9999, y: -9999, w: 0, h: 0 };
    }
    var g = state.geom[win];
    var headerH = winHeaderH(win);
    return { x: g.x, y: g.y + headerH, w: g.w, h: g.h - headerH };
  }

  /* ── 可寻址元素快照 ──
     桌面级元素总共几十个，每次几何变化连同 layout 全量上报。全量优于按需：
     省掉一次往返，并让"现在能点什么"零成本可查。
     矩形一律折算成桌面坐标，与 windows 字段同一坐标系。 */

  // 窗口内子元素：走 offset 链取"布局位置"而非 getBoundingClientRect。
  // 后者在 CSS 补间进行中返回的是动画途中的值，而 layout 是紧接着 applyGeom
  // 发出的——那一刻窗口还停在旧位置，报上去的矩形会整体偏移一个动画的距离。
  // offset 链配合 state.geom 的目标值，报的始终是"落定后的位置"。
  function offsetIn(el, root) {
    var x = 0, y = 0, n = el;
    while (n && n !== root) { x += n.offsetLeft; y += n.offsetTop; n = n.offsetParent; }
    return { x: x, y: y };
  }

  function winChildRect(win, el) {
    if (!el || !state.open[win] || state.minimized[win]) return null;
    var root = winEl(win), g = state.geom[win];
    var o = offsetIn(el, root);
    if (!el.offsetWidth || !el.offsetHeight) return null;
    return { x: g.x + o.x, y: g.y + o.y, w: el.offsetWidth, h: el.offsetHeight };
  }

  // dock 从不参与窗口补间，直接量屏幕矩形再除以舞台缩放即可。
  function screenRect(el) {
    if (!el) return null;
    var r = el.getBoundingClientRect();
    var s = els.stage.getBoundingClientRect();
    var scale = s.width / CONFIG.desktop.w;
    if (!r.width || !r.height || !scale) return null;
    return {
      x: Math.round((r.left - s.left) / scale),
      y: Math.round((r.top - s.top) / scale),
      w: Math.round(r.width / scale),
      h: Math.round(r.height / scale)
    };
  }

  function collectElements() {
    var out = {};
    function put(ref, rect) { if (rect) out[ref] = rect; }
    put("dock:term", screenRect(els.dockTerm));
    put("dock:browser", screenRect(els.dockBrowser));
    put("dock:image", screenRect(els.dockImage));
    ["term", "browser", "image"].forEach(function (win) {
      // 关掉的和收起的窗口都不在桌面上，不可寻址
      if (!state.open[win] || state.minimized[win]) return;
      var g = state.geom[win];
      put("win:" + win, { x: g.x, y: g.y, w: g.w, h: g.h });
      put("win:" + win + ".titlebar",
          winChildRect(win, winEl(win).querySelector(".titlebar")));
    });
    if (state.open.browser && !state.minimized.browser) {
      put("addr", winChildRect("browser", els.addr));
      var tabs = els.tabStrip.querySelectorAll(".tab");
      for (var i = 0; i < tabs.length; i++) {
        put("tab:" + i, winChildRect("browser", tabs[i]));
      }
    }
    return out;
  }

  /* ── 窗口管理：split / max / min / restore ── */
  // 可用桌面 = 扣掉菜单栏与 dock。dock 是一直浮在最上层的，不扣的话
  // split 铺满高度后左半边终端的最后几行正好被 dock 压住——画面上看不出
  // 是被挡了，只觉得终端"少输出了几行"。真实 macOS 同样为 dock 留白。
  function desktopArea() {
    var mb = els.menubar ? els.menubar.offsetHeight : 26;
    var dock = els.dock ? els.dock.offsetHeight + DOCK_MARGIN * 2 : 0;
    return { x: 0, y: mb, w: CONFIG.desktop.w, h: CONFIG.desktop.h - mb - dock };
  }

  /* ── 开关程序 ──
     close 不是"另一种最小化"：最小化的窗口飞进 dock、灯还亮着、restore 能召回；
     关掉的程序原地缩一点淡出、dock 的灯灭掉、窗口从桌面上消失。两个动作在画面上
     必须一眼分得开，否则观众看到窗口没了会以为程序只是收起来了。

     载体一个都不动——tmux 会话、演员标签、已经装进图片浏览器的那张图全都还在，
     所以 open 回来的是原样，不是一个新开的空程序。这是有意的：录一段"关掉终端
     只留浏览器"的镜头，不该顺手把跑了一半的会话杀掉。 */
  var CLOSE_MS = 220;

  function closeWin(win, ms) {
    if (!state.open[win]) return;
    var el = winEl(win);
    var dur = (typeof ms === "number" ? ms : CLOSE_MS);
    state.open[win] = false;
    // 收起状态一并清掉：关掉再打开的程序不该还记着"我当时是被收进 dock 的"
    state.minimized[win] = false;
    el.style.transitionDuration = dur + "ms";
    el.style.transform = "scale(0.92)";
    el.classList.add("closing");
    el.classList.remove("minimized", "focused");
    dockEl(win).classList.remove("running", "active");
    // 动画走完才真的摘掉。期间可能又来一条 open，那时这个定时器必须认账走人，
    // 否则它会在几百毫秒后把一扇刚打开的窗口重新藏起来。
    // closing 类一直留着不摘：display:none 之后 opacity 已经不起作用，留着是
    // 第二道保险——万一哪天有人动了 .stage-window[hidden] 那条规则，窗口至少
    // 还是透明的，而不是"关掉了却整扇画在桌面上"。摘 closing 的活交给 openWin。
    setTimeout(function () {
      if (state.open[win]) return;
      el.hidden = true;
      el.style.transform = "";
    }, dur);
    sendLayout();
  }

  function openWin(win, ms) {
    if (state.open[win]) return;
    var el = winEl(win);
    var dur = (typeof ms === "number" ? ms : CLOSE_MS);
    state.open[win] = true;
    state.minimized[win] = false;
    // 先落到起始形态再补间：直接从 hidden 变可见的话没有起始值可插值，
    // 窗口是"啪"地出现，和关闭那一下的质感对不上。
    el.hidden = false;
    el.style.transitionDuration = "0ms";
    el.style.transform = "scale(0.96)";
    el.classList.add("closing");
    void el.offsetWidth;          // 强制一次重排，让上面那组值成为动画起点
    el.style.transitionDuration = dur + "ms";
    el.classList.remove("closing");
    el.style.transform = "";
    dockEl(win).classList.add("running");
    sendLayout();
  }

  function restoreWin(win, ms) {
    var el = winEl(win);
    if (state.minimized[win]) {
      state.minimized[win] = false;
      el.style.transitionDuration = (typeof ms === "number" ? ms : 380) + "ms";
      el.style.transform = "";
      el.classList.remove("minimized");
    } else if (state.prevGeom[win]) {
      state.geom[win] = state.prevGeom[win];
      delete state.prevGeom[win];
      applyGeom(win, state.geom[win], ms);
    }
    sendLayout();
  }

  function minimizeWin(win, ms) {
    if (state.minimized[win]) return;
    var el = winEl(win);
    var dockEl_ = dockEl(win);
    state.minimized[win] = true;
    // 飞向自己的 dock 图标：把图标中心换算回桌面坐标系
    var icon = dockEl_.getBoundingClientRect();
    var stage = els.stage.getBoundingClientRect();
    var scale = stage.width / CONFIG.desktop.w;
    var g = state.geom[win];
    var tx = (icon.left + icon.width / 2 - stage.left) / scale - (g.x + g.w / 2);
    var ty = (icon.top + icon.height / 2 - stage.top) / scale - (g.y + g.h / 2);
    el.style.transitionDuration = (typeof ms === "number" ? ms : 380) + "ms";
    el.style.transform = "translate(" + tx + "px," + ty + "px) scale(0.04)";
    el.classList.add("minimized");
    sendLayout();
  }

  function maximizeWin(win, ms) {
    if (state.minimized[win]) restoreWin(win, 0);
    if (!state.prevGeom[win]) {
      state.prevGeom[win] = Object.assign({}, state.geom[win]);
    }
    var a = desktopArea(), pad = 10;
    var g = { x: a.x + pad, y: a.y + pad, w: a.w - pad * 2, h: a.h - pad * 2 };
    state.geom[win] = g;
    applyGeom(win, g, ms);
    sendLayout();
  }

  // splitLayout 已删除：对开要把浏览器压到半个桌面宽，与"浏览器恒占桌面宽的
  // 75–85%"直接冲突。这两条规则无法共存，留下后者。

  // 关掉的窗口是 display:none，量不到任何尺寸。先临时露出量好再收回去——
  // 同步 reflow，不经过绘制，不会闪。三扇窗都要走这条路：任何一扇都可能在
  // 这一刻是关着的（页面重连时 broker 会先补发各程序的开关状态）。
  function withVisible(el, fn) {
    var wasHidden = el.hidden;
    el.hidden = false;
    var out = fn(el);
    el.hidden = wasHidden;
    return out;
  }

  function measureHeaders() {
    els.termHeaderH = withVisible(els.winTerm, function (w) {
      return w.querySelector(".titlebar").offsetHeight;
    });
    els.browserHeaderH = withVisible(els.winBrowser, function (w) {
      return w.querySelector(".titlebar").offsetHeight +
             w.querySelector(".browser-chrome").offsetHeight;
    });
    els.imageHeaderH = withVisible(els.winImage, function (w) {
      return w.querySelector(".titlebar").offsetHeight;
    });
  }

  // 量一个字符格子的实际尺寸，据此算出终端窗口能放下多少行列。
  // 现实里没有哪个终端会显示一个装不进自己窗口的网格——窗口多大网格就多大，
  // 所以这个值要上报给 broker 去改 tmux 尺寸，而不是两边各定各的。
  function termCellH() {
    var cs = getComputedStyle(els.termScreen);
    return parseFloat(cs.lineHeight) || (parseFloat(cs.fontSize) * 1.35);
  }

  function termGrid() {
    var probe = document.createElement("span");
    var cs = getComputedStyle(els.termScreen);
    probe.style.cssText = "position:absolute;visibility:hidden;white-space:pre;" +
      "font-family:" + cs.fontFamily + ";font-size:" + cs.fontSize;
    probe.textContent = "0".repeat(100);
    document.body.appendChild(probe);
    var cw = probe.getBoundingClientRect().width / 100;
    document.body.removeChild(probe);
    var lh = parseFloat(cs.lineHeight) || (parseFloat(cs.fontSize) * 1.35);

    var body = els.winTerm.querySelector(".term-body");
    var pad = getComputedStyle(body);
    var w = body.clientWidth - parseFloat(pad.paddingLeft) - parseFloat(pad.paddingRight);
    var h = body.clientHeight - parseFloat(pad.paddingTop) - parseFloat(pad.paddingBottom);
    var rows = Math.max(6, Math.floor(h / lh));
    // 视口高度钉成整行数 × 行高。剩下那不到一行的空隙留给 .term-body，
    // 不留给视口：视口里挂半行字的话，broker 换算行号时那半行既算看得见
    // 又算看不见，取景就会差一行——而差一行在回执里完全看不出来。
    if (els.termScroll.style.height !== (rows * lh) + "px") {
      els.termScroll.style.height = (rows * lh) + "px";
      // 视口高度一变，能滚的范围就变了，位置得重摆一次。
      // 尤其是刚加载那一刻：高度是在这儿第一次被设上的，在此之前容器跟内容
      // 一样高、根本滚不动，补发过来的位置会被静静夹成 0——画面停在最上面，
      // 而 broker 记着的是另一行。
      applyTermScroll();
    }
    // 字符格子的尺寸与网格原点一并上报：broker 靠这三个值把 term:r12c40
    // 换算成桌面坐标，不必自己猜字体度量。
    var br = winChildRect("term", body);
    return {
      cols: Math.max(20, Math.floor(w / cw)),
      rows: rows,
      cellW: cw,
      cellH: lh,
      x: br ? br.x + parseFloat(pad.paddingLeft) : null,
      y: br ? br.y + parseFloat(pad.paddingTop) : null,
      // 视口现在停在缓冲区的哪一段。缓冲区可以有几千行而窗口只有几十行，
      // broker 的 term:rows / term:match 是按**画面上第几行**算的，
      // 没有这三个数它就只能假设"看的永远是最后一屏"——人一回看历史，
      // 镜头就对着别处，而回执里每个字段都正常。
      scrollTop: els.termScroll.scrollTop,
      bufferLines: state.term.lines.length,
      base: state.term.base,
      stuck: state.term.stuck
    };
  }

  /* ── 终端缓冲区：存、画、滚 ── */

  function termScrollMax() {
    var sc = els.termScroll;
    return Math.max(0, sc.scrollHeight - sc.clientHeight);
  }

  // 把视口摆到 broker 说的那一行。贴底时直接顶到底：按行号算出来的像素值
  // 可能比真实底部差半像素，那半像素会让下一行输出进来时画面差一点点没到底。
  //
  // 缓冲区一变就要重摆一次（见 applyTerm）：滚动指令可能在这块荧幕还没拿到
  // 内容时就到了——它记下位置，等内容到了再落位，而不是停在 0 或贴回底部。
  function applyTermScroll() {
    var T = state.term, sc = els.termScroll;
    sc.scrollTop = T.stuck
      ? termScrollMax()
      : Math.min(T.top * termCellH(), termScrollMax());
  }

  function termLineEl(text) {
    var d = document.createElement("div");
    d.className = "term-line";
    d.innerHTML = ansiToHtml(text);
    return d;
  }

  // broker 推的是增量：base（它丢掉了多少行）+ from（从哪一行起变了）+ 变化后
  // 的那一段。整段重推的成本不在带宽，在画面——几千行整块重画，人正回看的
  // 那几行会在脚下抖一下。
  function applyTerm(msg) {
    var T = state.term, host = els.termScreen;
    var base = msg.base | 0, from = msg.from | 0;
    if (base < T.base || from < T.base) {
      // 缓冲区被整段换掉了（会话重开、clear-history、改过窗口尺寸后重取）。
      // 旧的一行都不留——留着就会和新的接不上，而接不上的地方看起来像
      // 一段正常输出。
      host.innerHTML = "";
      T.lines = [];
      T.base = base;
    } else if (base > T.base) {
      // broker 丢了最老的一段，这边同步丢。
      var cut = base - T.base;
      for (var i = 0; i < cut && host.firstChild; i++) {
        host.removeChild(host.firstChild);
      }
      T.lines.splice(0, cut);
      T.base = base;
      // 行号基准跟着前移，与 broker 那边同一个算式。少挪这一下，人正在回看的
      // 那几行会自己往上走一段。
      T.top = Math.max(0, T.top - cut);
    }
    var at = Math.max(0, from - T.base);
    T.lines.length = at;
    while (host.children.length > at) host.removeChild(host.lastChild);
    for (var j = 0; j < msg.lines.length; j++) {
      T.lines.push(msg.lines[j]);
      host.appendChild(termLineEl(msg.lines[j]));
    }
    // 贴底就跟着走，这是真实终端的行为；人往回滚过就钉在原处——那正是回看，
    // 被新输出拽回底部的话这块缓冲区就白有了。
    applyTermScroll();
  }

  // 滚动是画面上看得见的动作，所以走补间。不用 scroll-behavior:smooth：
  // 那个时长是浏览器定的，而这块画面要被录进片子，节奏得由指令说了算。
  // 位置立刻落定，动画只管好看。
  //
  // 这两件事必须分开，而且分开的方式很关键：滚动**位置**一步到位地写进
  // scrollTop，视觉上的移动交给一条 CSS transition（先把内容反向平移回原处，
  // 再让它归零，看起来就是滚过去的）。
  //
  // 曾经是一个 rAF 补间逐帧改 scrollTop，看起来一样、错法很脏：浏览器判定
  // 标签不可见时会冻住 rAF，也会把定时器压到秒级，于是补间一帧都不跑——
  // 滚动静默地什么都没发生，而指令返回成功、行号照报。2026-08-20 实测撞到：
  // 同一条 `term scroll --to-end`，前台标签滚了，后台标签一动不动。
  // 画面对不对不能取决于哪个标签正被人看着。
  function termScrollTo(top, stuck, ms) {
    var T = state.term, sc = els.termScroll, host = els.termScreen;
    var from = sc.scrollTop;
    var dur = typeof ms === "number" ? ms : 400;
    // 位置和贴底与否都听 broker 的，这块荧幕不自己解释。
    //
    // 自己解释过一版，错法很难看：夹进"我这块荧幕的缓冲区有多少行"里。刚连上
    // 的荧幕（录制机位每次 rec start 都是新开的一页）此刻一行都还没有，目标被
    // 夹成 0、还顺手把自己判成贴底，等快照到了就一路贴回底部——画面停在最后
    // 一屏，而指令回执写着它在第 6 行。几块荧幕各画各的，谁也不算错。
    T.top = Math.max(0, top | 0);
    T.stuck = !!stuck;
    applyTermScroll();
    var delta = from - sc.scrollTop;
    if (delta && dur > 0) {
      host.style.transitionDuration = "0ms";
      host.style.transform = "translateY(" + delta + "px)";
      void host.offsetWidth;          // 强制一次重排，让上面那个值成为动画起点
      host.style.transitionDuration = dur + "ms";
      host.style.transform = "";
    }
    // 位置已经是最终值了，layout 立刻就能报——broker 的行号基准跟着变，
    // 不必等动画。
    sendLayout();
  }

  // 改终端字号。它连带改的是字符格子的宽高，而列数行数是"窗口内容区 ÷ 格子"
  // 算出来的，所以这一下会一路改到 tmux 的尺寸上。改完必须立刻重报一次 layout：
  // broker 的行号基准（term:rows / term:match 靠它换算成桌面坐标）是按旧格子
  // 算的，不重报的话取景会对着别处，而回执里每个字段都正常。
  function applyTermFontSize(px) {
    var v = Math.max(8, Math.min(64, Number(px) || 13));
    document.documentElement.style.setProperty("--term-fs", v + "px");
    // 视口高度钉成"整行数 × 行高"，行高变了要重算——termGrid() 自己会做，
    // 这里只负责把重算之后的网格报回去。补发期间报不出去也没关系：
    // synced 到了会再报一次，那一次报的才是最终的。
    sendLayout();
  }

  // layout 上报的几何只服务于两件事：终端的字符网格，以及桌面级 ref 的矩形。
  // 它不再决定演员视口，也不再决定浏览器窗口该多大——那两样的作者是 broker。
  // metrics 是这块荧幕的长相（可用区、浏览器窗口的装饰高度），只有这里量得到，
  // broker 算几何要用。
  function sendLayout() {
    // 补发还没走完就不报。刚加载的这一刻手上是出厂几何（终端 900x560），
    // 报上去 broker 会当真——照它 resize tmux 会话，等补发的真几何到了再
    // resize 回来。一来一回两次 SIGWINCH，zsh 每次重印提示符，旧的那行留在
    // 历史里，于是每开一次机位（rec start 都是新开一页）画面上就多堆一行。
    // 报得晚几十毫秒没有任何代价，报得早的代价是往会话里写垃圾。
    if (state.syncing) return;
    send({
      t: "layout",
      uiVersion: CONFIG.uiVersion,
      contentId: CONFIG.contentId,
      instanceId: CONFIG.instanceId,
      desktop: { w: CONFIG.desktop.w, h: CONFIG.desktop.h },
      windows: { term: contentRect("term"), browser: contentRect("browser"),
                 image: contentRect("image") },
      metrics: {
        area: desktopArea(),
        menubar: els.menubar ? els.menubar.offsetHeight : 26,
        browserHeader: els.browserHeaderH
      },
      termGrid: termGrid(),
      elements: collectElements()
    });
  }

  function send(obj) {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify(obj));
    }
  }

  /* 帧按自身比例塞进窗口内容区，取较小的那个缩放比——宁可留空边也不拉伸。
     窗口正在补间时量到的是动画途中的尺寸，所以每帧都重算一次，
     画面跟着窗口一起长，而不是等补间结束才对齐。 */
  function fitCanvas(fw, fh) {
    if (fw) { state.frameW = fw; state.frameH = fh; }
    fw = state.frameW; fh = state.frameH;
    var body = els.winBrowser.querySelector(".browser-body");
    var bw = body.clientWidth, bh = body.clientHeight;
    if (!fw || !fh || !bw || !bh) return;
    var k = Math.min(bw / fw, bh / fh);
    els.canvas.style.width = Math.round(fw * k) + "px";
    els.canvas.style.height = Math.round(fh * k) + "px";
  }

  // 补间期间页面往往是静止的，一帧都不发——只在收帧时重排的话，画面会僵在
  // 旧尺寸直到补间结束才跳一下。这里每帧跟一次，让画面和窗口一起长。
  function trackFit(ms) {
    var until = performance.now() + (typeof ms === "number" ? ms : 300) + 120;
    (function step() {
      fitCanvas();
      if (performance.now() < until) requestAnimationFrame(step);
    })();
  }

  /* ── 帧管线：离屏解码 + 只画最新帧 ── */
  function pushFrame(b64) {
    state.pendingFrame = b64; // 覆盖旧的待绘帧，积压帧直接丢弃
    if (!state.drawing) drainFrame();
  }

  function drainFrame() {
    var b64 = state.pendingFrame;
    if (b64 === null) return;
    state.pendingFrame = null;
    state.drawing = true;
    var img = new Image();
    img.onload = function () {
      requestAnimationFrame(function () {
        var c = els.canvas;
        if (c.width !== img.naturalWidth || c.height !== img.naturalHeight) {
          c.width = img.naturalWidth;
          c.height = img.naturalHeight;
        }
        els.ctx.drawImage(img, 0, 0);
        fitCanvas(img.naturalWidth, img.naturalHeight);
        if (!state.firstFrameSent) {
          state.firstFrameSent = true;
          send({ t: "ready" });
        }
        state.drawing = false;
        drainFrame(); // 期间若有新帧，接着画最新那帧
      });
    };
    img.onerror = function () { state.drawing = false; drainFrame(); };
    img.src = "data:image/jpeg;base64," + b64;
  }

  /* ── 虚拟鼠标 ── */
  function moveCursor(x, y, ms, ease) {
    els.vcursor.style.transitionDuration = (typeof ms === "number" ? ms : 200) + "ms";
    els.vcursor.style.transitionTimingFunction = ease || "cubic-bezier(.4,0,.2,1)";
    // 箭头尖端不在元素左上角：描边宽 1.2 居中，路径整体内缩了 0.6，
    // 乘缩放比 1.58 得 0.9px。改 index.html 里的 svg 尺寸必须同步改这里，
    // 否则鼠标看着总是点偏一点点，而且偏得很难被发现。
    els.vcursor.style.transform =
      "translate(" + (x - 0.9) + "px," + (y - 0.9) + "px)";
    state.cursorX = x;
    state.cursorY = y;
  }

  function clickEffect(phase) {
    if (phase === "down") {
      els.vcursor.classList.add("pressed");
      var r = document.createElement("div");
      r.className = "ripple";
      r.style.left = (state.cursorX || 0) + "px";
      r.style.top = (state.cursorY || 0) + "px";
      els.rippleLayer.appendChild(r);
      setTimeout(function () { r.remove(); }, 400);
    } else {
      els.vcursor.classList.remove("pressed");
    }
  }

  /* ── 字幕 ──
     多行堆叠：新的从底下进来，旧的往上顶，最多 3 行，每行按自己的时长各自退场。
     以前是一句顶掉一句，讲到第二句时第一句已经没了——观众想回看上一句时
     画面上什么都没有。每行独立计时而不是整块一起清，是因为它们本来就是
     不同时刻说出来的话，共用一个到期时间会让先说的那句活得比该有的久。 */
  var CAPTION_MAX_LINES = 3;
  var CAPTION_MAX_MS = 8000;

  function showCaption(text, ms) {
    var line = document.createElement("div");
    line.className = "caption-line";
    line.textContent = text;
    els.caption.appendChild(line);
    // 超出上限先挤掉最老的那行，再让新行淡入——顺序反过来会看到 4 行同框。
    // 只数还活着的：正在淡出的那些仍挂在 DOM 上（要走完动画才摘），
    // 把它们算进来会连累下一行被提前顶掉。
    var live = liveCaptions();
    while (live.length > CAPTION_MAX_LINES) {
      dropCaption(live.shift());
    }
    requestAnimationFrame(function () { line.classList.add("in"); });

    var life = Math.min(typeof ms === "number" ? ms : 3000, CAPTION_MAX_MS);
    line._timer = setTimeout(function () { dropCaption(line); }, life);
  }

  function liveCaptions() {
    return Array.prototype.filter.call(
      els.caption.children, function (n) { return !n._gone; }
    );
  }

  function dropCaption(line) {
    if (!line || line._gone) return;
    line._gone = true;
    clearTimeout(line._timer);
    line.classList.remove("in");
    // 等淡出走完再摘，否则元素瞬间消失，上面几行会往下跳一格
    setTimeout(function () {
      if (line.parentNode) line.parentNode.removeChild(line);
    }, 350);
  }

  /* ── 浮层标注 ──
     和字幕平行的一套东西，刻意不复用 showCaption：字幕是一列往上堆的文字流，
     浮层是各自定位、各自计时、可被 id 点名撤下的独立元素。共用一套生命周期
     只会让"撤下这张图"顺手把还该在的字幕一起清掉。
     坐标直接用桌面 px——#stage 本身就按 desktop.w/h 布局再整体 scale，
     跟 applyGeom 同一套路，这里不需要额外换算。 */
  var overlays = [];

  function showOverlay(msg) {
    // 同 id 重发视为替换：讲解时改一版图示是常事，两张叠着才是意外
    if (msg.id) clearOverlay(msg.id);

    var box = document.createElement("div");
    box.className = "overlay-item overlay-" + msg.kind +
                    " overlay-enter-" + (msg.enter || "fade");
    box._oid = msg.id || null;

    var at = msg.at;
    if (at) {
      box.style.left = at.x + "px";
      box.style.top = at.y + "px";
      if (at.w) box.style.width = at.w + "px";
      if (at.h) box.style.height = at.h + "px";
    } else {
      box.classList.add("overlay-centered");
    }

    // 内容装在 body 里而不是 box 上：box 只管定位和进场变换，body 只管长相。
    // 合成一层的话，居中态需要 transform 定位，就和进场动画抢同一个属性。
    if (msg.kind === "highlight") {
      // 纯圈选，不放内容——遮罩靠 CSS 的超大 box-shadow 打出去
      box.classList.add("overlay-hole");
    } else {
      var body = document.createElement("div");
      body.className = "overlay-body";
      if (msg.kind === "image") {
        var img = document.createElement("img");
        img.src = msg.content;
        body.appendChild(img);
      } else {
        // card / title 收的是 HTML 片段，按片段渲染是这条协议的用途本身
        body.innerHTML = msg.content;
      }
      box.appendChild(body);
    }

    els.overlayLayer.appendChild(box);
    overlays.push(box);
    requestAnimationFrame(function () { box.classList.add("in"); });

    var life = typeof msg.ms === "number" ? msg.ms : 3000;
    box._timer = setTimeout(function () { dropOverlay(box); }, life);
  }

  function dropOverlay(box) {
    if (!box || box._gone) return;
    box._gone = true;
    clearTimeout(box._timer);
    box.classList.remove("in");
    var i = overlays.indexOf(box);
    if (i >= 0) overlays.splice(i, 1);
    // 等淡出动画走完再摘，否则浮层是"啪"地消失而不是退场
    setTimeout(function () {
      if (box.parentNode) box.parentNode.removeChild(box);
    }, 320);
  }

  function clearOverlay(id) {
    // 不带 id = 全撤；带 id 只撤那一个，别的继续按自己的 ms 走完
    overlays.slice().forEach(function (box) {
      if (!id || box._oid === id) dropOverlay(box);
    });
  }

  /* ── 假浏览器工具栏 ── */
  function applyChrome(msg) {
    if (msg.url !== undefined) els.addrUrl.textContent = msg.url;
    if (msg.title !== undefined) {
      els.tabTitle.textContent = msg.title || "New Tab";
      els.browserTitle.textContent = msg.title || "Chrome";
    }
    if (msg.loading !== undefined) {
      els.spinner.classList.toggle("on", !!msg.loading);
    }
    if (msg.tabs) renderTabs(msg.tabs);
  }

  /* ── 演员标签在不在 ──
     不在就露出空白起始页，把画面遮掉。留着最后那一帧是最坏的选择：它和
     "页面正好没动"长得一模一样，人会对着一张几小时前的截图以为是实时画面。
     地址栏和标签标题一并复位，整扇窗口就是浏览器刚打开的样子。 */
  function applyActorState(alive) {
    if (!els.newtab) return;
    els.newtab.hidden = !!alive;
    if (!alive) {
      els.canvas.width = els.canvas.width;   // 清空画布，别留半张旧图在下面
      els.addrUrl.textContent = "";
      els.spinner.classList.remove("on");
      if (els.tabTitle) els.tabTitle.textContent = "New Tab";
      els.browserTitle.textContent = "Chrome";
    }
  }

  // 标签条镜像舞台 Chrome 的真实 tab 列表；active 标签跟随机位。
  function renderTabs(tabs) {
    els.tabStrip.innerHTML = "";
    tabs.forEach(function (t) {
      var tab = document.createElement("div");
      tab.className = "tab" + (t.active ? " active" : "");
      var fav = document.createElement("span");
      fav.className = "tab-favicon";
      var title = document.createElement("span");
      title.className = "tab-title";
      title.textContent = t.title || "New Tab";
      tab.appendChild(fav);
      tab.appendChild(title);
      els.tabStrip.appendChild(tab);
      if (t.active) els.tabTitle = title;
    });
    // 标签数变了，tab:<n> 的矩形也就变了——快照必须跟着重报，
    // 否则 broker 手上的 ref 表停留在上一批标签上。
    sendLayout();
  }

  /* ── 消息分发 ── */
  function onMessage(ev) {
    var msg;
    try { msg = JSON.parse(ev.data); } catch (e) { return; }
    switch (msg.t) {
      case "hello":
        if (msg.desktop) { CONFIG.desktop = msg.desktop; fitStage(); }
        if (msg.browser) {
          state.viewport = msg.browser;   // 仅供参考，几何不再受它约束
          measureHeaders();
        }
        // 这里不报：补发还没走完，手上还是出厂几何。broker 把整份现状发完
        // 会补一条 synced，那时才报，报的才是真的。
        break;
      case "reload":
        // broker 说这块荧幕的资产过旧了。这是纯显示器，刷新什么都不丢——
        // 状态全部由 broker 补发。不刷的话它会一直连着、一直被丢弃，
        // 而自检天天挂一条"有旧标签开着"，人还得自己认出是哪个标签。
        location.reload();
        break;
      case "synced":
        // 世界状态补发完毕：开关、几何、焦点、终端缓冲区都已就位。
        state.syncing = false;
        sendLayout();
        break;
      case "frame":
        // 有帧就说明演员标签活着。broker 的状态消息是权威，这里只是兜底：
        // 万一那条消息丢了，画面一动起来就该把起始页收掉。
        if (els.newtab && !els.newtab.hidden) applyActorState(true);
        pushFrame(msg.data);
        break;
      case "actor":
        applyActorState(msg.alive);
        break;
      case "term":
        applyTerm(msg);
        break;
      case "term.scroll":
        termScrollTo(msg.top, msg.stuck, msg.ms);
        break;
      case "term.fontsize":
        applyTermFontSize(msg.px);
        break;
      case "cursor":
        moveCursor(msg.x, msg.y, msg.ms, msg.ease);
        break;
      case "click":
        clickEffect(msg.phase);
        break;
      case "focus":
        applyFocus(msg.win);
        break;
      case "win":
        if (!state.geom[msg.win]) break;
        if (msg.action === "close") { closeWin(msg.win, msg.ms); break; }
        if (msg.action === "open") { openWin(msg.win, msg.ms); break; }
        if (msg.action === "min") { minimizeWin(msg.win, msg.ms); break; }
        if (msg.action === "max") { maximizeWin(msg.win, msg.ms); break; }
        if (msg.action === "restore") { restoreWin(msg.win, msg.ms); break; }
        state.geom[msg.win] = { x: msg.x, y: msg.y, w: msg.w, h: msg.h };
        applyGeom(msg.win, state.geom[msg.win], msg.ms);
        sendLayout(); // 元素矩形跟着窗口变了，重报一次快照
        break;
      case "image":
        // 这条只管**内容**：图片浏览器窗口开没开由 win 消息（action: open/close）
        // 决定，和另外两扇窗走同一条路。两者曾经合在一起——"有图=窗口在"——
        // 于是图片浏览器成了唯一一个用别的机制开关的程序，而 window close
        // 对它无效且不报错。
        els.imageTitle.textContent = msg.name || "Preview";
        if (msg.url) {
          // 地址恒为 /image，服务端已带 no-store；这里再加时间戳是双保险，
          // 防任何中间层缓存——否则换图后 <img> 仍是第一张。
          els.imageView.src = msg.url + "?_=" + Date.now();
        } else {
          els.imageView.removeAttribute("src");
        }
        sendLayout();
        break;
      case "chrome":
        applyChrome(msg);
        break;
      case "say":
        showCaption(msg.text, msg.ms);
        break;
      case "overlay":
        showOverlay(msg);
        break;
      case "overlay.clear":
        clearOverlay(msg.id);
        break;
    }
  }

  /* ── 连接管理：断了每秒重连，画面保持最后状态不动 ── */
  function connect() {
    var ws;
    try {
      ws = new WebSocket(CONFIG.brokerWs);
    } catch (e) {
      setTimeout(connect, 1000);
      return;
    }
    state.ws = ws;
    ws.onopen = function () {
      state.wsOpen = true;
      // 每次连上都重新等一遍补发。断线重连时几何其实还是对的，但"对不对"
      // 不该靠这种巧合——统一等 synced，只有一条路，也就只有一种时序。
      state.syncing = true;
      // 每次连上都要重新握手：ready 是"这一台 broker 已经看到我画出画面"的
      // 信号，而 broker 的 ready 标志随进程生死。不重置的话，一个长开的标签页
      // 只在首次加载时发过一次 ready，broker 重启后就永远等不到——ui_ready
      // 一直是 false，而画面其实好好的。假警报比不报警更糟：报久了就没人看了。
      state.firstFrameSent = false;
      // 第一条消息就自报家门。放在 layout 之前，broker 才能在收到任何几何
      // 之前就知道对面是谁——否则它只能等第一份 layout 到了再判断该不该收，
      // 而 /status 在这段空窗期里说不出连着的是哪块荧幕。
      send({
        t: "identify",
        contentId: CONFIG.contentId,
        instanceId: CONFIG.instanceId,
        uiVersion: CONFIG.uiVersion
      });
      sendLayout();
    };
    ws.onmessage = onMessage;
    ws.onclose = function () {
      state.wsOpen = false;
      setTimeout(connect, 1000);
    };
    ws.onerror = function () { ws.close(); };
  }

  /* ── 屏蔽真实鼠标/键盘：这是显示器，不是控制台 ── */
  function blockInput() {
    ["mousedown", "mouseup", "click", "dblclick", "contextmenu",
     "wheel", "keydown", "keyup", "keypress", "selectstart", "dragstart"
    ].forEach(function (type) {
      window.addEventListener(type, function (e) { e.preventDefault(); e.stopPropagation(); }, { capture: true, passive: false });
    });
  }

  /* ── 桌布：噪声网格渐变 ──────────────────────────────────
     窗口只占桌面中间，四周原先是一整片死渐变，录进视频里像贴纸压在纯色板上。

     这里的做法照抄 stripe.com 首页那块渐变（kevinhufnagl 的还原实现）。
     它和"自己画几条色带再模糊"是两条完全不同的路，差别有三处，每一处都
     直接决定成品是高级还是廉价：

     1. **不画任何形状。** 铺一张平面，平面上每个点的颜色由三维单纯形噪声
        (simplex noise) 决定，没有一条边界是人定的。手画的正弦曲线无论怎么
        模糊，看着都像人工吹出来的烟——因为它本来就是。
     2. **混色权重取噪声的四次方。** 半透明色带互相叠加在数学上必然趋向灰
        （青绿叠琥珀出橄榄褐是必然，不是没调好）。四次方让只有噪声很强的
        地方才上色，于是大片区域保持接近纯色，只留很窄的过渡带。
     3. **颜色同色系、明度相近。** 四个颜色是一组，不是各挑各的。

     噪声的第三维走时间：整块色场是在"长"而不是在"移动"，所以看不出运动
     方向，只觉得它活着。顺带它每帧都真的重画一次——CDP 只在页面重绘时
     产帧，桌面静止时帧率掉到 3fps 上下，运镜就会一顿一顿。

     所有数值取自 stripe 实现的默认值，注释里标了原名，改的时候有据可依。 */

  /* 三维单纯形噪声。Stefan Gustavson / Ashima Arts 的公有领域参考实现，
     ES5 直译。不引第三方库是这套 UI 的硬约束（不外链任何 CDN）。 */
  var SNOISE = (function () {
    var G = [[1,1,0],[-1,1,0],[1,-1,0],[-1,-1,0],
             [1,0,1],[-1,0,1],[1,0,-1],[-1,0,-1],
             [0,1,1],[0,-1,1],[0,1,-1],[0,-1,-1]];
    var P = [151,160,137,91,90,15,131,13,201,95,96,53,194,233,7,225,140,36,103,30,69,
      142,8,99,37,240,21,10,23,190,6,148,247,120,234,75,0,26,197,62,94,252,219,203,117,
      35,11,32,57,177,33,88,237,149,56,87,174,20,125,136,171,168,68,175,74,165,71,134,
      139,48,27,166,77,146,158,231,83,111,229,122,60,211,133,230,220,105,92,41,55,46,
      245,40,244,102,143,54,65,25,63,161,1,216,80,73,209,76,132,187,208,89,18,169,200,
      196,135,130,116,188,159,86,164,100,109,198,173,186,3,64,52,217,226,250,124,123,5,
      202,38,147,118,126,255,82,85,212,207,206,59,227,47,16,58,17,182,189,28,42,223,183,
      170,213,119,248,152,2,44,154,163,70,221,153,101,155,167,43,172,9,129,22,39,253,19,
      98,108,110,79,113,224,232,178,185,112,104,218,246,97,228,251,34,242,193,238,210,
      144,12,191,179,162,241,81,51,145,235,249,14,239,107,49,192,214,31,181,199,106,157,
      184,84,204,176,115,121,50,45,127,4,150,254,138,236,205,93,222,114,67,29,24,72,243,
      141,128,195,78,66,215,61,156,180];
    var PP = new Uint8Array(512);
    for (var q = 0; q < 512; q++) PP[q] = P[q & 255];
    var F3 = 1 / 3, G3 = 1 / 6;
    function dot(g, x, y, z) { return g[0] * x + g[1] * y + g[2] * z; }
    return function (x, y, z) {
      var s = (x + y + z) * F3;
      var i = Math.floor(x + s), j = Math.floor(y + s), k = Math.floor(z + s);
      var t = (i + j + k) * G3;
      var x0 = x - (i - t), y0 = y - (j - t), z0 = z - (k - t);
      var i1, j1, k1, i2, j2, k2;
      if (x0 >= y0) {
        if (y0 >= z0)      { i1=1;j1=0;k1=0; i2=1;j2=1;k2=0; }
        else if (x0 >= z0) { i1=1;j1=0;k1=0; i2=1;j2=0;k2=1; }
        else               { i1=0;j1=0;k1=1; i2=1;j2=0;k2=1; }
      } else {
        if (y0 < z0)       { i1=0;j1=0;k1=1; i2=0;j2=1;k2=1; }
        else if (x0 < z0)  { i1=0;j1=1;k1=0; i2=0;j2=1;k2=1; }
        else               { i1=0;j1=1;k1=0; i2=1;j2=1;k2=0; }
      }
      var x1 = x0 - i1 + G3,      y1 = y0 - j1 + G3,      z1 = z0 - k1 + G3;
      var x2 = x0 - i2 + 2 * G3,  y2 = y0 - j2 + 2 * G3,  z2 = z0 - k2 + 2 * G3;
      var x3 = x0 - 1 + 3 * G3,   y3 = y0 - 1 + 3 * G3,   z3 = z0 - 1 + 3 * G3;
      var ii = i & 255, jj = j & 255, kk = k & 255;
      var n = 0, tt;
      tt = 0.6 - x0*x0 - y0*y0 - z0*z0;
      if (tt > 0) { tt *= tt; n += tt * tt * dot(G[PP[ii+PP[jj+PP[kk]]] % 12], x0, y0, z0); }
      tt = 0.6 - x1*x1 - y1*y1 - z1*z1;
      if (tt > 0) { tt *= tt; n += tt * tt * dot(G[PP[ii+i1+PP[jj+j1+PP[kk+k1]]] % 12], x1, y1, z1); }
      tt = 0.6 - x2*x2 - y2*y2 - z2*z2;
      if (tt > 0) { tt *= tt; n += tt * tt * dot(G[PP[ii+i2+PP[jj+j2+PP[kk+k2]]] % 12], x2, y2, z2); }
      tt = 0.6 - x3*x3 - y3*y3 - z3*z3;
      if (tt > 0) { tt *= tt; n += tt * tt * dot(G[PP[ii+1+PP[jj+1+PP[kk+1]]] % 12], x3, y3, z3); }
      return 32 * n;
    };
  })();

  function startWallpaper() {
    var cv = els.wpMesh;
    if (!cv) return;
    var cx = cv.getContext("2d");
    var W = cv.width, H = cv.height;
    var img = cx.createImageData(W, H);
    var buf = img.data;

    /* 配色是一组四个，不是各挑各的：base 打底，另外三个是"波层"，按噪声
       强度往底上盖。同组之内色相相邻、明度相近，混出来才不会发灰。
       换配色：地址栏加 ?wp=<名字>，不带就用 indigo。 */
    var PALETTES = {
      plum:   ["140f26", "4a2a7a", "8f2f5e", "2f5a9e"],  // 深紫 → 洋红 → 蓝（Stripe 原配色降明度）
      indigo: ["101a33", "23306b", "3a3a86", "553f8f"],  // 靛蓝 → 紫罗兰（Linear / Big Sur 深色一路）
      mono:   ["0d1b2e", "14263f", "1b3355", "22406b"],  // 近乎单色的深蓝，只有明度起伏
      forest: ["0a1a18", "123330", "164a44", "1a5e63"]   // 墨绿 → 青，和终端窗口同语系
    };
    function hex2rgb(h) {
      return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
    }
    var pick = (location.search.match(/[?&]wp=([a-z]+)/) || [])[1];
    var PAL = PALETTES[pick] || PALETTES.mono;   // 2026-08-24 改默认：indigo 那档的第四色 #553f8f 在录屏里是一块抢戏的亮紫，深色内容压不住它。mono 只有明度起伏，不跟画面争。还原：app.js.bak-20260824-wp
    var BASE = hex2rgb(PAL[0]);
    // 桌面底色跟着配色走。画布不透明，这层底只在首帧之前和画布放大后
    // 四边那一两像素露出来，颜色对不上就会看见一圈接缝。
    if (cv.parentNode) cv.parentNode.style.background = "#" + PAL[0];
    var LAYERS = [
      { rgb: hex2rgb(PAL[1]) },
      { rgb: hex2rgb(PAL[2]) },
      { rgb: hex2rgb(PAL[3]) }
    ];
    // 每层的噪声参数，值来自 stripe 实现（原名标在后面）。三层频率/速度/
    // 种子都错开，色团才不会同步呼吸——同步了就一眼假。
    for (var li = 0; li < LAYERS.length; li++) {
      var e = li + 1;
      LAYERS[li].fx = 2 + e / 4;            // noiseFreq.x
      LAYERS[li].fy = 3 + e / 4;            // noiseFreq.y
      LAYERS[li].speed = 11 + 0.3 * e;      // noiseSpeed（走第三维＝时间）
      LAYERS[li].flow = 6.5 + 0.3 * e;      // noiseFlow（横向漂移）
      LAYERS[li].seed = 5 + 10 * e;         // noiseSeed
      LAYERS[li].floor = 0.1;               // noiseFloor
      LAYERS[li].ceil = 0.63 + 0.07 * e;    // noiseCeil
    }
    // 全局频率：噪声坐标 = 桌面像素 × 这两个数。整屏只跨约 1.5×2 个噪声
    // 单位，所以画面上是两三团大色块，不是一片细碎纹理——这是"大气"和
    // "廉价"的分界线。
    var FX = 14e-5, FY = 29e-5, TSCALE = 5e-6;   // freqX / freqY / u_global.noiseSpeed
    var REF_W = 1920, REF_H = 1080;

    // 顶部压暗。stripe 只压绿通道（color.g -= pow(...) * 0.4），单通道压暗
    // 会让暗处偏品红而不是单纯变黑，质感来源之一。0.4 是它 hero banner 的
    // 强度，桌面上太重，这里减到 0.16 只留一点色偏。
    var SHADOW_POWER = 6, SHADOW_AMT = 0.08, SHADOW_SKEW = Math.sin(-12);

    function smoothstep(a, b, v) {
      var u = (v - a) / (b - a);
      u = u < 0 ? 0 : u > 1 ? 1 : u;
      return u * u * (3 - 2 * u);
    }

    var t0 = null, last = 0, ms = 0;
    function loop(ts) {
      if (t0 === null) { t0 = ts; last = ts; }
      // 帧间隔钳在 1/15 秒：切后台或掉帧回来时，时间不会一次跳一大段，
      // 画面不会"闪一下"。stripe 原实现同样这么钳。
      ms += Math.min(ts - last, 1000 / 15);
      last = ts;
      var T = ms * TSCALE;

      var p = 0;
      for (var py = 0; py < H; py++) {
        var v = (py + 0.5) / H;
        var ny = (v * 2 - 1) * REF_H * FY;
        var sy = 1 - v;                     // stripe 的 st.y 从底边起算
        for (var px = 0; px < W; px++) {
          var u = (px + 0.5) / W;
          var nx = (u * 2 - 1) * REF_W * FX;
          var r = BASE[0], g = BASE[1], b = BASE[2];
          for (var i = 0; i < LAYERS.length; i++) {
            var L = LAYERS[i];
            var n = SNOISE(nx * L.fx + T * L.flow, ny * L.fy, T * L.speed + L.seed);
            n = smoothstep(L.floor, L.ceil, n / 2 + 0.5);
            var w = n * n * n * n;          // 四次方：只有强噪声处才上色
            if (w > 0.001) {
              r += (L.rgb[0] - r) * w;
              g += (L.rgb[1] - g) * w;
              b += (L.rgb[2] - b) * w;
            }
          }
          // 幂次项本身能到 11 以上（顶边 1.5 的 6 次方），不封顶就会把顶部
          // 的绿通道整个减没，剩红蓝＝一片紫——不管选什么配色都被染成紫色。
          // 先把它归一化到 0..1，再乘强度，最多只拿掉 SHADOW_AMT 那么多。
          var sh = Math.pow(sy + SHADOW_SKEW * u, SHADOW_POWER);
          g -= (sh > 1 ? 1 : sh) * SHADOW_AMT * 255;
          buf[p++] = r;
          buf[p++] = g < 0 ? 0 : g;
          buf[p++] = b;
          buf[p++] = 255;
        }
      }
      cx.putImageData(img, 0, 0);
      requestAnimationFrame(loop);
    }
    requestAnimationFrame(loop);
  }

  /* ── 扫描灯 ──────────────────────────────────────────────
     一个光点沿底边往复扫（KITT 那种），48 格离散灯条，拖尾 6 格。

     它首先是**取景保障**，其次才是装饰：CDP 只在页面重绘时产帧，
     桌面静止时 screencast 掉到 3fps 上下，运镜（推近/摇镜）就会一顿一顿，
     人眼盯着看很难受。canvas 逐帧重画持续触发重绘，实测把帧率钉在 90 上下。

     为什么不用 CSS transform 动画：那个走合成器层，虽然本机实测也能出帧，
     但它依赖浏览器的合成策略，换个版本或开了省电模式就可能不再触发。
     canvas 每帧真的画一次，重绘是确定的。 */
  function startScanline() {
    var c = els.scanline;
    if (!c) return;
    var x = c.getContext("2d");
    var N = 48, W = 1920 / N, GLOW = 6, SPEED = 0.10;
    var t = 0;
    (function loop() {
      t += SPEED;
      // 往复用三角波：0 → N-1 → 0，端点自然减速，不需要额外缓动
      var p = (N - 1) * Math.abs(((t / (N - 1)) % 2) - 1);
      x.clearRect(0, 0, 1920, 18);
      for (var i = 0; i < N; i++) {
        var a = Math.max(0, 1 - Math.abs(i - p) / GLOW);
        a = a * a;                      // 衰减取平方，主光点更突出、拖尾更收敛
        if (a < 0.01) continue;
        x.globalAlpha = a;
        x.fillStyle = "#ff2b2b";
        x.fillRect(i * W + 1, 3, W - 2, 12);
      }
      x.globalAlpha = 1;
      requestAnimationFrame(loop);
    })();
  }

  function boot() {
    els.stage = $("stage");
    els.clock = $("mb-clock");
    els.mbApp = $("mb-app");
    els.winTerm = $("win-term");
    els.winBrowser = $("win-browser");
    els.winImage = $("win-image");
    els.termScroll = $("term-scroll");
    els.termScreen = $("term-screen");
    els.imageView = $("image-view");
    els.imageTitle = $("image-title");
    els.canvas = $("browser-canvas");
    els.ctx = els.canvas.getContext("2d");
    els.dock = $("dock");
    els.dockTerm = $("dock-term");
    els.dockBrowser = $("dock-browser");
    els.dockImage = $("dock-image");
    els.caption = $("caption");
    els.overlayLayer = $("overlay-layer");
    els.vcursor = $("vcursor");
    els.rippleLayer = $("ripple-layer");
    els.scanline = $("scanline");
    els.wpMesh = $("wp-mesh");
    els.addrUrl = $("addr-url");
    els.addr = els.winBrowser.querySelector(".addressbar");
    els.menubar = $("menubar");
    els.tabStrip = $("tab-strip");
    els.tabTitle = $("tab-title");
    els.browserTitle = $("browser-title");
    els.spinner = $("addr-spinner");
    els.newtab = $("browser-newtab");

    fitStage();
    measureHeaders();
    tickClock();
    setInterval(tickClock, 1000);
    window.addEventListener("resize", fitStage);
    blockInput();

    startWallpaper();
    startScanline();
    applyGeom("term", state.geom.term, 0);
    applyGeom("browser", state.geom.browser, 0);
    applyGeom("image", state.geom.image, 0);
    // dock 的灯照初始开关状态点亮。broker 一连上就会补发三个程序各自的真实
    // 状态覆盖这里，这只是连上之前的样子。
    ["term", "browser", "image"].forEach(function (w) {
      dockEl(w).classList.toggle("running", state.open[w]);
      winEl(w).hidden = !state.open[w];
    });
    applyFocus("term");
    moveCursor(CONFIG.desktop.w / 2, CONFIG.desktop.h / 2, 0);

    fetch("config.json")
      .then(function (r) { return r.json(); })
      .then(function (cfg) {
        if (cfg.brokerWs) CONFIG.brokerWs = cfg.brokerWs;
        if (cfg.uiVersion) CONFIG.uiVersion = cfg.uiVersion;
        if (cfg.contentId) CONFIG.contentId = cfg.contentId;
        if (cfg.instanceId) CONFIG.instanceId = cfg.instanceId;
        if (cfg.desktop) { CONFIG.desktop = cfg.desktop; fitStage(); }
      })
      .catch(function () { /* 无 config.json 时用默认值 */ })
      .then(connect);
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
