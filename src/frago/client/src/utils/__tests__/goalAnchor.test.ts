import { describe, expect, it } from 'vitest';
import { cleanGoalText, extractGoalSummary, isLongLedgerText } from '../goalAnchor';

describe('goalAnchor utils', () => {
  it('剥离 <image>、<frago-employee>、<must-use-skill> 与附带图片/文档脚手架', () => {
    const raw = [
      '<image name=[Image #1] path="/Users/frago/.frago/webui_uploads/s1/a.png"></image>',
      '<frago-employee id="frago-developer" title="frago Developer" kernel="claude">',
      '岗位：frago Developer',
      '</frago-employee>',
      '<must-use-skill name="git-push" path="/Users/frago/.frago/skills/git-push/SKILL.md">',
      'skill 正文',
      '</must-use-skill>',
      '',
      'detail 的 PROGRESS LEDGER 高度太离谱，需要优化。',
      '',
      '[附带图片，请用读文件的工具逐一打开查看]:',
      '/Users/frago/.frago/webui_uploads/s1/a.png',
      '',
      '[附带文档，请用读文件的工具逐一打开阅读]:',
      '/Users/frago/.frago/webui_uploads/s1/spec.md',
    ].join('\n');

    const cleaned = cleanGoalText(raw);
    expect(cleaned).toBe('detail 的 PROGRESS LEDGER 高度太离谱，需要优化。');
  });

  it('纯卡片回执或空内容返回 null', () => {
    expect(cleanGoalText('【answer】A')).toBeNull();
    expect(cleanGoalText('   ')).toBeNull();
    expect(cleanGoalText(null)).toBeNull();
  });

  it('短文本直接原样返回且不触发折叠阈值', () => {
    const short = '梳理信息结构并更新表格布局';
    expect(extractGoalSummary(short)).toBe(short);
    expect(isLongLedgerText(short)).toBe(false);
  });

  it('长篇 Worker 任务书提炼核心标题与目标且跳过角色开场白', () => {
    const longBrief = [
      '你是 frago recipe 开发专家。',
      '',
      "任务：根据 spec 创建 recipe 'focus_compass'。",
      '',
      '先运行以下命令获取规范：',
      '  frago book recipe-creation',
      '',
      '# 任务书：构建 focus_compass 专注指南工作流',
      '',
      '## 1. 背景与目标',
      '',
      '提供一个单页可回放的专注罗盘控制台，支持任务计时、复盘归档与双主题适配。',
      '',
      '## 2. 约束',
      '- 必须通过 recipe validate。',
    ].join('\n');

    const summary = extractGoalSummary(longBrief);
    expect(summary).toContain('任务书：构建 focus_compass 专注指南工作流');
    expect(summary).toContain("任务：根据 spec 创建 recipe 'focus_compass'");
    expect(summary).not.toContain('你是 frago recipe 开发专家');
    expect(isLongLedgerText(longBrief)).toBe(true);
  });

  it('剥离浏览器扩展回传的 Focus 与网页完整可见上下文尾巴', () => {
    const raw = [
      '<frago-employee id="dev" title="Developer" kernel="claude">',
      '岗位描述',
      '</frago-employee>',
      '',
      '帮我总结这个 JIRA 工单的根因和下一步处理动作。',
      '',
      '---',
      '### 🎯 Focus 焦点内容（共 1 处）',
      '',
      '#### [FOCUS #1] [APEXP-4629] PIN answer（划词焦点）',
      '- 来源：https://jira.xpaas.lenovo.com/browse/APEXP-4629',
      '',
      'PIN code verification failed on retry',
      '',
      '---',
      '### 📄 网页完整可见上下文（共 1 页，按页去重并已原地锚定 Focus）',
      '',
      '#### [页面 1] [APEXP-4629] PIN answer（约 12108 字）',
      '- URL：https://jira.xpaas.lenovo.com/browse/APEXP-4629',
      '',
      '正文内容',
    ].join('\n');

    expect(cleanGoalText(raw)).toBe('帮我总结这个 JIRA 工单的根因和下一步处理动作。');
  });
});
