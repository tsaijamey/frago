import { describe, expect, it } from 'vitest';
import {
  dedupeImageGrids,
  normalizeImageSrc,
  parseAllImageGridOutputs,
  parseImageGridOutput,
  stripImageGridBlocks,
} from '../imageGridBlock';

describe('imageGridBlock', () => {
  it('将本机绝对路径标准化为 /api/file?disposition=inline 地址，保留 http(s):// 地址', () => {
    expect(normalizeImageSrc('/Users/frago/a b.png')).toContain(
      '/api/file?disposition=inline&path=%2FUsers%2Ffrago%2Fa%20b.png'
    );
    expect(normalizeImageSrc('https://example.com/demo.png')).toBe(
      'https://example.com/demo.png'
    );
  });

  it('从工具输出文本解析 image-grid 组件数据', () => {
    const raw = `Command exited with code 0.\n\n${JSON.stringify(
      {
        frago_ui_component: 'image-grid',
        component_type: 'image-grid',
        data: {
          type: 'image-grid',
          title: '海报方案对比',
          columns: 2,
          images: [
            {
              src: '/api/file?disposition=inline&path=%2FUsers%2Ffrago%2F1.png',
              raw: '/Users/frago/1.png',
              name: '1.png',
              caption: '图 1：方案 A',
              source: 'local',
            },
            {
              src: 'https://example.com/2.png',
              raw: 'https://example.com/2.png',
              name: '2.png',
              caption: '图 2：方案 B',
              source: 'remote',
            },
          ],
        },
      },
      null,
      2
    )}`;

    const parsed = parseImageGridOutput(raw);
    expect(parsed).not.toBeNull();
    expect(parsed?.title).toBe('海报方案对比');
    expect(parsed?.columns).toBe(2);
    expect(parsed?.images).toHaveLength(2);
    expect(parsed?.images[0].source).toBe('local');
    expect(parsed?.images[1].source).toBe('remote');
  });

  it('不误把 decision-card 识别为 image-grid，且支持提取同一段输出中的多个 image-grid', () => {
    const decisionRaw = JSON.stringify({
      frago_ui_component: 'decision-card',
      component_type: 'single-choice',
      data: {
        type: 'single-choice',
        question: '选哪个？',
        options: [{ key: 'A', label: 'A', effect: '选 A' }],
      },
    });
    expect(parseImageGridOutput(decisionRaw)).toBeNull();

    const g1 = JSON.stringify({
      frago_ui_component: 'image-grid',
      component_type: 'image-grid',
      data: {
        type: 'image-grid',
        title: '第一组',
        images: [{ src: 'https://example.com/a.png', raw: 'https://example.com/a.png', name: 'a.png' }],
      },
    });
    const g2 = JSON.stringify({
      frago_ui_component: 'image-grid',
      component_type: 'image-grid',
      data: {
        type: 'image-grid',
        title: '第二组',
        images: [{ src: 'https://example.com/b.png', raw: 'https://example.com/b.png', name: 'b.png' }],
      },
    });
    const all = parseAllImageGridOutputs(`${g1}\n${decisionRaw}\n${g2}`);
    expect(all).toHaveLength(2);
    expect(all.map((x) => x.title)).toEqual(['第一组', '第二组']);
  });

  it('对相同图片集合的网格去重，并剥离正文中手抄的 frago-app 代码块', () => {
    const payload = JSON.stringify({
      frago_ui_component: 'image-grid',
      component_type: 'image-grid',
      data: {
        type: 'image-grid',
        title: 'Timeline 对比',
        columns: 2,
        images: [
          { src: '/api/file?disposition=inline&path=%2Ftmp%2F1.png', raw: '/tmp/1.png', name: '1.png' },
          { src: '/api/file?disposition=inline&path=%2Ftmp%2F2.png', raw: '/tmp/2.png', name: '2.png' },
        ],
      },
    });
    const parsed = parseAllImageGridOutputs(`${payload}\n${payload}`);
    expect(parsed).toHaveLength(2);
    const deduped = dedupeImageGrids(parsed);
    expect(deduped).toHaveLength(1);

    const prose = `已修复遮挡问题。\n\n\`\`\`frago-app\n${payload}\n\`\`\``;
    expect(stripImageGridBlocks(prose)).toBe('已修复遮挡问题。');
  });
});
