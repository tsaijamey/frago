import { describe, expect, it } from 'vitest';
import { IMAGE_BLOCK_MARKER, splitAttachedImages } from '../attachedImages';

const P1 = '/Users/x/.frago/webui_uploads/a65e53ac-5caf/eb62b1b3.png';
const P2 = '/Users/x/.frago/webui_uploads/a65e53ac-5caf/ff00.jpg';

describe('splitAttachedImages', () => {
  it('没有图片段时原样返回', () => {
    expect(splitAttachedImages('你好')).toEqual({ text: '你好', images: [] });
  });

  it('摘出图片段，正文只留人写的话', () => {
    const r = splitAttachedImages(`先看看权限问题\n\n${IMAGE_BLOCK_MARKER}\n${P1}\n${P2}`);
    expect(r.text).toBe('先看看权限问题');
    expect(r.images.map((i) => i.name)).toEqual(['eb62b1b3.png', 'ff00.jpg']);
    expect(r.images[0].url).toBe('/api/workbench/uploads/a65e53ac-5caf/eb62b1b3.png');
  });

  it('后面跟着的文档段留在正文里', () => {
    const docs = '[附带文档，请用读文件的工具逐一打开阅读]:\n/x/webui_uploads/s/1-a.md';
    const r = splitAttachedImages(`看图\n\n${IMAGE_BLOCK_MARKER}\n${P1}\n\n${docs}`);
    expect(r.text).toBe(`看图\n\n${docs}`);
    expect(r.images).toHaveLength(1);
  });

  it('不在上传目录底下的路径也摘出来，只是取不回', () => {
    const r = splitAttachedImages(`插一句\n\n${IMAGE_BLOCK_MARKER}\n/tmp/a.png`);
    expect(r.text).toBe('插一句');
    expect(r.images).toEqual([{ path: '/tmp/a.png', name: 'a.png', url: null }]);
  });
});
