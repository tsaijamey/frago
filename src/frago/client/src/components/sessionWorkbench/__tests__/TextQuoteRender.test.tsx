import { beforeAll, describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import i18n from '@/i18n';
import {
  parseTextQuoteBlocks,
  serializeQuotesWithPrompt,
  stripTextQuoteBlocks,
} from '@/utils/textQuoteBlocks';
import { cleanGoalText, extractGoalSummary } from '@/utils/goalAnchor';
import RecordCard from '../RecordCard';
import SessionLaunchPanel from '../SessionLaunchPanel';
import type { WorkbenchRecord } from '@/hooks/useWorkbenchRecords';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

describe('textQuoteBlocks 解析、序列化与剥离', () => {
  it('serializeQuotesWithPrompt 生成标准 """...""" + >>> 格式，兼容空提问与多条引用', () => {
    const serialized = serializeQuotesWithPrompt(
      [
        { id: 'q1', text: '第一段引用内容' },
        { id: 'q2', text: '第二段引用内容\n含第二行' },
      ],
      '请对比这两段逻辑'
    );
    expect(serialized).toBe(
      '"""\n第一段引用内容\n"""\n"""\n第二段引用内容\n含第二行\n"""\n>>> 请对比这两段逻辑'
    );

    const parsed = parseTextQuoteBlocks(serialized);
    expect(parsed.hasQuotes).toBe(true);
    expect(parsed.quotes).toHaveLength(2);
    expect(parsed.quotes[0].text).toBe('第一段引用内容');
    expect(parsed.quotes[1].text).toBe('第二段引用内容\n含第二行');
    expect(parsed.quotes[1].lineCount).toBe(2);
    expect(parsed.userPrompt).toBe('请对比这两段逻辑');
    expect(stripTextQuoteBlocks(serialized)).toBe('请对比这两段逻辑');
  });

  it('跳过 Markdown 代码围栏内部的 Python docstring 三引号，不误判为引用块', () => {
    const codeMsg = [
      '请检查这段 Python 代码：',
      '```python',
      'def foo():',
      '"""',
      '这是函数文档字符串',
      '"""',
      '    return 42',
      '```',
    ].join('\n');
    const parsed = parseTextQuoteBlocks(codeMsg);
    expect(parsed.hasQuotes).toBe(false);
    expect(parsed.quotes).toHaveLength(0);
    expect(stripTextQuoteBlocks(codeMsg)).toBe(codeMsg);
  });

  it('兼容历史消息中多段交替的 """ 引用块与 >>> 跟评', () => {
    const legacy = [
      '先说背景',
      '"""',
      '历史引用甲',
      '"""',
      '>>> 针对甲的补充',
      '"""',
      '历史引用乙',
      '"""',
      '>>> 针对乙的结论',
    ].join('\n');
    const parsed = parseTextQuoteBlocks(legacy);
    expect(parsed.hasQuotes).toBe(true);
    expect(parsed.quotes.map((q) => q.text)).toEqual(['历史引用甲', '历史引用乙']);
    expect(parsed.userPrompt).toBe('先说背景\n\n针对甲的补充\n\n针对乙的结论');
  });

  it('cleanGoalText 与 extractGoalSummary 自动剥离引用源码，只保留用户真实目标', () => {
    const raw = '"""\n一大段被引用的历史日志或文档内容\n第二行引用\n"""\n>>> 请把这段引用渲染成特定样式';
    expect(cleanGoalText(raw)).toBe('请把这段引用渲染成特定样式');
    expect(extractGoalSummary(raw)).toBe('请把这段引用渲染成特定样式');
  });
});

describe('会话消息与首屏过渡面板中的 Quote 卡片渲染', () => {
  it('RecordCard UserSay 将 """...""" + >>> 渲染为复用 wb-ctx-focus-card / wb-ctx-focus-quote 契约的引用卡片，超 3 行可展开/收起', () => {
    const longQuote = ['第一行引用', '第二行引用', '第三行引用', '第四行超出默认折叠阈值'].join('\n');
    const rec: WorkbenchRecord = {
      id: 'rec-user-quote',
      session_id: 'sid-1',
      group_id: null,
      seq: 1,
      ts: Date.now(),
      kind: 'user.say',
      agent_path: [],
      payload: {
        text: `"""\n${longQuote}\n"""\n>>> 请按现有相似样式渲染`,
      },
      raw_available: false,
    };

    render(<RecordCard record={rec} sessionId="sid-1" />);

    const card = screen.getByTestId('session-quote-card');
    expect(card.className).toContain('wb-ctx-focus-card');
    const quoteBody = screen.getByTestId('session-quote-body');
    expect(quoteBody.className).toContain('wb-ctx-focus-quote');
    // 默认折叠（超过 3 行）
    expect(quoteBody.firstElementChild?.className).toContain('line-clamp-3');

    // 点击展开全文
    const toggle = screen.getByTestId('session-quote-toggle');
    fireEvent.click(toggle);
    expect(quoteBody.firstElementChild?.className).not.toContain('line-clamp-3');

    // 用户实际提问在卡片下方独立展示，不含裸 """ 或 >>>
    expect(screen.getByText('请按现有相似样式渲染')).toBeTruthy();
    expect(document.body.textContent).not.toContain('"""');
    expect(document.body.textContent).not.toContain('>>>');
  });

  it('SessionLaunchPanel 首屏过渡气泡同样将 Quote 渲染为结构化引用卡片', () => {
    render(
      <SessionLaunchPanel
        launch={{
          handle: 'h-1',
          sessionId: null,
          agentName: 'Claude Code',
          cwd: '/Users/frago/Repos/frago',
          text: '"""\n首屏引用的段落\n"""\n>>> 开启新会话分析这段话',
          phase: 'claiming',
          at: Date.now(),
          error: null,
        }}
        onDismiss={() => {}}
      />
    );

    expect(screen.getByTestId('session-quote-card').className).toContain('wb-ctx-focus-card');
    expect(screen.getByTestId('session-quote-body').textContent).toBe('首屏引用的段落');
    expect(screen.getByText('开启新会话分析这段话')).toBeTruthy();
  });
});
