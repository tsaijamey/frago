import type { TFunction } from 'i18next';
import { ExternalLink, Lightbulb, Link2, Code, GitBranch, ArrowRight, Workflow, Box } from 'lucide-react';
import { openPath } from '@/api';
import type { RecipeDetail as RecipeDetailType, ToastType } from '@/types/pywebview';
import CollapsibleSection from './CollapsibleSection';

interface RecipeOverviewProps {
  recipe: RecipeDetailType;
  showToast: (message: string, type: ToastType) => void;
  t: TFunction;
}

// Left column — what the recipe is and what it does.
export default function RecipeOverview({ recipe, showToast, t }: RecipeOverviewProps) {
  const hasUseCases = recipe.use_cases && recipe.use_cases.length > 0;
  const hasDependencies = recipe.dependencies && recipe.dependencies.length > 0;
  const hasFlow = recipe.flow && recipe.flow.length > 0;

  const prettyName = recipe.name.replace(/_/g, ' ');
  const techMeta = [recipe.source, recipe.runtime, recipe.output_targets?.join('/')]
    .filter(Boolean).join(' · ');
  const HeroIcon = recipe.category === 'workflow' ? Workflow : Box;

  return (
    <div className="rd-main">
      {/* Hero — human title first, technical id demoted to a footnote */}
      <div className="flex items-start gap-4">
        <div className="rd-hero-icon">
          <HeroIcon size={22} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="text-2xl font-bold text-[var(--text-primary)] capitalize tracking-tight">
              {prettyName}
            </h2>
            {recipe.version && (
              <span className="text-xs px-2 py-0.5 rounded bg-[var(--bg-subtle)] text-[var(--text-muted)] font-mono">
                v{recipe.version}
              </span>
            )}
            <span className={`text-xs px-2 py-0.5 rounded-full ${
              recipe.category === 'atomic'
                ? 'bg-[var(--status-running-bg)] text-[var(--accent-warning)]'
                : 'bg-[var(--status-completed-bg)] text-[var(--accent-success)]'
            }`}>
              {recipe.category === 'atomic' ? t('recipes.atomic') : t('recipes.workflow')}
            </span>
          </div>
          {recipe.description && (
            <p className="text-sm text-[var(--text-secondary)] mt-2 leading-relaxed">
              {recipe.description}
            </p>
          )}
          <div className="flex items-center gap-1.5 mt-2 text-xs text-[var(--text-muted)] font-mono flex-wrap">
            <span>{recipe.name}</span>
            {techMeta && <span>· {techMeta}</span>}
          </div>
          {recipe.script_path && (
            <button
              type="button"
              className="font-mono text-xs break-all text-left text-[var(--text-muted)] hover:text-[var(--accent-primary)] hover:underline inline-flex items-start gap-1 mt-1.5"
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
          )}
          {recipe.tags.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-3">
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
      </div>

      {/* What this recipe does */}
      <section className="rd-step">
        <header className="rd-step-head">
          <Lightbulb size={16} className="text-[var(--accent-primary)]" />
          <span>{t('recipes.whatItDoes')}</span>
        </header>
        <div className="rd-step-body space-y-3">
          {hasUseCases ? (
            <ul className="space-y-2">
              {recipe.use_cases!.map((useCase, index) => (
                <li key={index} className="flex items-start gap-2 text-sm text-[var(--text-secondary)]">
                  <span className="text-[var(--accent-primary)] mt-0.5">•</span>
                  <span>{useCase}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-[var(--text-secondary)]">
              {recipe.description || t('recipes.noDescription')}
            </p>
          )}

          {hasFlow && (
            <div className="space-y-2">
              <div className="flex items-center gap-1.5 flex-wrap text-xs text-[var(--text-secondary)]">
                <GitBranch size={13} className="text-[var(--accent-primary)]" />
                {recipe.flow!.map((step, i) => (
                  <span key={step.step} className="flex items-center gap-1.5">
                    <span className="font-mono text-[var(--text-primary)]">{step.action}</span>
                    {i < recipe.flow!.length - 1 && <span className="text-[var(--text-muted)]">→</span>}
                  </span>
                ))}
                <span className="text-[var(--text-muted)]">（{t('recipes.stepCount', { count: recipe.flow!.length })}）</span>
              </div>
              <CollapsibleSection
                title={t('recipes.viewFullFlow')}
                icon={<GitBranch size={16} className="text-[var(--accent-primary)]" />}
                defaultExpanded={true}
              >
                <div className="space-y-3">
                  {recipe.flow!.map((step, index) => (
                    <div key={step.step} className="flex items-start gap-3">
                      <div className="flex-shrink-0 w-8 h-8 rounded-full bg-[var(--text-primary)] text-[var(--bg-base)] flex items-center justify-center text-sm font-medium">
                        {step.step}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-mono text-sm text-[var(--text-primary)] font-medium">
                            {step.action}
                          </span>
                          {step.recipe && (
                            <span className="text-xs px-2 py-0.5 rounded bg-[var(--accent-success)]/20 text-[var(--accent-success)]">
                              {t('recipes.callsRecipe')}: {step.recipe}
                            </span>
                          )}
                        </div>
                        <p className="text-sm text-[var(--text-secondary)] mt-1">{step.description}</p>
                        {(step.inputs?.length || step.outputs?.length) && (
                          <div className="flex flex-wrap gap-2 mt-2 text-xs">
                            {step.inputs?.map((input, i) => (
                              <span key={i} className="px-2 py-0.5 rounded bg-[var(--bg-subtle)] text-[var(--text-muted)]">
                                ← {input.source}
                              </span>
                            ))}
                            {step.outputs?.map((output, i) => (
                              <span key={i} className="px-2 py-0.5 rounded bg-[var(--accent-primary)]/10 text-[var(--accent-primary)]">
                                → {output.name}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                      {index < recipe.flow!.length - 1 && (
                        <div className="flex-shrink-0 self-center text-[var(--text-muted)]">
                          <ArrowRight size={16} className="rotate-90" />
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </CollapsibleSection>
            </div>
          )}
        </div>
      </section>

      {/* Advanced — dependencies & source, collapsed by default */}
      {hasDependencies && (
        <CollapsibleSection
          title={t('recipes.dependencies')}
          icon={<Link2 size={16} className="text-[var(--accent-success)]" />}
          defaultExpanded={false}
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
  );
}
