/**
 * 点开一份文件那个浮窗。
 *
 * 盯五件事：内容照实摆（过大、读不成文本、取不到各说各的，NEVER 拿半份当整份）、
 * Esc 关与 ‹ › 翻这一套键在位、「打开所在目录」把路径原样交给外面、左边那一列点一下就翻、
 * 染色回来之后确实换成了染过的 HTML。
 */

import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

const getSessionFileContent = vi.fn();
const getSessionFileDiff = vi.fn();
const getSessionFileAnnotations = vi.fn();
const putSessionFileAnnotations = vi.fn();
vi.mock('@/api', () => ({
  getSessionFileContent: (sid: string, path: string) => getSessionFileContent(sid, path),
  getSessionFileDiff: (sid: string, path: string) => getSessionFileDiff(sid, path),
  getSessionFileAnnotations: (sid: string) => getSessionFileAnnotations(sid),
  putSessionFileAnnotations: (sid: string, body: unknown) => putSessionFileAnnotations(sid, body),
}));

const loadHighlighter = vi.fn();
vi.mock('@/utils/codeHighlight', () => ({
  loadHighlighter: () => loadHighlighter(),
  MAX_HIGHLIGHT_CHARS: 200_000,
  MAX_AUTODETECT_CHARS: 40_000,
}));

import FileViewer from '../FileViewer';
import type { SessionFileRow } from '@/types/api';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

const FILES: SessionFileRow[] = [
  { path: '/w/src/a.py', action: 'created', count: 1, first_seq: 0 },
  { path: '/w/src/b.py', action: 'modified', count: 3, first_seq: 4 },
];

/** 引擎取不回来那一档：染色无限期在路上，内容按纯文本摆。 */
function neverHighlight() {
  loadHighlighter.mockReturnValue(new Promise(() => {}));
}

beforeEach(() => {
  getSessionFileContent.mockReset();
  getSessionFileDiff.mockReset();
  getSessionFileAnnotations.mockReset();
  putSessionFileAnnotations.mockReset();
  loadHighlighter.mockReset();
  neverHighlight();
  getSessionFileAnnotations.mockResolvedValue({
    version: 1,
    trace_path: '~/.frago/sessions/claude-code/sid-1/file-annotations.json',
    annotations: [],
  });
  putSessionFileAnnotations.mockImplementation(async (_sid: string, body: unknown) => ({
    ...(body as object),
    trace_path: '~/.frago/sessions/claude-code/sid-1/file-annotations.json',
  }));
  getSessionFileContent.mockResolvedValue({
    path: '/w/src/a.py',
    size: 12,
    text: 'x = 1\ny = 2\n',
    reason: null,
  });
  getSessionFileDiff.mockResolvedValue({
    path: '/w/src/a.py',
    size: 12,
    reason: null,
    before: null,
    source: 'git HEAD',
    rows: [
      [{ sign: '-', no: 1, text: 'x = 1' }, { sign: '+', no: 1, text: 'x = 2' }],
      [{ sign: ' ', no: 2, text: 'y = 2' }, { sign: ' ', no: 2, text: 'y = 2' }],
    ],
  });
});

function open(overrides: Partial<Parameters<typeof FileViewer>[0]> = {}) {
  const props = {
    sessionId: 'sid-1',
    files: FILES,
    index: 0,
    onClose: vi.fn(),
    onStep: vi.fn(),
    onReveal: vi.fn(),
    ...overrides,
  };
  render(<FileViewer {...props} />);
  return props;
}

describe('内容摆出来', () => {
  it('取回来的正文照原样摆，路径与「新建／改过」写在头上', async () => {
    open();

    await waitFor(() => expect(screen.getByText(/x = 1/)).toBeTruthy());
    expect(getSessionFileContent).toHaveBeenCalledWith('sid-1', '/w/src/a.py');
    expect(screen.getByTestId('file-viewer').textContent).toContain('a.py');
    expect(screen.getByTestId('file-viewer').textContent).toContain('新建');
  });

  it('染色回来之后换成染过的 HTML', async () => {
    loadHighlighter.mockResolvedValue({
      getLanguage: () => true,
      highlight: () => ({ value: '<span class="hljs-keyword">def</span> f():' }),
      highlightAuto: () => ({ value: 'auto' }),
    });
    getSessionFileContent.mockResolvedValue({
      path: '/w/src/a.py',
      size: 12,
      text: 'def f():',
      reason: null,
    });

    open();

    await waitFor(() => expect(document.querySelector('.hljs-keyword')).toBeTruthy());
    expect(document.querySelector('.hljs-keyword')?.textContent).toBe('def');
  });

  it('太大：说有多大、去哪儿开，不摆半份', async () => {
    getSessionFileContent.mockResolvedValue({
      path: '/w/src/a.py',
      size: 2 * 1024 * 1024,
      text: null,
      reason: 'too-large',
    });

    open();

    await waitFor(() => expect(screen.getByText(/2\.0 MB/)).toBeTruthy());
    expect(screen.getByTestId('file-viewer').textContent).toContain('太大');
    expect(document.querySelector('pre')).toBeNull();
  });

  it('读不成文本：照实说它是二进制的', async () => {
    getSessionFileContent.mockResolvedValue({
      path: '/w/src/a.py',
      size: 8,
      text: null,
      reason: 'not-text',
    });

    open();

    await waitFor(() => expect(screen.getByText(/读不成文本/)).toBeTruthy());
  });

  it('取不到：把服务端说的话摆出来，不摆一个空白窗口', async () => {
    getSessionFileContent.mockRejectedValue(new Error('File is gone: /w/src/a.py'));

    open();

    await waitFor(() => expect(screen.getByText(/File is gone/)).toBeTruthy());
    expect(screen.getByTestId('file-viewer').textContent).toContain('没取到');
  });
});

describe('翻页与那几个动作', () => {
  it('‹ › 与左右键各走一步，方向不反', () => {
    const { onStep } = open();

    fireEvent.click(screen.getByTestId('file-viewer-next'));
    expect(onStep).toHaveBeenLastCalledWith(1);
    fireEvent.click(screen.getByTestId('file-viewer-prev'));
    expect(onStep).toHaveBeenLastCalledWith(-1);

    fireEvent.keyDown(document, { key: 'ArrowLeft' });
    expect(onStep).toHaveBeenLastCalledWith(-1);
    fireEvent.keyDown(document, { key: 'ArrowRight' });
    expect(onStep).toHaveBeenLastCalledWith(1);
  });

  it('Esc 关掉，点窗外也关掉', () => {
    const { onClose } = open();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByTestId('file-viewer-backdrop'));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it('左边那一列点一下就是翻到那一份', () => {
    const { onStep } = open();

    fireEvent.click(screen.getByTitle('/w/src/b.py'));
    // 当前在第一份，点第二份就是往后一步。
    expect(onStep).toHaveBeenCalledWith(1);
  });

  it('「打开所在目录」把这一份的路径原样交出去', () => {
    const { onReveal } = open();

    fireEvent.click(screen.getByTestId('file-viewer-reveal'));
    expect(onReveal).toHaveBeenCalledWith('/w/src/a.py');
  });

  it('「复制完整路径」把路径写进剪贴板', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    });

    open();
    fireEvent.click(screen.getByTestId('file-viewer-copy'));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith('/w/src/a.py'));
  });
});

describe('内容 / 改动 那一档', () => {
  it('读得出内容才有这一档：读不出来的（太大）连内容都没有，没什么可对照的', async () => {
    getSessionFileContent.mockResolvedValue({
      path: '/w/src/a.py',
      size: 2 * 1024 * 1024,
      text: null,
      reason: 'too-large',
    });

    open();

    await waitFor(() => expect(screen.getByText(/2\.0 MB/)).toBeTruthy());
    expect(screen.queryByTestId('file-viewer-mode')).toBeNull();
  });

  it('默认看内容，改动那一档要点过去才取', async () => {
    open();

    await waitFor(() => expect(screen.getByText(/x = 1/)).toBeTruthy());
    expect(screen.getByTestId('file-viewer-mode-file').getAttribute('aria-pressed')).toBe('true');
    // 没点过「改动」就不该去取：那一路要慢一步（服务端还得去 git 里取上一版）。
    expect(getSessionFileDiff).not.toHaveBeenCalled();
  });

  it('切到改动：左右两列对着摆，删的那行一层红底、增的那行一层绿底', async () => {
    open();
    await waitFor(() => expect(screen.getByText(/x = 1/)).toBeTruthy());

    fireEvent.click(screen.getByTestId('file-viewer-mode-changes'));

    await waitFor(() => expect(getSessionFileDiff).toHaveBeenCalledWith('sid-1', '/w/src/a.py'));
    const diff = await screen.findByTestId('file-diff');
    // 左边那一侧的来路说清楚：来自 git HEAD，不是会话开始那一刻的快照。
    expect(diff.textContent).toContain('git HEAD');
    const cells = diff.querySelectorAll('.diff-cell');
    expect([...cells].map((c) => c.getAttribute('data-sign'))).toEqual(['-', '+', ' ', ' ']);
    expect(diff.textContent).toContain('改动之前');
    expect(diff.textContent).toContain('现在');
  });

  it('这场会话新建的：只有右边一列，并写明 git 里没有上一版', async () => {
    getSessionFileDiff.mockResolvedValue({
      path: '/w/src/a.py',
      size: 12,
      reason: null,
      before: 'new',
      source: null,
      rows: [
        [null, { sign: '+', no: 1, text: 'x = 1' }],
        [null, { sign: '+', no: 2, text: 'y = 2' }],
      ],
    });
    open();
    await waitFor(() => expect(screen.getByText(/x = 1/)).toBeTruthy());

    fireEvent.click(screen.getByTestId('file-viewer-mode-changes'));

    const diff = await screen.findByTestId('file-diff');
    expect(diff.textContent).toContain('新建');
    const cells = diff.querySelectorAll('.diff-cell');
    expect([...cells].map((c) => c.getAttribute('data-sign'))).toEqual(['+', '+']);
    // 没有左边那一侧，就不摆「改动之前 / 现在」那行表头。
    expect(diff.textContent).not.toContain('改动之前');
  });

  it('不在 git 仓库里：照实说没有上一版，不装成新建的', async () => {
    getSessionFileDiff.mockResolvedValue({
      path: '/w/src/a.py',
      size: 12,
      reason: null,
      before: 'not-git',
      source: null,
      rows: [[null, { sign: '+', no: 1, text: 'x = 1' }]],
    });
    open();
    await waitFor(() => expect(screen.getByText(/x = 1/)).toBeTruthy());

    fireEvent.click(screen.getByTestId('file-viewer-mode-changes'));

    const diff = await screen.findByTestId('file-diff');
    expect(diff.textContent).toContain('不在 git 仓库里');
  });

  it('与 HEAD 那版没差别：说出来，免得人以为看错了', async () => {
    getSessionFileDiff.mockResolvedValue({
      path: '/w/src/a.py',
      size: 12,
      reason: null,
      before: null,
      source: 'git HEAD',
      rows: [[{ sign: ' ', no: 1, text: 'x = 1' }, { sign: ' ', no: 1, text: 'x = 1' }]],
    });
    open();
    await waitFor(() => expect(screen.getByText(/x = 1/)).toBeTruthy());

    fireEvent.click(screen.getByTestId('file-viewer-mode-changes'));

    await waitFor(() =>
      expect(screen.getByTestId('file-diff-same').textContent).toContain('没有差别')
    );
  });

  it('翻到下一个文件就回到「看内容」那一档', async () => {
    const props = {
      sessionId: 'sid-1',
      files: FILES,
      onClose: vi.fn(),
      onStep: vi.fn(),
      onReveal: vi.fn(),
    };
    const { rerender } = render(<FileViewer {...props} index={0} />);
    await waitFor(() => expect(screen.getByText(/x = 1/)).toBeTruthy());
    fireEvent.click(screen.getByTestId('file-viewer-mode-changes'));
    await screen.findByTestId('file-diff');

    // 翻到第二份：那一档要落回「看内容」——人翻下一份时想看的是它长什么样。
    rerender(<FileViewer {...props} index={1} />);

    await waitFor(() =>
      expect(screen.getByTestId('file-viewer-mode-file').getAttribute('aria-pressed')).toBe('true')
    );
  });
});

describe('换了文件就重取', () => {
  it('第几份变了，问的就是那一份', async () => {
    getSessionFileContent.mockImplementation(async (_sid: string, path: string) => ({
      path,
      size: 1,
      text: `${path}\n`,
      reason: null,
    }));

    const { rerender } = render(
      <FileViewer
        sessionId="sid-1"
        files={FILES}
        index={0}
        onClose={vi.fn()}
        onStep={vi.fn()}
        onReveal={vi.fn()}
      />
    );
    await waitFor(() => expect(getSessionFileContent).toHaveBeenCalledWith('sid-1', '/w/src/a.py'));

    rerender(
      <FileViewer
        sessionId="sid-1"
        files={FILES}
        index={1}
        onClose={vi.fn()}
        onStep={vi.fn()}
        onReveal={vi.fn()}
      />
    );
    await waitFor(() => expect(getSessionFileContent).toHaveBeenCalledWith('sid-1', '/w/src/b.py'));
  });
});

describe('固定比例大窗口、文档批注落盘与打包填入对话框', () => {
  it('默认窗口与主视口呈固定比例 88vw × 86vh，切到改动模式扩展为 92vw × 86vh', async () => {
    open();
    await waitFor(() => expect(screen.getByText(/x = 1/)).toBeTruthy());

    const win = screen.getByTestId('file-viewer-window');
    expect(win.className).toContain('w-[88vw]');
    expect(win.className).toContain('h-[86vh]');

    fireEvent.click(screen.getByTestId('file-viewer-mode-changes'));
    expect(win.className).toContain('w-[92vw]');
  });

  it('点击行号添加批注并关联落盘到当前会话目录，打包后填入对话框并关闭浮窗', async () => {
    const onPackPrompt = vi.fn();
    const { onClose } = open({ onPackPrompt });

    await waitFor(() => expect(screen.getByText(/x = 1/)).toBeTruthy());
    await waitFor(() =>
      expect(screen.getByTestId('file-viewer-trace-path').textContent).toContain(
        '~/.frago/sessions/claude-code/sid-1/file-annotations.json'
      )
    );

    // 点击第 1 行行号按钮打开行内批注框
    fireEvent.click(screen.getByTestId('file-viewer-line-btn-1'));
    const input = screen.getByTestId('file-viewer-inline-input');
    fireEvent.change(input, { target: { value: '把常量提取到配置模块' } });
    fireEvent.click(screen.getByTestId('file-viewer-inline-save'));

    // 行内批注卡片与右侧批注栏同步出现，且向服务端发起 PUT 落盘
    expect(screen.getByTestId('file-viewer-inline-card').textContent).toContain(
      '把常量提取到配置模块'
    );
    expect(screen.getByTestId('file-viewer-annotation-item').textContent).toContain(
      '把常量提取到配置模块'
    );
    await waitFor(() => expect(putSessionFileAnnotations).toHaveBeenCalledTimes(1));

    // 点击打包按钮，组装完整新 prompt 交给 Composer 并关闭浮窗
    fireEvent.click(screen.getByTestId('file-viewer-pack-btn'));
    expect(onPackPrompt).toHaveBeenCalledTimes(1);
    const packed = onPackPrompt.mock.calls[0][0];
    expect(packed.count).toBe(1);
    expect(packed.tracePath).toBe('~/.frago/sessions/claude-code/sid-1/file-annotations.json');
    expect(packed.text).toContain('/w/src/a.py:L1');
    expect(packed.text).toContain('x = 1');
    expect(packed.text).toContain('>>> 把常量提取到配置模块');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('打开 .md 文件时默认进入「预览」模式渲染 Markdown，并可切回「内容」查看源码行', async () => {
    const mdFiles: SessionFileRow[] = [
      { path: '/w/docs/design.md', action: 'modified', count: 2, first_seq: 1 },
    ];
    getSessionFileContent.mockResolvedValue({
      path: '/w/docs/design.md',
      size: 42,
      text: '# 架构说明\n\n- 第一条约束\n- 第二条约束\n',
      reason: null,
    });

    open({ files: mdFiles, index: 0 });

    await waitFor(() => expect(screen.getByTestId('file-viewer-md-preview')).toBeTruthy());
    expect(screen.getByTestId('file-viewer-mode-preview').getAttribute('aria-pressed')).toBe(
      'true'
    );
    expect(screen.getByTestId('file-viewer-md-preview').querySelector('h1')?.textContent).toBe(
      '架构说明'
    );
    expect(screen.getByTestId('file-viewer-md-preview').querySelectorAll('li').length).toBe(2);

    // 预览模式下仍可直接点击 + L1 添加批注
    fireEvent.click(screen.getByTestId('file-viewer-quick-annotate'));
    fireEvent.change(screen.getByTestId('file-viewer-inline-input'), {
      target: { value: '补充架构图' },
    });
    fireEvent.click(screen.getByTestId('file-viewer-inline-save'));
    expect(screen.getByTestId('file-viewer-annotation-item').textContent).toContain('补充架构图');

    // 切到「内容」模式查看带行号的源码
    fireEvent.click(screen.getByTestId('file-viewer-mode-file'));
    expect(screen.getByTestId('file-viewer-mode-file').getAttribute('aria-pressed')).toBe('true');
    expect(screen.getAllByTestId('file-viewer-line').length).toBe(4);
  });

  it('打开 .html 文件时默认进入「预览」模式，通过沙箱 iframe 渲染 HTML 文档', async () => {
    const htmlFiles: SessionFileRow[] = [
      { path: '/w/proto/index.html', action: 'created', count: 1, first_seq: 1 },
    ];
    const htmlSource = '<!doctype html><html><body><h1>Prototype Demo</h1></body></html>';
    getSessionFileContent.mockResolvedValue({
      path: '/w/proto/index.html',
      size: htmlSource.length,
      text: htmlSource,
      reason: null,
    });

    open({ files: htmlFiles, index: 0 });

    await waitFor(() => expect(screen.getByTestId('file-viewer-html-preview')).toBeTruthy());
    expect(screen.getByTestId('file-viewer-mode-preview').getAttribute('aria-pressed')).toBe(
      'true'
    );
    const iframe = screen.getByTestId('file-viewer-html-preview') as HTMLIFrameElement;
    expect(iframe.getAttribute('srcdoc')).toBe(htmlSource);

    // 切到「内容」可查看 HTML 源码行
    fireEvent.click(screen.getByTestId('file-viewer-mode-file'));
    expect(screen.getByTestId('file-viewer-mode-file').getAttribute('aria-pressed')).toBe('true');
    expect(screen.getAllByTestId('file-viewer-line').length).toBe(1);
  });
});
