import { describe, expect, it } from 'vitest';
import { splitSkillBlocks, truncateChars } from '../skillBlocks';

/** 与服务端 `frago.skills.skill_prompt.skill_block` 拼出来的形状一致。 */
function block(name: string, body = '# 正文\n第二行') {
  return `<must-use-skill name="${name}" path="/Users/x/.frago/skills/${name}/SKILL.md">\n说明\nskill 文档：/p\n---\n${body}\n</must-use-skill>`;
}

describe('splitSkillBlocks', () => {
  it('没有 skill 段时原样返回', () => {
    expect(splitSkillBlocks('你好')).toEqual({ text: '你好', skills: [] });
  });

  it('摘掉整段 skill，只留名字与人写的话', () => {
    const out = splitSkillBlocks(`${block('git-push')}\n\n帮我提交`);
    expect(out).toEqual({ text: '帮我提交', skills: ['git-push'] });
  });

  it('多个 skill 按出现的先后排，插件前缀原样保留', () => {
    const out = splitSkillBlocks(`${block('git-push')}\n\n${block('superpowers:brainstorming')}\n\nx`);
    expect(out.skills).toEqual(['git-push', 'superpowers:brainstorming']);
    expect(out.text).toBe('x');
  });

  it('只点名 skill、一个字没写时正文为空', () => {
    expect(splitSkillBlocks(block('git-push'))).toEqual({ text: '', skills: ['git-push'] });
  });

  it('正文里的尖括号不会被当成 skill 段的结尾', () => {
    const out = splitSkillBlocks(`${block('a', '用 <div> 包起来')}\n\n问题`);
    expect(out).toEqual({ text: '问题', skills: ['a'] });
  });

  it('人只是提到这个标签名、没有完整一段时不动', () => {
    expect(splitSkillBlocks('聊聊 <must-use-skill 这个写法').skills).toEqual([]);
  });
});

describe('truncateChars', () => {
  it('按字符截，中文不会截出半个字', () => {
    expect(truncateChars('智能分析 Git 工作区文件改动', 4)).toBe('智能分析…');
    expect(truncateChars('短', 4)).toBe('短');
  });

  it('换行与连续空白压成一个空格', () => {
    expect(truncateChars('a\n\n  b', 10)).toBe('a b');
  });
});
