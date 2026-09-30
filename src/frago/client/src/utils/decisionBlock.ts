/**
 * 「要人拍板」区块：agent 回复末尾那个 `answer-needed-by-human` 代码块的读、校验、拼答复。
 *
 * 规格正源在 `~/.frago/data/frago-webui/20260924-page-polish/decision-block-spec.md`（4 型版），
 * 页面这一侧的落法见 spec `20260924-webui-decision-cards`。三条纪律：
 *
 * 1. **只读、只画，不补不猜。** 字段缺了、写错地方了、类型不认识，一律判写坏、照原文
 *    显示并说明原因。NEVER 替 agent 补一个选项或猜它的意思。
 * 2. **只认回复最末尾的那一个。** 之前出现的同名代码块照普通代码块显示——它后面还有正文，
 *    说明 agent 没在那里停下来等人。
 * 3. **发出去的原文自带动作。** 答复里写所选项的 label 与 effect 原文，不是一个字母：
 *    agent 事后要证明「用户当轮明示了要这么做」，靠的就是这句话本身。
 *
 * 这里是纯函数，不碰 React。左栏 For you 的判据也从这里取（`trailingDecision`），NEVER 另写一份。
 *
 * YAML 按需加载：绝大多数回复没有区块，没必要让每个人首屏都背上解析器。页面遇到末尾
 * 真有区块的回复才调 `loadYaml()`，之后 `yamlNow()` 同步可取。
 */

import type * as JsYaml from 'js-yaml';

export type Yaml = typeof JsYaml;

/** 代码块的语言标记，也是 agent 写区块时用的名字。 */
export const BLOCK_NAME = 'answer-needed-by-human';

/** 人点卡片发出的那句话以它开头。agent 与随包规则都靠它认出「这是卡片答复」。 */
export const ANSWER_PREFIX = '【answer】';

export const BLOCK_TYPES = ['single-choice', 'multi-choice', 'text-answer', 'choice-and-text'] as const;
export type BlockType = (typeof BLOCK_TYPES)[number];

export interface DecisionOption {
  key: string;
  label: string;
  /** 点了会发生什么。必写。 */
  effect: string;
  /** 缺省视为可撤回；只有写明 `reversible: false` 才算收不回。 */
  reversible: boolean;
  recommended: boolean;
}

export interface DecisionBlock {
  type: BlockType;
  question: string;
  why: string | null;
  /** text-answer 恒为空数组。 */
  options: DecisionOption[];
  /** 只在 choice-and-text 上：选项改成勾选。 */
  multi: boolean;
  /** 只在 text-answer / choice-and-text 上：预先写好的草稿，去掉末尾那一个换行。 */
  draft: string | null;
  /** 只在 text-answer 上：可点的建议答案。 */
  suggestions: string[];
  /** 区块顶层写了 `from: teammate`。 */
  fromTeammate: boolean;
  /** 队友原话。只在 fromTeammate 时画。 */
  request: string | null;
  /** 会改本机什么。只在 fromTeammate 时画。 */
  changes: string | null;
}

/**
 * 写坏的原因。给的是**词表键**与参数，取字由界面做——原因要跟着界面语言走。
 * 键落在 `workbench.decision.broken.*`。
 */
export interface BrokenReason {
  code:
    | 'yaml'
    | 'notMapping'
    | 'type'
    | 'question'
    | 'optionsNotList'
    | 'needsOptions'
    | 'textAnswerNoOptions'
    | 'optionFields'
    | 'recommendedMany'
    | 'fromValue'
    | 'draftPlace'
    | 'suggestionsPlace'
    | 'multiPlace';
  params?: Record<string, string>;
}

export type ParseResult = { ok: true; block: DecisionBlock } | { ok: false; reason: BrokenReason };

export interface TrailingBlock {
  /** 区块之前的回复正文，照常按 Markdown 显示。 */
  body: string;
  /** 区块里的原文（不含围栏）。 */
  raw: string;
}

/**
 * 「标记写错地方」这一组检查开不开。
 *
 * 规格只写了「YAML 坏、type 不认识、该有 options 却没有」三条；这一组是原型自己加的，
 * 09-24 主人定了要。单独成组，以后要关只改这一处。
 */
export const CHECK_MISPLACED_MARKS = true;

// ── 加载 YAML ────────────────────────────────────────────────────────────
let yamlLib: Yaml | null = null;
let yamlLoading: Promise<Yaml> | null = null;

/** 已经加载好的 YAML 解析器；还没加载就是 null。 */
export function yamlNow(): Yaml | null {
  return yamlLib;
}

/** 加载 YAML 解析器。只加载一次，并发调用拿到的是同一个 Promise。 */
export function loadYaml(): Promise<Yaml> {
  if (yamlLib) return Promise.resolve(yamlLib);
  if (!yamlLoading) {
    yamlLoading = import('js-yaml').then((m) => {
      yamlLib = m as Yaml;
      return yamlLib;
    });
  }
  return yamlLoading;
}

// ── 切出末尾区块 ─────────────────────────────────────────────────────────
const OPEN = new RegExp('(^|\\n)```' + BLOCK_NAME + '[ \\t]*\\n', 'g');
const BARE_FENCE = /^```\s*$/;

/**
 * 回复末尾是区块就把它切出来；不是就返回 null。
 *
 * 只看最后一个开围栏：它之后只能是区块内容加一道闭围栏，再往后只许有空白。内容里若已经
 * 出现过一道单独的闭围栏，说明区块早就结束了、后面还跟着正文——那就不是末尾。
 */
export function splitTrailingBlock(text: string): TrailingBlock | null {
  if (!text || !text.includes(BLOCK_NAME)) return null;
  const src = text.replace(/\r\n/g, '\n');
  let start = -1;
  let contentStart = -1;
  OPEN.lastIndex = 0;
  for (let m = OPEN.exec(src); m; m = OPEN.exec(src)) {
    start = m.index + m[1].length;
    contentStart = m.index + m[0].length;
  }
  if (start < 0) return null;
  const rest = src.slice(contentStart).replace(/\s+$/, '');
  if (!rest.endsWith('```')) return null;
  const before = rest.slice(0, -3);
  if (before && !before.endsWith('\n')) return null;
  const raw = before.replace(/\n$/, '');
  if (raw.split('\n').some((line) => BARE_FENCE.test(line))) return null;
  return { body: src.slice(0, start).replace(/\s+$/, ''), raw };
}

// ── 解析与校验 ───────────────────────────────────────────────────────────
type Obj = Record<string, unknown>;

const isObj = (v: unknown): v is Obj => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown): string => (typeof v === 'string' ? v : String(v));
const broken = (code: BrokenReason['code'], params?: Record<string, string>): ParseResult => ({
  ok: false,
  reason: params ? { code, params } : { code },
});

/**
 * 解析区块原文并校验。以 JSON 规则集解析：默认规则集会把 `2026-09-24` 读成日期对象、
 * 把一些裸值改写类型，区块里的文字应当原样保留。
 */
export function parseDecisionBlock(raw: string, yaml: Yaml): ParseResult {
  let y: unknown;
  try {
    y = yaml.load(raw, { schema: yaml.JSON_SCHEMA });
  } catch (e) {
    const err = e as { reason?: string; mark?: { line: number } };
    const detail = `${err.reason || 'bad YAML'}${err.mark ? ` (line ${err.mark.line + 1})` : ''}`;
    return broken('yaml', { detail });
  }
  if (!isObj(y)) return broken('notMapping');
  if (!BLOCK_TYPES.includes(y.type as BlockType)) {
    return broken('type', { type: y.type == null ? '' : text(y.type), types: BLOCK_TYPES.join(', ') });
  }
  const type = y.type as BlockType;
  if (typeof y.question !== 'string' || !y.question.trim()) return broken('question');
  const opts = y.options == null ? [] : y.options;
  if (!Array.isArray(opts)) return broken('optionsNotList');
  if (type !== 'text-answer' && !opts.length) return broken('needsOptions', { type });
  if (type === 'text-answer' && opts.length) return broken('textAnswerNoOptions');
  if (opts.some((o) => !isObj(o) || o.key == null || o.label == null || o.effect == null)) {
    return broken('optionFields');
  }
  const options = (opts as Obj[]).map<DecisionOption>((o) => ({
    key: text(o.key),
    label: text(o.label),
    effect: text(o.effect),
    reversible: o.reversible !== false,
    recommended: o.recommended === true,
  }));
  if (options.filter((o) => o.recommended).length > 1) return broken('recommendedMany');

  if (CHECK_MISPLACED_MARKS) {
    if (y.from != null && y.from !== 'teammate') return broken('fromValue', { from: text(y.from) });
    if (y.draft != null && type !== 'text-answer' && type !== 'choice-and-text') {
      return broken('draftPlace');
    }
    if (y.suggestions != null && (type !== 'text-answer' || !Array.isArray(y.suggestions))) {
      return broken('suggestionsPlace');
    }
    if (y.multi != null && type !== 'choice-and-text') return broken('multiPlace');
  }

  const fromTeammate = y.from === 'teammate';
  return {
    ok: true,
    block: {
      type,
      question: y.question,
      why: y.why == null ? null : text(y.why),
      options,
      multi: type === 'choice-and-text' && y.multi === true,
      draft: y.draft == null ? null : text(y.draft).replace(/\n$/, ''),
      suggestions: Array.isArray(y.suggestions) ? y.suggestions.map(text) : [],
      fromTeammate,
      request: fromTeammate && y.request != null ? text(y.request) : null,
      changes: fromTeammate && y.changes != null ? text(y.changes) : null,
    },
  };
}

/**
 * 一条回复末尾的区块，切出并解析。没有末尾区块返回 null；YAML 还没加载好也返回 null
 * （调用方先 `loadYaml()`）。左栏 For you 用它判「这场留了一张卡片、问的是什么」。
 */
export function trailingDecision(
  replyText: string,
  yaml: Yaml | null = yamlNow()
): (TrailingBlock & { result: ParseResult }) | null {
  const split = splitTrailingBlock(replyText);
  if (!split || !yaml) return null;
  return { ...split, result: parseDecisionBlock(split.raw, yaml) };
}

// ── 答复 ─────────────────────────────────────────────────────────────────
/** 勾选（可选几项）还是单选。 */
export function isMany(block: DecisionBlock): boolean {
  return block.type === 'multi-choice' || block.multi;
}

/** 选项在答复里的那一行：`A · 发布 —— 打 v1.4.111 tag 并上传 PyPI，发出去收不回`。 */
export function optionLine(o: DecisionOption): string {
  return `${o.key} · ${o.label} —— ${o.effect}`;
}

const FENCE = '```';

/**
 * 拼出人点卡片后发出的那句话。
 *
 * 选项：单选一行，多选在 `【answer】` 下逐项 `- ` 列出。写的字隔一个空行接在后面，多行的
 * 包进代码块（09-24 主人定照原型）。text-answer 只有文字。
 */
export function composeAnswer(
  block: DecisionBlock,
  picked: DecisionOption[],
  written: string
): string {
  const head = !picked.length
    ? ''
    : isMany(block)
      ? '\n' + picked.map((o) => '- ' + optionLine(o)).join('\n')
      : optionLine(picked[0]);
  const t = written.trim();
  const body = !t ? '' : t.includes('\n') ? `${FENCE}\n${t}\n${FENCE}` : t;
  return ANSWER_PREFIX + head + (body ? (head ? '\n\n' : '') + body : '');
}

export function isCardAnswer(text: string): boolean {
  return text.startsWith(ANSWER_PREFIX);
}

/**
 * 从一条卡片答复里认回选中了哪几项（下标）。按「A · label —— effect」整行比对，认不出
 * 就当没选——宁可不高亮，也不高亮错。
 */
export function pickedFromAnswer(answer: string, block: DecisionBlock): number[] {
  if (!isCardAnswer(answer)) return [];
  const lines = '\n' + answer.slice(ANSWER_PREFIX.length).replace(/^- /gm, '') + '\n';
  const out: number[] = [];
  block.options.forEach((o, i) => {
    if (lines.includes('\n' + optionLine(o) + '\n')) out.push(i);
  });
  return out;
}

export interface ParsedCardAnswer {
  /** 选中的项，按答复里的次序。只写了字时为空。 */
  picked: Pick<DecisionOption, 'key' | 'label' | 'effect'>[];
  /** 人写的那段字，围栏去掉。没写就是空串。 */
  written: string;
}

const OPTION_LINE_RE = /^(\S{1,8}) · (.+?) —— (.+)$/;

function parseOptionLine(line: string): ParsedCardAnswer['picked'][number] | null {
  const m = OPTION_LINE_RE.exec(line);
  return m ? { key: m[1], label: m[2], effect: m[3] } : null;
}

/**
 * 不看卡片、只凭答复原文把它拆回「选了哪几项 + 写了什么」，给「You said」气泡排版用。
 *
 * 记录流里那句答复跟它回的卡片不在同一张记录上，气泡拿不到区块，只能照 `composeAnswer`
 * 的拼法反着读：开头换行的是多选清单，否则头一行形如「A · label —— effect」就是单选，
 * 都不是就整段算人写的字。认不出的形状返回 null，气泡照原文显示——宁可朴素，不可读错。
 *
 * 只改显示，发出去的原文一字不动：agent 与随包规则认的正是那句带 effect 的原话。
 */
export function parseCardAnswer(answer: string): ParsedCardAnswer | null {
  if (!isCardAnswer(answer)) return null;
  const rest = answer.slice(ANSWER_PREFIX.length);
  const gap = rest.indexOf('\n\n', rest.startsWith('\n') ? 1 : 0);
  const head = gap < 0 ? rest : rest.slice(0, gap);
  const tail = gap < 0 ? '' : rest.slice(gap + 2);

  let picked: ParsedCardAnswer['picked'] = [];
  let body = rest;
  if (head.startsWith('\n')) {
    const parsed = head
      .slice(1)
      .split('\n')
      .map((l) => (l.startsWith('- ') ? parseOptionLine(l.slice(2)) : null));
    if (!parsed.length || parsed.some((p) => !p)) return null;
    picked = parsed as ParsedCardAnswer['picked'];
    body = tail;
  } else {
    const one = head.includes('\n') ? null : parseOptionLine(head);
    if (one) {
      picked = [one];
      body = tail;
    }
  }
  const m = body.match(/^```\n([\s\S]*)\n```$/);
  const written = (m ? m[1] : body).trim();
  if (!picked.length && !written) return null;
  return { picked, written };
}

/** 从一条卡片答复里取回人写的那段字（代码块围栏去掉）。没写就是空串。 */
export function writtenFromAnswer(answer: string, block: DecisionBlock): string {
  if (!isCardAnswer(answer)) return '';
  const rest = answer.slice(ANSWER_PREFIX.length);
  let body = rest;
  if (pickedFromAnswer(answer, block).length) {
    const gap = rest.indexOf('\n\n');
    body = gap < 0 ? '' : rest.slice(gap + 2);
  }
  const m = body.match(/^```\n([\s\S]*)\n```$/);
  return (m ? m[1] : body).trim();
}
