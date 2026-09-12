/**
 * useReportLayout — 右栏的版面：每一格多高、哪几格折起来、整栏多宽。
 *
 * 由人来定，记在这个浏览器里，下次打开照旧。旁路 AI 每次改的只是格子里的字，格子的
 * 位置和大小不跟着内容跳——人的视线不用重新找位置，这是覆盖型槽位固定高度的本意；
 * 现在只是把「固定成多高」交还给人。
 *
 * 这是一个人在一台机器上的偏好，所以放本地存储。读写都包在 try 里：隐私窗口、清过站点
 * 数据的浏览器里它会读空或者直接抛错，那时版面照默认值画。
 */

import { useCallback, useState } from 'react';

/**
 * 会被整格替换的三格。
 *
 * 「需要你决策」不在这里：它不是时间线上的一段，是唯一一条要人动手的信息，钉在栏顶
 * 单独画（见 ReportPanel 的 CallBanner），不参与折叠和拖高度。
 */
export type CoverKey = 'anchor' | 'now' | 'output';
export type SlotKey = CoverKey | 'happened';

/** 默认高度沿用原来写死的两档：长文的格高一档。 */
export const DEFAULT_HEIGHTS: Record<CoverKey, number> = {
  anchor: 112,
  now: 76,
  output: 76,
};
export const MIN_SLOT_HEIGHT = 44;
export const MAX_SLOT_HEIGHT = 640;
export const MIN_PANEL_WIDTH = 260;
export const MAX_PANEL_WIDTH = 760;
/** 键盘上下左右一下挪多少。 */
export const RESIZE_STEP = 16;

const SLOTS_KEY = 'frago.workbench.reportSlots.v1';
const WIDTH_KEY = 'frago.workbench.reportWidth.v1';

export const clamp = (n: number, lo: number, hi: number) =>
  Math.min(hi, Math.max(lo, Math.round(n)));

function read(key: string): unknown {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function write(key: string, value: unknown) {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* 存不下就只在这一次打开里生效 */
  }
}

interface SlotLayout {
  heights: Record<CoverKey, number>;
  collapsed: SlotKey[];
}

const SLOT_KEYS: SlotKey[] = ['anchor', 'now', 'output', 'happened'];

function initialSlots(): SlotLayout {
  const saved = read(SLOTS_KEY) as Partial<SlotLayout> | null;
  const heights = { ...DEFAULT_HEIGHTS };
  for (const key of Object.keys(DEFAULT_HEIGHTS) as CoverKey[]) {
    const h = saved?.heights?.[key];
    if (typeof h === 'number' && Number.isFinite(h)) {
      heights[key] = clamp(h, MIN_SLOT_HEIGHT, MAX_SLOT_HEIGHT);
    }
  }
  const stored = saved?.collapsed;
  const collapsed = Array.isArray(stored)
    ? stored.filter((k): k is SlotKey => SLOT_KEYS.includes(k as SlotKey))
    : [];
  return { heights, collapsed };
}

export function useSlotLayout() {
  const [layout, setLayout] = useState<SlotLayout>(initialSlots);

  const update = useCallback((next: (prev: SlotLayout) => SlotLayout) => {
    setLayout((prev) => {
      const value = next(prev);
      write(SLOTS_KEY, value);
      return value;
    });
  }, []);

  const setHeight = useCallback(
    (key: CoverKey, h: number) =>
      update((p) => ({
        ...p,
        heights: { ...p.heights, [key]: clamp(h, MIN_SLOT_HEIGHT, MAX_SLOT_HEIGHT) },
      })),
    [update],
  );

  const resetHeight = useCallback(
    (key: CoverKey) =>
      update((p) => ({ ...p, heights: { ...p.heights, [key]: DEFAULT_HEIGHTS[key] } })),
    [update],
  );

  const toggleCollapsed = useCallback(
    (key: SlotKey) =>
      update((p) => ({
        ...p,
        collapsed: p.collapsed.includes(key)
          ? p.collapsed.filter((k) => k !== key)
          : [...p.collapsed, key],
      })),
    [update],
  );

  return {
    heights: layout.heights,
    collapsed: layout.collapsed,
    setHeight,
    resetHeight,
    toggleCollapsed,
  };
}

export type SlotLayoutController = ReturnType<typeof useSlotLayout>;

/** 整栏宽度。null 表示没调过，用页面给的默认宽度。 */
export function useReportWidth() {
  const [width, setWidthState] = useState<number | null>(() => {
    const w = read(WIDTH_KEY);
    return typeof w === 'number' && Number.isFinite(w)
      ? clamp(w, MIN_PANEL_WIDTH, MAX_PANEL_WIDTH)
      : null;
  });

  const setWidth = useCallback((w: number | null) => {
    const value = w === null ? null : clamp(w, MIN_PANEL_WIDTH, MAX_PANEL_WIDTH);
    setWidthState(value);
    write(WIDTH_KEY, value);
  }, []);

  return { width, setWidth };
}
