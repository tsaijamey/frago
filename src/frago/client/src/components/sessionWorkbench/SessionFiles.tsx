/**
 * SessionFiles — 会话详情里「这场改过哪些文件」那一档的清单。
 *
 * 数据是服务端从这场会话自己的记录里读出来的（`GET /api/workbench/sessions/{sid}/files`），
 * 这一侧不自算、不猜：路径、新建还是改、动过几次都照实摆。
 *
 * 三件事决定了它长这样：
 *
 * 1. **按目录归组。** 一场会话改过的文件常常一个目录连着好几个，平铺开来认不出是一摊事。
 *    组头写清目录与「几个改的、几个新建的」，组可以折起来。
 * 2. **它是一份下界，说在明处。** 经 shell 命令改的文件哪一家都不留结构化字段，会话工具
 *    自己的临时区也不算。顶上那行说明就写着这句话——不说清，人会拿这份清单当全集用。
 * 3. **点一行开浮窗，不开新页面。** 人是在读记录的中途瞄一眼这个文件，不是去编辑它。
 *    删掉的那一档例外：文件已经不在，点开只会取不到内容，所以它不给按钮。
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { ChevronDown, ChevronRight, Info, Loader2 } from 'lucide-react';
import type { SessionFileAction, SessionFileRow } from '@/types/api';
import { baseOf, dirOf, langOf, withTilde } from './filePaths';
import { FILE_BADGE } from './fileBadge';

/** 一行盒子的公共外框；能不能点是另一回事（删掉的那些点不开）。 */
const ROW =
  'flex w-full items-center gap-2.5 border-t border-border-color px-3 py-[6px] text-left text-[12.5px] text-text-secondary';

export interface SessionFilesProps {
  /** 这份清单。`null` 是还没取（这一档没打开过），空数组是取了、这一场确实没动过文件。 */
  files: SessionFileRow[] | null;
  loading: boolean;
  error: string | null;
  /** 点开第几个（在下发过来的那一整份里的下标）——浮窗按它翻上一个／下一个。 */
  onOpen: (index: number) => void;
  onReload: () => void;
}

interface Group {
  dir: string;
  /** `index` 是在**整份**清单里的位置，不是组内位置：浮窗的「3 / 8」与 ‹ › 按整份走。 */
  rows: { file: SessionFileRow; index: number }[];
}

/** 按下标顺序分组：同一目录的收在一组，组的先后照目录第一次出现的位置，不重排。 */
export function groupByDirectory(files: SessionFileRow[]): Group[] {
  const groups: Group[] = [];
  const at = new Map<string, Group>();
  files.forEach((file, index) => {
    const dir = dirOf(file.path);
    let group = at.get(dir);
    if (!group) {
      group = { dir, rows: [] };
      at.set(dir, group);
      groups.push(group);
    }
    group.rows.push({ file, index });
  });
  return groups;
}

/** 组头上那句「几个改的、几个新建的、几个删的」里的一档，按这个顺序排。 */
const MIX_ORDER: SessionFileAction[] = ['modified', 'created', 'deleted'];

/**
 * 组头那句组合。只写这一组里真有的档次——「0 个新建」占着地方又什么都没说；删的那档因此
 * 在没删过的组里根本不出现，不必再维护一句「带删的版本」。
 */
export function mixLabel(rows: Group['rows'], t: TFunction): string {
  const n: Record<SessionFileAction, number> = { created: 0, modified: 0, deleted: 0 };
  for (const row of rows) n[row.file.action] += 1;
  return MIX_ORDER.filter((action) => n[action] > 0)
    .map((action) => t(`workbench.files.mix.${action}`, { n: n[action] }))
    .join(' · ');
}

export default function SessionFiles({
  files,
  loading,
  error,
  onOpen,
  onReload,
}: SessionFilesProps) {
  const { t } = useTranslation();
  /** 折起来的目录。默认都铺开——人点这一档就是要看文件。 */
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const groups = useMemo(() => groupByDirectory(files ?? []), [files]);

  const note = (
    <div className="flex items-start gap-2 rounded-[8px] border border-border-color bg-bg-secondary px-3 py-2 text-[11.5px] leading-relaxed text-text-muted">
      <Info size={13} className="mt-[2px] shrink-0 text-text-dim" />
      <span>
        <b className="font-medium text-text-secondary">
          {t('workbench.files.noteCount', { n: files?.length ?? 0 })}
        </b>{' '}
        {t('workbench.files.noteBody')}
      </span>
    </div>
  );

  return (
    <div
      data-testid="session-files"
      className="h-full min-h-0 overflow-y-auto pb-10 pl-4 pr-4 pt-4"
    >
      {/* 文件清单跟它盖住的那条记录流同宽、同左边距：同一块地方，换档不该让左边线跳一下。 */}
      <div className="flex w-full min-w-0 flex-col gap-3">
        {error ? (
          <div className="flex items-center gap-3 rounded-[8px] bg-bg-subtle px-3 py-2 text-[12px] text-text-secondary">
            <span className="min-w-0 flex-1">{error}</span>
            <button
              type="button"
              data-testid="session-files-retry"
              onClick={onReload}
              className="shrink-0 rounded-[6px] px-2 py-[3px] text-[11px] text-text-muted hover:bg-bg-hover hover:text-text-primary"
            >
              {t('workbench.files.retry')}
            </button>
          </div>
        ) : null}

        {loading && files === null ? (
          <p
            data-testid="session-files-loading"
            className="flex items-center justify-center gap-2 py-16 text-[13px] text-text-muted"
          >
            <Loader2 size={16} className="animate-spin" />
            {t('workbench.files.loading')}
          </p>
        ) : null}

        {/* 取回来了、这一场确实没动过文件：把「没有」说清楚，而不是摆一片空白。 */}
        {!loading && !error && files !== null && files.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-16 text-text-muted">
            <p className="text-[13px]">{t('workbench.files.empty')}</p>
            <p className="max-w-[420px] text-center text-[12px] leading-relaxed">
              {t('workbench.files.emptyHint')}
            </p>
          </div>
        ) : null}

        {files !== null && files.length ? (
          <>
            {note}
            {groups.map((group) => {
              const shut = collapsed[group.dir] === true;
              return (
                <div
                  key={group.dir || '(no directory)'}
                  data-testid="session-files-group"
                  className="overflow-hidden rounded-[10px] border border-border-color"
                >
                  <button
                    type="button"
                    data-testid="session-files-group-head"
                    aria-expanded={!shut}
                    onClick={() =>
                      setCollapsed((prev) => ({ ...prev, [group.dir]: !shut }))
                    }
                    className="flex w-full items-center gap-2 bg-bg-hover px-3 py-[7px] text-left text-[12px] hover:bg-bg-active"
                  >
                    {shut ? (
                      <ChevronRight size={13} className="shrink-0 text-text-muted" />
                    ) : (
                      <ChevronDown size={13} className="shrink-0 text-text-muted" />
                    )}
                    <span
                      className="min-w-0 flex-1 truncate font-mono text-text-secondary"
                      title={group.dir || t('workbench.files.noDirectory')}
                    >
                      {group.dir ? withTilde(group.dir) : t('workbench.files.noDirectory')}
                    </span>
                    <span className="shrink-0 font-mono text-text-muted">{group.rows.length}</span>
                    <span className="shrink-0 text-[11px] text-text-muted">
                      {mixLabel(group.rows, t)}
                    </span>
                  </button>

                  {shut
                    ? null
                    : group.rows.map(({ file, index }) => {
                        const badge = FILE_BADGE[file.action];
                        const gone = file.action === 'deleted';
                        const body = (
                          <>
                            {/* 三档只差一个字母、一档底色。颜色从来不是唯一通道：字母、
                                组头上那句「几个改的、几个新建的、几个删的」都在说同一件事。 */}
                            <span
                              data-testid={`session-files-badge-${file.action}`}
                              title={t(badge.label)}
                              className={`inline-flex h-[15px] w-[15px] shrink-0 items-center justify-center rounded-[4px] font-mono text-[10px] font-semibold ${badge.tone}`}
                            >
                              {badge.letter}
                            </span>
                            <span
                              className={`min-w-0 truncate font-mono text-[11.5px] ${
                                gone ? 'text-text-dim line-through' : ''
                              }`}
                            >
                              {baseOf(file.path)}
                            </span>
                            <span className="ml-auto flex shrink-0 items-center gap-2 font-mono text-[11px] text-text-muted">
                              {/* 只动过一次的不写次数：满眼都是「×1」等于没说。 */}
                              {file.count > 1 ? (
                                <span title={t('workbench.files.touched', { n: file.count })}>
                                  ×{file.count}
                                </span>
                              ) : null}
                              {langOf(file.path) ? <span>{langOf(file.path)}</span> : null}
                            </span>
                          </>
                        );
                        // 删掉的那档点不开：文件已经不在，浮窗只会报「取不到」。留一行说明，
                        // 不给一个点了没反应的按钮。
                        return gone ? (
                          <div
                            key={file.path}
                            data-testid="session-files-row"
                            data-deleted="true"
                            title={`${file.path} — ${t('workbench.files.deletedHint')}`}
                            className={`${ROW} cursor-default`}
                          >
                            {body}
                          </div>
                        ) : (
                          <button
                            key={file.path}
                            type="button"
                            data-testid="session-files-row"
                            title={file.path}
                            onClick={() => onOpen(index)}
                            className={`${ROW} hover:bg-bg-hover hover:text-text-primary`}
                          >
                            {body}
                          </button>
                        );
                      })}
                </div>
              );
            })}
            <div className="h-2" />
          </>
        ) : null}
      </div>
    </div>
  );
}
