/**
 * Community Recipe Card Component
 *
 * Displays a single community recipe with install/update actions.
 *
 * 一屏二十多张卡，每张都挂一颗实心绿「安装」或实心红「卸载」，整页都在喊。现在按
 * 「这张卡处在哪一步」给按钮分量：
 * - 没装：描边的「安装」，是这张卡唯一要做的事，但不必比页头的主按钮更响；
 * - 有更新：琥珀描边的「更新」，这是唯一需要人留意的一档；
 * - 装好了：底栏左侧一个灰色「已安装」记号，卸载退成灰字，悬停时才露出红色。
 * 类型徽章一律中性灰：工作流与原子是分类，不是状态，不该借绿色和琥珀色。
 */

import { useTranslation } from 'react-i18next';
import { Check, Download, RefreshCw, ExternalLink, Trash2 } from 'lucide-react';
import type { CommunityRecipeItem } from '@/types/pywebview';

interface CommunityRecipeCardProps {
  recipe: CommunityRecipeItem;
  onInstall: (name: string, force: boolean) => Promise<void>;
  onUpdate: (name: string) => Promise<void>;
  onUninstall: (name: string) => Promise<void>;
  isInstalling: boolean;
}

export default function CommunityRecipeCard({
  recipe,
  onInstall,
  onUpdate,
  onUninstall,
  isInstalling,
}: CommunityRecipeCardProps) {
  const { t } = useTranslation();
  const spinner = <RefreshCw size={14} className="animate-spin" />;

  return (
    <div className="rl-card rl-card--static">
      {/* Header: Name + Link */}
      <span className="rl-card-head">
        <span className="rl-card-title">{recipe.name}</span>
        {recipe.url && (
          <a
            href={recipe.url}
            target="_blank"
            rel="noopener noreferrer"
            className="rl-card-link"
            title="View on GitHub"
            aria-label="View on GitHub"
          >
            <ExternalLink size={13} />
          </a>
        )}
      </span>

      {/* Metadata: Version + Type + Runtime */}
      <span className="rl-card-id">
        {recipe.version && `v${recipe.version}`}
        {recipe.installed && recipe.installed_version && recipe.has_update && (
          <span className="rl-card-outdated"> (local: v{recipe.installed_version})</span>
        )}
        {[recipe.type, recipe.runtime].filter(Boolean).map((part) => ` · ${part}`)}
      </span>

      {/* Description */}
      {recipe.description && <span className="rl-card-desc">{recipe.description}</span>}

      {/* Tags */}
      {recipe.tags.length > 0 && (
        <span className="rl-tags">
          {recipe.tags.slice(0, 5).map((tag) => (
            <span key={tag} className="rl-tag">
              {tag}
            </span>
          ))}
          {recipe.tags.length > 5 && <span className="rl-tag-more">+{recipe.tags.length - 5}</span>}
        </span>
      )}

      {/* Action row */}
      <span className="rl-card-foot">
        {recipe.installed && !recipe.has_update ? (
          <>
            <span className="rl-installed">
              <Check size={13} />
              {t('recipes.installed')}
            </span>
            <button
              type="button"
              className="rl-btn rl-btn--quiet-danger"
              onClick={() => onUninstall(recipe.name)}
              disabled={isInstalling}
            >
              {isInstalling ? spinner : <Trash2 size={14} />}
              <span>{t('recipes.uninstall')}</span>
            </button>
          </>
        ) : recipe.installed ? (
          <>
            <span />
            <button
              type="button"
              className="rl-btn rl-btn--warning-outline"
              onClick={() => onUpdate(recipe.name)}
              disabled={isInstalling}
            >
              {isInstalling ? spinner : <RefreshCw size={14} />}
              <span>{t('recipes.update')}</span>
            </button>
          </>
        ) : (
          <>
            <span />
            <button
              type="button"
              className="rl-btn"
              onClick={() => onInstall(recipe.name, false)}
              disabled={isInstalling}
            >
              {isInstalling ? spinner : <Download size={14} />}
              <span>{t('recipes.install')}</span>
            </button>
          </>
        )}
      </span>
    </div>
  );
}
