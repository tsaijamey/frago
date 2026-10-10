/**
 * 代码染色用的那个引擎，按需取。
 *
 * 挑的是 **highlight.js**：没运行时依赖、语言定义自带、三个候选里体积最小（原型那一轮比过，
 * 见 `20260924-page-polish/design-notes.md`）。用 `lib/common` 那一档——三十几种常用语言，
 * 盖得住本机会话里改过的那些东西，比全量小得多。实测本机打包：+166 KB（gzip 后 +55 KB），
 * 主包从 411 KB 到 466 KB。
 *
 * **走动态 `import()`，但这个仓库里它不省下载**：WebUI 打成一份 IIFE（`inlineDynamicImports`，
 * 为了 `file://` 下没有 CORS 问题），打包时动态引用会被并进同一个文件。省下的是**执行**——
 * 那一段代码第一次要染色时才跑，没点过浮窗预览的人不为它付解析与初始化的时间。写法照旧留着
 * 模块边界：哪天打包方式换了，它自己就切成单独一份。
 *
 * 取不到（引擎跑不起来）不算错：调用方退回纯文本，内容照样完整可读。
 */

import type { HLJSApi } from 'highlight.js';

let pending: Promise<HLJSApi> | null = null;

/** 拿引擎。第一次调用才去加载那一段代码，之后交回同一份。 */
export function loadHighlighter(): Promise<HLJSApi> {
  if (!pending) {
    pending = import('highlight.js/lib/common').then((mod) => mod.default);
  }
  return pending;
}

/**
 * 正文多长以上就不染色了（字符数）。
 *
 * 染色是逐字符跑的，半兆的压缩包文本会让这一下卡住好几秒——点一个文件白屏几秒，比没有颜色
 * 坏得多。过了这条线按纯文本摆，内容一个字不少。服务端那边的取内容上限是 512 KB。
 */
export const MAX_HIGHLIGHT_CHARS = 200_000;

/**
 * 认不出语言时（`lang` 空、或引擎里没这门语言）交给引擎自己猜的字数上限。
 *
 * 自己猜要把所有语言都试一遍，是上面那条的十几倍贵，所以门槛压得低得多，认得出语言的
 * 那些照旧走到 `MAX_HIGHLIGHT_CHARS`。
 */
export const MAX_AUTODETECT_CHARS = 40_000;
