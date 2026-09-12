/**
 * 本机服务不在时那张卡。
 *
 * 钉住两件事：服务在的时候它一点都不占（不能平白无故给正常页面盖一层东西），服务不在的
 * 时候它把话说全——是本机服务的问题，不是这一页坏了。
 */

import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import ReconnectOverlay from '../ReconnectOverlay';
import i18n from '@/i18n';
import { useConnectionStore } from '@/api/connection';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

afterEach(() => {
  useConnectionStore.setState({ reachable: true });
});

describe('ReconnectOverlay', () => {
  it('服务在的时候什么都不渲染', () => {
    useConnectionStore.setState({ reachable: true });
    render(<ReconnectOverlay />);

    expect(screen.queryByTestId('reconnect-overlay')).toBeNull();
  });

  it('服务不在时盖住整页，说清是本机后台服务在重连', () => {
    useConnectionStore.setState({ reachable: false });
    render(<ReconnectOverlay />);

    expect(screen.getByTestId('reconnect-overlay')).toBeTruthy();
    expect(screen.getByText('正在重新连接本机后台服务')).toBeTruthy();
  });

  it('服务回来就撤掉', () => {
    useConnectionStore.setState({ reachable: false });
    render(<ReconnectOverlay />);
    expect(screen.getByTestId('reconnect-overlay')).toBeTruthy();

    act(() => {
      useConnectionStore.setState({ reachable: true });
    });

    expect(screen.queryByTestId('reconnect-overlay')).toBeNull();
  });
});
