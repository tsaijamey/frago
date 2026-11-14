import { describe, it, expect } from 'vitest';
import {
  SESSION_DETAIL_AUTO_SCROLL_THRESHOLD_PX,
  isViewportCoveringBottom,
} from '../RecordStream';

describe('isViewportCoveringBottom 视口覆盖底部 100px 热区几何判定', () => {
  it('常量阈值为 100px', () => {
    expect(SESSION_DETAIL_AUTO_SCROLL_THRESHOLD_PX).toBe(100);
  });

  it('元素为空或 undefined 时返回 false', () => {
    expect(isViewportCoveringBottom(null)).toBe(false);
    expect(isViewportCoveringBottom(undefined)).toBe(false);
  });

  it('短内容（scrollHeight <= clientHeight）天然覆盖底部', () => {
    // 内容未撑满容器，无需滚动即可看见全量内容与底部
    expect(isViewportCoveringBottom({ scrollTop: 0, scrollHeight: 500, clientHeight: 800 })).toBe(true);
    expect(isViewportCoveringBottom({ scrollTop: 0, scrollHeight: 800, clientHeight: 800 })).toBe(true);
    expect(isViewportCoveringBottom({ scrollTop: 0, scrollHeight: 0, clientHeight: 0 })).toBe(true);
  });

  it('视口底边距底部刚好在 100px 阈值内时判定覆盖', () => {
    // 距底 0px：完全沉底
    expect(isViewportCoveringBottom({ scrollTop: 1200, scrollHeight: 2000, clientHeight: 800 })).toBe(true);
    // 距底 50px：处于底部上方 100px 热区内
    expect(isViewportCoveringBottom({ scrollTop: 1150, scrollHeight: 2000, clientHeight: 800 })).toBe(true);
    // 距底刚好 100px（2000 - 1100 - 800 = 100）
    expect(isViewportCoveringBottom({ scrollTop: 1100, scrollHeight: 2000, clientHeight: 800 })).toBe(true);
  });

  it('高分屏 DPI 缩放下浮点舍入微小误差（+0.5px 容差内）视为覆盖', () => {
    // 距底 100.2px（浮点误差）
    expect(isViewportCoveringBottom({ scrollTop: 1099.8, scrollHeight: 2000, clientHeight: 800 })).toBe(true);
    // 距底 100.5px
    expect(isViewportCoveringBottom({ scrollTop: 1099.5, scrollHeight: 2000, clientHeight: 800 })).toBe(true);
  });

  it('视口底边距底部超出 100px 阈值（101px+）时判定未覆盖', () => {
    // 距底 101px：2000 - 1099 - 800 = 101
    expect(isViewportCoveringBottom({ scrollTop: 1099, scrollHeight: 2000, clientHeight: 800 })).toBe(false);
    // 距底 500px
    expect(isViewportCoveringBottom({ scrollTop: 700, scrollHeight: 2000, clientHeight: 800 })).toBe(false);
    // 初始顶部（scrollTop = 0，距底 1200px）
    expect(isViewportCoveringBottom({ scrollTop: 0, scrollHeight: 2000, clientHeight: 800 })).toBe(false);
  });

  it('支持自定义阈值传参', () => {
    expect(isViewportCoveringBottom({ scrollTop: 1150, scrollHeight: 2000, clientHeight: 800 }, 30)).toBe(false);
    expect(isViewportCoveringBottom({ scrollTop: 1180, scrollHeight: 2000, clientHeight: 800 }, 30)).toBe(true);
  });
});
