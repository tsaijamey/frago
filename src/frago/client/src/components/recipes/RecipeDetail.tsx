import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useAppStore } from '@/stores/appStore';
import { getRecipeDetail, runRecipe, runRecipeAsync, openPath, getRecipeSecrets } from '@/api';
import LoadingSpinner from '@/components/ui/LoadingSpinner';
import { ExternalLink, ChevronDown, ChevronRight, Lightbulb, Link2, Code, Key, GitBranch, ArrowRight, Check, X, Workflow, Box, Play } from 'lucide-react';
import type { RecipeDetail as RecipeDetailType, RecipeSecretsResponse, RecipeInput } from '@/types/pywebview';
import RecipeSecretsModal from './RecipeSecretsModal';

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
  const [formValues, setFormValues] = useState<Record<string, unknown>>({});
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({});
  const [isInteractiveMode, setIsInteractiveMode] = useState(false);
  const [secretsData, setSecretsData] = useState<RecipeSecretsResponse | null>(null);
  const [showSecretsModal, setShowSecretsModal] = useState(false);

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

  // Initialize form values and interactive mode from recipe
  useEffect(() => {
    if (recipe) {
      const hasInteractiveTag = recipe.tags?.includes('interactive') ?? false;
      setIsInteractiveMode(hasInteractiveTag);

      if (recipe.inputs) {
        const initialValues: Record<string, unknown> = {};
        Object.entries(recipe.inputs).forEach(([name, input]) => {
          if (input.default !== undefined) {
            if (input.type === 'array' || input.type === 'object') {
              initialValues[name] = typeof input.default === 'string'
                ? input.default
                : JSON.stringify(input.default, null, 2);
            } else {
              initialValues[name] = input.default;
            }
          } else {
            initialValues[name] = input.type === 'boolean' ? false : '';
          }
        });
        setFormValues(initialValues);
        setValidationErrors({});
      }
    }
  }, [recipe]);

  // Fetch secrets when recipe loads
  useEffect(() => {
    if (!recipe) return;

    getRecipeSecrets(recipe.name)
      .then(setSecretsData)
      .catch((err) => {
        console.error('Failed to load recipe secrets:', err);
      });
  }, [recipe]);

  const refreshSecrets = async () => {
    if (!recipe) return;
    try {
      const data = await getRecipeSecrets(recipe.name);
      setSecretsData(data);
    } catch (err) {
      console.error('Failed to refresh recipe secrets:', err);
    }
  };

  const validateParameters = (): boolean => {
    if (!recipe?.inputs) return true;

    const errors: Record<string, string> = {};

    Object.entries(recipe.inputs).forEach(([name, input]) => {
      const value = formValues[name];

      if (input.required) {
        if (value === undefined || value === null || value === '') {
          errors[name] = t('recipes.validation.required');
          return;
        }
      }

      if (value === undefined || value === null || value === '') {
        return;
      }

      if (input.type === 'number') {
        if (isNaN(Number(value))) {
          errors[name] = t('recipes.validation.invalidNumber');
        }
      } else if (input.type === 'array' || input.type === 'object') {
        try {
          const parsed = JSON.parse(String(value));
          if (input.type === 'array' && !Array.isArray(parsed)) {
            errors[name] = t('recipes.validation.mustBeArray');
          }
          if (input.type === 'object' && (typeof parsed !== 'object' || Array.isArray(parsed) || parsed === null)) {
            errors[name] = t('recipes.validation.mustBeObject');
          }
        } catch {
          errors[name] = t('recipes.validation.invalidJson');
        }
      }
    });

    setValidationErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const prepareParameters = (): Record<string, unknown> => {
    if (!recipe?.inputs) return {};

    const params: Record<string, unknown> = {};

    Object.entries(recipe.inputs).forEach(([name, input]) => {
      const value = formValues[name];

      if ((value === undefined || value === null || value === '') && !input.required) {
        return;
      }

      switch (input.type) {
        case 'number':
          params[name] = Number(value);
          break;
        case 'boolean':
          params[name] = Boolean(value);
          break;
        case 'array':
        case 'object':
          params[name] = JSON.parse(String(value));
          break;
        default:
          params[name] = value;
      }
    });

    return params;
  };

  const handleFieldChange = (name: string, value: unknown) => {
    setFormValues(prev => ({ ...prev, [name]: value }));
    if (validationErrors[name]) {
      setValidationErrors(prev => {
        const next = { ...prev };
        delete next[name];
        return next;
      });
    }
  };

  const handleRun = async () => {
    if (!currentRecipeName || isRunning) return;

    const missingRequired = secretsData?.fields.filter(
      f => f.required && !f.has_value
    ) ?? [];
    if (missingRequired.length > 0) {
      showToast(t('recipes.missingEnvVars', { count: missingRequired.length }), 'warning');
      return;
    }

    const hasParams = recipe?.inputs && Object.keys(recipe.inputs).length > 0;
    if (hasParams && !validateParameters()) {
      showToast(t('recipes.validation.fixErrors'), 'error');
      return;
    }

    const params = prepareParameters();

    setIsRunning(true);
    try {
      const recipeParams = Object.keys(params).length > 0 ? params : undefined;
      if (isInteractiveMode) {
        await runRecipeAsync(currentRecipeName, recipeParams);
        showToast(t('recipes.startedAsync'), 'success');
      } else {
        const result = await runRecipe(currentRecipeName, recipeParams);
        if (result.status === 'ok') {
          showToast(t('recipes.executedSuccess'), 'success');
        } else {
          showToast(result.error || t('recipes.executionFailed'), 'error');
        }
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
  const hasSecrets = secretsData !== null && secretsData.fields.length > 0;
  const hasFlow = recipe.flow && recipe.flow.length > 0;

  // Run-readiness — drives the prepare banner and gates the Run button
  const requiredParamNames = recipe.inputs
    ? Object.entries(recipe.inputs).filter(([, input]) => input.required).map(([name]) => name)
    : [];
  const missingParams = requiredParamNames.filter((name) => {
    const v = formValues[name];
    return v === undefined || v === null || v === '';
  });
  const missingSecrets = secretsData?.fields.filter(f => f.required && !f.has_value) ?? [];
  const isReady = missingParams.length === 0 && missingSecrets.length === 0;
  const prettyName = recipe.name.replace(/_/g, ' ');
  const techMeta = [recipe.source, recipe.runtime, recipe.output_targets?.join('/')]
    .filter(Boolean).join(' · ');
  const HeroIcon = recipe.category === 'workflow' ? Workflow : Box;

  // Single parameter field (de-alarmed styling: neutral, not warning-yellow)
  const renderParamField = (name: string, input: RecipeInput) => {
    const error = validationErrors[name];
    const inputId = `param-${name}`;
    const errorId = `${inputId}-error`;
    const fieldClass = `w-full px-3 py-2 bg-[var(--bg-base)] border rounded-md text-sm
      text-[var(--text-primary)] placeholder-[var(--text-muted)]
      focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)]
      ${error ? 'border-[var(--accent-error)]' : 'border-[var(--border-color)]'}`;

    return (
      <div key={name} className="flex flex-col gap-1.5">
        <div className="flex items-center gap-2">
          <label htmlFor={inputId} className="font-mono text-sm text-[var(--text-primary)] font-medium">
            {name}
            {input.required && <span className="text-[var(--accent-error)] ml-0.5">*</span>}
          </label>
          <span className="text-xs text-[var(--text-muted)]">{input.type}</span>
        </div>
        {input.description && (
          <p className="text-xs text-[var(--text-secondary)] leading-relaxed">{input.description}</p>
        )}
        {input.type === 'boolean' ? (
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              id={inputId}
              type="checkbox"
              checked={Boolean(formValues[name])}
              onChange={(e) => handleFieldChange(name, e.target.checked)}
              className="w-4 h-4 rounded border-[var(--border-color)] text-[var(--accent-primary)] focus:ring-[var(--accent-primary)]"
            />
            <span className="text-sm text-[var(--text-secondary)]">
              {formValues[name] ? t('recipes.yes') : t('recipes.no')}
            </span>
          </label>
        ) : input.type === 'array' || input.type === 'object' ? (
          <textarea
            id={inputId}
            value={String(formValues[name] ?? '')}
            onChange={(e) => handleFieldChange(name, e.target.value)}
            placeholder={input.type === 'array' ? t('recipes.enterJsonArray') : t('recipes.enterJsonObject')}
            rows={3}
            className={`${fieldClass} font-mono`}
            aria-describedby={error ? errorId : undefined}
            aria-invalid={error ? 'true' : 'false'}
          />
        ) : input.type === 'number' ? (
          <input
            id={inputId}
            type="number"
            value={formValues[name] !== undefined && formValues[name] !== '' ? String(formValues[name]) : ''}
            onChange={(e) => handleFieldChange(name, e.target.value)}
            placeholder={t('recipes.enterValue')}
            className={fieldClass}
            aria-describedby={error ? errorId : undefined}
            aria-invalid={error ? 'true' : 'false'}
          />
        ) : (
          <input
            id={inputId}
            type="text"
            value={String(formValues[name] ?? '')}
            onChange={(e) => handleFieldChange(name, e.target.value)}
            placeholder={t('recipes.enterValue')}
            className={fieldClass}
            aria-describedby={error ? errorId : undefined}
            aria-invalid={error ? 'true' : 'false'}
          />
        )}
        {error && <p id={errorId} className="text-xs text-[var(--accent-error)]">{error}</p>}
      </div>
    );
  };

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

      {/* Two-column: intro on the left, action/parameters panel on the right */}
      <div className="flex-1 overflow-y-auto">
        <div className="rd-layout">
          {/* Left — what it is and what it does */}
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

          {/* Right — run action pinned at top, then parameters form */}
          <aside className="rd-aside">
            <div className="rd-panel">
              {/* Run — top of the right column */}
              <button
                type="button"
                className="btn btn-primary gap-2 w-full justify-center"
                onClick={handleRun}
                disabled={isRunning || !isReady}
              >
                {isRunning ? <LoadingSpinner size="sm" /> : <Play size={16} />}
                {t('recipes.run')}
              </button>

              <label className="flex items-center justify-between gap-2 cursor-pointer" title={t('recipes.interactiveModeHint')}>
                <span className={`text-xs transition-colors ${isInteractiveMode ? 'text-[var(--accent-primary)]' : 'text-[var(--text-muted)]'}`}>
                  {t('recipes.interactiveMode')}
                </span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={isInteractiveMode ? 'true' : 'false'}
                  aria-label={t('recipes.interactiveMode')}
                  onClick={() => setIsInteractiveMode(!isInteractiveMode)}
                  className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors border-2
                    ${isInteractiveMode
                      ? 'bg-[var(--accent-primary)] border-[var(--accent-primary)]'
                      : 'bg-transparent border-[var(--border-color)]'}`}
                >
                  <span
                    className={`inline-block h-3 w-3 rounded-full transition-all duration-200 shadow-sm
                      ${isInteractiveMode
                        ? 'bg-[var(--bg-base)] translate-x-4'
                        : 'bg-[var(--text-muted)] translate-x-0.5'}`}
                  />
                </button>
              </label>

              {/* Readiness */}
              <div className={`rd-ready ${isReady ? 'rd-ready--ok' : 'rd-ready--warn'}`}>
                {isReady ? (
                  <span className="flex items-center gap-2">
                    <Check size={15} />
                    {t('recipes.readyToRun')}
                  </span>
                ) : (
                  <div className="flex flex-col gap-1">
                    {missingSecrets.length > 0 && (
                      <span className="flex items-center gap-1.5">
                        <Key size={14} />
                        {t('recipes.missingSecretsCount', { count: missingSecrets.length })}
                      </span>
                    )}
                    {missingParams.length > 0 && (
                      <span className="flex items-center gap-1.5">
                        <X size={14} />
                        {t('recipes.missingParamsCount', { count: missingParams.length })}
                      </span>
                    )}
                  </div>
                )}
              </div>

              {/* Secrets */}
              {hasSecrets && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium text-[var(--text-secondary)]">{t('recipes.envVars')}</span>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm gap-1"
                      onClick={() => setShowSecretsModal(true)}
                    >
                      <Key size={12} />
                      {t('recipes.manageSecrets')}
                    </button>
                  </div>
                  {secretsData!.is_ref && secretsData!.ref_target && (
                    <div className="text-xs text-[var(--accent-primary)]">
                      {t('recipes.sharedWith')}: {secretsData!.ref_target}
                    </div>
                  )}
                  {secretsData!.fields.map((field) => (
                    <div
                      key={field.key}
                      className={`flex items-center justify-between p-2.5 rounded-md ${
                        field.required && !field.has_value
                          ? 'bg-[var(--accent-error)]/5 border border-[var(--accent-error)]/20'
                          : 'bg-[var(--bg-subtle)]'
                      }`}
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <code className="text-xs font-mono text-[var(--text-primary)] truncate">{field.key}</code>
                          {field.required && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--accent-error)]/20 text-[var(--accent-error)] shrink-0">
                              {t('recipes.required')}
                            </span>
                          )}
                        </div>
                      </div>
                      <div className="ml-2 shrink-0">
                        {field.has_value ? (
                          <Check size={16} className="text-[var(--accent-success)]" />
                        ) : (
                          <X size={16} className="text-[var(--accent-error)]" />
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Parameters */}
              {hasInputs ? (
                <div className="space-y-4 pt-1 border-t border-[var(--border-color)]">
                  <span className="text-xs font-medium text-[var(--text-secondary)] block pt-3">{t('recipes.parameters')}</span>
                  {Object.entries(recipe.inputs!).map(([name, input]) => renderParamField(name, input))}
                </div>
              ) : (
                !hasSecrets && (
                  <p className="text-xs text-[var(--text-muted)]">{t('recipes.noParamsNeeded')}</p>
                )
              )}
            </div>
          </aside>
        </div>
      </div>

      {/* Secrets Configuration Modal */}
      {secretsData && (
        <RecipeSecretsModal
          isOpen={showSecretsModal}
          onClose={() => setShowSecretsModal(false)}
          recipeName={recipe.name}
          secretsData={secretsData}
          onSaved={() => {
            refreshSecrets();
            setShowSecretsModal(false);
            showToast(t('recipes.secretSaved'), 'success');
          }}
        />
      )}
    </div>
  );
}
