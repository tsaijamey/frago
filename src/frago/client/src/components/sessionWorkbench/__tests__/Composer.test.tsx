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
import type { SendTrail } from '@/hooks/useWorkbenchRecords';
import Composer, { blockReason } from '../Composer';
import i18n from '@/i18n';
import { CONFIRM_WINDOW_MS } from '@/hooks/useSendToSession';

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

  it('发送失败：输入框还空着，就把这一单原样退回去，说明原因并给重试', async () => {
    fetchMock.mockImplementationOnce(async () => failResponse('send failed: tmux 会话没起来'));
    render(<Composer sessionId={SID} family="claude-code" onSent={NOOP} />);

    fireEvent.change(screen.getByTestId('composer-input'), { target: { value: '这段话不许丢' } });
    await pasteImage();
    fireEvent.click(screen.getByTestId('composer-send'));

    await waitFor(() => expect(screen.getByTestId('composer-error')).toBeTruthy());
    expect(screen.getByTestId('composer-error').textContent).toContain('tmux 会话没起来');
    // 报错条交代原文去哪了：退回了下面的输入框
    expect(screen.getByTestId('composer-kept').textContent).toContain('退回下面的输入框');
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

describe('点了发送，输入框当场空出来', () => {
  /** 一条永远不回来的发送请求：模拟"接口要等整整一轮才返回"。 */
  function stubHangingSend() {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise<Response>(() => {}))
    );
  }

  it('请求还挂着，输入框就已经空了——那句话撤不回，留在框里只会像没发出去', async () => {
    stubHangingSend();
    render(<Composer sessionId={SID} family="claude-code" onSent={() => {}} deliveredAt={null} />);
    const input = screen.getByTestId('composer-input') as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: '复制到 recipes 目录下' } });
    fireEvent.click(screen.getByTestId('composer-send'));

    await waitFor(() => expect(input.value).toBe(''));
    expect(screen.getByTestId('composer-send').textContent).toContain('发送中');
  });

  it('送达信号到就把按钮放回去，不必等整轮跑完', async () => {
    stubHangingSend();
    const { rerender } = render(
      <Composer sessionId={SID} family="claude-code" onSent={() => {}} deliveredAt={null} />
    );
    fireEvent.change(screen.getByTestId('composer-input'), { target: { value: '接着说' } });
    fireEvent.click(screen.getByTestId('composer-send'));
    await waitFor(() => expect(screen.getByTestId('composer-send').textContent).toContain('发送中'));

    rerender(
      <Composer sessionId={SID} family="claude-code" onSent={() => {}} deliveredAt={Date.now()} />
    );
    await waitFor(() =>
      expect(screen.getByTestId('composer-send').textContent).not.toContain('发送中')
    );
  });

  it('出门那一刻就报出原文与附件数，好给它开一个信封', async () => {
    stubHangingSend();
    const onSendStart = vi.fn(() => 'out-1');
    render(
      <Composer
        sessionId={SID}
        family="claude-code"
        onSent={() => {}}
        onSendStart={onSendStart}
      />
    );
    fireEvent.change(screen.getByTestId('composer-input'), { target: { value: '把日志翻出来' } });
    await pasteImage();
    fireEvent.click(screen.getByTestId('composer-send'));

    await waitFor(() => expect(onSendStart).toHaveBeenCalledWith('把日志翻出来', 1));
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
    await waitFor(() => expect(input.value).toBe(''));

    rerender(
      <Composer sessionId={SID} family="claude-code" onSent={() => {}} deliveredAt={Date.now()} />
    );

    fireEvent.change(input, { target: { value: '第二句还没发' } });
    await act(async () => {
      settle?.({ ok: true, json: async () => ({ sid: SID, status: 'ready', text: '' }) } as Response);
      await Promise.resolve();
    });
    expect(input.value).toBe('第二句还没发');
  });
});

describe('服务器重启，等整轮的那条请求断在半路', () => {
  /** 请求先挂着，由用例决定什么时候让它断：跟服务器重启时浏览器看到的一样，是连接失败。 */
  function stubDroppableSend() {
    let drop: (() => void) | null = null;
    vi.stubGlobal(
      'fetch',
      vi.fn(
        () =>
          new Promise<Response>((_, reject) => {
            drop = () => reject(new TypeError('Failed to fetch'));
          })
      )
    );
    return async () => {
      await act(async () => {
        drop?.();
        await Promise.resolve();
      });
    };
  }

  it('话已经送达再断：当它发成了，不亮红条，也不退回输入框', async () => {
    const dropConnection = stubDroppableSend();
    const onSendFailed = vi.fn();
    const { rerender } = render(
      <Composer sessionId={SID} family="claude-code" onSent={NOOP} onSendFailed={onSendFailed} deliveredAt={null} />
    );
    const input = screen.getByTestId('composer-input') as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: '把名字改成 teams' } });
    fireEvent.click(screen.getByTestId('composer-send'));
    await waitFor(() => expect(input.value).toBe(''));

    rerender(
      <Composer sessionId={SID} family="claude-code" onSent={NOOP} onSendFailed={onSendFailed} deliveredAt={Date.now()} />
    );
    await dropConnection();

    expect(screen.queryByTestId('composer-error')).toBeNull();
    expect(input.value).toBe('');
    expect(onSendFailed).not.toHaveBeenCalled();
  });

  it('还没见送达就断：先不判失败，服务器回来后记录里出现了就算发成', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const dropConnection = stubDroppableSend();
      const onSendFailed = vi.fn();
      const { rerender } = render(
        <Composer sessionId={SID} family="claude-code" onSent={NOOP} onSendFailed={onSendFailed} deliveredAt={null} />
      );
      const input = screen.getByTestId('composer-input') as HTMLTextAreaElement;
      fireEvent.change(input, { target: { value: '接着改' } });
      fireEvent.click(screen.getByTestId('composer-send'));
      await waitFor(() => expect(input.value).toBe(''));
      await dropConnection();

      expect(screen.queryByTestId('composer-error')).toBeNull();
      expect(input.value).toBe('');

      await act(async () => {
        vi.advanceTimersByTime(5_000);
      });
      rerender(
        <Composer sessionId={SID} family="claude-code" onSent={NOOP} onSendFailed={onSendFailed} deliveredAt={Date.now()} />
      );
      await act(async () => {
        vi.advanceTimersByTime(CONFIRM_WINDOW_MS);
      });

      expect(screen.queryByTestId('composer-error')).toBeNull();
      expect(input.value).toBe('');
      expect(onSendFailed).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it('还没见送达就断、等满也没见到：这才判失败，原话退回并给重试', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const dropConnection = stubDroppableSend();
      const onSendFailed = vi.fn();
      render(
        <Composer sessionId={SID} family="claude-code" onSent={NOOP} onSendFailed={onSendFailed} deliveredAt={null} />
      );
      const input = screen.getByTestId('composer-input') as HTMLTextAreaElement;
      fireEvent.change(input, { target: { value: '这句真没出去' } });
      fireEvent.click(screen.getByTestId('composer-send'));
      await waitFor(() => expect(input.value).toBe(''));
      await dropConnection();

      await act(async () => {
        vi.advanceTimersByTime(CONFIRM_WINDOW_MS);
      });

      expect(screen.getByTestId('composer-error').textContent).toContain('Failed to fetch');
      expect(input.value).toBe('这句真没出去');
      expect(onSendFailed).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('待发的气泡：与记录流里的「你说」同一种画法', () => {
  const WAITING = {
    id: 'out-1',
    text: '把 recipes 目录清一遍',
    attachments: 0,
    at: Date.now(),
    state: 'sent' as const,
  };
  const trail = (over: Partial<SendTrail> = {}): SendTrail => ({
    id: 'out-1',
    text: '把 recipes 目录清一遍',
    attachments: 0,
    recordId: null,
    midTurn: false,
    steps: { on_its_way: Date.now() },
    ...over,
  });

  it('在路上：虚线气泡，说清它离开了页面还没进会话；标题已说了这一档，步骤链不重复', () => {
    render(
      <Composer
        sessionId={SID}
        family="claude-code"
        onSent={NOOP}
        outbound={[WAITING]}
        trails={[trail()]}
      />
    );

    const bubble = screen.getByTestId('composer-outbound');
    expect(bubble.getAttribute('data-state')).toBe('sent');
    expect(bubble.className).toContain('border-dashed');
    expect(bubble.textContent).toContain('在路上');
    expect(bubble.textContent).toContain('已离开这个页面，还没进会话');
    expect(bubble.textContent).toContain('把 recipes 目录清一遍');
    expect(bubble.textContent?.split('在路上').length).toBe(2);
    expect(screen.queryByTestId('send-progress')).toBeNull();
  });

  it('排队中：实线中性框加时钟，不用绿', () => {
    render(
      <Composer
        sessionId={SID}
        family="claude-code"
        onSent={NOOP}
        outbound={[{ ...WAITING, state: 'queued' }]}
        trails={[trail({ midTurn: true, steps: { on_its_way: 1, queued: 2 } })]}
      />
    );

    const bubble = screen.getByTestId('composer-outbound');
    expect(bubble.getAttribute('data-state')).toBe('queued');
    // 标题写着排队中，步骤链只留之前那一步
    expect(bubble.textContent?.split('排队中').length).toBe(2);
    expect(screen.getByTestId('send-progress').getAttribute('data-step')).toBe('on_its_way');
    expect(bubble.textContent).toContain('排队中');
    expect(bubble.textContent).toContain('agent 还在处理你上一句');
    expect(bubble.className).not.toContain('border-dashed');
    // 排队不是成功，也不是动作：这一块里一处品牌绿都没有
    expect(bubble.outerHTML).not.toContain('accent-primary');
  });

  it('纯附件那一单没有正文，气泡照样说得清它是什么', () => {
    render(
      <Composer
        sessionId={SID}
        family="claude-code"
        onSent={NOOP}
        outbound={[{ ...WAITING, text: '', attachments: 2 }]}
      />
    );

    const bubble = screen.getByTestId('composer-outbound');
    expect(bubble.textContent).toContain('只有附件');
    expect(bubble.textContent).toContain('2');
  });

  it('一条都没有就什么都不画——输入区上方不该无故多出一块', () => {
    render(<Composer sessionId={SID} family="claude-code" onSent={NOOP} />);
    expect(screen.queryByTestId('composer-outbound')).toBeNull();
    expect(screen.queryByTestId('composer-moved-up')).toBeNull();
  });

  it('全部落进记录流之后留一行「移进上面的对话 · 看看」，点看看交出那条记录', () => {
    const onShow = vi.fn();
    const { rerender } = render(
      <Composer
        sessionId={SID}
        family="claude-code"
        onSent={NOOP}
        outbound={[WAITING]}
        trails={[trail()]}
        onShowInStream={onShow}
      />
    );
    rerender(
      <Composer
        sessionId={SID}
        family="claude-code"
        onSent={NOOP}
        outbound={[]}
        trails={[trail({ recordId: 'rec-9', steps: { on_its_way: 1, in_the_session: 2 } })]}
        onShowInStream={onShow}
      />
    );
    const line = screen.getByTestId('composer-moved-up');
    expect(line.textContent).toContain('这句话已经移进上面的对话');
    fireEvent.click(screen.getByTestId('composer-moved-up-show'));
    expect(onShow).toHaveBeenCalledWith('rec-9');
  });

  it('发送中那颗按钮变灰，这一屏没有实心绿', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => {})));
    render(<Composer sessionId={SID} family="claude-code" onSent={NOOP} />);
    fireEvent.change(screen.getByTestId('composer-input'), { target: { value: 'ping' } });
    expect(screen.getByTestId('composer-send').className).toContain('bg-accent-primary');
    fireEvent.click(screen.getByTestId('composer-send'));
    await waitFor(() =>
      expect(screen.getByTestId('composer-send').className).not.toContain('bg-accent-primary')
    );
    vi.unstubAllGlobals();
  });
});

describe('没发出去：报错条里带同一串步骤名', () => {
  it('✓ 在路上 › ✕ 没发出去，并说原文退回了输入框', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => failResponse('send failed: tmux 会话没起来'))
    );
    const failed: SendTrail = {
      id: 'out-1',
      text: 'x',
      attachments: 0,
      recordId: null,
      midTurn: false,
      steps: { on_its_way: 1, failed: 2 },
    };
    render(<Composer sessionId={SID} family="claude-code" onSent={NOOP} trails={[failed]} />);
    fireEvent.change(screen.getByTestId('composer-input'), { target: { value: 'x' } });
    fireEvent.click(screen.getByTestId('composer-send'));
    await waitFor(() => expect(screen.getByTestId('composer-error')).toBeTruthy());
    const bar = screen.getByTestId('composer-error');
    const progress = bar.querySelector('[data-testid=send-progress]');
    expect(progress?.textContent).toContain('在路上');
    expect(progress?.textContent).toContain('没发出去');
    expect(bar.textContent).toContain('一个字没丢');
    vi.unstubAllGlobals();
  });
});

/**
 * 上沿那条线上的小人。
 *
 * 他不表达任何新状态，所以用例只钉两件事：这一场在跑他就得在走，落下来他就得坐下；
 * 以及踱步这件事不许影响发不发得出去——跑着的时候照样能插话。
 */
describe('Composer 线上的小人', () => {
  it('会话在跑他就在走，会话落下他就坐下', () => {
    const { rerender } = render(
      <Composer sessionId={SID} family="claude-code" running onSent={NOOP} />
    );
    const pose = () =>
      screen.getByTestId('composer-walker').querySelector('[data-pose]')?.getAttribute('data-pose');
    expect(screen.getByTestId('composer-walker').getAttribute('data-walking')).toBe('yes');
    expect(pose()).toBe('walk');

    rerender(<Composer sessionId={SID} family="claude-code" running={false} onSent={NOOP} />);
    expect(screen.getByTestId('composer-walker').getAttribute('data-walking')).toBe('no');
    expect(pose()).toBe('rest');
  });

  it('他在走的时候照样发得出去——踱步不是闸门', () => {
    render(<Composer sessionId={SID} family="claude-code" running onSent={NOOP} />);
    fireEvent.change(screen.getByTestId('composer-input'), { target: { value: '插一句' } });
    expect((screen.getByTestId('composer-send') as HTMLButtonElement).disabled).toBe(false);
  });
});

/**
 * 他走的是来回，不是一路往一边。
 *
 * 每走完一段临时抽一个新落点，落点可能在他左边也可能在右边——所以方向自己就会翻。
 * 用例走十几段，两个方向都得出现过，且一段都不许迈出那条线的两端。
 */
describe('Composer 小人的走法', () => {
  it('十几段走下来两个方向都出现过，而且没有一段迈出线外', () => {
    vi.useFakeTimers();
    try {
      render(<Composer sessionId={SID} family="claude-code" running onSent={NOOP} />);
      const mark = screen.getByTestId('composer-walker').firstElementChild as HTMLElement;
      const readX = () => Number(/translateX\((-?[\d.]+)px\)/.exec(mark.style.transform)?.[1] ?? 0);

      const track: number[] = [readX()];
      for (let i = 0; i < 16; i += 1) {
        act(() => {
          vi.advanceTimersByTime(4000);
        });
        track.push(readX());
      }

      const moves = track.slice(1).map((x, i) => x - track[i]);
      expect(moves.some((d) => d > 0)).toBe(true);
      expect(moves.some((d) => d < 0)).toBe(true);
      expect(track.every((x) => x >= 0)).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('交接到新会话', () => {
  it('上下文不到三十万时置灰，悬停说明还差多少', () => {
    render(<Composer sessionId={SID} family="claude-code" onSent={NOOP} contextTokens={120_000} onHandoff={NOOP} />);
    const btn = screen.getByTestId('composer-handoff');
    expect((btn as HTMLButtonElement).disabled).toBe(true);
    expect(btn.getAttribute('title')).toBe('上下文到 300k 才需要换场（现在 120k）');
  });

  it('还没读到用量刻度时也置灰', () => {
    render(<Composer sessionId={SID} family="claude-code" onSent={NOOP} contextTokens={null} onHandoff={NOOP} />);
    expect((screen.getByTestId('composer-handoff') as HTMLButtonElement).disabled).toBe(true);
  });

  it('到了三十万放开，按下去交给页面', () => {
    const onHandoff = vi.fn();
    render(<Composer sessionId={SID} family="claude-code" onSent={NOOP} contextTokens={300_000} onHandoff={onHandoff} />);
    const btn = screen.getByTestId('composer-handoff');
    expect((btn as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(btn);
    expect(onHandoff).toHaveBeenCalledTimes(1);
  });

  it('比发送低一档：只描边不填色', () => {
    render(<Composer sessionId={SID} family="claude-code" onSent={NOOP} contextTokens={400_000} onHandoff={NOOP} />);
    const handoff = screen.getByTestId('composer-handoff').className;
    const send = screen.getByTestId('composer-send').className;
    expect(send).toContain('bg-accent-primary');
    expect(handoff).not.toMatch(/(^|\s)bg-accent-primary(\s|$)/);
    expect(handoff).toContain('border-border-accent');
  });

  it('一场都没选时不画', () => {
    render(<Composer sessionId={null} family={null} onSent={NOOP} contextTokens={400_000} onHandoff={NOOP} />);
    expect(screen.queryByTestId('composer-handoff')).toBeNull();
  });
});

describe('决定卡片的答复', () => {
  it('输入框里有字时收到卡片答复：投出的是答复，框里的字原样留着', async () => {
    const onSent = vi.fn();
    const onSendStart = vi.fn(() => 'out-1');
    const { rerender } = render(
      <Composer sessionId={SID} family="claude-code" onSent={onSent} onSendStart={onSendStart} />
    );
    fireEvent.change(screen.getByTestId('composer-input'), { target: { value: '还没写完的一句' } });

    const answer = { text: '【answer】A · 发布 —— 打 v1.4.111 tag 并上传 PyPI，发出去收不回', at: 1 };
    rerender(
      <Composer
        sessionId={SID}
        family="claude-code"
        onSent={onSent}
        onSendStart={onSendStart}
        answer={answer}
      />
    );

    await waitFor(() => expect(onSent).toHaveBeenCalledTimes(1));
    expect(sentBody(fetchMock)).toEqual({ text: answer.text, images: [], documents: [] });
    // 同一条出门路：信封照开
    expect(onSendStart).toHaveBeenCalledWith(answer.text, 0);
    expect((screen.getByTestId('composer-input') as HTMLTextAreaElement).value).toBe('还没写完的一句');
  });

  it('发送失败：框里有字就收着等重试，不覆盖人在打的字', async () => {
    fetchMock.mockImplementationOnce(async () => failResponse('send failed: tmux 会话没起来'));
    const onSendFailed = vi.fn();
    const { rerender } = render(
      <Composer sessionId={SID} family="claude-code" onSent={NOOP} onSendStart={() => 'out-9'} onSendFailed={onSendFailed} />
    );
    fireEvent.change(screen.getByTestId('composer-input'), { target: { value: '框里的字' } });
    rerender(
      <Composer
        sessionId={SID}
        family="claude-code"
        onSent={NOOP}
        onSendStart={() => 'out-9'}
        onSendFailed={onSendFailed}
        answer={{ text: '【answer】B · 先不发 —— 改动留在 main，不打 tag', at: 1 }}
      />
    );
    await waitFor(() => expect(onSendFailed).toHaveBeenCalledWith('out-9'));
    expect((screen.getByTestId('composer-input') as HTMLTextAreaElement).value).toBe('框里的字');
    expect(screen.getByTestId('composer-kept').textContent).toBe(i18n.t('workbench.composer.heldForRetry'));
  });
});
