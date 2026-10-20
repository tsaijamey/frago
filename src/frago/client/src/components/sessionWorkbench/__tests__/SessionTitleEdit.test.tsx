import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import SessionWorkbenchPage from '../SessionWorkbenchPage';
import { usePageStore } from '@/stores/pageStore';
import * as api from '@/api';
import * as workbenchSessionsHook from '@/hooks/useWorkbenchSessions';
import * as workbenchRecordsHook from '@/hooks/useWorkbenchRecords';
import * as sessionMarksHook from '@/hooks/useSessionMarks';
import * as sessionFilesHook from '@/hooks/useSessionFiles';

const SID = '00a02979-7eb4-5c70-94ae-867c8281e3f6';

describe('SessionWorkbenchPage 标题内联编辑与星号按钮生成', () => {
  const setSessionTitle = vi.fn();

  beforeEach(() => {
    vi.restoreAllMocks();
    setSessionTitle.mockReset();
    usePageStore.setState({ workbenchSessionId: SID });

    vi.spyOn(workbenchSessionsHook, 'useWorkbenchSessions').mockReturnValue({
      sessions: [
        {
          session_id: SID,
          family: 'claude-code',
          title: '初始会话标题',
          directory: '/Users/frago/Repos/frago',
          created_at: 1_753_700_000_000,
          last_active_at: 1_753_800_000_000,
          last_reply_at: null,
          agent_paths: [],
          status: 'done',
          digest_done: null,
          digest_stuck: null,
          origin: 'human',
          parent_session_id: null,
        },
      ],
      visible: [],
      todaySessions: [],
      loading: false,
      error: null,
      filter: 'all',
      setFilter: () => {},
      counts: { all: 1, 'for-you': 0 },
      reload: async () => {},
      setSessionTitle,
    });

    vi.spyOn(workbenchRecordsHook, 'useWorkbenchRecords').mockReturnValue({
      records: [],
      recordsSessionId: SID,
      loading: false,
      loadingOlder: false,
      hasOlder: false,
      error: null,
      loadOlder: async () => {},
      reload: async () => {},
      awaitingAgent: false,
      outbound: [],
      markSent: () => 'out-1',
      deliveredAt: null,
      clearSent: () => {},
      markQueued: () => {},
      settleSent: () => {},
      trails: [],
    });

    vi.spyOn(sessionMarksHook, 'useSessionMarks').mockReturnValue({
      marks: [],
      loaded: true,
      addMark: () => null,
      addMarks: () => {},
      setNote: () => {},
      remove: () => {},
      move: () => {},
      markUsed: () => {},
      syncBranches: async () => {},
    });

    vi.spyOn(sessionFilesHook, 'useSessionFiles').mockReturnValue({
      files: [],
      loading: false,
      error: null,
      ensure: () => {},
      reload: () => {},
    });
  });

  it('点击原文标题进入内联编辑，按回车保存修改后的标题', async () => {
    const updateSpy = vi
      .spyOn(api, 'updateSessionTitle')
      .mockResolvedValue({ session_id: SID, title: '人工修改后的新标题' });

    render(<SessionWorkbenchPage />);

    const titleEl = screen.getByTestId('session-detail-title');
    expect(titleEl.textContent).toBe('初始会话标题');

    fireEvent.click(titleEl);
    const inputEl = screen.getByTestId('session-detail-title-input') as HTMLInputElement;
    expect(inputEl.value).toBe('初始会话标题');

    fireEvent.change(inputEl, { target: { value: '  人工修改后的新标题  ' } });
    fireEvent.keyDown(inputEl, { key: 'Enter' });

    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalledWith(SID, '人工修改后的新标题');
    });
    expect(setSessionTitle).toHaveBeenCalledWith(SID, '人工修改后的新标题');
  });

  it('点击星号按钮调用 CoreAgent 生成会话标题并更新', async () => {
    const generateSpy = vi
      .spyOn(api, 'generateSessionTitle')
      .mockResolvedValue({ session_id: SID, title: 'CoreAgent生成的标题' });

    render(<SessionWorkbenchPage />);

    const starBtn = screen.getByTestId('session-detail-title-generate');
    fireEvent.click(starBtn);

    await waitFor(() => {
      expect(generateSpy).toHaveBeenCalledWith(SID);
    });
    expect(setSessionTitle).toHaveBeenCalledWith(SID, 'CoreAgent生成的标题');
  });
});
