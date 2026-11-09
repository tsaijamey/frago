import { describe, expect, it } from 'vitest';
import {
  isPureAsyncCallbackRecord,
  splitAllLeadingBlocks,
  splitAsyncCallbackBlocks,
} from '../asyncCallbackBlocks';
import { humanReplyText } from '@/hooks/useDecisionCards';
import type { WorkbenchRecord } from '@/hooks/useWorkbenchRecords';

const WORKER_CALLBACK_SAMPLE = `<frago-async-callback kind="worker" mode="new" job_id="disp-beaa67f7b8ea" worker_session_id="core_20261106_115104_b00cf771" status="completed">
【下属 Worker 异步回传】来自 Worker 会话 \`core_20261106_115104_b00cf771\`（模式：新建执行，内核：\`coreagent\`）
- 派发单号：\`disp-beaa67f7b8ea\`
- 任务摘要：# Worker 任务书：阶段四验证
1. 运行 pytest 验证全量单测；
2. 汇总最终回归结果。
- 执行状态：\`completed\` (exit_code=0)

### Worker 交付结果
已完成阶段四验证，**全部 48 条单测通过**。

---
请作为管理者（Employee）结合领域知识与执行准则审核上述 Worker 产出：
1. 若产出合格且满足人类诉求，请提炼结论并向人类给出最终结果与决策建议；
2. 若发现遗漏或需补充验证，可继续向该 Worker（\`frago agent --resume core_20261106_115104_b00cf771\`）追派任务书。
</frago-async-callback>`;

const EMPLOYEE_CALLBACK_SAMPLE = `<frago-async-callback kind="employee" mode="ask" job_id="disp-72fc9081aa11" employee_id="frago-developer" session_id="3a91c0d2-1122-4333-8444-556677889900" status="failed">
【同侪员工异步回传】来自 \`frago-developer\`（会话 \`3a91c0d2-1122-4333-8444-556677889900\`，模式：协查提问）
- 派发单号：\`disp-72fc9081aa11\`
- 原始诉求：请排查 async_dispatch 投喂链路
- 执行状态：\`failed\` (exit_code=1)

### 同侪员工返回结论
定位到原因：缺少前端独立卡片解析。

---
请基于上述同侪员工回传结论，结合你掌握的领域背景与事务围栏进行复核，在本会话中直接向人类汇报最终处理结果与决策建议。
</frago-async-callback>`;

describe('splitAsyncCallbackBlocks', () => {
  it('解析下属 Worker 异步回传块并剥离尾部管理者样板提示词', () => {
    const { text, callbacks } = splitAsyncCallbackBlocks(WORKER_CALLBACK_SAMPLE);
    expect(text).toBe('');
    expect(callbacks).toHaveLength(1);
    expect(callbacks[0]).toEqual({
      kind: 'worker',
      mode: 'new',
      jobId: 'disp-beaa67f7b8ea',
      targetSessionId: 'core_20261106_115104_b00cf771',
      employeeId: '',
      agentKernel: 'coreagent',
      status: 'completed',
      exitCode: 0,
      taskSummary: '# Worker 任务书：阶段四验证\n1. 运行 pytest 验证全量单测；\n2. 汇总最终回归结果。',
      taskTitle: 'Worker 任务书：阶段四验证',
      resultBody: '已完成阶段四验证，**全部 48 条单测通过**。',
    });
  });

  it('解析同侪员工异步回传块及失败退出码', () => {
    const { text, callbacks } = splitAsyncCallbackBlocks(EMPLOYEE_CALLBACK_SAMPLE);
    expect(text).toBe('');
    expect(callbacks).toHaveLength(1);
    expect(callbacks[0]).toEqual({
      kind: 'employee',
      mode: 'ask',
      jobId: 'disp-72fc9081aa11',
      targetSessionId: '3a91c0d2-1122-4333-8444-556677889900',
      employeeId: 'frago-developer',
      agentKernel: '',
      status: 'failed',
      exitCode: 1,
      taskSummary: '请排查 async_dispatch 投喂链路',
      taskTitle: '请排查 async_dispatch 投喂链路',
      resultBody: '定位到原因：缺少前端独立卡片解析。',
    });
  });

  it('回调块后紧跟人类输入文字时（如输入框滞留回传后人类继续打字），同时保留回调与人类正文', () => {
    const combined = `${WORKER_CALLBACK_SAMPLE}\n查一下本地workbuddy proxy是不是被误关了`;
    const { text, callbacks } = splitAsyncCallbackBlocks(combined);
    expect(callbacks).toHaveLength(1);
    expect(callbacks[0].jobId).toBe('disp-beaa67f7b8ea');
    expect(text).toBe('查一下本地workbuddy proxy是不是被误关了');
  });

  it('正文中间引用的 <frago-async-callback> 样本不误判为注入块', () => {
    const quoted = `原文：\n"""\n${WORKER_CALLBACK_SAMPLE}\n"""\n>>> 请把这类块做成独立卡片`;
    const { text, callbacks } = splitAsyncCallbackBlocks(quoted);
    expect(callbacks).toHaveLength(0);
    expect(text).toBe(quoted);
  });

  it('splitAllLeadingBlocks 支持与 <frago-employee>、<must-use-skill> 组合剥离', () => {
    const emp = `<frago-employee id="lenovo" title="Lenovo 顾问" kernel="claude">\n岗位说明\n</frago-employee>`;
    const raw = `${emp}\n\n${WORKER_CALLBACK_SAMPLE}`;
    const res = splitAllLeadingBlocks(raw);
    expect(res.employees).toHaveLength(1);
    expect(res.employees[0].id).toBe('lenovo');
    expect(res.callbacks).toHaveLength(1);
    expect(res.callbacks[0].jobId).toBe('disp-beaa67f7b8ea');
    expect(res.text).toBe('');
  });

  it('isPureAsyncCallbackRecord 与 humanReplyText 对纯异步回传与混合发言分别返回正确结果', () => {
    const pureRecord: WorkbenchRecord = {
      id: 'r1',
      session_id: 's1',
      group_id: null,
      seq: 1,
      ts: 1000,
      kind: 'user.say',
      agent_path: [],
      payload: { text: WORKER_CALLBACK_SAMPLE },
      raw_available: true,
    };
    expect(isPureAsyncCallbackRecord(pureRecord)).toBe(true);
    expect(humanReplyText(pureRecord)).toBeNull();

    const mixedRecord: WorkbenchRecord = {
      ...pureRecord,
      id: 'r2',
      payload: { text: `${WORKER_CALLBACK_SAMPLE}\n查一下本地workbuddy proxy是不是被误关了` },
    };
    expect(isPureAsyncCallbackRecord(mixedRecord)).toBe(false);
    expect(humanReplyText(mixedRecord)).toBe('查一下本地workbuddy proxy是不是被误关了');
  });
});
