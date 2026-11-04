import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { X, Wand2 } from 'lucide-react';
import { forgeRecipe } from '@/api/client';
import { usePageStore } from '@/stores/pageStore';

interface RecipeForgeModalProps {
  onClose: () => void;
}

/**
 * 「创建配方」：人用自己的话写需求，勾不勾「需要界面」，点开始。
 *
 * 点下去之后发生的事在服务端：起一场隐藏的「导演」会话，导演指挥虚拟桌面——worker
 * 在桌面终端里写配方，配方页面在桌面浏览器里长出来。这里只负责把桌面开成一扇独立
 * 窗口（像浏览器的 APP 模式），窗口里带一条输入行，人可以一边看一边追加需求。
 */
export default function RecipeForgeModal({ onClose }: RecipeForgeModalProps) {
  const { t } = useTranslation();
  const [requirement, setRequirement] = useState('');
  const [page, setPage] = useState(true);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = requirement.trim().length > 0 && !busy;

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      const result = await forgeRecipe({
        requirement: requirement.trim(),
        page,
        name: name.trim() || undefined,
      });
      // 虚拟桌面常驻在左侧菜单 desktop 项下：带上导演会话编号直接切过去，不再另开浏览器窗口。
      usePageStore.getState().switchPage('desktop', result.session_id);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="sa-modal-overlay" onClick={onClose}>
      <div
        className="recipe-run-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-labelledby="recipe-forge-title"
      >
        <div className="recipe-run-modal-header">
          <div>
            <h3 id="recipe-forge-title" className="recipe-run-modal-title flex items-center gap-2">
              <Wand2 size={18} />
              {t('recipes.forge.title')}
            </h3>
            <p className="text-sm text-[var(--text-secondary)] mt-1">{t('recipes.forge.intro')}</p>
          </div>
          <button type="button" className="sa-modal-close" onClick={onClose} aria-label={t('common.close')}>
            <X size={16} />
          </button>
        </div>

        <label className="block text-sm text-[var(--text-secondary)] mb-1" htmlFor="recipe-forge-requirement">
          {t('recipes.forge.requirementLabel')}
        </label>
        <textarea
          id="recipe-forge-requirement"
          className="w-full rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] text-[var(--text-primary)] p-3 text-sm"
          rows={7}
          autoFocus
          placeholder={t('recipes.forge.requirementPlaceholder')}
          value={requirement}
          onChange={(e) => setRequirement(e.target.value)}
        />

        <div className="flex flex-wrap items-center gap-4 mt-3">
          <label className="flex items-center gap-2 text-sm text-[var(--text-primary)] cursor-pointer">
            <input type="checkbox" checked={page} onChange={(e) => setPage(e.target.checked)} />
            {t('recipes.forge.needPage')}
          </label>
          <input
            type="text"
            className="flex-1 min-w-[200px] rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] text-[var(--text-primary)] px-3 py-1.5 text-sm font-mono"
            placeholder={t('recipes.forge.namePlaceholder')}
            value={name}
            onChange={(e) => setName(e.target.value)}
            spellCheck={false}
          />
        </div>
        <p className="text-xs text-[var(--text-muted)] mt-2">
          {page ? t('recipes.forge.pageHint') : t('recipes.forge.noPageHint')}
        </p>

        {error && (
          <div className="mt-3 text-sm text-[var(--accent-error)]" role="alert">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-2 mt-4">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            {t('common.cancel')}
          </button>
          <button type="button" className="btn btn-primary" onClick={submit} disabled={!canSubmit}>
            {busy ? t('recipes.forge.starting') : t('recipes.forge.start')}
          </button>
        </div>
      </div>
    </div>
  );
}
