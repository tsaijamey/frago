/**
 * 会话图片网格组件（`frago image`）：解析 CLI 工具产出的 `frago_ui_component: "image-grid"`
 * 结构化 JSON 数据，供 `RecordCard` 与 `RecordStream` 渲染自适应屏幕的图片网格及点击放大浮窗。
 */

export const UI_IMAGE_GRID_MARKER = 'image-grid';

export interface ImageGridItem {
  /** 浏览器可直接加载的图片 URL（同源 `/api/file?disposition=inline&path=...` 或 `http(s)://...`）。 */
  src: string;
  /** 原始本机绝对路径或互联网 URL，用于浮窗顶栏展示与新标签打开。 */
  raw: string;
  /** 图片短文件名。 */
  name: string;
  /** 可选图注说明。 */
  caption: string | null;
  /** 图片来源分类。 */
  source: 'local' | 'remote';
}

export interface ImageGridBlock {
  type: 'image-grid';
  title: string | null;
  columns: number | null;
  images: ImageGridItem[];
}

type Obj = Record<string, unknown>;

const isObj = (v: unknown): v is Obj => !!v && typeof v === 'object' && !Array.isArray(v);
const asText = (v: unknown): string => (typeof v === 'string' ? v : v == null ? '' : String(v));

/**
 * 将后端或 CLI 传入的图片地址标准化为浏览器可直接请求的 URL。
 */
export function normalizeImageSrc(rawSrc: string): string {
  const trimmed = (rawSrc || '').trim();
  if (!trimmed) return '';
  if (trimmed.startsWith('http://') || trimmed.startsWith('https://')) {
    return trimmed;
  }
  const apiBase = import.meta.env.VITE_API_URL || '';
  if (trimmed.startsWith('/api/')) {
    return `${apiBase}${trimmed}`;
  }
  if (trimmed.startsWith('/')) {
    return `${apiBase}/api/file?disposition=inline&path=${encodeURIComponent(trimmed)}`;
  }
  return trimmed;
}

function deriveName(raw: string, src: string): string {
  const target = raw || src;
  const clean = target.split('?')[0].replace(/\/+$/, '');
  const last = clean.split('/').pop() || target;
  try {
    return decodeURIComponent(last) || last;
  } catch {
    return last;
  }
}

function parseSingleImageItem(item: unknown): ImageGridItem | null {
  if (typeof item === 'string') {
    const trimmed = item.trim();
    if (!trimmed) return null;
    const isRemote = trimmed.startsWith('http://') || trimmed.startsWith('https://');
    const src = normalizeImageSrc(trimmed);
    return {
      src,
      raw: trimmed,
      name: deriveName(trimmed, src),
      caption: null,
      source: isRemote ? 'remote' : 'local',
    };
  }
  if (!isObj(item)) return null;
  const rawSrc = asText(item.src || item.url || item.path).trim();
  if (!rawSrc) return null;
  const rawPath = asText(item.raw || item.path || rawSrc).trim() || rawSrc;
  const src = normalizeImageSrc(rawSrc);
  if (!src) return null;
  const isRemote =
    item.source === 'remote' ||
    rawPath.startsWith('http://') ||
    rawPath.startsWith('https://');
  const name = asText(item.name).trim() || deriveName(rawPath, src);
  const captionRaw =
    item.caption != null
      ? asText(item.caption).trim()
      : item.label != null
        ? asText(item.label).trim()
        : '';
  return {
    src,
    raw: rawPath,
    name,
    caption: captionRaw || null,
    source: isRemote ? 'remote' : 'local',
  };
}

/**
 * 校验已解析的 JSON 对象并构造 `ImageGridBlock`。不合法时返回 null。
 */
export function validateImageGridObject(rawObj: unknown): ImageGridBlock | null {
  if (!isObj(rawObj)) return null;
  const y: Obj =
    rawObj.frago_ui_component === UI_IMAGE_GRID_MARKER && isObj(rawObj.data)
      ? rawObj.data
      : rawObj;
  const type = y.type ?? rawObj.component_type;
  if (type !== UI_IMAGE_GRID_MARKER) return null;

  const rawImages = y.images;
  if (!Array.isArray(rawImages) || !rawImages.length) return null;

  const images: ImageGridItem[] = [];
  for (const item of rawImages) {
    const parsed = parseSingleImageItem(item);
    if (!parsed) return null;
    images.push(parsed);
  }

  const title = typeof y.title === 'string' && y.title.trim() ? y.title.trim() : null;
  let columns: number | null = null;
  if (typeof y.columns === 'number' && Number.isInteger(y.columns) && y.columns >= 1 && y.columns <= 4) {
    columns = y.columns;
  }

  return {
    type: UI_IMAGE_GRID_MARKER,
    title,
    columns,
    images,
  };
}

function findMatchingBrace(src: string, start: number): number {
  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let i = start; i < src.length; i += 1) {
    const ch = src[i];
    if (escaped) {
      escaped = false;
      continue;
    }
    if (inString) {
      if (ch === '\\') escaped = true;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') {
      inString = true;
    } else if (ch === '{') {
      depth += 1;
    } else if (ch === '}') {
      depth -= 1;
      if (depth === 0) return i;
    }
  }
  return -1;
}

/**
 * 从工具输出或回复文本中提取所有合法的 `frago_ui_component: "image-grid"` 组件数据。
 */
export function parseAllImageGridOutputs(raw: string): ImageGridBlock[] {
  if (!raw || !raw.includes('"frago_ui_component"') || !raw.includes(UI_IMAGE_GRID_MARKER)) {
    return [];
  }
  const results: ImageGridBlock[] = [];
  let searchFrom = 0;
  while (searchFrom < raw.length) {
    const markerIdx = raw.indexOf('"frago_ui_component"', searchFrom);
    if (markerIdx < 0) break;
    const start = raw.lastIndexOf('{', markerIdx);
    if (start < 0) {
      searchFrom = markerIdx + 20;
      continue;
    }
    const end = findMatchingBrace(raw, start);
    if (end < 0) {
      searchFrom = markerIdx + 20;
      continue;
    }
    try {
      const parsed: unknown = JSON.parse(raw.slice(start, end + 1));
      if (isObj(parsed) && parsed.frago_ui_component === UI_IMAGE_GRID_MARKER) {
        const block = validateImageGridObject(parsed);
        if (block) results.push(block);
      }
    } catch {
      // 忽略非 JSON 片段
    }
    searchFrom = end + 1;
  }
  return results;
}

/**
 * 解析文本中最后一个 `frago_ui_component: "image-grid"` 组件数据。
 */
export function parseImageGridOutput(raw: string): ImageGridBlock | null {
  const all = parseAllImageGridOutputs(raw);
  return all.length ? all[all.length - 1] : null;
}
