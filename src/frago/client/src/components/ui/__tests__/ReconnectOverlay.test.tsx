/**
 * 本机后台服务断连提示与 10 秒终端唤醒指引测试。
 */

import { useState } from 'react';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import ReconnectOverlay from '../ReconnectOverlay';
import i18n from '@/i18n';
import { useConnectionStore, WAKE_COMMAND } from '@/api/connection';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  act(() => {
    useConnectionStore.setState({
      reachable: true,
      prolonged: false,
      collapsed: false,
      probing: false,
    });
  });
});

function WorkbenchWithDraft() {
  const [draft, setDraft] = useState('帮我对比 Metix AI 与海纳 AI');
  return (
    <div>
      <textarea
        data-testid="page-draft-input"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
      />
      <ReconnectOverlay />
    </div>
  );
}

describe('ReconnectOverlay', () => {
  it('服务在的时候什么都不渲染', () => {
    act(() => {
      useConnectionStore.setState({ reachable: true, prolonged: false });
    });
    render(<ReconnectOverlay />);

    expect(screen.queryByTestId('reconnect-overlay')).toBeNull();
    expect(screen.queryByTestId('reconnect-compact-banner')).toBeNull();
  });

  it('短暂失联（< 10s）只展示轻量重连转圈提示，不弹出终端唤醒大面板', () => {
    act(() => {
      useConnectionStore.setState({ reachable: false, prolonged: false, collapsed: false });
    });
    render(<ReconnectOverlay />);

    expect(screen.getByTestId('reconnect-overlay')).toBeTruthy();
    expect(screen.getByText('正在重新连接本机后台服务')).toBeTruthy();
    expect(screen.queryByTestId('reconnect-wake-guide')).toBeNull();
  });

  it('连续失联满 10s 展示零代码友好的终端唤醒指引，且严禁出现开发者专属路径或 uv run', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    });

    act(() => {
      useConnectionStore.setState({ reachable: false, prolonged: true, collapsed: false });
    });
    const { container } = render(<ReconnectOverlay />);

    expect(screen.getByTestId('reconnect-wake-guide')).toBeTruthy();
    expect(screen.getByText('本地服务连接已断开')).toBeTruthy();
    expect(screen.getByTestId('reconnect-wake-command').textContent).toBe(WAKE_COMMAND);
    expect(screen.getByText(/搜索并打开「终端」/)).toBeTruthy();
    expect(screen.getByText(/打开「PowerShell」/)).toBeTruthy();

    // 严守零先验普通用户红线：界面文案绝不含 uv run 或开发者本机路径
    const fullText = container.textContent || '';
    expect(fullText).not.toContain('uv run');
    expect(fullText).not.toContain('/Users/frago');

    fireEvent.click(screen.getByTestId('reconnect-copy-btn'));
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith('frago server restart');
      expect(screen.getByText('已复制')).toBeTruthy();
    });
  });

  it('支持暂时收起退化为顶部紧凑警示条、再次展开，且服务恢复后自动收起并保留页面草稿', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ host: '127.0.0.1', port: 8093 }),
    });
    vi.stubGlobal('fetch', fetchMock);

    act(() => {
      useConnectionStore.setState({ reachable: false, prolonged: true, collapsed: false });
    });
    render(<WorkbenchWithDraft />);

    // 点击「暂时收起（查看页面内容）」→ 退化为顶部紧凑警示条，草稿完好
    fireEvent.click(screen.getByTestId('reconnect-collapse-btn'));
    expect(screen.queryByTestId('reconnect-wake-guide')).toBeNull();
    expect(screen.getByTestId('reconnect-compact-banner')).toBeTruthy();
    expect((screen.getByTestId('page-draft-input') as HTMLTextAreaElement).value).toBe(
      '帮我对比 Metix AI 与海纳 AI'
    );

    // 点击顶部警示条「展开唤醒指引」→ 重新回到完整指引面板
    fireEvent.click(screen.getByTestId('reconnect-expand-btn'));
    expect(screen.getByTestId('reconnect-wake-guide')).toBeTruthy();

    // 点击「立即重新检测」且服务返回 200 JSON → 立即自动收起全部提示，草稿不丢失
    fireEvent.click(screen.getByTestId('reconnect-probe-btn'));
    await waitFor(() => {
      expect(screen.queryByTestId('reconnect-overlay')).toBeNull();
      expect(screen.queryByTestId('reconnect-compact-banner')).toBeNull();
    });
    expect((screen.getByTestId('page-draft-input') as HTMLTextAreaElement).value).toBe(
      '帮我对比 Metix AI 与海纳 AI'
    );
  });
});
