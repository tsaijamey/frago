import { describe, expect, it } from 'vitest';
import {
  parseWebBridgeContext,
  splitFocusAnchorSegments,
  stripWebBridgeContext,
} from '../webBridgeContext';

describe('webBridgeContext parser', () => {
  it('解析仅含整页上下文的存量消息（e010429e 首条消息结构）', () => {
    const raw = [
      '请阅读以下当前网页的完整可见上下文并协助处理。',
      '',
      '---',
      '### 📄 网页完整可见上下文（共 1 页，按页去重并已原地锚定 Focus）',
      '',
      '#### [页面 1] [APEXP-4629] PIN answer not relevant - XPaaS JIRA（约 12108 字）',
      '- URL：https://jira.xpaas.lenovo.com/browse/APEXP-4629',
      '',
      '## PIN answer not relevant',
      '',
      '### Description',
      'Tested as Kailee.',
    ].join('\n');

    const parsed = parseWebBridgeContext(raw);
    expect(parsed.hasBridgeContext).toBe(true);
    expect(parsed.userPrompt).toBe('请阅读以下当前网页的完整可见上下文并协助处理。');
    expect(parsed.focusItems).toHaveLength(0);
    expect(parsed.pages).toHaveLength(1);
    expect(parsed.pages[0]).toMatchObject({
      pageIndex: 1,
      title: '[APEXP-4629] PIN answer not relevant - XPaaS JIRA',
      url: 'https://jira.xpaas.lenovo.com/browse/APEXP-4629',
      safeUrl: 'https://jira.xpaas.lenovo.com/browse/APEXP-4629',
      domain: 'jira.xpaas.lenovo.com',
      charCount: 12108,
      focusNumbers: [],
    });
    expect(parsed.pages[0].markdown).toContain('## PIN answer not relevant');
    expect(parsed.pages[0].markdown).not.toContain('- URL：https://jira.xpaas.lenovo.com');
  });

  it('同时解析多条 Focus、整页上下文与原地锚点高亮切片', () => {
    const raw = [
      '帮我对比这两段问题并给出修复方案。',
      '',
      '---',
      '### 🎯 Focus 焦点内容（共 2 处）',
      '',
      '#### [FOCUS #1] APEXP-4629 详情页（划词焦点）',
      '- 来源：https://jira.xpaas.lenovo.com/browse/APEXP-4629',
      '',
      'PIN searched order records instead of Contact records.',
      '',
      '#### [FOCUS #2] 错误日志面板（网页区块 · `#log-panel > pre`）',
      '- 来源：https://jira.xpaas.lenovo.com/browse/APEXP-4629',
      '',
      '```txt',
      'WARN intent=order_lookup',
      '```',
      '',
      '---',
      '### 📄 网页完整可见上下文（共 1 页，按页去重并已原地锚定 Focus）',
      '',
      '#### [页面 1] APEXP-4629（约 533 字）',
      '- URL：https://jira.xpaas.lenovo.com/browse/APEXP-4629',
      '- 本页关联 Focus：#1, #2',
      '',
      '正文开头。',
      '',
      '<<< 🎯 FOCUS #1 开始 >>>',
      'PIN searched order records instead of Contact records.',
      '<<< 🎯 FOCUS #1 结束 >>>',
      '',
      '中间说明。',
      '',
      '<<< 🎯 FOCUS #2 开始 >>>',
      'WARN intent=order_lookup',
      '<<< 🎯 FOCUS #2 结束 >>>',
      '',
      '正文结尾。',
    ].join('\n');

    const parsed = parseWebBridgeContext(raw);
    expect(parsed.hasBridgeContext).toBe(true);
    expect(parsed.userPrompt).toBe('帮我对比这两段问题并给出修复方案。');
    expect(parsed.focusItems).toHaveLength(2);
    expect(parsed.focusItems[0]).toMatchObject({
      index: 1,
      title: 'APEXP-4629 详情页',
      kindLabel: '划词焦点',
      selector: '',
      domain: 'jira.xpaas.lenovo.com',
      body: 'PIN searched order records instead of Contact records.',
    });
    expect(parsed.focusItems[1]).toMatchObject({
      index: 2,
      title: '错误日志面板',
      kindLabel: '网页区块',
      selector: '#log-panel > pre',
      domain: 'jira.xpaas.lenovo.com',
    });
    expect(parsed.pages).toHaveLength(1);
    expect(parsed.pages[0].focusNumbers).toEqual([1, 2]);
    expect(parsed.pages[0].charCount).toBe(533);

    const segments = splitFocusAnchorSegments(parsed.pages[0].markdown);
    expect(segments).toEqual([
      { type: 'markdown', content: '正文开头。' },
      {
        type: 'focus',
        focusNumber: 1,
        content: 'PIN searched order records instead of Contact records.',
      },
      { type: 'markdown', content: '中间说明。' },
      { type: 'focus', focusNumber: 2, content: 'WARN intent=order_lookup' },
      { type: 'markdown', content: '正文结尾。' },
    ]);
  });

  it('兼容变体标题「来自网页的参考内容」与「网页完整可见上下文」以及超长附件提示', () => {
    const raw = [
      '总结一下重点',
      '',
      '---',
      '### 来自网页的参考内容',
      '',
      '#### [FOCUS #1] 文档中心（划词焦点）',
      '- 来源：https://docs.example.com/guide',
      '',
      '核心段落内容。',
      '',
      '---',
      '### 网页完整可见上下文',
      '',
      '#### [页面 1] 文档中心（约 42000 字）',
      '- URL：https://docs.example.com/guide',
      '- 本页关联 Focus：#1',
      '- 超长页面保护：整页全文共 42000 字，已完整挂载为文档附件 `page-context-1-docs.md`（下方为 Focus 锚点窗口摘录）',
      '',
      '<<< 🎯 FOCUS #1 开始 >>>',
      '核心段落内容。',
      '<<< 🎯 FOCUS #1 结束 >>>',
    ].join('\n');

    const parsed = parseWebBridgeContext(raw);
    expect(parsed.hasBridgeContext).toBe(true);
    expect(parsed.userPrompt).toBe('总结一下重点');
    expect(parsed.focusItems).toHaveLength(1);
    expect(parsed.pages[0].offloadedAttachmentName).toBe('page-context-1-docs.md');
    expect(stripWebBridgeContext(raw)).toBe('总结一下重点');
  });

  it('普通消息里的 --- 分隔线不会被误判为网页上下文', () => {
    const normal = ['第一段说明', '', '---', '', '### 普通小节标题', '普通内容'].join('\n');
    const parsed = parseWebBridgeContext(normal);
    expect(parsed.hasBridgeContext).toBe(false);
    expect(parsed.userPrompt).toBe(normal);
    expect(stripWebBridgeContext(normal)).toBe(normal);
  });

  it('清理孤立的 Focus 锚点标记而不残留裸标记文本', () => {
    const broken = '前文\n<<< 🎯 FOCUS #1 开始 >>>\n片段内容';
    const segs = splitFocusAnchorSegments(broken);
    expect(segs).toEqual([{ type: 'markdown', content: '前文\n片段内容' }]);
  });

  it('剥离服务端折叠为单行并截断的会话标题尾巴（core_05cc72126ea84c939e9722d63387f1db）', () => {
    const collapsedTitle =
      '解读这个ticket里connie后来的comment内容。 --- ### 📄 网页完整可见上下文（共 1 页，按页去重并已原地锚定 Focus） #### [页面 1] [APEXP-4652';
    expect(stripWebBridgeContext(collapsedTitle)).toBe('解读这个ticket里connie后来的comment内容。');

    const truncatedMidHeading = '帮我看一下这个页面 --- ### 🎯 Focus';
    expect(stripWebBridgeContext(truncatedMidHeading)).toBe('帮我看一下这个页面');
  });
});
