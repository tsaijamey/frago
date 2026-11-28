/**
 * Digital Employee DiceBear Micah Avatar Utility (100% Offline).
 *
 * - Uses bundled `@dicebear/core` + `@dicebear/micah` with zero external CDN requests.
 * - Renders Micah SVGs as `data:image/svg+xml;utf8,...` inside `<img>` tags so internal
 *   SVG `<clipPath>` / `<g id="headStandard-...">` IDs never collide across multiple avatars.
 * - Matches backend `frago.employee.avatar` deterministic hash & 8-color low-saturation
 *   architectural backdrop palette bit-for-bit.
 */

import { createAvatar } from '@dicebear/core';
import * as micah from '@dicebear/micah';

export interface AvatarPaletteEntry {
  id: string;
  hex: string;
  labelZh: string;
  labelEn: string;
}

export const AVATAR_BG_PALETTE: readonly AvatarPaletteEntry[] = [
  { id: 'mist-blue', hex: '#e8edf3', labelZh: '雾蓝', labelEn: 'Mist Blue' },
  { id: 'sage', hex: '#e6efe9', labelZh: '鼠尾草', labelEn: 'Sage' },
  { id: 'oat', hex: '#f3ece4', labelZh: '燕麦米', labelEn: 'Oat' },
  { id: 'lilac', hex: '#ece8f5', labelZh: '淡丁香', labelEn: 'Lilac' },
  { id: 'dust-rose', hex: '#f5e8eb', labelZh: '烟灰粉', labelEn: 'Dust Rose' },
  { id: 'glacier', hex: '#e5eef2', labelZh: '冰川青', labelEn: 'Glacier' },
  { id: 'warm-sand', hex: '#efeae1', labelZh: '暖砂', labelEn: 'Warm Sand' },
  { id: 'mineral', hex: '#e8ebf0', labelZh: '矿石灰', labelEn: 'Mineral' },
] as const;

export const MAX_AVATAR_UPLOAD_BYTES = 2 * 1024 * 1024; // 2 MiB

export const ALLOWED_AVATAR_MIME_TYPES = new Set([
  'image/png',
  'image/jpeg',
  'image/webp',
]);

export const ALLOWED_AVATAR_EXTENSIONS = new Set(['.png', '.jpg', '.jpeg', '.webp']);

export type AvatarKind = 'default' | 'micah' | 'upload';

export interface EmployeeAvatarSpec {
  kind: AvatarKind;
  seed?: string;
  bg_color?: string;
  palette_id?: string;
  upload_file?: string | null;
  mime_type?: string | null;
  updated_at?: string;
}

export interface EmployeeAvatarResolved {
  kind: AvatarKind;
  effective_kind: AvatarKind;
  seed: string;
  bg_color: string;
  palette_id: string;
  mime_type?: string | null;
  upload_url?: string | null;
  fallback_reason?: 'missing' | 'corrupted' | 'unreadable' | null;
  updated_at?: string;
}

export interface AvatarCandidate {
  seed: string;
  bgColor: string;
  paletteId: string;
  labelZh: string;
  labelEn: string;
}

export type AvatarDraft =
  | {
      kind: 'default';
      seed: string;
      bgColor: string;
      paletteId: string;
    }
  | {
      kind: 'micah';
      seed: string;
      bgColor: string;
      paletteId: string;
    }
  | {
      kind: 'upload';
      dataUrl: string;
      fileName: string;
      mimeType: string;
      existingUrl?: string | null;
    };

export type AvatarFileValidationError =
  | 'empty_file'
  | 'unsupported_type'
  | 'file_too_large';

/**
 * Deterministic unsigned 32-bit hash identical to backend `stable_avatar_hash`.
 */
export function stableAvatarHash(text: string): number {
  let h = 0;
  for (let i = 0; i < text.length; i += 1) {
    h = (Math.imul(h, 31) + text.charCodeAt(i)) >>> 0;
  }
  return h;
}

export function defaultAvatarPalette(memberPostId: string): AvatarPaletteEntry {
  const key = (memberPostId || '').trim() || 'employee';
  const idx = stableAvatarHash(key) % AVATAR_BG_PALETTE.length;
  return AVATAR_BG_PALETTE[idx];
}

export function defaultAvatarSeed(memberPostId: string): string {
  return (memberPostId || '').trim() || 'employee';
}

export function defaultAvatarSpec(memberPostId: string): {
  kind: 'default';
  seed: string;
  bg_color: string;
  palette_id: string;
} {
  const palette = defaultAvatarPalette(memberPostId);
  return {
    kind: 'default',
    seed: defaultAvatarSeed(memberPostId),
    bg_color: palette.hex,
    palette_id: palette.id,
  };
}

export function findPaletteEntry(
  bgColor?: string | null,
  paletteId?: string | null
): AvatarPaletteEntry | undefined {
  if (paletteId) {
    const byId = AVATAR_BG_PALETTE.find((p) => p.id === paletteId);
    if (byId) return byId;
  }
  if (bgColor) {
    const clean = bgColor.trim().toLowerCase();
    return AVATAR_BG_PALETTE.find((p) => p.hex.toLowerCase() === clean);
  }
  return undefined;
}

const MICAH_URI_CACHE = new Map<string, string>();
const MAX_CACHE_SIZE = 500;

function normalizeHexNoHash(bgColor: string): string {
  const clean = (bgColor || '').trim().replace(/^#/, '').toLowerCase();
  if (/^[0-9a-f]{6}$/.test(clean)) return clean;
  return 'e8edf3';
}

/**
 * Generates an isolated `data:image/svg+xml;utf8,...` URI for a DiceBear Micah avatar.
 * Offline-only, cached in memory.
 */
export function generateMicahDataUri(seed: string, bgColor: string): string {
  const safeSeed = (seed || '').trim() || 'employee';
  const hexNoHash = normalizeHexNoHash(bgColor);
  const cacheKey = `${safeSeed}|${hexNoHash}`;
  const cached = MICAH_URI_CACHE.get(cacheKey);
  if (cached) return cached;

  const svg = createAvatar(micah, {
    seed: safeSeed,
    backgroundColor: [hexNoHash],
    radius: 50,
  }).toString();

  const uri = `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
  if (MICAH_URI_CACHE.size >= MAX_CACHE_SIZE) {
    const firstKey = MICAH_URI_CACHE.keys().next().value;
    if (firstKey !== undefined) {
      MICAH_URI_CACHE.delete(firstKey);
    }
  }
  MICAH_URI_CACHE.set(cacheKey, uri);
  return uri;
}

/**
 * Generates a 4x2 (8-item) deterministic shuffle batch of DiceBear Micah candidates
 * across all 8 architectural backdrop colors.
 */
export function generateShuffleBatch(
  memberPostId: string,
  batchIndex: number
): AvatarCandidate[] {
  const baseKey = defaultAvatarSeed(memberPostId);
  const startPalette = (stableAvatarHash(baseKey) + batchIndex * 5) % AVATAR_BG_PALETTE.length;
  const out: AvatarCandidate[] = [];
  for (let i = 0; i < 8; i += 1) {
    const palette = AVATAR_BG_PALETTE[(startPalette + i) % AVATAR_BG_PALETTE.length];
    const seed =
      batchIndex === 0 && i === 0
        ? baseKey
        : `${baseKey}-pick-${batchIndex}-${i}`;
    out.push({
      seed,
      bgColor: palette.hex,
      paletteId: palette.id,
      labelZh: palette.labelZh,
      labelEn: palette.labelEn,
    });
  }
  return out;
}

export function validateAvatarFileClient(
  file: File
): { ok: true; mimeType: string } | { ok: false; error: AvatarFileValidationError } {
  if (!file || file.size <= 0) {
    return { ok: false, error: 'empty_file' };
  }
  if (file.size > MAX_AVATAR_UPLOAD_BYTES) {
    return { ok: false, error: 'file_too_large' };
  }
  const name = (file.name || '').toLowerCase();
  const dotIdx = name.lastIndexOf('.');
  const ext = dotIdx >= 0 ? name.slice(dotIdx) : '';
  const mime = (file.type || '').toLowerCase();

  // Strictly block SVG / HTML / scriptable formats even if browser reports odd mime.
  if (ext === '.svg' || mime === 'image/svg+xml' || mime.includes('svg') || mime.includes('html')) {
    return { ok: false, error: 'unsupported_type' };
  }

  const mimeOk = mime ? ALLOWED_AVATAR_MIME_TYPES.has(mime) : false;
  const extOk = ext ? ALLOWED_AVATAR_EXTENSIONS.has(ext) : false;
  if (!mimeOk && !extOk) {
    return { ok: false, error: 'unsupported_type' };
  }
  if (mime && !ALLOWED_AVATAR_MIME_TYPES.has(mime)) {
    return { ok: false, error: 'unsupported_type' };
  }
  if (ext && !ALLOWED_AVATAR_EXTENSIONS.has(ext)) {
    return { ok: false, error: 'unsupported_type' };
  }

  const resolvedMime =
    mime ||
    (ext === '.png'
      ? 'image/png'
      : ext === '.webp'
        ? 'image/webp'
        : 'image/jpeg');
  return { ok: true, mimeType: resolvedMime };
}

export function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === 'string') {
        resolve(reader.result);
      } else {
        reject(new Error('Failed to read image file'));
      }
    };
    reader.onerror = () => reject(reader.error ?? new Error('Failed to read image file'));
    reader.readAsDataURL(file);
  });
}

export function avatarDraftFromResolved(
  memberPostId: string,
  resolved?: EmployeeAvatarResolved | null
): AvatarDraft {
  const def = defaultAvatarSpec(memberPostId);
  if (!resolved) {
    return {
      kind: 'default',
      seed: def.seed,
      bgColor: def.bg_color,
      paletteId: def.palette_id,
    };
  }
  if (resolved.effective_kind === 'upload' && resolved.upload_url) {
    return {
      kind: 'upload',
      dataUrl: resolved.upload_url,
      fileName: 'custom-avatar',
      mimeType: resolved.mime_type || 'image/png',
      existingUrl: resolved.upload_url,
    };
  }
  if (resolved.effective_kind === 'micah') {
    const palette =
      findPaletteEntry(resolved.bg_color, resolved.palette_id) ??
      defaultAvatarPalette(memberPostId);
    return {
      kind: 'micah',
      seed: resolved.seed || def.seed,
      bgColor: palette.hex,
      paletteId: palette.id,
    };
  }
  return {
    kind: 'default',
    seed: def.seed,
    bgColor: def.bg_color,
    paletteId: def.palette_id,
  };
}

export function isDraftDefault(memberPostId: string, draft: AvatarDraft): boolean {
  if (draft.kind === 'default') return true;
  if (draft.kind !== 'micah') return false;
  const def = defaultAvatarSpec(memberPostId);
  return (
    draft.seed === def.seed &&
    draft.bgColor.toLowerCase() === def.bg_color.toLowerCase()
  );
}
