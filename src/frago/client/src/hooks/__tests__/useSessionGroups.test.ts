/**
 * 切去别的菜单再回来，分组不能先消失一下。
 *
 * 会话页一切走就整个卸掉；回来时若从空白开局，分组取回来之前左栏没有任何分区，
 * 「未分组」连同各标签一起不见，正选着的那一场也在清单里跳位置。
 */

import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useSessionGroups } from '../useSessionGroups';

const payload = {
  tags: [{ id: 'frago', name: 'Frago', source: 'human' }],
  sessions: { frago: ['s1'] },
  ai_tags_created: false,
  ai_job: null,
};

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ ok: true, json: async () => payload })) as unknown as typeof fetch
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('useSessionGroups 切菜单回来', () => {
  it('一挂回来就是上次那份分组，同时照常重取', async () => {
    const first = renderHook(() => useSessionGroups());
    await waitFor(() => expect(first.result.current.tags).toHaveLength(1));
    first.unmount();

    const second = renderHook(() => useSessionGroups());
    // 第一次渲染就有分组，不等服务端。
    expect(second.result.current.tags.map((t) => t.id)).toEqual(['frago']);
    expect(second.result.current.groupOf('s1')).toBe('frago');
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  });

  it('网页刚打开、还没取过时从空开局', () => {
    const { result } = renderHook(() => useSessionGroups());
    expect(result.current.tags).toEqual([]);
  });
});
