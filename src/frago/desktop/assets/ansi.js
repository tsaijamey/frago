/* ANSI(SGR) → HTML。只处理 SGR 着色，其余转义序列全部吞掉。 */
(function (global) {
  "use strict";

  var BASE = [
    "#14161c", "#e06c75", "#98c379", "#e5c07b",
    "#61afef", "#c678dd", "#56b6c2", "#d8dee9"
  ];
  var BRIGHT = [
    "#5c6370", "#ff7b86", "#a9dc8e", "#f0cf8f",
    "#79c0ff", "#d8a0e8", "#6fd3de", "#ffffff"
  ];
  var DEFAULT_FG = "#d8dee9";
  var DEFAULT_BG = null; // 透明，露出终端底色

  function esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // 256 色索引 → css 颜色（16 基础 + 6×6×6 立方 + 24 级灰）
  function color256(n) {
    n = n | 0;
    if (n < 8) return BASE[n];
    if (n < 16) return BRIGHT[n - 8];
    if (n < 232) {
      n -= 16;
      var steps = [0, 95, 135, 175, 215, 255];
      var r = steps[(n / 36) | 0], g = steps[((n / 6) | 0) % 6], b = steps[n % 6];
      return "rgb(" + r + "," + g + "," + b + ")";
    }
    var v = 8 + (n - 232) * 10;
    return "rgb(" + v + "," + v + "," + v + ")";
  }

  function freshState() {
    return { fg: null, bg: null, bold: false, inverse: false };
  }

  function applySgr(state, params) {
    if (!params.length) params = [0];
    for (var i = 0; i < params.length; i++) {
      var p = params[i];
      if (p === 0) { var s = freshState(); state.fg = s.fg; state.bg = s.bg; state.bold = s.bold; state.inverse = s.inverse; }
      else if (p === 1) state.bold = true;
      else if (p === 22) state.bold = false;
      else if (p === 7) state.inverse = true;
      else if (p === 27) state.inverse = false;
      else if (p >= 30 && p <= 37) state.fg = BASE[p - 30];
      else if (p === 38 || p === 48) {
        var target = p === 38 ? "fg" : "bg";
        if (params[i + 1] === 5) { state[target] = color256(params[i + 2]); i += 2; }
        else if (params[i + 1] === 2) {
          state[target] = "rgb(" + (params[i + 2] | 0) + "," + (params[i + 3] | 0) + "," + (params[i + 4] | 0) + ")";
          i += 4;
        }
      }
      else if (p === 39) state.fg = null;
      else if (p >= 40 && p <= 47) state.bg = BASE[p - 40];
      else if (p === 49) state.bg = null;
      else if (p >= 90 && p <= 97) state.fg = BRIGHT[p - 90];
      else if (p >= 100 && p <= 107) state.bg = BRIGHT[p - 100];
      // 其余 SGR 参数（下划线、闪烁、斜体等）静默忽略
    }
  }

  function openSpan(state) {
    var fg = state.fg || DEFAULT_FG;
    var bg = state.bg || DEFAULT_BG;
    if (state.inverse) {
      var t = fg;
      fg = bg || "#14161c";
      bg = t;
    }
    var css = "";
    if (fg) css += "color:" + fg + ";";
    if (bg) css += "background-color:" + bg + ";";
    if (state.bold) css += "font-weight:700;";
    return css ? '<span style="' + css + '">' : "<span>";
  }

  // 吞掉所有非 SGR 的转义：CSI（非 m 结尾）、OSC、单字符 ESC 序列、其他 C0 控制符
  var TOKEN = /\x1b\[([0-9;]*)m|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?|\x1b\[[0-9;?]*[ -\/]*[@-~]|\x1b[@-_]|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g;

  function ansiToHtml(text) {
    var state = freshState();
    var out = [];
    var last = 0;
    var m;
    TOKEN.lastIndex = 0;
    function flush(end) {
      if (end > last) out.push(openSpan(state) + esc(text.slice(last, end)) + "</span>");
    }
    while ((m = TOKEN.exec(text)) !== null) {
      flush(m.index);
      last = TOKEN.lastIndex;
      if (m[1] !== undefined) {
        var params = m[1].length ? m[1].split(";").map(function (x) { return x === "" ? 0 : parseInt(x, 10); }) : [];
        applySgr(state, params);
      }
      // 其他匹配（非 SGR 转义、控制符）直接丢弃
    }
    flush(text.length);
    return out.join("");
  }

  global.ansiToHtml = ansiToHtml;
})(typeof window !== "undefined" ? window : globalThis);
