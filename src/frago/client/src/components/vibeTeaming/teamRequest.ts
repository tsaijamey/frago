/**
 * Teams 页上几样「从已有数据推出来」的判读，全部是纯函数。
 *
 * - 遮连接码：页面上能看到的完整码一律只露前 4 位。码是队友进门的凭证，左栏的内容
 *   每 15 秒同步给队友、截图录屏也会带出去；要把码发给人，走页头的 Copy。
 * - 认出队友请求：两侧记录里，队友请求都是一条用户发言，正文 = 收件侧的投递前缀 +
 *   原文 + 核实行。前缀是收件侧自己改得到的，界面不知道对方改成了什么，所以**只认
 *   核实行**（它的字面固定，见 `frago/team/state.py` 的 `VERIFY_LINE`，hook 规则也认它）。
 * - 发请求前的预判：按请求里的词点亮三档之一。这只是提示——最终怎么处理由对方的
 *   agent 按对方主人的设置判，所以句式一律说依据（「Mentions “push”」），不说结论。
 * - 「Your request」卡走到哪一步：只从两侧已有的记录推，看不出来的就停在上一步，
 *   NEVER 预告还没发生的步骤。
 *
 * 独立成文件而不塞进页面：页面本身已经很长，这几样又要单测，放在不碰 React 的地方
 * 才好直接喂字符串。
 */

import type { WorkbenchRecord } from '@/hooks/useWorkbenchRecords';

// ── 连接码 ───────────────────────────────────────────────────────────────

/** 页面上露出来的样子：前 4 位 + 6 个圆点。 */
export function maskCode(code: string): string {
  return `${code.slice(0, 4)}••••••`;
}

/** 把一段文字里出现的完整连接码换成遮过的样子。只遮完整码，前几位不动。 */
export function maskCodesIn(text: string, codes: readonly string[]): string {
  let out = text;
  for (const code of codes) {
    if (code && out.includes(code)) out = out.split(code).join(maskCode(code));
  }
  return out;
}

function maskValue(value: unknown, codes: readonly string[]): unknown {
  if (typeof value === 'string') return maskCodesIn(value, codes);
  if (Array.isArray(value)) {
    let changed = false;
    const next = value.map((one) => {
      const masked = maskValue(one, codes);
      if (masked !== one) changed = true;
      return masked;
    });
    return changed ? next : value;
  }
  if (value && typeof value === 'object') {
    let changed = false;
    const next: Record<string, unknown> = {};
    for (const [key, one] of Object.entries(value as Record<string, unknown>)) {
      const masked = maskValue(one, codes);
      if (masked !== one) changed = true;
      next[key] = masked;
    }
    return changed ? next : value;
  }
  return value;
}

/**
 * 记录正文里出现的完整连接码按页头的遮法遮掉。
 *
 * 没出现码的记录原样返回同一个对象——卡片是记忆化的，换成新对象会让整条流跟着重画。
 */
export function maskCodes(records: WorkbenchRecord[], codes: readonly string[]): WorkbenchRecord[] {
  const live = codes.filter(Boolean);
  if (!live.length) return records;
  return records.map((record) => {
    const payload = maskValue(record.payload, live) as Record<string, unknown>;
    return payload === record.payload ? record : { ...record, payload };
  });
}

// ── 认出队友请求 ─────────────────────────────────────────────────────────

/** 核实行。与 `frago/team/state.py` 的 `VERIFY_LINE` 同一个字面。 */
const VERIFY_RE = /（核实来源：frago team verify --team-code (\S+) --message (\S+)）\s*$/;

/**
 * 收件侧插在原文与核实行之间的那一行「本机主人的设置」。
 * 与 `frago/team/state.py` 的 `RULES_LINE` 同一个开头。旧版 frago 投进来的没有这一行。
 */
const RULES_LINE_RE = /\n*（本机主人的设置：[^\n]*）\s*$/;

/** 一条记录被认成队友请求之后拆出来的样子。 */
export interface RelayedRequest {
  /** 核实行里的连接码。显示前要遮。 */
  code: string;
  /** 核实行里的消息编号。 */
  messageId: string;
  /** 去掉前缀、设置行与核实行之后的原文。 */
  body: string;
}

/**
 * 一段用户发言是不是经中继投来的队友请求；是就拆出原文。
 *
 * 拆前缀的办法：投递时前缀、原文、核实行之间固定用一个空行隔开，取第一个空行之后、
 * 核实行之前的部分。没有核实行的一律不认——有人照着前缀手打一条，照普通发言显示。
 */
export function parseRelayedText(text: string): RelayedRequest | null {
  const hit = VERIFY_RE.exec(text);
  if (!hit) return null;
  const before = text.slice(0, hit.index);
  const gap = before.indexOf('\n\n');
  const middle = gap >= 0 ? before.slice(gap + 2) : before;
  return {
    code: hit[1],
    messageId: hit[2],
    body: middle.replace(RULES_LINE_RE, '').trim(),
  };
}

/** 这条记录是不是队友请求。只看主会话里的用户发言。 */
export function parseRelayed(record: WorkbenchRecord): RelayedRequest | null {
  if (record.kind !== 'user.say' || record.agent_path.length) return null;
  const text = record.payload.text;
  return typeof text === 'string' ? parseRelayedText(text) : null;
}

// ── 三档与各自主人的设置 ─────────────────────────────────────────────────

/** 一句请求落在哪一档。`idle` 是还没写字。 */
export type Tier = 'idle' | 'read' | 'change' | 'never';

/** 那一侧主人给自己的 agent 定的「队友请求怎么处理」。第三档恒为拒绝，不可设。 */
export interface RequestRules {
  read: 'do' | 'ask';
  change: 'ask' | 'refuse';
}

/** 与现行结对手册的三档一致：只读的直接做，会改动的先问主人。 */
export const FRAGO_DEFAULT_RULES: RequestRules = { read: 'do', change: 'ask' };

export type Verdict = 'do' | 'ask' | 'refuse';

/** 落在这一档、那一侧主人这样设，对方 agent 会怎么处理。 */
export function verdictOf(tier: Exclude<Tier, 'idle'>, rules: RequestRules): Verdict {
  if (tier === 'read') return rules.read;
  if (tier === 'change') return rules.change;
  return 'refuse';
}

/**
 * 词表照原型原样搬。英文词两侧要求词边界，中文词不要求。
 * 先判第三档、再判改动，其余算只读。
 */
const TIER_NEVER =
  /\b(secrets?|tokens?|passwords?|passwd|api[ -]?keys?|private keys?|credentials?|cookies?|rm -rf|wipe|erase|bypass|ignore (?:the |your |previous )?rules)\b|\.env\b|密钥|口令|密码|令牌|私钥|清空|绕过/gi;
const TIER_CHANGE =
  /\b(push|publish|deploy|release|merge|commit|install|uninstall|upgrade|update|edit|change|modify|rewrite|fix|write|delete|remove|rename|restart|reboot|kill|email|hostname|ip address)\b|推送|发布|部署|合并|提交|安装|卸载|升级|更新|删除|改|重启/gi;

export interface TierGuess {
  tier: Tier;
  /** 命中的前两个词，写进预判那句话里，让人看得到依据。 */
  words: string[];
}

export function classifyTier(text: string): TierGuess {
  const t = text.trim();
  if (!t) return { tier: 'idle', words: [] };
  const firstTwo = (found: RegExpMatchArray | null) =>
    [...new Set((found ?? []).map((w) => w.toLowerCase()))].slice(0, 2);
  const never = firstTwo(t.match(TIER_NEVER));
  if (never.length) return { tier: 'never', words: never };
  const change = firstTwo(t.match(TIER_CHANGE));
  if (change.length) return { tier: 'change', words: change };
  return { tier: 'read', words: [] };
}

/** 预判那句话属于哪一种说法。文字在界面词表里，这里只挑键。 */
export type PredictionKey = 'idle' | 'readDo' | 'readAsk' | 'changeAsk' | 'changeRefuse' | 'never';

export function predictionKey(guess: TierGuess, rules: RequestRules): PredictionKey {
  if (guess.tier === 'idle') return 'idle';
  if (guess.tier === 'never') return 'never';
  if (guess.tier === 'read') return rules.read === 'do' ? 'readDo' : 'readAsk';
  return rules.change === 'refuse' ? 'changeRefuse' : 'changeAsk';
}

// ── 「Your request」卡 ───────────────────────────────────────────────────

/**
 * 回复末尾是不是一张「来自队友」的决定卡。
 *
 * 区块的完整解析与校验归 `20260924-webui-decision-cards`（`utils/decisionBlock.ts`）。
 * 这里只需要回答一个是或否：回复**最末尾**是不是 `answer-needed-by-human` 代码块、块里
 * 顶层有没有 `from: teammate`。那份解析落地后换成它的判据，两处 NEVER 各判各的。
 */
export function endsWithTeammateCard(text: string): boolean {
  const fence = /```answer-needed-by-human[^\n]*\n([\s\S]*?)\n```\s*$/.exec(text);
  if (!fence) return false;
  return /^from:\s*['"]?teammate['"]?\s*$/m.test(fence[1]);
}

/** 我从右下框发出、还在等对方记录带回来的一条请求。只活在这一页的内存里。 */
export interface SentRequest {
  /** 本页本次的编号，只用作 React 的 key。 */
  key: string;
  text: string;
  sentAt: number;
  /** 中继回的消息编号。有它就按编号比对送达，原文相同的两次请求不会认混。 */
  messageId?: string;
}

export type RequestStep = 'sent' | 'delivered' | 'on_it' | 'waiting_owner' | 'replied';

export interface RequestProgress {
  /** 已经发生的步骤与眼下这一步，按先后排。最后一项是眼下。 */
  steps: { step: RequestStep; at: number | null }[];
  /** 对方记录里那条请求发言的编号；还没送达时为空。 */
  deliveredRecordId: string | null;
}

function isMainAgentSay(record: WorkbenchRecord): boolean {
  return record.kind === 'agent.say' && !record.agent_path.length;
}

function textOf(record: WorkbenchRecord): string {
  const text = record.payload.text;
  return typeof text === 'string' ? text : '';
}

/**
 * 从对方记录里的那条请求发言往后推：对方 agent 回了没有、是不是停下来在等它的主人。
 *
 * 看的是这条请求之后、下一件事开始之前的那一段。「下一件事」是下一条不是卡片答复
 * （`【answer】` 开头）的主人发言——对方主人点了卡片、他的 agent 接着回，仍然算在
 * 这一段里。
 */
export function afterDelivery(
  peerRecords: WorkbenchRecord[],
  deliveredIndex: number,
): { step: 'on_it' | 'waiting_owner' | 'replied'; at: number | null } {
  let last: WorkbenchRecord | null = null;
  for (let i = deliveredIndex + 1; i < peerRecords.length; i += 1) {
    const r = peerRecords[i];
    if (r.kind === 'user.say' && !r.agent_path.length && !textOf(r).startsWith('【answer】')) break;
    if (isMainAgentSay(r)) last = r;
  }
  if (!last) return { step: 'on_it', at: null };
  if (endsWithTeammateCard(textOf(last))) return { step: 'waiting_owner', at: last.ts };
  return { step: 'replied', at: last.ts };
}

/**
 * 一条从本页发出的请求此刻走到哪一步。只读两侧已有数据：
 *
 * | 步 | 判据 |
 * |---|---|
 * | sent | 本页发出、接口回了成功 |
 * | delivered | 对方记录里出现带核实行、原文相同（有编号时编号相同）的用户发言 |
 * | on_it | 送达之后对方还没有 agent 回复 |
 * | waiting_owner | 送达之后对方最后一条 agent 回复末尾是来自队友的决定卡 |
 * | replied | 送达之后对方有 agent 回复，且不是上一行那种 |
 */
export function stepsFor(request: SentRequest, peerRecords: WorkbenchRecord[]): RequestProgress {
  const body = request.text.trim();
  const index = peerRecords.findIndex((record) => {
    const relayed = parseRelayed(record);
    if (!relayed) return false;
    if (request.messageId) return relayed.messageId === request.messageId;
    // 旧中继不回编号时只能按原文比。发出之前的同文请求不算——那是上一次的。
    return relayed.body === body && record.ts >= request.sentAt - 60_000;
  });
  const steps: RequestProgress['steps'] = [{ step: 'sent', at: request.sentAt }];
  if (index < 0) return { steps, deliveredRecordId: null };
  const delivered = peerRecords[index];
  steps.push({ step: 'delivered', at: delivered.ts });
  steps.push(afterDelivery(peerRecords, index));
  return { steps, deliveredRecordId: delivered.id };
}

/**
 * 对方记录里一条真实转来的请求（不一定是本页这次发的）走到哪一步。
 *
 * 发出那一步没有本地记录可查，不带时刻；送达时刻取那条发言本身。
 */
export function stepsForRelayed(
  peerRecords: WorkbenchRecord[],
  index: number,
  sentAt: number | null,
): RequestProgress['steps'] {
  return [
    { step: 'sent', at: sentAt },
    { step: 'delivered', at: peerRecords[index].ts },
    afterDelivery(peerRecords, index),
  ];
}
