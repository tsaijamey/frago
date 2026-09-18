/**
 * ⌘K 搜会话浮窗的用例。
 *
 * 盯五件事：⌘K 开合、只在回车时发请求、结果只摆在浮窗里、同一句再按回车就打开高亮那场、
 * 关掉再开那句话与那批结果还在。怎么搜由服务端那份用例与 `frago session search` 把关，
 * 这里把请求换成替身。
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';

import SessionSearchPalette from '../SessionSearchPalette';
import { usePageStore, useUIStore } from '@/stores/appStore';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

const HIT = {
  source: 'claude',
  session_id: '00a02979-7eb4-5c70-94ae-867c8281e3f6',
  title: '飞书推送修复',
  cwd: '/Users/frago/Repos/frago',
  last_activity: 1_700_000_000,
  matched_terms: ['飞书'],
  hit_lines: 3,
  resume_command: 'claude --resume 00a02979',
  capped: false,
  degraded: false,
  snippets: [{ term: '飞书', text: '…把飞书那条推送修一下…' }],
};

const calls: string[] = [];

beforeEach(() => {
  calls.length = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      calls.push(url);
      return {
        ok: true,
        json: async () => ({
          query: '飞书',
          plan: { terms: ['飞书', 'lark'], note: '中英两种叫法', source: 'agent' },
          hits: [HIT],
          scanned_sessions: 7,
          duration_ms: 1200,
          warnings: ['2 场只剩早期的加工副本'],
        }),
      };
    }) as unknown as typeof fetch
  );
  useUIStore.getState().setSessionSearchOpen(false);
  usePageStore.setState({ currentPage: 'todos', workbenchSessionId: null });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const pressModK = () => fireEvent.keyDown(window, { key: 'k', metaKey: true });
const input = () => screen.getByTestId('session-search-input') as HTMLInputElement;

async function searchFeishu() {
  render(<SessionSearchPalette />);
  act(() => pressModK());
  fireEvent.change(input(), { target: { value: '飞书' } });
  fireEvent.keyDown(input(), { key: 'Enter' });
  await waitFor(() => expect(screen.getAllByTestId('session-search-hit')).toHaveLength(1));
}

describe('SessionSearchPalette', () => {
  it('⌘K 打开，再按一次关上；Ctrl+K 同样认', () => {
    render(<SessionSearchPalette />);
    expect(screen.queryByTestId('session-search-palette')).toBeNull();
    act(() => pressModK());
    expect(screen.getByTestId('session-search-palette')).toBeTruthy();
    act(() => pressModK());
    expect(screen.queryByTestId('session-search-palette')).toBeNull();
    act(() => {
      fireEvent.keyDown(window, { key: 'K', ctrlKey: true });
    });
    expect(screen.getByTestId('session-search-palette')).toBeTruthy();
  });

  it('敲字不发请求，回车才搜；结果、关键词与没做全的地方都摆在浮窗里', async () => {
    render(<SessionSearchPalette />);
    act(() => pressModK());
    fireEvent.change(input(), { target: { value: '飞书' } });
    expect(calls).toHaveLength(0);

    fireEvent.keyDown(input(), { key: 'Enter' });
    expect(calls).toEqual(['/api/workbench/search?q=%E9%A3%9E%E4%B9%A6']);
    await waitFor(() => expect(screen.getAllByTestId('session-search-hit')).toHaveLength(1));

    const palette = screen.getByTestId('session-search-palette').textContent ?? '';
    expect(palette).toContain('飞书推送修复');
    expect(palette).toContain('飞书 · lark');
    expect(palette).toContain('命中 1/2 个词');
    expect(palette).toContain('2 场只剩早期的加工副本');
  });

  it('同一句再按回车就打开高亮那场，并切到会话页', async () => {
    await searchFeishu();
    fireEvent.keyDown(input(), { key: 'Enter' });
    expect(calls).toHaveLength(1);
    expect(usePageStore.getState().workbenchSessionId).toBe(HIT.session_id);
    expect(usePageStore.getState().currentPage).toBe('session_workbench');
    expect(useUIStore.getState().sessionSearchOpen).toBe(false);
  });

  it('改了词再回车是重搜，不是打开', async () => {
    await searchFeishu();
    fireEvent.change(input(), { target: { value: '飞书 推送' } });
    fireEvent.keyDown(input(), { key: 'Enter' });
    expect(calls).toHaveLength(2);
    expect(usePageStore.getState().workbenchSessionId).toBeNull();
  });

  it('点窗外关上，再开时那句话与那批结果都还在', async () => {
    await searchFeishu();
    fireEvent.mouseDown(screen.getByTestId('session-search-palette'));
    expect(screen.queryByTestId('session-search-palette')).toBeNull();
    act(() => pressModK());
    expect(input().value).toBe('飞书');
    expect(screen.getAllByTestId('session-search-hit')).toHaveLength(1);
    expect(calls).toHaveLength(1);
  });

  it('焦点不在浮窗里时，Esc 照样关上', async () => {
    await searchFeishu();
    // 点了结果区的空白，焦点落回页面本身。
    input().blur();
    expect(document.activeElement).toBe(document.body);
    fireEvent.keyDown(document.body, { key: 'Escape' });
    expect(screen.queryByTestId('session-search-palette')).toBeNull();
  });

  it('Esc 关上', async () => {
    render(<SessionSearchPalette />);
    act(() => pressModK());
    fireEvent.keyDown(input(), { key: 'Escape' });
    expect(screen.queryByTestId('session-search-palette')).toBeNull();
  });
});
