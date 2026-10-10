/**
 * FileDiff — 浮窗里「改动」那一档：这份文件改动之前与现在，左右两列并排。
 *
 * 只画，不取：对齐好的两列由服务端交过来（左边那一侧只有它拿得到），这一层管的是
 * **把「左边那一侧是什么来路」说清楚**：
 *
 * - 有左边：它是 **git HEAD 里那一版**，不是「这场会话开始那一刻」的快照。会话改的东西若
 *   已经被提交，两边就一样了——所以下面还有一句「没有差别」的话兜着，别让人以为看错了。
 * - 左边是「新建」：git 里没有它的上一版，整份都是新增，左边整列空着。
 * - 左边是「不在仓库里」：产物常写在 `~/.frago/data` 下，那里不是仓库。这时**不装成新建的**，
 *   照实说没有上一版可对照。
 */

import { useTranslation } from 'react-i18next';
import { Info, Loader2 } from 'lucide-react';
import type { FileDiffCell, SessionFileDiff } from '@/types/api';

export interface FileDiffProps {
  diff: SessionFileDiff | null;
  loading: boolean;
  error: string | null;
}

/** 一格：行号 + 正文，整格一层底色（没改的不上底）。 */
function Cell({ cell }: { cell: FileDiffCell | null }) {
  const tone = cell === null ? 'void' : cell.sign === '+' ? 'add' : cell.sign === '-' ? 'del' : '';
  return (
    <div className={`diff-cell${tone ? ` ${tone}` : ''}`} data-sign={cell ? cell.sign : 'void'}>
      <span className="diff-line-no">{cell ? cell.no : ''}</span>
      <span className="min-w-0">{cell ? cell.text : ''}</span>
    </div>
  );
}

export default function FileDiff({ diff, loading, error }: FileDiffProps) {
  const { t } = useTranslation();

  if (loading) {
    return (
      <p
        data-testid="file-diff-loading"
        className="flex h-full items-center justify-center gap-2 text-[12px] text-text-muted"
      >
        <Loader2 size={14} className="animate-spin" />
        {t('workbench.files.diffLoading')}
      </p>
    );
  }
  if (error) {
    return (
      <p
        data-testid="file-diff-error"
        className="flex h-full flex-col items-center justify-center gap-2 px-5 text-center text-[12px] leading-relaxed text-text-muted"
      >
        <span>{t('workbench.files.diffFailed')}</span>
        <span className="max-w-[360px]">{error}</span>
      </p>
    );
  }
  if (!diff || !diff.rows) {
    return (
      <p className="flex h-full items-center justify-center px-5 text-center text-[12px] text-text-muted">
        {diff?.reason === 'too-many-lines'
          ? t('workbench.files.diffTooManyLines')
          : t('workbench.files.diffNone')}
      </p>
    );
  }

  const { rows, before, source } = diff;
  const hasLeft = before === null;
  const changed = rows.some(([left, right]) => left?.sign !== ' ' || right?.sign !== ' ');

  /** 左边那一侧的来路，一句话写清。这是这一档最要紧的一行字。 */
  const note =
    before === null
      ? t('workbench.files.diffFrom', { source: source ?? 'git' })
      : before === 'new'
        ? t('workbench.files.diffNew')
        : before === 'not-git'
          ? t('workbench.files.diffNotGit')
          : t('workbench.files.diffBeforeTooLarge');

  return (
    <div data-testid="file-diff" className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center gap-1.5 border-b border-border-color bg-bg-secondary px-3 py-[6px] text-[11.5px] leading-relaxed text-text-muted">
        <Info size={13} className="shrink-0 text-text-dim" />
        <span>{note}</span>
      </div>

      {!changed ? (
        <p
          data-testid="file-diff-same"
          className="shrink-0 border-b border-border-color px-3 py-[6px] text-[11.5px] text-text-muted"
        >
          {t('workbench.files.diffSame', { source: source ?? 'git' })}
        </p>
      ) : null}

      {hasLeft ? (
        <div className="sticky top-0 z-[1] grid shrink-0 grid-cols-[minmax(0,1fr)_minmax(0,1fr)] border-b border-border-color bg-bg-secondary text-[11px] text-text-muted">
          <span className="px-3 py-[3px]">{t('workbench.files.diffBefore')}</span>
          <span className="border-l border-border-color px-3 py-[3px]">
            {t('workbench.files.diffAfter')}
          </span>
        </div>
      ) : null}

      {/* **每一行自己是一张网格**，不是一整张网格铺到底——这不是排版口味，是长行折行时的
          正误：一整张网格铺到底时，行高按**不换行**时的字宽算出来，长行折成两行而格子仍只有
          一行高，折下来的那半截就压在下一行上（主人 10-10 报的「乱码」就是这个）。
          一行一张网格，行高就按这一行的内容长。改回去之前先看一眼这条注释。 */}
      <div
        data-testid="file-diff-rows"
        className="min-h-0 flex-1 overflow-auto font-mono text-[11.5px] leading-[1.62]"
      >
        {rows.map(([left, right], i) => (
          <div
            key={i}
            className={`grid ${hasLeft ? 'grid-cols-[minmax(0,1fr)_minmax(0,1fr)]' : 'grid-cols-1'}`}
          >
            {hasLeft ? <Cell cell={left} /> : null}
            <Cell cell={hasLeft ? right : (right ?? left)} />
          </div>
        ))}
      </div>
    </div>
  );
}
