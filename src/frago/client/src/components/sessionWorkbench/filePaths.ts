/**
 * 会话文件那几处的路径处理：列表按目录归组、页头与浮窗顶部都要把家目录缩成 `~`、
 * 按扩展名认出是什么语言好染色。
 *
 * 只做**显示层**的缩写与切分，NEVER 在这里拼服务端要用的路径——服务端认的是会话记录里
 * 那个原样的路径（`SessionFileRow.path`），一拼就与它的白名单对不上了。会话记录里的路径
 * 本来就可能是 `~` 开头或相对写法，所以「原样那份」交出去、这里这份只用来摆。
 */

/** 家目录缩成 `~`。首段是 `Users` 或 `home` 时把 `/<首段>/<用户名>` 换掉，其余原样。 */
export function withTilde(dir: string): string {
  return dir.replace(/^\/(?:Users|home)\/[^/]+/, '~');
}

/**
 * 路径最后一段（文件名）。末尾的斜杠先去掉：服务端给的路径不带尾斜杠，但人手上的标注、
 * 复制粘贴过来的可能带。
 */
export function baseOf(path: string): string {
  const trimmed = path.replace(/\/+$/, '');
  const cut = trimmed.lastIndexOf('/');
  return cut === -1 ? trimmed : trimmed.slice(cut + 1);
}

/**
 * 路径所在的目录。没有斜杠那一层就返回空串——相对写法或光秃秃一个文件名都归到空目录，
 * 界面上就是「不分目录，平铺」。根目录（`/a`）的目录是 `/`。
 */
export function dirOf(path: string): string {
  const trimmed = path.replace(/\/+$/, '');
  const cut = trimmed.lastIndexOf('/');
  if (cut === -1) return '';
  return cut === 0 ? '/' : trimmed.slice(0, cut);
}

/**
 * 扩展名（或几个固定名字）→ highlight.js 的语言名。认不出返回空串，那边按纯文本摆。
 *
 * 认不出的**不许猜近似的**：猜错了染出来的颜色让人读错结构，比不染色更坏。几个没有扩展名
 * 的常见名字（`Makefile`、`Dockerfile`）照名字认。
 */
const BY_EXTENSION: Record<string, string> = {
  py: 'python',
  pyi: 'python',
  js: 'javascript',
  mjs: 'javascript',
  cjs: 'javascript',
  jsx: 'javascript',
  ts: 'typescript',
  mts: 'typescript',
  cts: 'typescript',
  tsx: 'typescript',
  json: 'json',
  jsonc: 'json',
  sh: 'bash',
  bash: 'bash',
  zsh: 'bash',
  fish: 'bash',
  yml: 'yaml',
  yaml: 'yaml',
  md: 'markdown',
  markdown: 'markdown',
  css: 'css',
  scss: 'scss',
  less: 'less',
  html: 'xml',
  htm: 'xml',
  xml: 'xml',
  svg: 'xml',
  plist: 'xml',
  vue: 'xml',
  sql: 'sql',
  go: 'go',
  rs: 'rust',
  toml: 'ini',
  ini: 'ini',
  cfg: 'ini',
  conf: 'ini',
  java: 'java',
  c: 'c',
  h: 'c',
  cpp: 'cpp',
  cc: 'cpp',
  cxx: 'cpp',
  hpp: 'cpp',
  hh: 'cpp',
  rb: 'ruby',
  php: 'php',
  swift: 'swift',
  kt: 'kotlin',
  kts: 'kotlin',
  lua: 'lua',
  r: 'r',
  pl: 'perl',
  scala: 'scala',
  diff: 'diff',
  patch: 'diff',
};

const BY_NAME: Record<string, string> = {
  dockerfile: 'dockerfile',
  makefile: 'makefile',
  'gemfile': 'ruby',
  'go.mod': 'go',
};

/** 这个路径是哪种语言。认不出返回空串。 */
export function langOf(path: string): string {
  const base = baseOf(path);
  const named = BY_NAME[base.toLowerCase()];
  if (named) return named;
  const cut = base.lastIndexOf('.');
  if (cut <= 0 || cut === base.length - 1) return '';
  return BY_EXTENSION[base.slice(cut + 1).toLowerCase()] ?? '';
}

export type DocPreviewKind = 'markdown' | 'html';

const MARKDOWN_EXTS = new Set(['md', 'markdown']);
const HTML_EXTS = new Set(['html', 'htm']);

/**
 * 判断文件是否支持在 FileViewer 中直接进行文档渲染预览（目前针对 Markdown 与 HTML）。
 * 其他代码文件返回 null，仅展示「内容 / 改动」两档。
 */
export function previewKindOf(path: string): DocPreviewKind | null {
  const base = baseOf(path);
  const cut = base.lastIndexOf('.');
  if (cut <= 0 || cut === base.length - 1) return null;
  const ext = base.slice(cut + 1).toLowerCase();
  if (MARKDOWN_EXTS.has(ext)) return 'markdown';
  if (HTML_EXTS.has(ext)) return 'html';
  return null;
}

