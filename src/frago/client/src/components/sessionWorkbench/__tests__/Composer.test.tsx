/**
 * 输入区的组件测试。
 *
 * 覆盖四条硬要求各自最容易破的那一面：发完要重拉真记录、失败一个字都不许丢、图片粘进来
 * 要能看见也要能逐个撤、三家的会话都发得出去而一场都没选时闸死。
 *
 * 不连真服务端——`fetch` 全程被替身接管，只核对出门的那一份请求长什么样。
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import Composer, { blockReason } from '../Composer';
import i18n from '@/i18n';

/**
 * 界面上的字全部走词表了，用例断言的是中文那一份，所以先把语言切到中文。
 *
 * 这一句顺带把另一件事也核了：`zh.json` 里的字必须与从前写死在组件里的逐字相同，
 * 差一个标点，下面这些断言就红。
 */
beforeAll(async () => {
  await i18n.changeLanguage('zh');
});


const SID = '00a02979-7eb4-5c70-94ae-867c8281e3f6';
const OPENCODE_SID = 'ses_058288655ffeYMxYC1AZKCcv56';
const CODEX_SID = '01a01a98-82e9-7013-b24e-e5e91b03995a';

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
    documents: { name: string; data: string }[];
  };
}

function pngFile(name = 'shot.png') {
  return new File(['fake-png-bytes'], name, { type: 'image/png' });
}

/** 一份非图片文件。MIME 不是 image/*，所以它该被分到文档那条路。 */
function docFile(name = 'spec.md', type = 'text/markdown') {
  return new File(['# spec'], name, { type });
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
  it('只有一场都没选才闸死，三家的会话都发得出去', () => {
    // 交回的是词表键，取字由界面做——这样切语言时这句提示才跟着变。
    expect(blockReason(null)).toBe('workbench.composer.blockedNoSession');
    expect(blockReason(SID)).toBeNull();
    expect(blockReason(OPENCODE_SID)).toBeNull();
    expect(blockReason(CODEX_SID)).toBeNull();
  });
});

describe('Composer 输入区', () => {
  it('纯文本发出去，发完重拉真记录', async () => {
    const onSent = vi.fn();
    render(<Composer sessionId={SID} family="claude-code" onSent={onSent} />);

    fireEvent.change(screen.getByTestId('composer-input'), { target: { value: '  开工  ' } });
    fireEvent.click(screen.getByTestId('composer-send'));

    await waitFor(() => expect(onSent).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls[0][0]).toContain(`/api/workbench/sessions/${SID}/send`);
    expect(sentBody(fetchMock)).toEqual({ text: '开工', images: [], documents: [] });
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

  it('挂一份文档也能发，它跟图片分两路走', async () => {
    const onSent = vi.fn();
    render(<Composer sessionId={SID} family="claude-code" onSent={onSent} />);

    fireEvent.change(screen.getByTestId('composer-file'), {
      target: { files: [docFile('spec.md')] },
    });
    // 文档不做缩略图，界面上是一行带文件名的条。
    await waitFor(() => expect(screen.getByTestId('composer-doc')).toBeTruthy());
    expect(screen.getByTestId('composer-doc').textContent).toContain('spec.md');
    expect(screen.queryByTestId('composer-thumb')).toBeNull();

    fireEvent.click(screen.getByTestId('composer-send'));
    await waitFor(() => expect(onSent).toHaveBeenCalledTimes(1));

    const body = sentBody(fetchMock);
    expect(body.images).toHaveLength(0);
    expect(body.documents).toHaveLength(1);
    // 原文件名要带上去：服务端拿它给落盘文件起名，agent 靠扩展名判断怎么读。
    expect(body.documents[0].name).toBe('spec.md');
    expect(body.documents[0].data).toMatch(/^data:text\/markdown;base64,/);
  });

  it('同一次选中图片和文档，各归各路', async () => {
    render(<Composer sessionId={SID} family="claude-code" onSent={NOOP} />);

    fireEvent.change(screen.getByTestId('composer-file'), {
      target: { files: [pngFile('shot.png'), docFile('notes.txt', 'text/plain')] },
    });

    await waitFor(() => expect(screen.getByTestId('composer-thumb')).toBeTruthy());
    await waitFor(() => expect(screen.getByTestId('composer-doc')).toBeTruthy());
    expect(screen.getByTestId('composer-doc').textContent).toContain('notes.txt');
  });

  it('文本与附件都空时按钮闸死，请求根本不出门', () => {
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

  it('opencode 的会话照样发得出去，走的是同一条通道', async () => {
    const onSent = vi.fn();
    render(<Composer sessionId={OPENCODE_SID} family="opencode" onSent={onSent} />);

    expect(screen.queryByTestId('composer-blocked')).toBeNull();
    expect(isDisabled('composer-input')).toBe(false);

    fireEvent.change(screen.getByTestId('composer-input'), { target: { value: '接着干' } });
    fireEvent.click(screen.getByTestId('composer-send'));

    await waitFor(() => expect(onSent).toHaveBeenCalledTimes(1));
    // 编号原样进 URL：该续接哪一家由服务端按编号判，前端一个字都不猜。
    expect(fetchMock.mock.calls[0][0]).toContain(
      `/api/workbench/sessions/${encodeURIComponent(OPENCODE_SID)}/send`
    );
  });

  it('codex 的会话一样，来源不再是闸门', async () => {
    const onSent = vi.fn();
    render(<Composer sessionId={CODEX_SID} family="codex" onSent={onSent} />);

    fireEvent.change(screen.getByTestId('composer-input'), { target: { value: '继续' } });
    fireEvent.click(screen.getByTestId('composer-send'));

    await waitFor(() => expect(onSent).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls[0][0]).toContain(`/api/workbench/sessions/${CODEX_SID}/send`);
  });

  it('输入框的占位话写明这一场是哪一家', () => {
    render(<Composer sessionId={CODEX_SID} family="codex" onSent={NOOP} />);

    expect(
      (screen.getByTestId('composer-input') as HTMLTextAreaElement).placeholder
    ).toContain('codex');
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

describe('送达即放行：不许等整轮跑完才清输入框', () => {
  /** 一条永远不回来的发送请求：模拟"接口要等整整一轮才返回"。 */
  function stubHangingSend() {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise<Response>(() => {}))
    );
  }

  it('话落进流里就清空输入框、把按钮放回去', async () => {
    stubHangingSend();
    const { rerender } = render(
      <Composer sessionId={SID} family="claude-code" onSent={() => {}} deliveredAt={null} />
    );
    const input = screen.getByTestId('composer-input') as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: '复制到 recipes 目录下' } });
    fireEvent.click(screen.getByTestId('composer-send'));

    // 请求还挂着：按钮转圈、文字还在。人此刻已经能在流里看到自己那句话了。
    await waitFor(() => expect(screen.getByTestId('composer-send').textContent).toContain('发送中'));
    expect(input.value).toBe('复制到 recipes 目录下');

    // 送达信号到——不必等接口返回。
    rerender(
      <Composer sessionId={SID} family="claude-code" onSent={() => {}} deliveredAt={Date.now()} />
    );
    await waitFor(() => expect(input.value).toBe(''));
    expect(screen.getByTestId('composer-send').textContent).not.toContain('发送中');
  });

  it('放行之后人接着打的新内容，不许被上一单的返回抹掉', async () => {
    // 上一单最终会回来，那时它若再清一次，人刚打的下一句就凭空消失了。
    let settle: ((r: Response) => void) | null = null;
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise<Response>((res) => { settle = res; }))
    );
    const { rerender } = render(
      <Composer sessionId={SID} family="claude-code" onSent={() => {}} deliveredAt={null} />
    );
    const input = screen.getByTestId('composer-input') as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: '第一句' } });
    fireEvent.click(screen.getByTestId('composer-send'));

    rerender(
      <Composer sessionId={SID} family="claude-code" onSent={() => {}} deliveredAt={Date.now()} />
    );
    await waitFor(() => expect(input.value).toBe(''));

    fireEvent.change(input, { target: { value: '第二句还没发' } });
    await act(async () => {
      settle?.({ ok: true, json: async () => ({ sid: SID, status: 'ready', text: '' }) } as Response);
      await Promise.resolve();
    });
    expect(input.value).toBe('第二句还没发');
  });
});
