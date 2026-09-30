/**
 * 从人说的那句话里认出点名的 skill。
 *
 * 人在输入框里敲 `/` 挑中一个 skill，服务端把它的文档路径与全文嵌到这句话前面，包成
 * `<must-use-skill name="…" path="…">…</must-use-skill>` 一段（见服务端
 * `frago.skills.skill_prompt`）。agent 要读那段全文，人不用：记录流里只把名字画成引用，
 * 正文一个字都不摆。
 *
 * 标签写法 MUST 与服务端逐字一致——那边改一个字，这里就认不出来，整篇 skill 会原样摊在
 * 记录流里。
 */

const SKILL_BLOCK_RE = /<must-use-skill\s+name="([^"]*)"[^>]*>[\s\S]*?<\/must-use-skill>\s*/g;

function unescapeAttr(value: string): string {
  return value.replace(/&quot;/g, '"').replace(/&amp;/g, '&');
}

/** 把正文拆成「人写的话」与「点名的 skill 名」。没有那几段时原样返回、名字为空。 */
export function splitSkillBlocks(text: string): { text: string; skills: string[] } {
  if (!text.includes('<must-use-skill')) return { text, skills: [] };
  const skills: string[] = [];
  const rest = text.replace(SKILL_BLOCK_RE, (_m, name: string) => {
    skills.push(unescapeAttr(name));
    return '';
  });
  if (!skills.length) return { text, skills: [] };
  return { text: rest.trim(), skills };
}

/** 截到 `n` 个字，超出的补省略号。按字符数算，不按字节，中文不会截出半个字。 */
export function truncateChars(text: string, n: number): string {
  const chars = Array.from(text.replace(/\s+/g, ' ').trim());
  return chars.length > n ? `${chars.slice(0, n).join('')}…` : chars.join('');
}
