/**
 * 输入区的组件测试。
 *
 * 覆盖四条硬要求各自最容易破的那一面：发完要重拉真记录、失败一个字都不许丢、图片粘进来
 * 要能看见也要能逐个撤、发不出去的会话在打字之前就闸死。
 *
 * 不连真服务端——`fetch` 全程被替身接管，只核对出门的那一份请求长什么样。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import Composer, { blockReason } from '../Composer';

const SID = '00a02979-7eb4-5c70-94ae-867c8281e3f6';
const OPENCODE_SID = 'ses_058288655ffeYMxYC1AZKCcv56';

const NOOP = () => {};

/** 发送成功时服务端回什么。 */
function okResponse() {
  return {
    ok: true,
    status: 200,
    json: async () => ({ sid: SID, status: 'warm', text: '' }),
  } as unknown as Response;
}

/** 发送失败时服务端回什么。原因照抄 FastAPI 的 `detail`。 */
function failResponse(detail: string) {
  return {
    ok: false,
    status: 500,
    json: async () => ({ detail }),
  } as unknown as Response;
}

/** 出门那一份请求的 body。 */
function sentBody(fetchMock: ReturnType<typeof vi.fn>) {
  return JSON.parse(String(fetchMock.mock.calls[0][1].body)) as {
    text: string;
    images: string[];
  };
}

function pngFile(name = 'shot.png') {
  return new File(['fake-png-bytes'], name, { type: 'image/png' });
}

/** 这个控件此刻按不按得动。用原生属性判，不依赖 jest-dom 的匹配器。 */
function isDisabled(testId: string): boolean {
  return (screen.getByTestId(testId) as HTMLButtonElement | HTMLTextAreaElement).disabled;
}

/**
 * 把一张图粘进文本框，等它的缩略图出现。
 *
 * 等的是「总数到了 `expectTotal` 张」，不是「至少有一张」——读文件是异步的，连粘两张时
 * 后一张还没读完，「至少有一张」早就成立了，等于没等。
 */
async function pasteImage(name?: string, expectTotal = 1) {
  fireEvent.paste(screen.getByTestId('composer-input'), {
    clipboardData: { files: [pngFile(name)] },
  });
  await waitFor(() =>
    expect(screen.getAllByTestId('composer-thumb')).toHaveLength(expectTotal)
  );
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn(async () => okResponse());
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('blockReason 可发判定', () => {
  it('没选会话、或选的是 opencode，都给得出理由', () => {
    expect(blockReason(null, null)).toContain('挑一场会话');
    expect(blockReason(OPENCODE_SID, 'opencode')).toContain('opencode');
    expect(blockReason(SID, 'claude-code')).toBeNull();
  });
});

describe('Composer 输入区', () => {
  it('纯文本发出去，发完重拉真记录', async () => {
    const onSent = vi.fn();
    render(<Composer sessionId={SID} family="claude-code" onSent={onSent} />);

    fireEvent.change(screen.getByTestId('composer-input'), { target: { value: '  开工  ' } });
    fireEvent.click(screen.getByTestId('composer-send'));

    await waitFor(() => expect(onSent).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls[0][0]).toContain(`/api/claude-sessions/${SID}/send`);
    expect(sentBody(fetchMock)).toEqual({ text: '开工', images: [] });
    // 成功才清空。
    expect((screen.getByTestId('composer-input') as HTMLTextAreaElement).value).toBe('');
  });

  it('一个字都不打、只挂一张图也能发', async () => {
    const onSent = vi.fn();
    render(<Composer sessionId={SID} family="claude-code" onSent={onSent} />);

    await pasteImage();
    fireEvent.click(screen.getByTestId('composer-send'));

    await waitFor(() => expect(onSent).toHaveBeenCalledTimes(1));
    const body = sentBody(fetchMock);
    expect(body.text).toBe('');
    expect(body.images).toHaveLength(1);
    expect(body.images[0]).toMatch(/^data:image\/png;base64,/);
  });

  it('文本与图片都空时按钮闸死，请求根本不出门', () => {
    render(<Composer sessionId={SID} family="claude-code" onSent={NOOP} />);

    expect(isDisabled('composer-send')).toBe(true);
    fireEvent.click(screen.getByTestId('composer-send'));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('发送失败：文本与图片原样留着，说明原因并给重试', async () => {
    fetchMock.mockImplementationOnce(async () => failResponse('send failed: tmux 会话没起来'));
    render(<Composer sessionId={SID} family="claude-code" onSent={NOOP} />);

    fireEvent.change(screen.getByTestId('composer-input'), { target: { value: '这段话不许丢' } });
    await pasteImage();
    fireEvent.click(screen.getByTestId('composer-send'));

    await waitFor(() => expect(screen.getByTestId('composer-error')).toBeTruthy());
    expect(screen.getByTestId('composer-error').textContent).toContain('tmux 会话没起来');
    expect((screen.getByTestId('composer-input') as HTMLTextAreaElement).value).toBe('这段话不许丢');
    expect(screen.getAllByTestId('composer-thumb')).toHaveLength(1);

    // 重试就是再调一次，内容还是原来那一份。
    fireEvent.click(screen.getByTestId('composer-retry'));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(JSON.parse(String(fetchMock.mock.calls[1][1].body)).text).toBe('这段话不许丢');
  });

  it('opencode 的会话在打字之前就闸死，并写明为什么', () => {
    render(<Composer sessionId={OPENCODE_SID} family="opencode" onSent={NOOP} />);

    expect(screen.getByTestId('composer-blocked').textContent).toContain('opencode');
    expect(isDisabled('composer-input')).toBe(true);
    expect(isDisabled('composer-send')).toBe(true);
    expect(isDisabled('composer-pick')).toBe(true);
  });

  it('一场会话都没选时同样闸死，理由是让人先挑一场', () => {
    render(<Composer sessionId={null} family={null} onSent={NOOP} />);

    expect(screen.getByTestId('composer-blocked').textContent).toContain('挑一场会话');
    expect(isDisabled('composer-send')).toBe(true);
  });

  it('粘贴图片出现缩略图，截图不会变成一串乱码落进文本框', async () => {
    render(<Composer sessionId={SID} family="claude-code" onSent={NOOP} />);

    await pasteImage('screenshot.png');
    const thumb = screen.getByTestId('composer-thumb').querySelector('img');
    expect(thumb?.getAttribute('alt')).toBe('screenshot.png');
    expect(thumb?.getAttribute('src')).toMatch(/^data:image\/png;base64,/);
    expect((screen.getByTestId('composer-input') as HTMLTextAreaElement).value).toBe('');
    // 光挂着图，发送按钮就已经能按。
    expect(isDisabled('composer-send')).toBe(false);
  });

  it('拖进来的图片一样收', async () => {
    render(<Composer sessionId={SID} family="claude-code" onSent={NOOP} />);

    fireEvent.drop(screen.getByTestId('composer'), {
      dataTransfer: { files: [pngFile('dropped.png')] },
    });
    await waitFor(() => expect(screen.getAllByTestId('composer-thumb')).toHaveLength(1));
  });

  it('缩略图逐个可移除，移完按钮重新闸死', async () => {
    render(<Composer sessionId={SID} family="claude-code" onSent={NOOP} />);

    await pasteImage('a.png');
    await pasteImage('b.png', 2);

    fireEvent.click(screen.getByLabelText('移除 a.png'));
    await waitFor(() => expect(screen.getAllByTestId('composer-thumb')).toHaveLength(1));
    expect(screen.getByTestId('composer-thumb').querySelector('img')?.getAttribute('alt')).toBe(
      'b.png'
    );

    fireEvent.click(screen.getByLabelText('移除 b.png'));
    await waitFor(() => expect(screen.queryByTestId('composer-thumb')).toBeNull());
    expect(isDisabled('composer-send')).toBe(true);
  });
});
