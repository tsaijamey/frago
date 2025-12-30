import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useAppStore } from '@/stores/appStore';
import { getRecipeDetail, runRecipe, openPath } from '@/api';
import LoadingSpinner from '@/components/ui/LoadingSpinner';
import { ExternalLink, ChevronDown, ChevronRight, Lightbulb, Settings, Link2, Code } from 'lucide-react';
import type { RecipeDetail as RecipeDetailType } from '@/types/pywebview';

interface CollapsibleSectionProps {
  title: string;
  icon: React.ReactNode;
  defaultExpanded?: boolean;
  children: React.ReactNode;
}

function CollapsibleSection({ title, icon, defaultExpanded = true, children }: CollapsibleSectionProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  return (
    <div className="border border-[var(--border-color)] rounded-lg overflow-hidden">
      <button
        type="button"
        className="flex items-center gap-2 w-full text-left px-4 py-3 bg-[var(--bg-subtle)] hover:bg-[var(--bg-hover)] transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? (
          <ChevronDown size={16} className="text-[var(--text-muted)]" />
        ) : (
          <ChevronRight size={16} className="text-[var(--text-muted)]" />
        )}
        {icon}
        <span className="font-medium text-[var(--text-primary)]">{title}</span>
      </button>
      {expanded && (
        <div className="p-4 border-t border-[var(--border-color)]">
          {children}
        </div>
      )}
    </div>
  );
}

export default function RecipeDetail() {
  const { t } = useTranslation();
  const { currentRecipeName, switchPage, showToast } = useAppStore();
  const [recipe, setRecipe] = useState<RecipeDetailType | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRunning, setIsRunning] = useState(false);

  useEffect(() => {
    if (!currentRecipeName) return;

    setIsLoading(true);
    getRecipeDetail(currentRecipeName)
      .then(setRecipe)
      .catch((err) => {
        console.error('Failed to load recipe:', err);
        showToast(t('recipes.failedToLoad'), 'error');
      })
      .finally(() => setIsLoading(false));
  }, [currentRecipeName, showToast, t]);

  const handleRun = async () => {
    if (!currentRecipeName || isRunning) return;

    setIsRunning(true);
    try {
      const result = await runRecipe(currentRecipeName);
      if (result.status === 'ok') {
        showToast(t('recipes.executedSuccess'), 'success');
      } else {
        showToast(result.error || t('recipes.executionFailed'), 'error');
      }
    } catch (err) {
      console.error('Failed to run recipe:', err);
      showToast(t('recipes.failedToExecute'), 'error');
    } finally {
      setIsRunning(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  if (!recipe) {
    return (
      <div className="text-[var(--text-muted)] text-center py-scaled-8">
        {t('recipes.recipeNotExist')}
      </div>
    );
  }

  const hasInputs = recipe.inputs && Object.keys(recipe.inputs).length > 0;
  const hasUseCases = recipe.use_cases && recipe.use_cases.length > 0;
  const hasDependencies = recipe.dependencies && recipe.dependencies.length > 0;

  return (
    <div className="flex flex-col gap-4 h-full overflow-hidden p-4">
      {/* Back button */}
      <button
        type="button"
        className="btn btn-ghost self-start shrink-0"
        onClick={() => switchPage('recipes')}
      >
        ← {t('recipes.backToRecipeList')}
      </button>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto space-y-4">
        {/* Header card */}
        <div className="card">
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-3">
                <h2 className="text-lg font-medium text-[var(--text-primary)] break-words">
                  {recipe.name}
                </h2>
                {recipe.version && (
                  <span className="text-xs px-2 py-0.5 rounded bg-[var(--bg-subtle)] text-[var(--text-muted)]">
                    v{recipe.version}
                  </span>
                )}
              </div>
              {recipe.description && (
                <p className="text-sm text-[var(--text-secondary)] mt-2">
                  {recipe.description}
                </p>
              )}
            </div>
            <button
              type="button"
              className="btn btn-primary shrink-0"
              onClick={handleRun}
              disabled={isRunning}
            >
              {isRunning ? <LoadingSpinner size="sm" /> : t('recipes.run')}
            </button>
          </div>

          {/* Metadata grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4 text-sm">
            <div>
              <span className="text-[var(--text-muted)] block text-xs">{t('recipes.type')}</span>
              <span className={`inline-block mt-1 px-2 py-0.5 rounded text-xs ${
                recipe.category === 'atomic'
                  ? 'bg-[var(--status-running-bg)] text-[var(--accent-warning)]'
                  : 'bg-[var(--status-completed-bg)] text-[var(--accent-success)]'
              }`}>
                {recipe.category === 'atomic' ? t('recipes.atomic') : t('recipes.workflow')}
              </span>
            </div>
            <div>
              <span className="text-[var(--text-muted)] block text-xs">{t('recipes.source')}</span>
              <span className="text-[var(--text-primary)] mt-1 block">{recipe.source || '-'}</span>
            </div>
            <div>
              <span className="text-[var(--text-muted)] block text-xs">{t('recipes.runtime')}</span>
              <span className="text-[var(--text-primary)] mt-1 block">{recipe.runtime || '-'}</span>
            </div>
            {recipe.output_targets && recipe.output_targets.length > 0 && (
              <div>
                <span className="text-[var(--text-muted)] block text-xs">{t('recipes.output')}</span>
                <span className="text-[var(--text-primary)] mt-1 block">
                  {recipe.output_targets.join(', ')}
                </span>
              </div>
            )}
          </div>

          {/* Path */}
          {recipe.script_path && (
            <div className="mt-4 pt-4 border-t border-[var(--border-color)]">
              <button
                type="button"
                className="font-mono text-xs break-all text-left text-[var(--accent-primary)] hover:underline inline-flex items-start gap-1"
                onClick={async () => {
                  const result = await openPath(recipe.script_path!, true);
                  if (result.status !== 'ok') {
                    showToast(result.error || t('recipes.unableToOpenPath'), 'error');
                  }
                }}
                title={t('recipes.showInFileManager')}
              >
                {recipe.script_path}
                <ExternalLink size={12} className="shrink-0 mt-0.5" />
              </button>
            </div>
          )}

          {/* Tags */}
          {recipe.tags.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-4">
              {recipe.tags.map((tag) => (
                <span
                  key={tag}
                  className="text-xs bg-[var(--bg-subtle)] text-[var(--text-muted)] px-2 py-0.5 rounded"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Use Cases */}
        {hasUseCases && (
          <CollapsibleSection
            title={t('recipes.useCases')}
            icon={<Lightbulb size={16} className="text-[var(--accent-warning)]" />}
          >
            <ul className="space-y-2">
              {recipe.use_cases!.map((useCase, index) => (
                <li key={index} className="flex items-start gap-2 text-sm text-[var(--text-secondary)]">
                  <span className="text-[var(--accent-primary)] mt-0.5">•</span>
                  <span>{useCase}</span>
                </li>
              ))}
            </ul>
          </CollapsibleSection>
        )}

        {/* Parameters */}
        {hasInputs && (
          <CollapsibleSection
            title={t('recipes.parameters')}
            icon={<Settings size={16} className="text-[var(--accent-primary)]" />}
          >
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[var(--border-color)]">
                    <th className="text-left py-2 pr-4 text-[var(--text-muted)] font-medium">{t('recipes.name')}</th>
                    <th className="text-left py-2 pr-4 text-[var(--text-muted)] font-medium">{t('recipes.type')}</th>
                    <th className="text-left py-2 pr-4 text-[var(--text-muted)] font-medium">{t('recipes.required')}</th>
                    <th className="text-left py-2 pr-4 text-[var(--text-muted)] font-medium">{t('recipes.default')}</th>
                    <th className="text-left py-2 text-[var(--text-muted)] font-medium">{t('recipes.description')}</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(recipe.inputs!).map(([name, input]) => (
                    <tr key={name} className="border-b border-[var(--border-color)] last:border-0">
                      <td className="py-2 pr-4 font-mono text-[var(--accent-primary)]">{name}</td>
                      <td className="py-2 pr-4 text-[var(--text-secondary)]">{input.type}</td>
                      <td className="py-2 pr-4">
                        {input.required ? (
                          <span className="text-[var(--accent-error)]">{t('recipes.yes')}</span>
                        ) : (
                          <span className="text-[var(--text-muted)]">{t('recipes.no')}</span>
                        )}
                      </td>
                      <td className="py-2 pr-4 font-mono text-xs text-[var(--text-muted)]">
                        {input.default !== undefined ? String(input.default) : '-'}
                      </td>
                      <td className="py-2 text-[var(--text-secondary)]">{input.description || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CollapsibleSection>
        )}

        {/* Dependencies */}
        {hasDependencies && (
          <CollapsibleSection
            title={t('recipes.dependencies')}
            icon={<Link2 size={16} className="text-[var(--accent-success)]" />}
          >
            <div className="flex flex-wrap gap-2">
              {recipe.dependencies!.map((dep) => (
                <span
                  key={dep}
                  className="px-3 py-1 rounded-full text-sm bg-[var(--bg-subtle)] text-[var(--text-primary)] border border-[var(--border-color)]"
                >
                  {dep}
                </span>
              ))}
            </div>
          </CollapsibleSection>
        )}

        {/* Source Code */}
        {recipe.source_code && (
          <CollapsibleSection
            title={t('recipes.sourceCode')}
            icon={<Code size={16} className="text-[var(--text-muted)]" />}
            defaultExpanded={false}
          >
            <pre className="bg-[var(--bg-tertiary)] p-4 rounded text-xs font-mono overflow-auto max-h-96 whitespace-pre-wrap break-words">
              {recipe.source_code}
            </pre>
          </CollapsibleSection>
        )}
      </div>
    </div>
  );
}
