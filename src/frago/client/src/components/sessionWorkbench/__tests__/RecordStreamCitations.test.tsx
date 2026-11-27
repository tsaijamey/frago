import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { WorkbenchRecord } from '@/hooks/useWorkbenchRecords';
import i18n from '@/i18n';

const getSessionFileContent = vi.fn();
const getSessionFileDiff = vi.fn();
const putSessionFileContent = vi.fn();
const getSessionFileAnnotations = vi.fn();
const putSessionFileAnnotations = vi.fn();
const probeSessionPath = vi.fn();
const listDirectory = vi.fn();

vi.mock('@/api', () => ({
  getSessionFileContent: (sid: string, path: string, scope?: 'touched' | 'cited') =>
    getSessionFileContent(sid, path, scope),
  getSessionFileDiff: (sid: string, path: string) => getSessionFileDiff(sid, path),
  putSessionFileContent: (sid: string, path: string, text: string) =>
    putSessionFileContent(sid, path, text),
  getSessionFileAnnotations: (sid: string) => getSessionFileAnnotations(sid),
  putSessionFileAnnotations: (sid: string, body: unknown) => putSessionFileAnnotations(sid, body),
  probeSessionPath: (sid: string, path: string) => probeSessionPath(sid, path),
  listDirectory: (path: string) => listDirectory(path),
}));

import RecordStream from '../RecordStream';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

const SID = '00a02979-7eb4-5c70-94ae-867c8281e3f6';
const LOCAL_PATH = '/home/yammi/repos/frago/src/frago/server/routes/workbench.py';

function makeCiteRecords(): WorkbenchRecord[] {
  return [
    {
      session_id: SID,
      group_id: null,
      id: 'r-cite-1',
      seq: 0,
      ts: 1_753_800_000_000,
      kind: 'agent.say',
      agent_path: [],
      payload: {
        text: [
          `后端仅允许白名单路径[^1]，外部协议规范请看文档[^2]，常规链接见 [routes.ts](file://${LOCAL_PATH}#L2)。`,
          '',
          `[^1]: [workbench.py](file://${LOCAL_PATH}#L2-L3 "校验 scope=cited 沙箱")`,
          '[^2]: [RFC 3986](https://datatracker.ietf.org/doc/html/rfc3986 "URI 通用语法")',
        ].join('\n'),
      },
      raw_available: true,
    },
  ];
}

function renderStream(props: Partial<Parameters<typeof RecordStream>[0]> = {}) {
  return render(
    <RecordStream
      sessionId={SID}
      records={makeCiteRecords()}
      loading={false}
      loadingOlder={false}
      hasOlder={false}
      error={null}
      onLoadOlder={() => {}}
      {...props}
    />
  );
}

describe('RecordStream — 句段引用溯源交互、零预拉取与蓝虚线/绿实线分流', () => {
  const origScrollIntoView = Element.prototype.scrollIntoView;

  beforeEach(() => {
    vi.clearAllMocks();
    getSessionFileContent.mockResolvedValue({
      path: LOCAL_PATH,
      size: 64,
      text: 'line 1\nline 2 cited\nline 3 cited\nline 4',
      reason: null,
    });
    getSessionFileAnnotations.mockResolvedValue({ annotations: [] });
    probeSessionPath.mockResolvedValue({
      path: LOCAL_PATH,
      resolved: LOCAL_PATH,
      exists: true,
      is_file: true,
      is_dir: false,
      size: 64,
    });
  });

  afterEach(() => {
    Element.prototype.scrollIntoView = origScrollIntoView;
    vi.restoreAllMocks();
  });

  it('首屏渲染与悬停 Popover 均禁止预拉取任何 file:// 本地文件', () => {
    const { container } = renderStream();
    expect(getSessionFileContent).not.toHaveBeenCalled();

    const pill = container.querySelector('.cite-pill') as HTMLElement;
    expect(pill).not.toBeNull();
    fireEvent.mouseEnter(pill);

    const popover = screen.getByTestId('cite-popover');
    expect(popover).toBeTruthy();
    expect(popover.textContent).toContain('workbench.py');
    expect(getSessionFileContent).not.toHaveBeenCalled();
  });

  it('点击本地 [^1] 按需请求 scope="cited"，打开蓝虚线核实横幅侧栏、高亮行并滚动，可展开到 FileViewer', async () => {
    const scrollIntoViewMock = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoViewMock;

    const { container } = renderStream();
    const pills = container.querySelectorAll('.cite-pill');
    fireEvent.click(pills[0]);

    await waitFor(() =>
      expect(getSessionFileContent).toHaveBeenCalledWith(SID, LOCAL_PATH, 'cited')
    );

    const drawer = screen.getByTestId('cite-preview-drawer');
    expect(drawer.getAttribute('data-drawer-mode')).toBe('cite');
    const banner = screen.getByTestId('cite-drawer-banner');
    expect(banner.classList.contains('file-mode')).toBe(false);

    const hlLines = await waitFor(() => {
      const els = drawer.querySelectorAll('.cite-code-line.hl');
      expect(els.length).toBe(2);
      return els;
    });
    expect(hlLines[0].getAttribute('data-line')).toBe('2');
    expect(hlLines[1].getAttribute('data-line')).toBe('3');
    expect(scrollIntoViewMock).toHaveBeenCalledWith({ block: 'center' });

    fireEvent.click(screen.getByTestId('cite-drawer-expand'));
    expect(screen.getByTestId('file-viewer')).toBeTruthy();
    expect(screen.getByTestId('file-viewer-line-anchor').textContent).toBe('#L2-L3');
  });

  it('点击普通 file:// 链接打开绿实线全文预览侧栏（file-mode），不加 .cite-code-line.hl 句段高亮', async () => {
    renderStream();
    const link = screen.getByRole('link', { name: 'routes.ts' });
    fireEvent.click(link);

    await waitFor(() =>
      expect(getSessionFileContent).toHaveBeenCalledWith(SID, LOCAL_PATH, 'cited')
    );

    const drawer = screen.getByTestId('cite-preview-drawer');
    expect(drawer.getAttribute('data-drawer-mode')).toBe('file');
    const banner = screen.getByTestId('cite-drawer-banner');
    expect(banner.classList.contains('file-mode')).toBe(true);

    await waitFor(() => {
      expect(drawer.querySelector('[data-line="2"]')).not.toBeNull();
    });
    expect(drawer.querySelectorAll('.cite-code-line.hl').length).toBe(0);
  });

  it('点击外部 [^2] 打开外链二次确认弹窗，确认后携带 noopener,noreferrer 在新标签打开', () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    const { container } = renderStream();
    const pills = container.querySelectorAll('.cite-pill');
    fireEvent.click(pills[1]);

    const modal = screen.getByTestId('cite-ext-modal');
    expect(modal).toBeTruthy();
    expect(screen.getByTestId('cite-ext-url').textContent).toBe(
      'https://datatracker.ietf.org/doc/html/rfc3986'
    );
    expect(getSessionFileContent).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId('cite-ext-confirm'));
    expect(openSpy).toHaveBeenCalledWith(
      'https://datatracker.ietf.org/doc/html/rfc3986',
      '_blank',
      'noopener,noreferrer'
    );
    expect(screen.queryByTestId('cite-ext-modal')).toBeNull();
  });

  it('后端返回 403 / 404 / too-large / not-text 时在侧栏展示明确错误状态', async () => {
    const { container } = renderStream();
    const pills = container.querySelectorAll('.cite-pill');

    getSessionFileContent.mockRejectedValueOnce(new Error('403 Forbidden: outside sandbox'));
    fireEvent.click(pills[0]);
    expect(await screen.findByText(i18n.t('workbench.citations.unsafeBlocked'))).toBeTruthy();

    fireEvent.click(screen.getByTestId('close-cite-drawer-btn'));

    getSessionFileContent.mockRejectedValueOnce(new Error('404 Not Found'));
    fireEvent.click(pills[0]);
    expect(await screen.findByText(i18n.t('workbench.citations.missingFile'))).toBeTruthy();

    fireEvent.click(screen.getByTestId('close-cite-drawer-btn'));

    getSessionFileContent.mockResolvedValueOnce({
      path: LOCAL_PATH,
      size: 5_000_000,
      text: null,
      reason: 'too-large',
    });
    fireEvent.click(pills[0]);
    expect(await screen.findByText(i18n.t('workbench.citations.tooLarge'))).toBeTruthy();

    fireEvent.click(screen.getByTestId('close-cite-drawer-btn'));

    getSessionFileContent.mockResolvedValueOnce({
      path: LOCAL_PATH,
      size: 1024,
      text: null,
      reason: 'not-text',
    });
    fireEvent.click(pills[0]);
    expect(await screen.findByText(i18n.t('workbench.citations.notText'))).toBeTruthy();
  });

  it('Esc 逐层关闭外链弹窗与预览侧栏，切换镜头或打开文件清单时互斥关闭侧栏', async () => {
    const onFilesOpenChange = vi.fn();
    const { container, rerender } = renderStream({
      filesView: <div data-testid="files-body" />,
      filesOpen: false,
      onFilesOpenChange,
    });

    const pills = container.querySelectorAll('.cite-pill');
    fireEvent.click(pills[0]);
    await waitFor(() => expect(screen.getByTestId('cite-preview-drawer')).toBeTruthy());

    fireEvent.click(pills[1]);
    expect(screen.getByTestId('cite-ext-modal')).toBeTruthy();

    // 第一下 Esc 先关外链确认弹窗，保留侧栏
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByTestId('cite-ext-modal')).toBeNull();
    expect(screen.getByTestId('cite-preview-drawer')).toBeTruthy();

    // 第二下 Esc 关闭侧栏
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByTestId('cite-preview-drawer')).toBeNull();

    // 重新打开侧栏后切换到「全部」镜头，侧栏互斥关闭
    fireEvent.click(pills[0]);
    await waitFor(() => expect(screen.getByTestId('cite-preview-drawer')).toBeTruthy());
    fireEvent.click(screen.getByTestId('lens-all'));
    expect(screen.queryByTestId('cite-preview-drawer')).toBeNull();

    // 重新打开侧栏后当 filesOpen 变为 true，侧栏互斥关闭
    fireEvent.click(pills[0]);
    await waitFor(() => expect(screen.getByTestId('cite-preview-drawer')).toBeTruthy());
    rerender(
      <RecordStream
        sessionId={SID}
        records={makeCiteRecords()}
        loading={false}
        loadingOlder={false}
        hasOlder={false}
        error={null}
        onLoadOlder={() => {}}
        filesView={<div data-testid="files-body" />}
        filesOpen={true}
        onFilesOpenChange={onFilesOpenChange}
      />
    );
    expect(screen.queryByTestId('cite-preview-drawer')).toBeNull();
  });

  it('workbench.css 与 React 组件的全部 .cite-* 样式类名完全一致（含 .cite-lt 缩进保留）', async () => {
    const fsMod = (await import(/* @vite-ignore */ ['node', 'fs'].join(':'))) as {
      readFileSync: (path: string, encoding: string) => string;
    };
    const pathMod = (await import(/* @vite-ignore */ ['node', 'path'].join(':'))) as {
      resolve: (...segments: string[]) => string;
    };
    const proc = (globalThis as unknown as { process: { cwd: () => string } }).process;
    const css = fsMod.readFileSync(
      pathMod.resolve(proc.cwd(), 'src/styles/pages/workbench.css'),
      'utf8'
    );
    const requiredSelectors = [
      '.cite-sources-label',
      '.cite-src-num',
      '.cite-src-name',
      '.cite-src-loc',
      '.cite-pop-head',
      '.cite-pop-num',
      '.cite-pop-title',
      '.cite-pop-kind',
      '.cite-pop-path',
      '.cite-pop-foot',
      '.cite-pop-open',
      '.cite-drawer-head',
      '.cite-drawer-file',
      '.cite-drawer-name',
      '.cite-drawer-sub',
      '.cite-drawer-actions',
      '.cite-code-line .cite-ln',
      '.cite-code-line .cite-lt',
      '.cite-code-line.hl .cite-ln',
      '.cite-ext-head',
      '.cite-ext-body',
      '.cite-ext-foot',
    ];
    for (const selector of requiredSelectors) {
      expect(css, `workbench.css 缺失选择器 ${selector}`).toContain(selector);
    }
    const deprecatedSelectors = [
      '.cite-sources-lbl',
      '.cite-pop-top',
      '.cite-pop-badge',
      '.cite-pop-loc',
      '.cite-pop-hint',
      '.cite-drawer-hd',
      '.cite-drawer-path',
      '.cite-code-line .ln',
      '.cite-code-line .txt',
      '.cite-ext-hd',
      '.cite-ext-bd',
    ];
    for (const selector of deprecatedSelectors) {
      expect(css, `workbench.css 不应残留旧缩写选择器 ${selector}`).not.toContain(selector);
    }
    expect(css).toMatch(/\.cite-code-line\s+\.cite-lt\s*\{[^}]*white-space:\s*pre-wrap/s);
    const citeSectionStart = css.indexOf('.cite-pill');
    const citeSectionEnd = css.indexOf('.sp-used-list', citeSectionStart);
    const citeSection = css.slice(citeSectionStart, citeSectionEnd > citeSectionStart ? citeSectionEnd : undefined);
    expect(citeSection, '引用样式段不应出现硬编码十六进制色值').not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
  });
});
