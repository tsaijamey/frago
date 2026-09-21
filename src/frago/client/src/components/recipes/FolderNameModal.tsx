/**
 * 建文件夹 / 改文件夹名的那扇小窗。
 *
 * 只问名字，不问 id。问 id 等于要人在起名之外再想一个英文短词，而这个词他此后再也
 * 不会看见——id 由中文名推，推不出来就是 `folder-2` 这种，反正只有命令行会用到它。
 *
 * 中文名必填，英文名可空：界面切到英文时空着的那门回落到中文，总比逼人当场翻译一
 * 个自己都还没想好的名字强。
 *
 * 外壳沿用创建配方那扇窗的类名，不另起一套：同一页上两扇窗长得不一样，人会以为它
 * 们是两种东西。
 */

import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';

interface Props {
  /** 建新文件夹时是空的；改名时是现有的名字。 */
  initialZh?: string;
  initialEn?: string;
  /** 建文件夹时顺带说明这一下会把几张配方放进去。 */
  withCount?: number;
  busy?: boolean;
  error?: string | null;
  onSubmit: (nameZh: string, nameEn: string) => void;
  onClose: () => void;
}

export default function FolderNameModal({
  initialZh = '',
  initialEn = '',
  withCount = 0,
  busy = false,
  error = null,
  onSubmit,
  onClose,
}: Props) {
  const { t } = useTranslation();
  const [zh, setZh] = useState(initialZh);
  const [en, setEn] = useState(initialEn);
  const firstField = useRef<HTMLInputElement>(null);
  const renaming = Boolean(initialZh || initialEn);

  useEffect(() => {
    firstField.current?.focus();
    firstField.current?.select();
  }, []);

  const canSubmit = zh.trim().length > 0 && !busy;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    onSubmit(zh.trim(), en.trim());
  };

  const field = 'w-full rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] '
    + 'text-[var(--text-primary)] px-3 py-1.5 text-sm';

  return (
    // 点遮罩不关窗。这扇窗里有人正在打字，手一滑点到旁边就把刚起的名字连同挑好
    // 的那几张配方一起丢掉，而且丢得没有任何提示。关窗只走右上角的 × 和取消——
    // 两个都是他明确按下去的。
    <div className="sa-modal-overlay" role="presentation">
      <form
        className="recipe-run-modal"
        onSubmit={submit}
        role="dialog"
        aria-modal="true"
        aria-labelledby="folder-name-title"
      >
        <div className="recipe-run-modal-header">
          <h3 id="folder-name-title" className="recipe-run-modal-title">
            {renaming ? t('recipes.folder.rename') : t('recipes.folder.create')}
          </h3>
          <button
            type="button"
            className="sa-modal-close"
            onClick={onClose}
            aria-label={t('common.close')}
          >
            <X size={16} />
          </button>
        </div>

        {withCount > 0 && (
          <p className="text-sm text-[var(--text-secondary)] mb-3">
            {t('recipes.folder.willHold', { count: withCount })}
          </p>
        )}

        <label className="block text-sm text-[var(--text-secondary)] mb-1" htmlFor="folder-name-zh">
          {t('recipes.folder.nameZh')}
        </label>
        <input
          id="folder-name-zh"
          ref={firstField}
          type="text"
          className={field}
          value={zh}
          maxLength={24}
          onChange={(e) => setZh(e.target.value)}
          placeholder={t('recipes.folder.nameZhPlaceholder')}
        />

        <label
          className="block text-sm text-[var(--text-secondary)] mb-1 mt-3"
          htmlFor="folder-name-en"
        >
          {t('recipes.folder.nameEn')}
        </label>
        <input
          id="folder-name-en"
          type="text"
          className={field}
          value={en}
          maxLength={24}
          onChange={(e) => setEn(e.target.value)}
          placeholder={t('recipes.folder.nameEnPlaceholder')}
        />

        {error && (
          <div className="mt-3 text-sm text-[var(--accent-error)]" role="alert">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-2 mt-4">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            {t('common.cancel')}
          </button>
          <button type="submit" className="btn btn-primary" disabled={!canSubmit}>
            {t('common.confirm')}
          </button>
        </div>
      </form>
    </div>
  );
}
