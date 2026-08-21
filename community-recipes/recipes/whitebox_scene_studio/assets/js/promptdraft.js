/* 提示词里的标签手术：拼进去、原样撤掉、组内换掉另一个。
 *
 * 单独拿出来是因为这里动的是**人自己写的字**。撤一个标签时多吃掉一个字、
 * 或者把他写的一句话连带删了，是这种功能最容易出、也最伤人的错——
 * 他写了三行，点了下标签又取消，回头发现自己那三行少了半句。
 * 所以这一段必须能被断言钉住，不能靠肉眼看。
 */

const SEP = '，';

function escapeRegExp(s) {
  return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** 把某一段原样摘掉，连同它前后多出来的那个分隔符。整段匹配不上就原样返回。 */
export function stripSegment(text, seg) {
  if (!seg || !text || !text.includes(seg)) return text;
  const e = escapeRegExp(seg);
  return text
    .replace(new RegExp(`${SEP}\\s*${e}`, 'g'), '')
    .replace(new RegExp(`${e}\\s*${SEP}`, 'g'), '')
    .split(seg).join('')
    .replace(new RegExp(`${SEP}{2,}`, 'g'), SEP)
    .replace(new RegExp(`^${SEP}+|${SEP}+$`, 'g'), '')
    .trim();
}

/** 这一段在不在正文里。标签的高亮完全由它决定，不另存一份状态。 */
export function hasSegment(text, seg) {
  return Boolean(seg) && String(text || '').includes(seg);
}

/**
 * 点一个标签之后，正文该变成什么。
 * 已经在里面 → 撤掉；不在 → 先撤掉同组的另一个，再拼到末尾。
 * siblings 是同组的全部条目（含自己）。
 */
export function togglePresetText(text, item, siblings = []) {
  let out = String(text || '');
  if (hasSegment(out, item.text)) return stripSegment(out, item.text);

  for (const other of siblings) {
    if (other.text !== item.text) out = stripSegment(out, other.text);
  }
  out = out.trim();
  return out ? `${out}${SEP}${item.text}` : item.text;
}

/** 撤掉全部标签拼进来的内容，人自己写的一个字都不动。 */
export function clearPresetText(text, items = []) {
  let out = String(text || '');
  for (const it of items) out = stripSegment(out, it.text);
  return out;
}
