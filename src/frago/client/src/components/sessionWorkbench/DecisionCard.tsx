/**
 * DecisionCard — agent 回复末尾的 `answer-needed-by-human` 区块画成的可点卡片。
 *
 * 卡片上每一个字都取自区块字段，页面不补不猜（解析与校验见 `utils/decisionBlock.ts`）。
 * 点选之后交出去的是一句**人的发言**：页面把它交给输入区，走的是跟「发送」同一条路，
 * 记录流里以「You said」出现。只有走人的输入口才算人的授权——07-30 查明 hook 注进去的
 * 不算——所以卡片 NEVER 自己开一条通道去调发送接口。
 *
 * 按人怎么作答分 4 型，统一为「选 / 写 + 点 Answer 按钮才发送」（不再点选项即发）：
 *
 * | type | 怎么点 |
 * |---|---|
 * | single-choice | 选一项 + 可选输入，再按「Answer」；收不回的先出确认条 |
 * | multi-choice | 勾选 + 可选输入，再按「Answer with N picked」 |
 * | text-answer | 打字作答；建议答案点了只填不发 |
 * | choice-and-text | 选（`multi: true` 时可多选）、写，或都有，再按「Answer」 |
 *
 * 视觉守全局规矩：卡上没有实心绿（这一屏的实心绿只给 Send）；收不回的一律告警橙；选中态
 * 整卡换 `--sel-bg` 底加一圈 `--sel-border`，不用单边条；字号只用 11 / 12 / 13。
 *
 * 卡片要的三样页面状态——这场能不能发、这张卡答过没有、怎么把一句话交给输入区——经
 * {@link DecisionCardContext} 取。记录卡是记忆化的，只收记录本身；走上下文，记录流里其余
 * 两百张卡不跟着重渲染。没有提供者（Teams 页右栏）时卡片只读。
 */

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Check, Info, Users } from 'lucide-react';
import {
  composeAnswer,
  isMany,
  loadYaml,
  parseDecisionBlock,
  pickedFromAnswer,
  writtenFromAnswer,
  yamlNow,
  type BrokenReason,
  type DecisionBlock,
  type DecisionOption,
  type ParsedCardAnswer,
  type TrailingBlock,
  type Yaml,
} from '@/utils/decisionBlock';

/**
 * 本地时刻，与记录卡上的时刻同一种写法。不从 `RecordCard` 取：那边要引这个文件来画卡，
 * 两头互引会让谁先加载都说不准。
 */
function clock(ts: number): string {
  const d = new Date(ts);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

// ── 页面状态 ──────────────────────────────────────────────────────────
/**
 * 一张卡的答复。
 *
 * | kind | 什么意思 |
 * |---|---|
 * | card | 卡片之后人的第一条发言是卡片发的（以【answer】开头） |
 * | own-words | 卡片之后人自己打了字回话，没点卡片 |
 * | pending | 点了、还没在记录里见到那句话 |
 */
export interface DecisionAnswer {
  kind: 'card' | 'own-words' | 'pending';
  text: string;
  at: number;
}

export interface DecisionCardHost {
  /** 这场此刻能不能发。 */
  canAnswer: boolean;
  /** 不能发时的原因（词表键），与输入区那一句相同。 */
  blockedReason: string | null;
  /** 这张卡答过没有、怎么答的。按记录判，刷新后仍在。 */
  answerOf: (recordId: string) => DecisionAnswer | null;
  /** 把一句答复交给输入区整句投出。 */
  answer: (recordId: string, text: string) => void;
}

export const DecisionCardContext = createContext<DecisionCardHost | null>(null);

// ── 小件 ──────────────────────────────────────────────────────────────
/** 反引号画成行内代码，其余一概不解析。 */
function Inline({ text }: { text: string }) {
  const parts = text.split(/`([^`]+)`/);
  return (
    <>
      {parts.map((part, i) =>
        i % 2 ? (
          <code key={i} className="rounded-[4px] bg-bg-hover px-1 font-mono text-[11px]">
            {part}
          </code>
        ) : (
          part
        )
      )}
    </>
  );
}

const BTN =
  'inline-flex h-6 shrink-0 items-center rounded-[7px] border border-border-color px-2.5 text-[12px] text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary disabled:cursor-default disabled:opacity-50 disabled:hover:bg-transparent disabled:hover:text-text-secondary';

const BOX =
  'whitespace-pre-wrap break-words rounded-[8px] border px-[9px] py-[7px] text-[12px] leading-[1.55]';

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="mb-0.5 text-[11px] text-text-muted">{label}</div>
      {children}
    </div>
  );
}

// ── 卡片 ──────────────────────────────────────────────────────────────
export function DecisionCard({ block, recordId }: { block: DecisionBlock; recordId: string }) {
  const { t } = useTranslation();
  const host = useContext(DecisionCardContext);
  const answered = host?.answerOf(recordId) ?? null;
  const done = answered !== null;
  const live = Boolean(host?.canAnswer) && !done;

  const T = block.type;
  const opts = block.options;
  const many = isMany(block);
  const irr = opts.some((o) => !o.reversible);

  const [picks, setPicks] = useState<number[]>([]);
  const [confirm, setConfirm] = useState(false);
  const [input, setInput] = useState('');
  const [editing, setEditing] = useState(false);
  const [draftText, setDraftText] = useState(block.draft ?? '');

  const doneKeys = done && answered.kind !== 'own-words' ? pickedFromAnswer(answered.text, block) : [];
  const isOn = (i: number) => (done ? doneKeys.includes(i) : picks.includes(i));

  /** 此刻写了什么。有草稿时：照原文、或改了但一字没动，都算没写（text-answer 的草稿本身就是答案）。 */
  const writtenNow = (): string => {
    if (block.draft == null) return input;
    if (T === 'text-answer') return editing ? draftText : block.draft;
    return editing && draftText.trim() !== block.draft.trim() ? draftText : '';
  };

  const send = (text: string) => {
    setConfirm(false);
    host?.answer(recordId, text);
  };

  const toggle = (i: number) => {
    if (!live) return;
    setConfirm(false);
    setPicks((cur) =>
      many ? (cur.includes(i) ? cur.filter((x) => x !== i) : [...cur, i].sort((a, b) => a - b)) : cur.includes(i) ? [] : [i]
    );
  };

  const picked: DecisionOption[] = opts.filter((_, i) => picks.includes(i));
  const canSubmit = picked.length > 0 || Boolean(writtenNow().trim());

  const submit = (sure = false) => {
    if (!live || !canSubmit) return;
    if (picked.some((o) => !o.reversible) && !sure) {
      setConfirm(true);
      return;
    }
    send(composeAnswer(block, picked, writtenNow()));
  };

  const onEnter = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  const fillSuggestion = (s: string) => {
    if (!live) return;
    if (block.draft != null) {
      setEditing(true);
      setDraftText(s);
    } else {
      setInput(s);
    }
  };

  const allPicked = opts.length > 0 && opts.every((_, i) => picks.includes(i));
  const pending = (i: number) =>
    !done && confirm && picks.includes(i) && !opts[i].reversible;

  /* 只变底色与透明度（可提交 ↔ 不可提交、hover）。此前是 `transition-all`，把宽高也包了进去——
     这张卡在记录流里会随答案长度重排，`transition-all` 会让那次重排也走一遍动画。 */
  const answerBtnClass = `inline-flex h-[32px] shrink-0 items-center justify-center rounded-[8px] border border-accent-primary px-4 text-[13px] font-medium transition-[background-color,color,opacity] ${
    canSubmit
      ? 'bg-accent-primary text-[var(--text-on-accent)] shadow-sm hover:opacity-90 cursor-pointer'
      : 'bg-transparent text-accent-primary opacity-60 cursor-not-allowed'
  }`;

  const head = t(`workbench.decision.head.${T === 'choice-and-text' && block.multi ? 'choice-and-text-multi' : T}`);

  const tags = (o: DecisionOption) => (
    <>
      {o.recommended ? (
        <span className="h-4 whitespace-nowrap rounded-[4px] border border-[var(--sel-border)] px-[5px] text-[11px] font-medium leading-[14px] text-text-primary">
          {t('workbench.decision.recommended')}
        </span>
      ) : null}
      {!o.reversible ? (
        <span className="h-4 whitespace-nowrap rounded-[4px] bg-accent-warning-10 px-[5px] text-[11px] font-medium leading-4 text-accent-warning">
          {t('workbench.decision.cantUndo')}
        </span>
      ) : null}
    </>
  );

  /**
   * 选项行：标题一档、说明一档。
   *
   * 卡内字号只留四档——问题标题（正文档 16）、选项标题（13）、说明文字（12）、
   * 字段标签与提示（11）。此前这里挤了 11/12/13/14/16/17 六档，选项标题 16 与说明 14
   * 只差两像素、又和卡上别处的 16 撞在一起，读起来层级是平的。2026-11-13 收口。
   */
  const optionBody = (o: DecisionOption) => (
    <span className="flex min-w-0 flex-1 flex-col">
      <span className="flex flex-wrap items-center gap-x-1.5 gap-y-[3px] break-words text-[13px] font-medium leading-[1.45] text-text-primary">
        <Inline text={o.label} />
        {tags(o)}
      </span>
      <span className="mt-px break-words text-[12px] leading-[1.55] text-text-secondary">
        <Inline text={o.effect} />
      </span>
    </span>
  );

  const optionTone = (i: number) => {
    const on = isOn(i);
    if (pending(i)) return 'border-accent-warning bg-accent-warning-10';
    if (on) return 'border-[var(--sel-border)] bg-[var(--sel-bg)]';
    const dim = done ? 'opacity-45' : '';
    return `border-transparent bg-bg-primary ${live ? 'hover:bg-bg-hover' : ''} ${dim}`;
  };

  /**
   * 选项 KEY 的小方块。
   *
   * 短 KEY（`A`/`B`/`C`…）保持 18 像素见方的方块观感——`min-w-[18px]` 顶住下限，加不加内边距
   * 都不变样。KEY 变长时横向自然撑开，到 72 像素封顶后截断加省略号，悬停看完整值。
   *
   * 此前这里是写死的 `w-[18px]`：11 号等宽字下 18 像素只装得下两三个字符，`HOLD` 就已经
   * 往外溢，`IMPL_DYNAMIC` 这种整句直接压住标题、越过选项行边框——2026-11-13 修。
   * 短 KEY 是常规输入，长 KEY 是历史卡片与手写区块里的遗留，两头都要接住。
   */
  const keyBox = (o: DecisionOption, i: number) => (
    <span
      title={o.key}
      className={`mt-px flex h-[18px] min-w-[18px] max-w-[72px] shrink-0 items-center justify-center overflow-hidden rounded-[5px] border px-1 font-mono text-[11px] ${
        isOn(i)
          ? 'border-text-primary bg-text-primary text-bg-primary'
          : 'border-border-strong text-text-secondary'
      }`}
    >
      <span className="min-w-0 truncate">{o.key}</span>
    </span>
  );

  const OPTION = 'flex w-full min-w-0 items-start gap-2 rounded-[8px] border px-[9px] pb-2 pt-[7px] text-left';

  const optionList = opts.length ? (
    <div
      className={
        T === 'single-choice' && opts.length === 2
          ? 'grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-1.5'
          : 'flex flex-col gap-1.5'
      }
    >
      {opts.map((o, i) =>
        many ? (
          <label
            key={i}
            data-testid="decision-option"
            data-on={isOn(i) ? 'true' : undefined}
            className={`${OPTION} ${live ? 'cursor-pointer' : 'cursor-default'} ${optionTone(i)}`}
          >
            <input
              type="checkbox"
              checked={isOn(i)}
              disabled={!live}
              onChange={() => toggle(i)}
              className="mt-[3px] h-[13px] w-[13px] shrink-0 accent-[var(--text-primary)]"
            />
            {keyBox(o, i)}
            {optionBody(o)}
          </label>
        ) : (
          <button
            key={i}
            type="button"
            data-testid="decision-option"
            data-on={isOn(i) ? 'true' : undefined}
            disabled={!live}
            onClick={() => toggle(i)}
            className={`${OPTION} ${live ? '' : 'cursor-default'} ${optionTone(i)}`}
          >
            {keyBox(o, i)}
            {optionBody(o)}
            {done && isOn(i) ? <Check size={14} className="mt-0.5 shrink-0 text-text-primary" /> : null}
          </button>
        )
      )}
    </div>
  ) : null;

  const doneWritten = done && answered.kind !== 'own-words' ? writtenFromAnswer(answered.text, block) : '';

  let textArea: ReactNode = null;
  if (block.draft != null) {
    if (done) {
      textArea = (
        <Field label={t('workbench.decision.draft')}>
          <div className={`${BOX} border-border-color bg-bg-base text-text-primary`}>
            {doneWritten || (T === 'choice-and-text' ? block.draft : '')}
          </div>
        </Field>
      );
    } else {
      textArea = (
        <div className="min-w-0">
          <div className="mb-1 flex items-center gap-2">
            <span className="text-[11px] text-text-muted">{t('workbench.decision.draft')}</span>
            <span className="inline-flex overflow-hidden rounded-[6px] border border-border-color">
              {[false, true].map((edit) => (
                <button
                  key={String(edit)}
                  type="button"
                  data-testid={edit ? 'decision-draft-edit' : 'decision-draft-asis'}
                  aria-pressed={editing === edit}
                  disabled={!live}
                  onClick={() => {
                    setEditing(edit);
                    if (edit && !editing) setDraftText(block.draft ?? '');
                  }}
                  className={`h-5 px-2 text-[11px] disabled:cursor-default ${
                    editing === edit
                      ? 'bg-[var(--sel-bg)] font-medium text-text-primary'
                      : 'text-text-secondary hover:bg-bg-hover'
                  }`}
                >
                  {t(edit ? 'workbench.decision.edit' : 'workbench.decision.asIs')}
                </button>
              ))}
            </span>
          </div>
          {editing ? (
            <textarea
              data-testid="decision-draft-input"
              value={draftText}
              disabled={!live}
              onChange={(e) => setDraftText(e.target.value)}
              className="block min-h-[150px] w-full resize-y rounded-[8px] border border-border-strong bg-bg-primary px-[9px] py-[7px] text-[12px] leading-[1.55] text-text-primary outline-none"
            />
          ) : (
            <div data-testid="decision-draft" className={`${BOX} border-border-color bg-bg-base text-text-primary`}>
              {block.draft}
            </div>
          )}
        </div>
      );
    }
  } else if (!done) {
    textArea = (
      <div className="flex items-center gap-1.5">
        <input
          data-testid="decision-input"
          value={input}
          disabled={!live}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onEnter}
          placeholder={t(T === 'text-answer' ? 'workbench.decision.typePlaceholder' : 'workbench.decision.writeOwn')}
          className="h-8 min-w-0 flex-1 rounded-[8px] border border-border-color bg-bg-primary px-3 text-[13px] text-text-primary outline-none placeholder:text-text-muted focus:border-border-strong disabled:cursor-default"
        />
        {T === 'text-answer' ? (
          <button type="button" data-testid="decision-answer" disabled={!live || !canSubmit} onClick={() => submit()} className={answerBtnClass}>
            {t('workbench.decision.answer')}
          </button>
        ) : null}
      </div>
    );
  }

  const suggestions =
    T === 'text-answer' && block.suggestions.length && !done ? (
      <div className="min-w-0">
        <div className="mb-1 text-[11px] text-text-muted">{t('workbench.decision.suggested')}</div>
        <div className="flex flex-wrap gap-1.5">
          {block.suggestions.map((s, i) => {
            const on = (block.draft != null ? editing && draftText === s : input === s);
            return (
              <button
                key={i}
                type="button"
                data-testid="decision-suggestion"
                disabled={!live}
                onClick={() => fillSuggestion(s)}
                className={`h-6 max-w-full truncate rounded-full border px-[9px] text-[12px] text-text-primary disabled:cursor-default ${
                  on ? 'border-[var(--sel-border)] bg-[var(--sel-bg)]' : 'border-border-color bg-bg-primary hover:bg-bg-hover'
                }`}
              >
                {s}
              </button>
            );
          })}
        </div>
      </div>
    ) : null;

  let actions: ReactNode = null;
  if (!done) {
    if (T !== 'text-answer') {
      const label =
        T === 'multi-choice'
          ? picked.length
            ? t('workbench.decision.answerPicked', { count: picked.length })
            : canSubmit
              ? t('workbench.decision.answer')
              : t('workbench.decision.pickAtLeastOne')
          : t('workbench.decision.answer');
      actions = (
        <div className="flex items-center justify-end gap-1.5">
          <span className="mr-auto text-[11px] text-text-muted">
            {t(block.draft != null ? 'workbench.decision.draftHint' : 'workbench.decision.hint')}
          </span>
          <button type="button" data-testid="decision-answer" disabled={!live || !canSubmit} onClick={() => submit()} className={answerBtnClass}>
            {label}
          </button>
        </div>
      );
    } else if (block.draft != null) {
      actions = (
        <div className="flex justify-end">
          <button type="button" data-testid="decision-answer" disabled={!live || !canSubmit} onClick={() => submit()} className={answerBtnClass}>
            {t('workbench.decision.answer')}
          </button>
        </div>
      );
    }
  }

  const confirmBar =
    confirm && !done ? (
      <div
        data-testid="decision-confirm"
        className="flex flex-wrap items-center gap-2 rounded-[8px] border border-accent-warning bg-accent-warning-10 px-[9px] py-[7px] text-[12px] text-accent-warning"
      >
        <AlertTriangle size={14} className="shrink-0" />
        <span className="min-w-[140px] flex-1 font-medium">
          {t('workbench.decision.confirm')}
          {picked
            .filter((o) => !o.reversible)
            .map((o, i) => (
              <span key={i} className="block break-words text-[11px] font-normal text-text-secondary">
                {o.key} · {o.label} — {o.effect}
              </span>
            ))}
        </span>
        <span className="ml-auto flex gap-1.5">
          <button type="button" onClick={() => setConfirm(false)} className={`${BTN} border-border-strong bg-bg-primary text-text-primary`}>
            {t('workbench.decision.cancel')}
          </button>
          <button
            type="button"
            data-testid="decision-confirm-yes"
            onClick={() => submit(true)}
            className={`${BTN} border-accent-warning bg-bg-primary font-medium text-accent-warning hover:bg-accent-warning-10 hover:text-accent-warning`}
          >
            {t('workbench.decision.yesDoIt')}
          </button>
        </span>
      </div>
    ) : null;

  let foot: ReactNode = null;
  if (done) {
    foot = (
      <div
        data-testid="decision-answered"
        className="flex items-center gap-1.5 pt-[7px] text-[12px] text-text-secondary"
      >
        <Check size={12} className="shrink-0" />
        <span>
          {answered.kind === 'own-words'
            ? t('workbench.decision.repliedOwn')
            : t('workbench.decision.answeredAt', { time: clock(answered.at) })}
        </span>
      </div>
    );
  } else if (host && !host.canAnswer && host.blockedReason) {
    foot = (
      <p data-testid="decision-blocked" className="text-[12px] text-text-muted">
        {t(host.blockedReason)}
      </p>
    );
  }

  return (
    <div
      data-testid="decision-card"
      data-type={T}
      data-state={done ? answered.kind : live ? 'open' : 'read-only'}
      /* 浅色主题下卡片与页面底都是 #FFFFFF（`--bg-card` = `--bg-primary`），白压白，
         卡片边界只剩圆角在暗示。这里补一圈内描边把它勾出来。
         用 `box-shadow` 的 inset 而不是 `border`：border 会占内容宽度、把卡里的
         换行位置挪一挪，而 box-shadow 画在盒内、不参与布局，卡的尺寸一个像素都不动。
         `--border-card` 只在浅色侧有值，深色侧没定义——那条 shadow 声明在深色下
         整条作废，等于没加（深色靠 #242424 对 #1f1f1f 的明度差已经分得开）。

         **正在等人拍板的那一张走 `.ui-decision-spotlight`**：品牌绿柔和聚光外环加
         双层边框，是全流对比度最高的一处——一屏记录扫下来，眼睛先落在「现在等你拍什么板」。
         答过、只读、这场发不出去的那几张退回普通卡：聚光是给"还要你动手"的，
         已经答完的再亮着，那一处就不再是信号。 */
      className={`mt-2 flex min-w-0 flex-col gap-2.5 text-[13px] leading-[1.6] ${
        live
          ? 'ui-decision-spotlight'
          : 'rounded-[10px] bg-bg-card px-3.5 pb-3.5 pt-3 [box-shadow:inset_0_0_0_1px_var(--border-card)]'
      } ${irr ? 'border border-accent-warning' : 'border-0'}`}
    >
      <div className="flex min-w-0 items-center gap-1.5">
        {block.fromTeammate ? (
          <span className="inline-flex h-5 shrink-0 items-center gap-[5px] rounded-full bg-[var(--peer-chip)] px-2 text-[11px] font-semibold text-[var(--peer-ink)]">
            <Users size={12} />
            {t('workbench.decision.fromTeammate')}
          </span>
        ) : null}
        <span
          className={`min-w-0 truncate text-[12px] font-semibold uppercase tracking-[0.04em] ${
            irr ? 'text-accent-warning' : 'text-text-muted'
          }`}
        >
          {head}
          {irr ? t('workbench.decision.cantUndoSuffix') : ''}
        </span>
        {T === 'multi-choice' && live ? (
          <button
            type="button"
            data-testid="decision-toggle-all"
            onClick={() => setPicks(allPicked ? [] : opts.map((_, i) => i))}
            className="ml-auto shrink-0 text-[12px] text-text-secondary underline underline-offset-2 hover:text-text-primary"
          >
            {t(allPicked ? 'workbench.decision.clearAll' : 'workbench.decision.selectAll')}
          </button>
        ) : null}
      </div>
      {/* 问题标题：卡内最大的一档，15（与全站页标题同档）。此前是 17——全站只此一处，
          和选项标题的 16 只差一像素，层级分不开。 */}
      <div className="break-words text-[15px] font-semibold leading-[1.45] text-text-primary">
        <Inline text={block.question} />
      </div>
      {block.why != null ? (
        <div className="-mt-[4px] break-words text-[12px] leading-[1.6] text-text-secondary">
          <Inline text={block.why} />
        </div>
      ) : null}
      {block.fromTeammate && block.request != null ? (
        <Field label={t('workbench.decision.theirRequest')}>
          <div className={`${BOX} border-transparent bg-[var(--peer-chip)] text-text-primary`}>{block.request}</div>
        </Field>
      ) : null}
      {block.fromTeammate && block.changes != null ? (
        <Field label={t('workbench.decision.wouldChange')}>
          <div className={`${BOX} border-border-color bg-bg-base font-mono text-[11px] leading-[1.6] text-text-primary`}>
            {block.changes}
          </div>
        </Field>
      ) : null}
      {optionList}
      {textArea}
      {suggestions}
      {actions}
      {confirmBar}
      {foot}
    </div>
  );
}

// ── 人发出的那句卡片答复 ──────────────────────────────────────────────
/**
 * 「You said」气泡里的卡片答复。
 *
 * 原文是给 agent 读的一行（`【answer】A · label —— effect`），照字面摆出来前缀突兀、
 * 选项和效果挤成一串。这里拆开重排：选中的每一项画成卡片上那一项被选中后的样子——
 * 同一个字母方块、同一种选中底色——人在卡上点了什么，回到记录流里一眼对得上；写的字
 * 另起一段。前缀本身不再显示，由气泡标题旁的「卡片答复」小标说出这句话是从卡片来的。
 */
export function CardAnswerBody({ answer }: { answer: ParsedCardAnswer }) {
  return (
    <div data-testid="card-answer" className="flex min-w-0 flex-col gap-1.5">
      {answer.picked.map((o, i) => (
        <div
          key={i}
          data-testid="card-answer-option"
          className="flex min-w-0 items-start gap-2 rounded-[8px] border border-[var(--sel-border)] bg-[var(--sel-bg)] px-[9px] pb-2 pt-[7px]"
        >
          {/* 与卡上的 KEY 方块同一套边界：短 KEY 保持 18 像素见方，长 KEY 撑开到 72 像素封顶后
              截断，悬停看完整值——历史会话里 `IMPL_DYNAMIC` 这类长 KEY 的答复也撑不破气泡。 */}
          <span
            title={o.key}
            className="mt-px flex h-[18px] min-w-[18px] max-w-[72px] shrink-0 items-center justify-center overflow-hidden rounded-[5px] border border-text-primary bg-text-primary px-1 font-mono text-[11px] text-bg-primary"
          >
            <span className="min-w-0 truncate">{o.key}</span>
          </span>
          <span className="flex min-w-0 flex-1 flex-col">
            <span className="break-words text-[13px] font-medium leading-[1.45] text-text-primary">
              <Inline text={o.label} />
            </span>
            <span className="mt-px break-words text-[12px] leading-[1.55] text-text-secondary">
              <Inline text={o.effect} />
            </span>
          </span>
        </div>
      ))}
      {/* 自己写的那段：跟记录正文同一档 16，读起来是同一种字。 */}
      {answer.written ? (
        <p className="text-scaled-prose whitespace-pre-wrap break-words leading-[1.72] text-text-primary">
          {answer.written}
        </p>
      ) : null}
    </div>
  );
}

/** 气泡标题旁那枚「卡片答复」小标，替掉正文开头的 `【answer】`。 */
export function CardAnswerTag() {
  const { t } = useTranslation();
  return (
    <span
      data-testid="card-answer-tag"
      className="inline-flex items-center gap-1 rounded-full bg-bg-subtle px-2 py-[1px] text-[11px] text-text-secondary"
    >
      <Check size={11} className="shrink-0" />
      {t('workbench.decision.cardAnswerTag')}
    </span>
  );
}

// ── 接在 agent 回复上 ──────────────────────────────────────────────────
function useYaml(): Yaml | null {
  const [yaml, setYaml] = useState<Yaml | null>(yamlNow);
  useEffect(() => {
    if (yaml) return;
    let alive = true;
    void loadYaml().then((y) => {
      if (alive) setYaml(() => y);
    });
    return () => {
      alive = false;
    };
  }, [yaml]);
  return yaml;
}

function useBrokenText() {
  const { t } = useTranslation();
  return (reason: BrokenReason) =>
    t('workbench.decision.brokenLead', {
      reason: t(`workbench.decision.broken.${reason.code}`, reason.params ?? {}),
    });
}

/**
 * 报错或写坏的交互卡片：把原始输出塞进 ```code 围栏块展示，并在下方附一行小字说明原因。
 */
export function DecisionBroken({
  raw,
  reason,
  rich,
}: {
  raw?: string;
  reason: BrokenReason;
  rich?: (text: string) => ReactNode;
}) {
  const brokenText = useBrokenText();
  const trimmed = raw?.trim() ?? '';
  return (
    <>
      {trimmed && rich ? (
        <div className="mt-2 min-w-0">{rich(`\`\`\`\n${trimmed}\n\`\`\``)}</div>
      ) : null}
      <p
        data-testid="decision-broken"
        className="mt-1 flex items-start gap-1.5 text-[11px] leading-[1.5] text-text-muted"
      >
        <Info size={12} className="mt-0.5 shrink-0" />
        <span>{brokenText(reason)}</span>
      </p>
    </>
  );
}

/**
 * 一条末尾带区块的 agent 回复：正文照常，区块换成卡片；读不了就照原文显示并写明原因。
 *
 * `rich` 由记录卡给：正文怎么排版归它管，这里只决定哪一段交给它。
 */
export function DecisionReply({
  recordId,
  text,
  split,
  rich,
}: {
  recordId: string;
  text: string;
  split: TrailingBlock;
  rich: (text: string) => ReactNode;
}) {
  const yaml = useYaml();
  // YAML 解析器还在路上：先只画正文，不把区块原文先摆出来再换掉。
  if (!yaml) return <>{split.body ? rich(split.body) : null}</>;
  const result = parseDecisionBlock(split.raw, yaml);
  if (!result.ok) {
    return (
      <>
        {rich(text)}
        <DecisionBroken reason={result.reason} />
      </>
    );
  }
  return (
    <>
      {split.body ? rich(split.body) : null}
      <DecisionCard block={result.block} recordId={recordId} />
    </>
  );
}
