import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MermaidDiagram, {
  EXPORT_PADDING,
  MAX_CANVAS_SIDE,
  MIN_EXPORT_SCALE,
  MIN_EXPORT_WIDTH,
  computeExportDimensions,
  naturalSize,
} from '../MermaidDiagram';

describe('MermaidDiagram 导出尺寸与复制/下载按钮', () => {
  beforeEach(() => {
    (window as unknown as { mermaid?: unknown }).mermaid = {
      initialize: vi.fn(),
      render: vi.fn().mockResolvedValue({
        svg: '<svg viewBox="0 0 600 240" width="100%" height="240"><g><text>节点A</text></g></svg>',
      }),
    };
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('computeExportDimensions 保证窄图总宽至少 1600px、常规图至少 2× 超采样且不越过 8192px 上限', () => {
    // 窄小图（352×152，加两侧 24px 留白后 400×200）→ 自动拉到 4×，输出 1600×800
    const small = computeExportDimensions(352, 152, 1);
    expect(small.scale).toBe(4);
    expect(small.width).toBe(MIN_EXPORT_WIDTH);
    expect(small.height).toBe((152 + EXPORT_PADDING * 2) * 4);
    expect(small.pad).toBe(EXPORT_PADDING * 4);

    // 中等图（752×300，加留白后 800×348）→ 2× 超采样即可达到 1600px 宽
    const medium = computeExportDimensions(752, 300, 2);
    expect(medium.scale).toBe(MIN_EXPORT_SCALE);
    expect(medium.width).toBe(1600);
    expect(medium.height).toBe((300 + EXPORT_PADDING * 2) * 2);

    // 宽图（1200×500）→ 保持 2× 超采样，输出 2496×1096
    const large = computeExportDimensions(1200, 500, 2);
    expect(large.scale).toBe(2);
    expect(large.width).toBe((1200 + EXPORT_PADDING * 2) * 2);
    expect(large.height).toBe((500 + EXPORT_PADDING * 2) * 2);

    // 超长时序图（5000×800）→ 单边封顶 8192px
    const huge = computeExportDimensions(5000, 800, 2);
    expect(huge.width).toBeLessThanOrEqual(MAX_CANVAS_SIDE);
    expect(huge.height).toBeLessThanOrEqual(MAX_CANVAS_SIDE);
  });

  it('naturalSize 在 width="100%" 时从 viewBox 取真实宽高', () => {
    const div = document.createElement('div');
    div.innerHTML = '<svg width="100%" style="max-width: 640px;" viewBox="0 0 640 280"></svg>';
    const svg = div.querySelector('svg')!;
    expect(naturalSize(svg)).toEqual({ width: 640, height: 280 });
  });

  it('在放大按钮旁渲染复制图片与下载图片按钮，共用同一套 PNG 光栅化管线', async () => {
    const fakeBlob = new Blob(['png-bytes'], { type: 'image/png' });

    const OrigImage = globalThis.Image;
    class MockImage {
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      decoding = 'sync';
      set src(_val: string) {
        setTimeout(() => this.onload?.(), 0);
      }
    }
    globalThis.Image = MockImage as unknown as typeof Image;

    const fillRect = vi.fn();
    const drawImage = vi.fn();
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
      fillStyle: '',
      fillRect,
      drawImage,
    } as unknown as CanvasRenderingContext2D);
    vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation((cb) => {
      cb(fakeBlob);
    });

    const clipboardWrite = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: { write: clipboardWrite },
    });
    (globalThis as unknown as { ClipboardItem: unknown }).ClipboardItem = class {
      items: Record<string, unknown>;
      constructor(items: Record<string, unknown>) {
        this.items = items;
      }
    };

    const createObjectURL = vi.fn().mockReturnValue('blob:mock-diagram-png');
    const revokeObjectURL = vi.fn();
    URL.createObjectURL = createObjectURL;
    URL.revokeObjectURL = revokeObjectURL;
    const anchorClick = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => undefined);

    try {
      render(<MermaidDiagram source="flowchart LR\n  A-->B" />);

      const copyBtn = await screen.findByTestId('mermaid-copy');
      const downloadBtn = await screen.findByTestId('mermaid-download');
      const zoomBtn = await screen.findByTestId('mermaid-zoom');

      expect(copyBtn).toBeTruthy();
      expect(downloadBtn).toBeTruthy();
      expect(zoomBtn).toBeTruthy();

      fireEvent.click(copyBtn);
      await waitFor(() => expect(clipboardWrite).toHaveBeenCalledTimes(1));
      expect(fillRect).toHaveBeenCalledWith(0, 0, 1600, expect.any(Number));
      expect(drawImage).toHaveBeenCalledTimes(1);

      fireEvent.click(downloadBtn);
      await waitFor(() => expect(createObjectURL).toHaveBeenCalledWith(fakeBlob));
      expect(anchorClick).toHaveBeenCalledTimes(1);
    } finally {
      globalThis.Image = OrigImage;
    }
  });
});
