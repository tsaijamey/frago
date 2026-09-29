/**
 * DecisionCard — agent 回复末尾的 `answer-needed-by-human` 区块画成的可点卡片。
 *
 * 卡片上每一个字都取自区块字段，页面不补不猜（解析与校验见 `utils/decisionBlock.ts`）。
 * 点选之后交出去的是一句**人的发言**：页面把它交给输入区，走的是跟「发送」同一条路，
 * 记录流里以「You said」出现。只有走人的输入口才算人的授权——07-30 查明 hook 注进去的
 * 不算——所以卡片 NEVER 自己开一条通道去调发送接口。
 *
 * 按人怎么作答分 4 型：
 *
 * | type | 怎么点 |
 * |---|---|
 * | single-choice | 点即答；收不回的先出确认条 |
 * | multi-choice | 勾选，再按「Answer with N picked」 |
 * | text-answer | 打字作答；建议答案点了只填不发 |
 * | choice-and-text | 选（`multi: true` 时可多选）、写，或都有 |
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
  const [confirm, setConfirm] = useState<number | 'multi' | null>(null);
  const [input, setInput] = useState('');
  const [editing, setEditing] = useState(false);
  const [draftText, setDraftText] = useState(block.draft ?? '');

  const doneKeys = done && answered.kind !== 'own-words' ? pickedFromAnswer(answered.text, block) : [];
  const isOn = (i: number) => (done ? doneKeys.includes(i) : T !== 'single-choice' && picks.includes(i));

  /** 此刻写了什么。有草稿时：照原文、或改了但一字没动，都算没写（text-answer 的草稿本身就是答案）。 */
  const writtenNow = (): string => {
    if (T === 'multi-choice' || T === 'single-choice') return '';
    if (block.draft == null) return input;
    if (T === 'text-answer') return editing ? draftText : block.draft;
    return editing && draftText.trim() !== block.draft.trim() ? draftText : '';
  };

  const send = (text: string) => {
    setConfirm(null);
    host?.answer(recordId, text);
  };

  const pickOne = (i: number, sure = false) => {
    if (!live) return;
    const o = opts[i];
    if (!o.reversible && !sure) {
      setConfirm(i);
      return;
    }
    send(composeAnswer(block, [o], ''));
  };

  const toggle = (i: number) => {
    if (!live) return;
    setConfirm(null);
    setPicks((cur) =>
      many ? (cur.includes(i) ? cur.filter((x) => x !== i) : [...cur, i].sort((a, b) => a - b)) : cur.includes(i) ? [] : [i]
    );
  };

  const picked: DecisionOption[] = opts.filter((_, i) => picks.includes(i));
  const canSubmit = picked.length > 0 || Boolean(writtenNow().trim());

  const submit = (sure = false) => {
    if (!live || !canSubmit) return;
    if (picked.some((o) => !o.reversible) && !sure) {
      setConfirm('multi');
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
    !done && (confirm === i || (confirm === 'multi' && picks.includes(i) && !opts[i].reversible));

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

  const optionBody = (o: DecisionOption) => (
    <span className="flex min-w-0 flex-1 flex-col">
      <span className="flex flex-wrap items-center gap-x-1.5 gap-y-[3px] break-words text-[13px] font-medium leading-[1.45] text-text-primary">
        <Inline text={o.label} />
        {tags(o)}
      </span>
      <span className="mt-px break-words text-[12px] leading-[1.5] text-text-secondary">
        <Inline text={o.effect} />
      </span>
    </span>
  );

  const optionTone = (i: number) => {
    const on = isOn(i);
    if (pending(i)) return 'border-accent-warning bg-accent-warning-10';
    if (on) return 'border-[var(--sel-border)] bg-[var(--sel-bg)]';
    const dim = done ? 'opacity-45' : '';
    return `border-border-color bg-bg-primary ${live ? 'hover:border-border-strong hover:bg-bg-hover' : ''} ${dim}`;
  };

  const keyBox = (o: DecisionOption, i: number) => (
    <span
      className={`mt-px flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-[5px] border font-mono text-[11px] ${
        isOn(i)
          ? 'border-text-primary bg-text-primary text-bg-primary'
          : 'border-border-strong text-text-secondary'
      }`}
    >
      {o.key}
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
            onClick={() => (T === 'single-choice' ? pickOne(i) : toggle(i))}
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

  const takesText = T === 'text-answer' || T === 'choice-and-text';
  const doneWritten = done && answered.kind !== 'own-words' ? writtenFromAnswer(answered.text, block) : '';

  let textArea: ReactNode = null;
  if (takesText && block.draft != null) {
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
  } else if (takesText && !done) {
    textArea = (
      <div className="flex items-center gap-1.5">
        <input
          data-testid="decision-input"
          value={input}
          disabled={!live}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onEnter}
          placeholder={t(T === 'text-answer' ? 'workbench.decision.typePlaceholder' : 'workbench.decision.writeOwn')}
          className="h-7 min-w-0 flex-1 rounded-[7px] border border-border-color bg-bg-primary px-[9px] text-[13px] text-text-primary outline-none placeholder:text-text-muted focus:border-border-strong disabled:cursor-default"
        />
        {T === 'text-answer' ? (
          <button type="button" data-testid="decision-answer" disabled={!live || !canSubmit} onClick={() => submit()} className={BTN}>
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
  if (!done && confirm !== 'multi') {
    if (T === 'multi-choice' || T === 'choice-and-text') {
      const label =
        T === 'multi-choice'
          ? picked.length
            ? t('workbench.decision.answerPicked', { count: picked.length })
            : t('workbench.decision.pickAtLeastOne')
          : t('workbench.decision.answer');
      actions = (
        <div className="flex items-center justify-end gap-1.5">
          {T === 'choice-and-text' ? (
            <span className="mr-auto text-[11px] text-text-muted">
              {t(block.draft != null ? 'workbench.decision.draftHint' : 'workbench.decision.hint')}
            </span>
          ) : null}
          <button type="button" data-testid="decision-answer" disabled={!live || !canSubmit} onClick={() => submit()} className={BTN}>
            {label}
          </button>
        </div>
      );
    } else if (T === 'text-answer' && block.draft != null) {
      actions = (
        <div className="flex justify-end">
          <button type="button" data-testid="decision-answer" disabled={!live || !canSubmit} onClick={() => submit()} className={BTN}>
            {t('workbench.decision.answer')}
          </button>
        </div>
      );
    }
  }

  const confirmBar =
    confirm !== null && !done ? (
      <div
        data-testid="decision-confirm"
        className="flex flex-wrap items-center gap-2 rounded-[8px] border border-accent-warning bg-accent-warning-10 px-[9px] py-[7px] text-[12px] text-accent-warning"
      >
        <AlertTriangle size={14} className="shrink-0" />
        <span className="min-w-[140px] flex-1 font-medium">
          {t('workbench.decision.confirm')}
          {(confirm === 'multi' ? picked.filter((o) => !o.reversible) : [opts[confirm]]).map((o, i) => (
            <span key={i} className="block break-words text-[11px] font-normal text-text-secondary">
              {o.key} · {o.label} — {o.effect}
            </span>
          ))}
        </span>
        <span className="ml-auto flex gap-1.5">
          <button type="button" onClick={() => setConfirm(null)} className={`${BTN} border-border-strong bg-bg-primary text-text-primary`}>
            {t('workbench.decision.cancel')}
          </button>
          <button
            type="button"
            data-testid="decision-confirm-yes"
            onClick={() => (confirm === 'multi' ? submit(true) : pickOne(confirm, true))}
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
        className="flex items-center gap-1.5 border-t border-dashed border-border-color pt-[7px] text-[11px] text-text-secondary"
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
      <p data-testid="decision-blocked" className="text-[11px] text-text-muted">
        {t(host.blockedReason)}
      </p>
    );
  }

  return (
    <div
      data-testid="decision-card"
      data-type={T}
      data-state={done ? answered.kind : live ? 'open' : 'read-only'}
      className={`mt-2 flex min-w-0 flex-col gap-2 rounded-[10px] border bg-bg-card px-3 pb-3 pt-2.5 text-[13px] leading-[1.5] ${
        irr ? 'border-accent-warning' : 'border-border-strong'
      }`}
    >
      <div className="flex min-w-0 items-center gap-1.5">
        {block.fromTeammate ? (
          <span className="inline-flex h-5 shrink-0 items-center gap-[5px] rounded-full bg-[var(--peer-chip)] px-2 text-[11px] font-semibold text-[var(--peer-ink)]">
            <Users size={12} />
            {t('workbench.decision.fromTeammate')}
          </span>
        ) : null}
        <span
          className={`min-w-0 truncate text-[11px] font-semibold uppercase tracking-[0.04em] ${
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
            className="ml-auto shrink-0 text-[11px] text-text-secondary underline underline-offset-2 hover:text-text-primary"
          >
            {t(allPicked ? 'workbench.decision.clearAll' : 'workbench.decision.selectAll')}
          </button>
        ) : null}
      </div>
      <div className="break-words text-[13px] font-semibold leading-[1.5] text-text-primary">
        <Inline text={block.question} />
      </div>
      {block.why != null ? (
        <div className="-mt-[5px] break-words text-[12px] text-text-secondary">
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
  const brokenText = useBrokenText();
  // YAML 解析器还在路上：先只画正文，不把区块原文先摆出来再换掉。
  if (!yaml) return <>{split.body ? rich(split.body) : null}</>;
  const result = parseDecisionBlock(split.raw, yaml);
  if (!result.ok) {
    return (
      <>
        {rich(text)}
        <p data-testid="decision-broken" className="mt-1 flex items-start gap-1.5 text-[11px] leading-[1.5] text-text-muted">
          <Info size={12} className="mt-0.5 shrink-0" />
          <span>{brokenText(result.reason)}</span>
        </p>
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
