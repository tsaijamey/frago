import { beforeEach, describe, expect, it } from 'vitest';
import {
  PROFILE_SORT_STORAGE_KEY,
  compareProfileNames,
  formatProviderMetaEndpoint,
  readProfileSortOrder,
  sortProfilesByName,
  writeProfileSortOrder,
} from '../profileSort';

describe('profileSort', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('按名字大小写不敏感与自然数字排序正逆序排列，且不修改原数组', () => {
    const items = [
      { id: '4', name: 'Model 10' },
      { id: '1', name: 'beta' },
      { id: '2', name: 'Alpha' },
      { id: '3', name: 'Model 2' },
    ];

    const asc = sortProfilesByName(items, 'asc');
    expect(asc.map((p) => p.name)).toEqual(['Alpha', 'beta', 'Model 2', 'Model 10']);

    const desc = sortProfilesByName(items, 'desc');
    expect(desc.map((p) => p.name)).toEqual(['Model 10', 'Model 2', 'beta', 'Alpha']);

    // 原数组顺序不被篡改
    expect(items.map((p) => p.id)).toEqual(['4', '1', '2', '3']);
  });

  it('中英文混排结果在正逆序间严格互逆，同名时按 id 稳定兜底', () => {
    const items = [
      { id: 'b', name: 'Same' },
      { id: 'a', name: 'Same' },
      { id: 'c', name: '智谱 GLM' },
      { id: 'd', name: 'Anthropic' },
    ];

    const asc = sortProfilesByName(items, 'asc');
    const desc = sortProfilesByName(items, 'desc');

    expect(asc.map((p) => p.id)).toEqual([...desc].reverse().map((p) => p.id));
    expect(compareProfileNames({ id: 'a', name: 'Same' }, { id: 'b', name: 'Same' }, 'asc')).toBeLessThan(0);
  });

  it('在 localStorage 中持久化与恢复排序偏好，非法值回退为 asc', () => {
    expect(readProfileSortOrder()).toBe('asc');

    writeProfileSortOrder('desc');
    expect(window.localStorage.getItem(PROFILE_SORT_STORAGE_KEY)).toBe('desc');
    expect(readProfileSortOrder()).toBe('desc');

    window.localStorage.setItem(PROFILE_SORT_STORAGE_KEY, 'invalid');
    expect(readProfileSortOrder()).toBe('asc');
  });

  it('custom 端点从 URL 提取主机名，预设端点保留原类型', () => {
    expect(
      formatProviderMetaEndpoint({
        endpoint_type: 'custom',
        url: 'http://127.0.0.1:8080',
        channels: [],
      }),
    ).toBe('127.0.0.1:8080');

    expect(
      formatProviderMetaEndpoint({
        endpoint_type: 'custom',
        url: null,
        channels: [{ protocol: 'responses', url: 'https://api.groq.com/openai/v1', models: ['whisper-large-v3-turbo'] }],
      }),
    ).toBe('api.groq.com');

    expect(
      formatProviderMetaEndpoint({
        endpoint_type: 'deepseek',
        url: 'https://api.deepseek.com/anthropic',
        channels: [],
      }),
    ).toBe('deepseek');
  });
});
