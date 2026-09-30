/**
 * 从人说的那句话里认出随附的图片。
 *
 * 会话页发图走的是「内容上传、路径下发」：服务端把图落盘到 `~/.frago/webui_uploads/<目录>/`，
 * 再在这句话尾巴上拼一段「[附带图片，…]:」加每行一个绝对路径（见服务端
 * `webui_uploads.build_prompt_with_attachments`）。agent 靠这几行去打开图，人却只看到一串
 * 十六进制路径。这里把那一段从正文里摘出来，交给界面摆成缩略图。
 *
 * 标记行 MUST 与服务端那一句逐字一致——那边改一个字，这里就认不出来，正文会原样露出路径。
 */

export const IMAGE_BLOCK_MARKER = '[附带图片，请用读文件的工具逐一打开查看]:';

export interface AttachedImageRef {
  /** 盘上的绝对路径，原样保留，浮窗里给人看、给人复制。 */
  path: string;
  /** 文件名。 */
  name: string;
  /** 能经服务端取回时的地址；不在 webui_uploads 底下的路径取不回，为 null。 */
  url: string | null;
}

const UPLOAD_PATH_RE = /\/webui_uploads\/([A-Za-z0-9_-]+)\/([A-Za-z0-9_-][A-Za-z0-9._-]*)$/;

function toRef(path: string): AttachedImageRef {
  const m = UPLOAD_PATH_RE.exec(path);
  const name = path.split('/').pop() || path;
  const url = m
    ? `${import.meta.env.VITE_API_URL || ''}/api/workbench/uploads/${encodeURIComponent(m[1])}/${encodeURIComponent(m[2])}`
    : null;
  return { path, name, url };
}

/**
 * 把正文拆成「人写的话」与「随附的图」。没有那一段时原样返回、图为空。
 *
 * 图片段到下一个空行为止——后面可能还跟着一段「[附带文档，…]」，那段原样留在正文里。
 */
export function splitAttachedImages(text: string): { text: string; images: AttachedImageRef[] } {
  const at = text.indexOf(IMAGE_BLOCK_MARKER);
  if (at < 0) return { text, images: [] };

  const after = text.slice(at + IMAGE_BLOCK_MARKER.length);
  const end = after.search(/\n\s*\n/);
  const block = end < 0 ? after : after.slice(0, end);
  const rest = end < 0 ? '' : after.slice(end);

  const images = block
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map(toRef);
  if (!images.length) return { text, images: [] };

  const remaining = (text.slice(0, at) + rest).replace(/\n{3,}/g, '\n\n').trim();
  return { text: remaining, images };
}
