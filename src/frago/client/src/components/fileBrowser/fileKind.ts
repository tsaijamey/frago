/**
 * 一份文件该按哪一类摆出来。
 *
 * 只看扩展名，不看内容。理由是人点开一份文件之前就已经知道它是什么——决定用哪种摆法
 * 的是名字，而名字在清单里就有；内容是什么要取回来才知道，那一步在预览那一侧做。
 *
 * 认不出来的扩展名归 `code`，按文本试一次：认错成文本的代价是看到一段乱码，比把一份
 * 代码当成打不开的二进制好。反过来，下面 `BINARY` 里那些一眼就知道不是文本的，不去
 * 试。
 */

export type FileKind =
  | 'image'
  | 'video'
  | 'audio'
  | 'pdf'
  | 'html'
  | 'markdown'
  | 'code'
  | 'binary';

const IMAGE = new Set(['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'bmp', 'ico', 'avif']);
const VIDEO = new Set(['mp4', 'webm', 'mov', 'm4v', 'mkv', 'avi']);
const AUDIO = new Set(['mp3', 'wav', 'ogg', 'm4a', 'flac', 'aac']);
const MARKDOWN = new Set(['md', 'markdown']);
const HTML = new Set(['html', 'htm']);

/**
 * 一眼就知道不是文本的。
 *
 * 字体、压缩包、可执行文件、数据库：这些都是按字节喂给浏览器的，拿去当文本读只会白读
 * 一遍再报错。`lock` 这类看着像二进制的扩展名不在里面——它们其实是文本。
 */
const BINARY = new Set([
  'zip', 'gz', 'tgz', 'bz2', 'xz', '7z', 'rar', 'tar',
  'dmg', 'pkg', 'exe', 'dll', 'so', 'dylib', 'o', 'a', 'class', 'jar', 'wasm',
  'woff', 'woff2', 'ttf', 'otf', 'eot',
  'db', 'sqlite', 'sqlite3', 'bin', 'pyc', 'pdb', 'psd', 'sketch',
]);

/** 扩展名，小写，不带那个点。没有扩展名时是空串。 */
export function extensionOf(name: string): string {
  const base = name.slice(name.lastIndexOf('/') + 1);
  const cut = base.lastIndexOf('.');
  // 开头的点不算扩展名：`.gitignore` 是文件名就叫这个，不是「无名的 gitignore 文件」。
  if (cut <= 0) return '';
  return base.slice(cut + 1).toLowerCase();
}

export function kindOf(name: string): FileKind {
  const ext = extensionOf(name);
  if (IMAGE.has(ext)) return 'image';
  if (VIDEO.has(ext)) return 'video';
  if (AUDIO.has(ext)) return 'audio';
  if (ext === 'pdf') return 'pdf';
  if (HTML.has(ext)) return 'html';
  if (MARKDOWN.has(ext)) return 'markdown';
  if (BINARY.has(ext)) return 'binary';
  return 'code';
}

/** 这一类是不是「交给浏览器自己的标签去取」的：图片、音视频、pdf 都走这条路。 */
export function isNative(kind: FileKind): boolean {
  return kind === 'image' || kind === 'video' || kind === 'audio' || kind === 'pdf';
}
