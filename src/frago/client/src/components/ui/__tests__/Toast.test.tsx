/**
 * ToastContainer 层叠与 Portal 挂载回归测试：
 * 确认全局 Toast 容器直接挂到 document.body（脱离局部层叠上下文），
 * 并在无消息时卸载、点击时可关闭。
 */

import { afterEach, describe, expect, it } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { ToastContainer } from '../Toast';
import { useUIStore } from '@/stores/uiStore';

afterEach(() => {
  cleanup();
  act(() => {
    useUIStore.setState({ toasts: [] });
  });
});

describe('ToastContainer', () => {
  it('renders nothing when there are no active toasts', () => {
    render(<ToastContainer />);
    expect(screen.queryByTestId('toast-container')).toBeNull();
  });

  it('portals toast-container directly to document.body outside any local stacking wrapper', () => {
    const { container } = render(
      <div style={{ transform: 'translateZ(0)', zIndex: 1 }}>
        <ToastContainer />
      </div>,
    );

    act(() => {
      useUIStore.getState().showToast('Profile save failed', 'error');
    });

    const portalHost = screen.getByTestId('toast-container');
    expect(portalHost.parentElement).toBe(document.body);
    expect(container.querySelector('.toast-container')).toBeNull();
    const toastEl = screen.getByText('Profile save failed').closest('.toast');
    expect(toastEl?.classList.contains('toast-error')).toBe(true);

    fireEvent.click(screen.getByText('Profile save failed'));
    expect(screen.queryByTestId('toast-container')).toBeNull();
  });
});
