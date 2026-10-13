/**
 * 圈中的那段文字「看着像不像一条路径」。
 *
 * 这一条只做形状判断，所以这一份用例盯的全是**判否**的那一侧：圈中的多半是人话，多认
 * 一条就多一颗按下去没反应的按钮。真正「有没有这份文件」由服务端答，不在这里验。
 *
 * 跨系统那几条（盘符、UNC、反斜杠）与 Unix 那几条一样必须过：规则不按系统分支，界面不
 * 需要知道自己在哪台机器上。
 */

import { describe, expect, it } from 'vitest';
import { pathCandidateOf } from '../pathLike';

describe('看着像路径的', () => {
  it('Unix 绝对路径', () => {
    expect(pathCandidateOf('/Users/frago/Repos/frago/README.md')).toEqual({
      path: '/Users/frago/Repos/frago/README.md',
      rooted: true,
    });
  });

  it('~ 起头', () => {
    expect(pathCandidateOf('~/.frago/data/lenovo/brief.html')?.rooted).toBe(true);
  });

  it('路径里带中文：标点才拦，汉字不拦', () => {
    expect(
      pathCandidateOf('~/.frago/data/lenovo/executive-brief-技术方案.html')?.path
    ).toBe('~/.frago/data/lenovo/executive-brief-技术方案.html');
  });

  it('Windows 盘符与 UNC，正反斜杠都认', () => {
    expect(pathCandidateOf('C:\\Users\\me\\notes.md')?.rooted).toBe(true);
    expect(pathCandidateOf('D:/work/report.pdf')?.rooted).toBe(true);
    expect(pathCandidateOf('\\\\server\\share\\a.txt')?.rooted).toBe(true);
  });

  it('相对写法：至少一层目录加一个带扩展名的文件名', () => {
    expect(pathCandidateOf('docs/user-guide.md')).toEqual({
      path: 'docs/user-guide.md',
      rooted: false,
    });
    expect(pathCandidateOf('./src/app.tsx')?.rooted).toBe(false);
  });

  it('明确以根开头时允许有空格——路径可以长这样', () => {
    expect(pathCandidateOf('/Users/frago/Downloads/Pinnacle AI Ecosystem.pdf')).not.toBeNull();
  });
});

describe('看着不像路径的，一律不给', () => {
  it('一句人话', () => {
    expect(pathCandidateOf('产出的报告已经放到那边的目录里了')).toBeNull();
  });

  it('圈选跨了行', () => {
    expect(pathCandidateOf('/Users/frago/a.md\n还有下一行')).toBeNull();
  });

  it('散文里的斜杠：光一个 a/b 不算', () => {
    expect(pathCandidateOf('甲/乙')).toBeNull();
    expect(pathCandidateOf('a/b')).toBeNull();
  });

  it('带中文标点', () => {
    expect(pathCandidateOf('这个在 ~/.frago/data 下，你看一下')).toBeNull();
    expect(pathCandidateOf('「/Users/frago/x.md」')).toBeNull();
  });

  it('相对写法又带空格：与散文无从区分', () => {
    expect(pathCandidateOf('docs/some notes.md')).toBeNull();
  });

  it('光一个 ~ 或 / 说的是目录', () => {
    expect(pathCandidateOf('~')).toBeNull();
    expect(pathCandidateOf('/')).toBeNull();
  });

  it('Windows 上根本不能进文件名的字符', () => {
    expect(pathCandidateOf('/Users/frago/a|b.md')).toBeNull();
  });
});

describe('剥掉不该算进路径的那些', () => {
  it('结尾的行号后缀', () => {
    expect(pathCandidateOf('src/app.tsx:42')?.path).toBe('src/app.tsx');
    expect(pathCandidateOf('src/app.tsx:42:7')?.path).toBe('src/app.tsx');
  });

  it('外面包的引号与反引号', () => {
    expect(pathCandidateOf('`~/.frago/config.json`')?.path).toBe('~/.frago/config.json');
    expect(pathCandidateOf('"/Users/frago/a.md"')?.path).toBe('/Users/frago/a.md');
  });
});
