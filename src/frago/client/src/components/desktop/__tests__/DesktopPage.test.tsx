import { beforeAll, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import DesktopPage from '../DesktopPage';
import i18n from '@/i18n';
import { usePageStore } from '@/stores/pageStore';

vi.mock('@/hooks/useWebSocket', () => ({
  useWebSocket: () => ({ isConnected: true }),
}));

beforeAll(async () => {
  await i18n.changeLanguage('en');
});

describe('DesktopPage (P1-5)', () => {
  it('renders unified .ph header controls and single-row compact .dt-toolbar with virtual app switcher', () => {
    usePageStore.setState({
      currentPage: 'desktop',
      desktopSessionId: '12345678-abcd-ef01-2345-6789abcdef01',
    });

    const { container } = render(<DesktopPage />);
    const header = container.querySelector('header.ui-page-header.ph');
    expect(header).toBeTruthy();
    expect(screen.getByTestId('desktop-status-pill')).toBeTruthy();

    const resSelect = screen.getByLabelText('Resolution') as HTMLSelectElement;
    expect(resSelect.value).toBe('1920×1080');
    fireEvent.change(resSelect, { target: { value: '1440×900' } });
    expect(resSelect.value).toBe('1440×900');

    const fpsSelect = screen.getByLabelText('FPS') as HTMLSelectElement;
    expect(fpsSelect.value).toBe('30 fps');
    fireEvent.change(fpsSelect, { target: { value: '60 fps' } });
    expect(fpsSelect.value).toBe('60 fps');

    const narratorBtn = screen.getByTestId('desktop-narrator-toggle');
    expect(narratorBtn.textContent).toContain('Voice: Xiaoxiao');
    fireEvent.click(narratorBtn);
    expect(narratorBtn.textContent).toContain('Voice: Muted');

    const observeBtn = screen.getByRole('button', { name: 'Observe' });
    const takeoverBtn = screen.getByRole('button', { name: 'Takeover' });
    expect(observeBtn.getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(takeoverBtn);
    expect(takeoverBtn.getAttribute('aria-pressed')).toBe('true');

    const toolbar = screen.getByTestId('desktop-compact-toolbar');
    expect(toolbar.className).toContain('dt-toolbar');
    const appSelect = screen.getByLabelText('Virtual App') as HTMLSelectElement;
    fireEvent.change(appSelect, { target: { value: 'browser' } });
    expect(appSelect.value).toBe('browser');
    expect(screen.getByRole('button', { name: 'Browser' }).getAttribute('aria-pressed')).toBe('true');

    const iframe = container.querySelector('iframe.dt-frame') as HTMLIFrameElement;
    expect(iframe).toBeTruthy();
    fireEvent.load(iframe);
    expect(screen.getByTestId('desktop-status-pill').textContent).toContain('Connected');
  });
});
