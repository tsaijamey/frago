import { beforeAll, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import RecordCard from '../RecordCard';
import RecordStream from '../RecordStream';
import SessionLaunchPanel from '../SessionLaunchPanel';
import { previewOf } from '../SessionItem';
import type { WorkbenchRecord } from '@/hooks/useWorkbenchRecords';
import type { WorkbenchSession } from '@/hooks/useWorkbenchSessions';
import type { SessionObserverView } from '@/hooks/useSessionObserver';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

const FULL_USER_MESSAGE = [
  '请帮我核对这条工单的处理结论。',
  '',
  '---',
  '### 🎯 Focus 焦点内容（共 1 处）',
  '',
  '#### [FOCUS #1] [APEXP-4629] PIN answer not relevant（划词焦点）',
  '- 来源：https://jira.xpaas.lenovo.com/browse/APEXP-4629',
  '',
  'PIN answer verification failed after 3 attempts.',
  '',
  '---',
  '### 📄 网页完整可见上下文（共 1 页，按页去重并已原地锚定 Focus）',
  '',
  '#### [页面 1] [APEXP-4629] PIN answer not relevant - XPaaS JIRA（约 12108 字）',
  '- URL：https://jira.xpaas.lenovo.com/browse/APEXP-4629',
  '- 本页关联 Focus：#1',
  '',
  '工单描述前置段落。',
  '',
  '<<< 🎯 FOCUS #1 开始 >>>',
  'PIN answer verification failed after 3 attempts.',
  '<<< 🎯 FOCUS #1 结束 >>>',
  '',
  '工单后续评论内容。',
].join('\n');

describe('RecordCard Web Bridge Context', () => {
  it('将用户提问、Focus 引用卡与默认折叠的整页上下文分别渲染，展开后高亮 Focus 锚点且不留裸标记', () => {
    const record: WorkbenchRecord = {
      id: 'rec-bridge-1',
      session_id: 's1',
      seq: 1,
      ts: 1_753_800_000_000,
      kind: 'user.say',
      group_id: null,
      agent_path: [],
      raw_available: true,
      payload: {
        text: FULL_USER_MESSAGE,
        images: [],
        input_mode: 'keyboard',
        is_tool_result: false,
      },
    };

    const { container } = render(<RecordCard record={record} sessionId="s1" />);

    // 1. 顶部人类提问正常显示
    expect(screen.getByText('请帮我核对这条工单的处理结论。')).toBeTruthy();

    // 2. Focus 引用卡渲染，含徽标、标题、域名链接与引用内容，且无裸列表元数据
    const focusCard = screen.getByTestId('web-bridge-focus-card');
    expect(focusCard.textContent).toContain('🎯 Focus #1');
    expect(focusCard.textContent).toContain('[APEXP-4629] PIN answer not relevant');
    expect(focusCard.textContent).toContain('jira.xpaas.lenovo.com');
    expect(focusCard.textContent).toContain('PIN answer verification failed after 3 attempts.');
    expect(focusCard.textContent).not.toContain('来源：');

    // 3. 整页上下文默认折叠，显示摘要胶囊
    const toggle = screen.getByTestId('web-bridge-page-toggle');
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(toggle.textContent).toContain('网页完整可见上下文');
    expect(toggle.textContent).toContain('12,108');
    expect(toggle.textContent).toContain('含 1 处 Focus 锚点');
    expect(screen.queryByTestId('web-bridge-page-body')).toBeNull();
    expect(container.textContent).not.toContain('工单描述前置段落。');

    // 4. 点击展开后渲染全文，且 <<< 🎯 FOCUS #N >>> 裸标记替换为高亮块
    fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    const body = screen.getByTestId('web-bridge-page-body');
    expect(body.textContent).toContain('工单描述前置段落。');
    expect(body.textContent).toContain('工单后续评论内容。');

    const anchorHit = screen.getByTestId('web-bridge-anchor-highlight');
    expect(anchorHit.textContent).toContain('🎯 Focus #1');
    expect(anchorHit.textContent).toContain('PIN answer verification failed after 3 attempts.');
    expect(body.textContent).not.toContain('<<< 🎯 FOCUS');
    expect(body.textContent).not.toContain('开始 >>>');
    expect(body.textContent).not.toContain('结束 >>>');
  });

  it('SessionItem.previewOf 会剥离扩展回传网页上下文尾巴', () => {
    const session = {
      id: 's1',
      title: '测试会话',
      digest_done: FULL_USER_MESSAGE,
    } as unknown as WorkbenchSession;

    const preview = previewOf(session, null);
    expect(preview).toBe('请帮我核对这条工单的处理结论。');
  });

  it('SessionLaunchPanel 对无 Focus 的纯整页上下文（core_05cc 场景）默认折叠渲染', () => {
    const pageOnlyMessage = [
      '解读这个ticket里connie后来的comment内容。',
      '',
      '---',
      '### 📄 网页完整可见上下文（共 1 页，按页去重并已原地锚定 Focus）',
      '',
      '#### [页面 1] [APEXP-4652] PIN | Who are the most recently added contacts? - XPaaS JIRA（约 15116 字）',
      '- URL：https://jira.xpaas.lenovo.com/browse/APEXP-4652',
      '',
      'Linked Applications',
    ].join('\n');

    render(
      <SessionLaunchPanel
        launch={{
          handle: 'h1',
          sessionId: 'core_05cc72126ea84c939e9722d63387f1db',
          agentName: 'CoreAgent',
          cwd: '/Users/frago/Repos',
          phase: 'claiming',
          at: Date.now(),
          text: pageOnlyMessage,
          error: null,
        }}
        onDismiss={vi.fn()}
      />
    );

    expect(screen.getByTestId('launch-first-message').textContent).toBe(
      '解读这个ticket里connie后来的comment内容。'
    );
    const toggle = screen.getByTestId('web-bridge-page-toggle');
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(toggle.textContent).toContain('15,116');
    expect(screen.queryByTestId('web-bridge-page-body')).toBeNull();
  });

  it('Progress 视图 Goal Anchor 不受服务端污染的 anchor_summary 影响，仅展示干净提问', () => {
    const pageOnlyMessage = [
      '解读这个ticket里connie后来的comment内容。',
      '',
      '---',
      '### 📄 网页完整可见上下文（共 1 页，按页去重并已原地锚定 Focus）',
      '',
      '#### [页面 1] [APEXP-4652] PIN | Who are the most recently added contacts? - XPaaS JIRA（约 15116 字）',
      '- URL：https://jira.xpaas.lenovo.com/browse/APEXP-4652',
      '',
      'Linked Applications',
    ].join('\n');

    const records: WorkbenchRecord[] = [
      {
        id: 'u-05cc',
        session_id: 'core_05cc72126ea84c939e9722d63387f1db',
        seq: 1,
        ts: 1_753_800_000_000,
        kind: 'user.say',
        group_id: null,
        agent_path: [],
        raw_available: true,
        payload: { text: pageOnlyMessage, images: [], input_mode: 'keyboard' },
      },
    ];

    const observer: SessionObserverView = {
      state: {
        bound: true,
        anchor: pageOnlyMessage,
        anchor_summary:
          '解读这个ticket里connie后来的comment内容。 URL：https://jira.xpaas.lenovo.com/browse/APEXP-4652 Linked Applications',
        phase_goal: '解读 ticket 中 Connie 后续评论的内容',
        tail: { kind: 'now', text: '正在查询' },
        decision: '',
        happened: [],
        tasks: [],
        runs: [],
        updated_at: 1_753_800_010_000,
        model: 'minimax-m3.1-flash',
        status: 'ok',
        status_detail: null,
      },
      loading: false,
      error: null,
    };

    render(
      <RecordStream
        sessionId="core_05cc72126ea84c939e9722d63387f1db"
        records={records}
        loading={false}
        loadingOlder={false}
        hasOlder={false}
        error={null}
        onLoadOlder={vi.fn()}
        observer={observer}
      />
    );

    fireEvent.click(screen.getByTestId('lens-watcher'));
    const goalAnchor = screen.getByTestId('watcher-goal-anchor');
    expect(goalAnchor.textContent).toContain('解读这个ticket里connie后来的comment内容。');
    expect(goalAnchor.textContent).not.toContain('Linked Applications');
    expect(goalAnchor.textContent).not.toContain('URL：');
  });
});
