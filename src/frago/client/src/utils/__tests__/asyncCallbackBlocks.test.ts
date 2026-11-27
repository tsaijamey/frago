import { describe, expect, it } from 'vitest';
import {
  asyncCallbackGroupKey,
  dedupeAsyncCallbacks,
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

  it('dedupeAsyncCallbacks 按同源合并多条回传并保留不同来源的回传', () => {
    const { callbacks: c1 } = splitAsyncCallbackBlocks(WORKER_CALLBACK_SAMPLE);
    const secondSameSource = WORKER_CALLBACK_SAMPLE
      .replace('disp-beaa67f7b8ea', 'disp-beaa67f7b8eb')
      .replace('全部 48 条单测通过', '全部 50 条单测通过');
    const { callbacks: c2 } = splitAsyncCallbackBlocks(secondSameSource);
    const { callbacks: c3 } = splitAsyncCallbackBlocks(EMPLOYEE_CALLBACK_SAMPLE);

    expect(asyncCallbackGroupKey(c1[0])).toBe(asyncCallbackGroupKey(c2[0]));
    expect(asyncCallbackGroupKey(c1[0])).not.toBe(asyncCallbackGroupKey(c3[0]));

    const deduped = dedupeAsyncCallbacks([c1[0], c2[0], c3[0]]);
    expect(deduped).toHaveLength(2);
    expect(deduped[0].dedupeCount).toBe(2);
    expect(deduped[0].callback.jobId).toBe('disp-beaa67f7b8eb');
    expect(deduped[0].callback.resultBody).toContain('全部 50 条单测通过');
    expect(deduped[1].dedupeCount).toBe(1);
    expect(deduped[1].callback.employeeId).toBe('frago-developer');
  });

  it('解析 <frago-async-callbacks count="1" delivery="idle-batch"> 批信封并剥离外层标签与系统导语', () => {
    const batch = `<frago-async-callbacks count="1" delivery="idle-batch" priority="background-after-human">

【后台异步派发回执汇总】以下 1 项后台异步任务已完成且当前会话处于空闲安全窗口，请结合领域上下文复核关键结论并按需向人类汇报。

${WORKER_CALLBACK_SAMPLE}

</frago-async-callbacks>`;

    const { text, callbacks } = splitAsyncCallbackBlocks(batch);
    expect(text).toBe('');
    expect(callbacks).toHaveLength(1);
    expect(callbacks[0].jobId).toBe('disp-beaa67f7b8ea');
    expect(callbacks[0].delivery).toBe('idle-batch');
    expect(callbacks[0].batchCount).toBe(1);
    expect(callbacks[0].resultBody).toContain('全部 48 条单测通过');
    expect(callbacks[0].resultBody).not.toContain('</frago-async-callback');
  });

  it('解析 <frago-async-callbacks count="2" delivery="idle-batch"> 多条混合来源批信封', () => {
    const batch = `<frago-async-callbacks count="2" delivery="idle-batch" priority="background-after-human">

【后台异步派发回执汇总】以下 2 项后台异步任务已完成且当前会话处于空闲安全窗口，请结合领域上下文复核关键结论并按需向人类汇报。

${WORKER_CALLBACK_SAMPLE}

${EMPLOYEE_CALLBACK_SAMPLE}

</frago-async-callbacks>`;

    const { text, callbacks } = splitAsyncCallbackBlocks(batch);
    expect(text).toBe('');
    expect(callbacks).toHaveLength(2);
    expect(callbacks[0].kind).toBe('worker');
    expect(callbacks[0].jobId).toBe('disp-beaa67f7b8ea');
    expect(callbacks[0].delivery).toBe('idle-batch');
    expect(callbacks[0].batchCount).toBe(2);
    expect(callbacks[1].kind).toBe('employee');
    expect(callbacks[1].employeeId).toBe('frago-developer');
    expect(callbacks[1].exitCode).toBe(1);
    expect(callbacks[1].delivery).toBe('idle-batch');

    const pureBatchRecord: WorkbenchRecord = {
      id: 'rb1',
      session_id: 's1',
      group_id: null,
      seq: 2,
      ts: 2000,
      kind: 'user.say',
      agent_path: [],
      payload: { text: batch },
      raw_available: true,
    };
    expect(isPureAsyncCallbackRecord(pureBatchRecord)).toBe(true);
    expect(humanReplyText(pureBatchRecord)).toBeNull();
  });

  it('解析 turn-submit-hitchhike 超 5500 字符紧凑降级批信封与省略尾项说明', () => {
    const compactBatch = `<frago-async-callbacks count="4" delivery="turn-submit-hitchhike" priority="background-after-human">

【优先主线声明】主人的本轮当前请求是唯一最高优先级主线；请先直接、完整回应主人本轮请求。
以下是在此之前由后台完成的异步派发回执，仅作附带参考信息；严禁让后台回执劫持你当前回应主人主线的议程（除非主人本轮正好在询问该任务）。

<frago-async-callback kind="worker" mode="new" job_id="disp-compact-1" worker_session_id="core_w1" status="completed">
- 来源：Worker \`core_w1\` | 派发单号：\`disp-compact-1\` | 状态：\`completed\` (exit_code=0)
- 诉求：核查 8093 构建产物哈希
- 摘要：构建产物已刷新，index.html 返回 200 OK。
- 完整交付：\`/tmp/report-1.md\`（或 \`frago session read core_w1\`）
</frago-async-callback>

<frago-async-callback kind="employee" mode="ask" job_id="disp-compact-2" employee_id="frago-developer" session_id="emp_s2" status="failed">
- 来源：同侪 \`frago-developer\` | 派发单号：\`disp-compact-2\` | 状态：\`failed\` (exit_code=2)
- 诉求：回归测试
- 完整交付：\`frago session read emp_s2\`
</frago-async-callback>

（因上下文预算上限，其余 2 条回执已省略详情；请查阅 \`~/.frago/sessions/async_dispatches/\`。）

</frago-async-callbacks>`;

    const { text, callbacks } = splitAsyncCallbackBlocks(compactBatch);
    expect(text).toBe('');
    expect(callbacks).toHaveLength(2);
    expect(callbacks[0]).toMatchObject({
      kind: 'worker',
      jobId: 'disp-compact-1',
      targetSessionId: 'core_w1',
      status: 'completed',
      exitCode: 0,
      taskSummary: '核查 8093 构建产物哈希',
      taskTitle: '核查 8093 构建产物哈希',
      delivery: 'turn-submit-hitchhike',
      batchCount: 4,
    });
    expect(callbacks[0].resultBody).toContain('构建产物已刷新');
    expect(callbacks[0].resultBody).toContain('/tmp/report-1.md');
    expect(callbacks[1]).toMatchObject({
      kind: 'employee',
      jobId: 'disp-compact-2',
      employeeId: 'frago-developer',
      targetSessionId: 'emp_s2',
      status: 'failed',
      exitCode: 2,
      delivery: 'turn-submit-hitchhike',
      batchCount: 4,
    });
    expect(callbacks[1].batchNotice).toContain('其余 2 条回执已省略详情');
  });

  it('解析极窄预算纯索引行降级批信封（无内部 <frago-async-callback>）', () => {
    const narrowBatch = `<frago-async-callbacks count="2" delivery="turn-submit-hitchhike" priority="background-after-human">
- job_id=disp-n1 status=completed report=/tmp/r1.md
- job_id=disp-n2 status=failed report=-
</frago-async-callbacks>`;

    const { text, callbacks } = splitAsyncCallbackBlocks(narrowBatch);
    expect(text).toBe('');
    expect(callbacks).toHaveLength(2);
    expect(callbacks[0]).toMatchObject({
      jobId: 'disp-n1',
      status: 'completed',
      delivery: 'turn-submit-hitchhike',
      batchCount: 2,
    });
    expect(callbacks[0].resultBody).toContain('/tmp/r1.md');
    expect(callbacks[1]).toMatchObject({
      jobId: 'disp-n2',
      status: 'failed',
    });
  });

  it('批信封与人类正文混合出现时拆出回调并完整保留人类正文', () => {
    const mixed = `<frago-async-callbacks count="1" delivery="turn-submit-hitchhike" priority="background-after-human">

【优先主线声明】主人的本轮当前请求是唯一最高优先级主线；请先直接、完整回应主人本轮请求。

${WORKER_CALLBACK_SAMPLE}

</frago-async-callbacks>

帮我看一下这个报错是什么原因`;

    const { text, callbacks } = splitAsyncCallbackBlocks(mixed);
    expect(callbacks).toHaveLength(1);
    expect(callbacks[0].jobId).toBe('disp-beaa67f7b8ea');
    expect(text).toBe('帮我看一下这个报错是什么原因');

    const mixedRecord: WorkbenchRecord = {
      id: 'rb-mixed',
      session_id: 's1',
      group_id: null,
      seq: 3,
      ts: 3000,
      kind: 'user.say',
      agent_path: [],
      payload: { text: mixed },
      raw_available: true,
    };
    expect(isPureAsyncCallbackRecord(mixedRecord)).toBe(false);
    expect(humanReplyText(mixedRecord)).toBe('帮我看一下这个报错是什么原因');
  });

  it('回调正文内含反引号或围栏代码块引用 </frago-async-callback> / </frago-async-callbacks> 时不提前截断且不外泄尾标签', () => {
    const bodyWithLiteralTags = `<frago-async-callbacks count="1" delivery="idle-batch" priority="background-after-human">

【后台异步派发回执汇总】以下 1 项后台异步任务已完成且当前会话处于空闲安全窗口。

<frago-async-callback kind="worker" mode="new" job_id="disp-tags-1" worker_session_id="core_tags" status="completed">
【下属 Worker 异步回传】来自 Worker 会话 \`core_tags\`（模式：新建执行，内核：\`coreagent\`）
- 派发单号：\`disp-tags-1\`
- 任务摘要：修复 \`</frago-async-callback>\` 裸露
- 执行状态：\`completed\` (exit_code=0)

### Worker 交付结果
已修复消息尾部裸露以下标签的问题：
\`\`\`xml
</frago-async-callback>
</frago-async-callbacks>
\`\`\`
验证完成。

---
请作为管理者（Employee）结合领域知识与执行准则审核上述 Worker 产出：
1. 若结论已向人类汇报且内容一致，仅需一句话确认收口。
</frago-async-callback>

</frago-async-callbacks>`;

    const { text, callbacks } = splitAsyncCallbackBlocks(bodyWithLiteralTags);
    expect(text).toBe('');
    expect(callbacks).toHaveLength(1);
    expect(callbacks[0].jobId).toBe('disp-tags-1');
    expect(callbacks[0].resultBody).toContain('验证完成。');
  });

  it('畸形或未闭合批信封与孤立尾标签优雅降级，不崩且不外泄闭合标签', () => {
    // 1. 外层批信封未闭合，但内部子项闭合且后跟人类正文
    const unclosedOuterWithHuman = `<frago-async-callbacks count="1" delivery="idle-batch">

【后台异步派发回执汇总】以下 1 项后台异步任务已完成。

${WORKER_CALLBACK_SAMPLE}

继续下一步部署`;
    const res1 = splitAsyncCallbackBlocks(unclosedOuterWithHuman);
    expect(res1.callbacks).toHaveLength(1);
    expect(res1.callbacks[0].jobId).toBe('disp-beaa67f7b8ea');
    expect(res1.text).toBe('继续下一步部署');

    // 2. 外层与内层均未闭合
    const unclosedBoth = `<frago-async-callbacks count="1" delivery="idle-batch">
<frago-async-callback kind="worker" mode="new" job_id="disp-trunc" worker_session_id="core_trunc" status="completed">
### Worker 交付结果
输出被截断但仍应优雅展示`;
    const res2 = splitAsyncCallbackBlocks(unclosedBoth);
    expect(res2.callbacks).toHaveLength(1);
    expect(res2.callbacks[0].jobId).toBe('disp-trunc');
    expect(res2.callbacks[0].resultBody).toContain('输出被截断但仍应优雅展示');
    expect(res2.text).toBe('');

    // 3. 尾部残留孤立闭合标签
    const strayTrailing = `${WORKER_CALLBACK_SAMPLE}\n</frago-async-callback>\n</frago-async-callbacks>\n人类补充提问`;
    const res3 = splitAsyncCallbackBlocks(strayTrailing);
    expect(res3.callbacks).toHaveLength(1);
    expect(res3.text).toBe('人类补充提问');
    expect(res3.text).not.toContain('</frago-async-callback');
  });

  it('正文中间引用的 <frago-async-callbacks> 不误判为注入批信封', () => {
    const quoted = '请排查为什么 <frago-async-callbacks count="2"> 没有被前端拆开';
    const { text, callbacks } = splitAsyncCallbackBlocks(quoted);
    expect(callbacks).toHaveLength(0);
    expect(text).toBe(quoted);
  });
});
