/**
 * 会话文件那几处的路径处理：显示层的缩写、切分，以及按扩展名认语言。
 *
 * 这几条都只是「摆给人看」的那一层，认错的后果是把文件归错组或染错色，不是读错数据——
 * 所以这里钉的是容易破的那几下：末尾斜杠、没有斜杠的相对路径、名字带点但不是扩展名的。
 */

import { describe, expect, it } from 'vitest';
import { baseOf, dirOf, isEditableTextFile, langOf, withTilde } from '../filePaths';

describe('家目录缩成 ~', () => {
  it('macOS 与 Linux 两种家目录写法都缩，别处原样', () => {
    expect(withTilde('/Users/frago/Repos/frago')).toBe('~/Repos/frago');
    expect(withTilde('/home/someone/.frago')).toBe('~/.frago');
    expect(withTilde('/var/log')).toBe('/var/log');
    expect(withTilde('~')).toBe('~');
  });

  it('只缩开头那一段：路径中间的 Users 不算', () => {
    expect(withTilde('/opt/Users/frago')).toBe('/opt/Users/frago');
  });
});

describe('切出文件名与目录', () => {
  it('普通绝对路径', () => {
    expect(baseOf('/w/src/a.py')).toBe('a.py');
    expect(dirOf('/w/src/a.py')).toBe('/w/src');
  });

  it('末尾带斜杠照样切得出', () => {
    expect(baseOf('/w/src/')).toBe('src');
    expect(dirOf('/w/src/')).toBe('/w');
  });

  it('没有斜杠那一层：名字就是它自己，目录是空的（界面上归到「不分目录」那组）', () => {
    expect(baseOf('a.py')).toBe('a.py');
    expect(dirOf('a.py')).toBe('');
  });

  it('根目录底下那一份的目录是根', () => {
    expect(dirOf('/a')).toBe('/');
  });
});

describe('按扩展名认语言', () => {
  it('常见的认得出来', () => {
    expect(langOf('/w/a.py')).toBe('python');
    expect(langOf('/w/a.tsx')).toBe('typescript');
    expect(langOf('/w/a.yaml')).toBe('yaml');
    expect(langOf('/w/a.md')).toBe('markdown');
    // 大写扩展名照样认。
    expect(langOf('/w/A.PY')).toBe('python');
  });

  it('认不出就是空串，不猜近似的', () => {
    // 认错语言染出来的颜色让人读错结构，比不染色更坏。
    expect(langOf('/w/a.zzz')).toBe('');
    expect(langOf('/w/Dockerfile2')).toBe('');
    expect(langOf('/w/.gitignore')).toBe('');
    expect(langOf('/w/noext')).toBe('');
  });

  it('几个没有扩展名的固定名字按名字认', () => {
    expect(langOf('/w/Dockerfile')).toBe('dockerfile');
    expect(langOf('/w/Makefile')).toBe('makefile');
  });
});

describe('判断文件是否支持直接进入 Edit 模式', () => {
  it('当且仅当 md、txt 或类似文稿/纯文本类型文件返回 true，代码与 HTML/二进制文件返回 false', () => {
    expect(isEditableTextFile('/w/poster.md')).toBe(true);
    expect(isEditableTextFile('/w/README.MARKDOWN')).toBe(true);
    expect(isEditableTextFile('/w/notes.txt')).toBe(true);
    expect(isEditableTextFile('/w/config.yaml')).toBe(true);
    expect(isEditableTextFile('/w/data.json')).toBe(true);

    expect(isEditableTextFile('/w/src/a.py')).toBe(false);
    expect(isEditableTextFile('/w/src/b.tsx')).toBe(false);
    expect(isEditableTextFile('/w/proto/index.html')).toBe(false);
    expect(isEditableTextFile('/w/logo.png')).toBe(false);
    expect(isEditableTextFile('/w/Makefile')).toBe(false);
  });
});

