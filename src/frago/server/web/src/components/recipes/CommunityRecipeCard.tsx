/**
 * Community Recipe Card Component
 *
 * Displays a single community recipe with install/update actions.
 */

import { useTranslation } from 'react-i18next';
import { Check, Download, RefreshCw, ExternalLink } from 'lucide-react';
import type { CommunityRecipeItem } from '@/types/pywebview';

interface CommunityRecipeCardProps {
  recipe: CommunityRecipeItem;
  onInstall: (name: string, force: boolean) => Promise<void>;
  onUpdate: (name: string) => Promise<void>;
  isInstalling: boolean;
}

export default function CommunityRecipeCard({
  recipe,
  onInstall,
  onUpdate,
  isInstalling,
}: CommunityRecipeCardProps) {
  const { t } = useTranslation();

  return (
    <div className="card hover:border-[var(--accent-primary)] transition-colors">
      {/* Header: Name + Version + Link */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium text-[var(--text-primary)] truncate">
              {recipe.name}
            </span>
            {recipe.url && (
              <a
                href={recipe.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[var(--text-muted)] hover:text-[var(--accent-primary)] shrink-0"
                title="View on GitHub"
              >
                <ExternalLink size={14} />
              </a>
            )}
          </div>
          {recipe.version && (
            <span className="text-xs text-[var(--text-muted)]">
              v{recipe.version}
              {recipe.installed && recipe.installed_version && recipe.has_update && (
                <span className="ml-1 text-[var(--accent-warning)]">
                  (local: v{recipe.installed_version})
                </span>
              )}
            </span>
          )}
        </div>

        {/* Action Button */}
        <div className="shrink-0">
          {recipe.installed ? (
            recipe.has_update ? (
              <button
                type="button"
                className="btn btn-sm btn-warning flex items-center gap-1"
                onClick={() => onUpdate(recipe.name)}
                disabled={isInstalling}
              >
                {isInstalling ? (
                  <RefreshCw size={14} className="animate-spin" />
                ) : (
                  <RefreshCw size={14} />
                )}
                <span>{t('recipes.update')}</span>
              </button>
            ) : (
              <span className="inline-flex items-center gap-1 text-xs text-[var(--accent-success)] px-2 py-1 bg-[var(--status-completed-bg)] rounded">
                <Check size={14} />
                {t('recipes.installed')}
              </span>
            )
          ) : (
            <button
              type="button"
              className="btn btn-sm btn-primary flex items-center gap-1"
              onClick={() => onInstall(recipe.name, false)}
              disabled={isInstalling}
            >
              {isInstalling ? (
                <RefreshCw size={14} className="animate-spin" />
              ) : (
                <Download size={14} />
              )}
              <span>{t('recipes.install')}</span>
            </button>
          )}
        </div>
      </div>

      {/* Description */}
      {recipe.description && (
        <p className="text-sm text-[var(--text-secondary)] mt-2 line-clamp-2">
          {recipe.description}
        </p>
      )}

      {/* Metadata: Type + Runtime */}
      <div className="flex items-center gap-2 mt-3">
        <span
          className={`text-xs px-2 py-0.5 rounded ${
            recipe.type === 'workflow'
              ? 'bg-[var(--status-completed-bg)] text-[var(--accent-success)]'
              : 'bg-[var(--status-running-bg)] text-[var(--accent-warning)]'
          }`}
        >
          {recipe.type}
        </span>
        {recipe.runtime && (
          <span className="text-xs text-[var(--text-muted)]">
            {recipe.runtime}
          </span>
        )}
      </div>

      {/* Tags */}
      {recipe.tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2">
          {recipe.tags.slice(0, 5).map((tag) => (
            <span
              key={tag}
              className="text-xs bg-[var(--bg-subtle)] text-[var(--text-muted)] px-2 py-0.5 rounded"
            >
              {tag}
            </span>
          ))}
          {recipe.tags.length > 5 && (
            <span className="text-xs text-[var(--text-muted)]">
              +{recipe.tags.length - 5}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
