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
export type MediaPreviewKind = 'image' | 'video' | 'audio' | 'pdf';

const MARKDOWN_EXTS = new Set(['md', 'markdown']);
const HTML_EXTS = new Set(['html', 'htm']);
const IMAGE_EXTS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'ico', 'avif']);
const VIDEO_EXTS = new Set(['mp4', 'webm', 'mov', 'm4v', 'mkv', 'avi']);
const AUDIO_EXTS = new Set(['mp3', 'wav', 'ogg', 'm4a', 'flac', 'aac']);

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

/**
 * 判断文件是否属于浏览器原生可渲染的多媒体/二进制预览类型（图片、视频、音频、PDF）。
 */
export function mediaKindOf(path: string): MediaPreviewKind | null {
  const base = baseOf(path);
  const cut = base.lastIndexOf('.');
  if (cut <= 0 || cut === base.length - 1) return null;
  const ext = base.slice(cut + 1).toLowerCase();
  if (IMAGE_EXTS.has(ext)) return 'image';
  if (VIDEO_EXTS.has(ext)) return 'video';
  if (AUDIO_EXTS.has(ext)) return 'audio';
  if (ext === 'pdf') return 'pdf';
  return null;
}

const EDITABLE_TEXT_EXTS = new Set([
  'md',
  'markdown',
  'mdx',
  'txt',
  'text',
  'rst',
  'adoc',
  'org',
  'csv',
  'tsv',
  'log',
  'json',
  'jsonc',
  'yaml',
  'yml',
  'toml',
  'ini',
  'cfg',
  'conf',
]);

/**
 * 判断文件是否支持在 FileViewer 中直接进入「编辑 (Edit)」模式。
 * 当且仅当 md、txt 或类似文稿/纯文本类型文件时允许直接编辑；代码与二进制文件返回 false。
 */
export function isEditableTextFile(path: string): boolean {
  const base = baseOf(path);
  const cut = base.lastIndexOf('.');
  if (cut <= 0 || cut === base.length - 1) return false;
  const ext = base.slice(cut + 1).toLowerCase();
  return EDITABLE_TEXT_EXTS.has(ext);
}

/**
 * 路径过长时节省中间部分：保留开头与结尾，中间用省略号「…」连起。
 * 例如：`~/Repos/very-long-project-name/sub/folder` → `~/Repos/…/sub/folder`
 * 悬停提示（title）保留完整路径，此处只为在标题行容纳用量与模型信息。
 */
export function shortenPathMiddle(path: string, maxLength = 32): string {
  if (!path || path.length <= maxLength) return path;

  // 统一用当前路径中占主导的分隔符
  const sep = path.includes('\\') && !path.includes('/') ? '\\' : '/';
  const segments = path.split(sep);

  if (segments.length <= 2) {
    const headLen = Math.max(4, Math.floor((maxLength - 1) / 2));
    const tailLen = maxLength - 1 - headLen;
    return `${path.slice(0, headLen)}…${path.slice(-tailLen)}`;
  }

  const first = segments[0] || (path.startsWith(sep) ? sep : '');
  const last = segments[segments.length - 1];

  // 如果首段 + 尾段拼起来已经超长，按纯字符切首尾
  if (`${first}${sep}…${sep}${last}`.length > maxLength) {
    const tailLen = Math.min(last.length, Math.floor(maxLength * 0.6));
    const headLen = Math.max(3, maxLength - 1 - tailLen);
    return `${path.slice(0, headLen)}…${path.slice(-tailLen)}`;
  }

  let headIdx = 0;
  let tailIdx = segments.length - 1;
  let headParts = [segments[0]];
  let tailParts = [segments[tailIdx]];

  while (headIdx < tailIdx - 1) {
    // 优先尝试保留末尾上一级父目录
    const prevTailIdx = tailIdx - 1;
    if (prevTailIdx > headIdx) {
      const nextTail = segments[prevTailIdx];
      const candidateTail = [nextTail, ...tailParts];
      const candidateLen = [...headParts, '…', ...candidateTail].join(sep).length;
      if (candidateLen <= maxLength) {
        tailParts = candidateTail;
        tailIdx = prevTailIdx;
        continue;
      }
    }

    // 其次尝试保留开头的下一级目录
    const nextHeadIdx = headIdx + 1;
    if (nextHeadIdx < tailIdx) {
      const nextHead = segments[nextHeadIdx];
      const candidateHead = [...headParts, nextHead];
      const candidateLen = [...candidateHead, '…', ...tailParts].join(sep).length;
      if (candidateLen <= maxLength) {
        headParts = candidateHead;
        headIdx = nextHeadIdx;
        continue;
      }
    }

    break;
  }

  return [...headParts, '…', ...tailParts].join(sep);
}

/** 悬停说明与水位读数里 k 为单位的写法：312k。 */
export function formatTokensK(n: number): string {
  return `${Math.round(n / 1000)}k`;
}

/**
 * 本场累计到七位数，用 k 写成一串谁读不出量级，收一档到 M：30.1M。
 * 百万以下还是 k，跟上下文用同一把尺子。
 */
export function formatTokensM(n: number): string {
  if (n < 1_000_000) return formatTokensK(n);
  return `${(n / 1_000_000).toFixed(1)}M`;
}


