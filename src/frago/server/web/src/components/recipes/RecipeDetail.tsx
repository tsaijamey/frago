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
  const [formValues, setFormValues] = useState<Record<string, unknown>>({});
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({});
  const [isInteractiveMode, setIsInteractiveMode] = useState(false);

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
      // Set interactive mode based on tags
      const hasInteractiveTag = recipe.tags?.includes('interactive') ?? false;
      setIsInteractiveMode(hasInteractiveTag);

      // Initialize form values from defaults
      if (recipe.inputs) {
        const initialValues: Record<string, unknown> = {};
        Object.entries(recipe.inputs).forEach(([name, input]) => {
          if (input.default !== undefined) {
            // For array/object types, stringify the default value for textarea display
            if (input.type === 'array' || input.type === 'object') {
              initialValues[name] = typeof input.default === 'string'
                ? input.default
                : JSON.stringify(input.default, null, 2);
            } else {
              initialValues[name] = input.default;
            }
          } else {
            // Set empty defaults based on type
            initialValues[name] = input.type === 'boolean' ? false : '';
          }
        });
        setFormValues(initialValues);
        setValidationErrors({});
      }
    }
  }, [recipe]);

  // Validate parameters before running
  const validateParameters = (): boolean => {
    if (!recipe?.inputs) return true;

    const errors: Record<string, string> = {};

    Object.entries(recipe.inputs).forEach(([name, input]) => {
      const value = formValues[name];

      // Required check
      if (input.required) {
        if (value === undefined || value === null || value === '') {
          errors[name] = t('recipes.validation.required');
          return;
        }
      }

      // Skip validation for empty optional fields
      if (value === undefined || value === null || value === '') {
        return;
      }

      // Type-specific validation
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

  // Prepare parameters with proper type conversion
  const prepareParameters = (): Record<string, unknown> => {
    if (!recipe?.inputs) return {};

    const params: Record<string, unknown> = {};

    Object.entries(recipe.inputs).forEach(([name, input]) => {
      const value = formValues[name];

      // Skip empty optional values
      if ((value === undefined || value === null || value === '') && !input.required) {
        return;
      }

      // Convert to proper type
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

  // Handle field value change
  const handleFieldChange = (name: string, value: unknown) => {
    setFormValues(prev => ({ ...prev, [name]: value }));
    // Clear validation error when user modifies the field
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

    // Validate if recipe has parameters
    const hasInputs = recipe?.inputs && Object.keys(recipe.inputs).length > 0;
    if (hasInputs && !validateParameters()) {
      showToast(t('recipes.validation.fixErrors'), 'error');
      return;
    }

    // Prepare params with type conversion
    const params = prepareParameters();

    setIsRunning(true);
    try {
      const result = await runRecipe(
        currentRecipeName,
        Object.keys(params).length > 0 ? params : undefined,
        isInteractiveMode
      );
      if (result.status === 'ok') {
        showToast(
          isInteractiveMode ? t('recipes.startedAsync') : t('recipes.executedSuccess'),
          'success'
        );
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
            <div className="flex items-center gap-3 shrink-0">
              {/* Interactive mode switch */}
              <label className="flex items-center gap-2 cursor-pointer" title={t('recipes.interactiveModeHint')}>
                <span className={`text-xs transition-colors ${isInteractiveMode ? 'text-[var(--accent-primary)]' : 'text-[var(--text-muted)]'}`}>
                  {t('recipes.interactiveMode')}
                </span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={isInteractiveMode}
                  aria-label={t('recipes.interactiveMode')}
                  onClick={() => setIsInteractiveMode(!isInteractiveMode)}
                  className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors border-2
                    ${isInteractiveMode
                      ? 'bg-[var(--accent-primary)] border-[var(--accent-primary)]'
                      : 'bg-transparent border-[var(--border-color)]'}`}
                >
                  <span
                    className="inline-block h-3 w-3 rounded-full transition-all duration-200 shadow-sm"
                    style={{
                      backgroundColor: isInteractiveMode ? 'var(--bg-base)' : 'var(--text-muted)',
                      transform: isInteractiveMode ? 'translateX(1rem)' : 'translateX(0.125rem)',
                    }}
                  />
                </button>
              </label>
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleRun}
                disabled={isRunning}
              >
                {isRunning ? <LoadingSpinner size="sm" /> : t('recipes.run')}
              </button>
            </div>
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
            <div className="space-y-4">
              {Object.entries(recipe.inputs!).map(([name, input]) => {
                const error = validationErrors[name];
                const inputId = `param-${name}`;
                const errorId = `${inputId}-error`;

                return (
                  <div key={name} className="flex flex-col gap-2">
                    {/* Label row */}
                    <div className="flex items-center gap-2">
                      <label
                        htmlFor={inputId}
                        className="font-mono text-sm text-[var(--accent-primary)]"
                      >
                        {name}
                        {input.required && (
                          <span className="text-[var(--accent-error)] ml-0.5">*</span>
                        )}
                      </label>
                      <span className="text-xs text-[var(--text-muted)]">({input.type})</span>
                    </div>

                    {/* Input field based on type */}
                    {input.type === 'boolean' ? (
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          id={inputId}
                          type="checkbox"
                          checked={Boolean(formValues[name])}
                          onChange={(e) => handleFieldChange(name, e.target.checked)}
                          className="w-4 h-4 rounded border-[var(--border-color)] text-[var(--accent-primary)] focus:ring-[var(--accent-primary)]"
                          aria-describedby={error ? errorId : undefined}
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
                        placeholder={input.type === 'array'
                          ? t('recipes.enterJsonArray')
                          : t('recipes.enterJsonObject')
                        }
                        rows={3}
                        className={`w-full px-3 py-2 bg-[var(--bg-base)] border rounded-md text-sm font-mono
                          text-[var(--text-primary)] placeholder-[var(--text-muted)]
                          focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)]
                          ${error ? 'border-[var(--accent-error)]' : 'border-[var(--border-color)]'}`}
                        aria-describedby={error ? errorId : undefined}
                        aria-invalid={error ? 'true' : undefined}
                      />
                    ) : input.type === 'number' ? (
                      <input
                        id={inputId}
                        type="number"
                        value={formValues[name] !== undefined && formValues[name] !== '' ? String(formValues[name]) : ''}
                        onChange={(e) => handleFieldChange(name, e.target.value)}
                        placeholder={t('recipes.enterValue')}
                        className={`w-full px-3 py-2 bg-[var(--bg-base)] border rounded-md text-sm
                          text-[var(--text-primary)] placeholder-[var(--text-muted)]
                          focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)]
                          ${error ? 'border-[var(--accent-error)]' : 'border-[var(--border-color)]'}`}
                        aria-describedby={error ? errorId : undefined}
                        aria-invalid={error ? 'true' : undefined}
                      />
                    ) : (
                      <input
                        id={inputId}
                        type="text"
                        value={String(formValues[name] ?? '')}
                        onChange={(e) => handleFieldChange(name, e.target.value)}
                        placeholder={t('recipes.enterValue')}
                        className={`w-full px-3 py-2 bg-[var(--bg-base)] border rounded-md text-sm
                          text-[var(--text-primary)] placeholder-[var(--text-muted)]
                          focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)]
                          ${error ? 'border-[var(--accent-error)]' : 'border-[var(--border-color)]'}`}
                        aria-describedby={error ? errorId : undefined}
                        aria-invalid={error ? 'true' : undefined}
                      />
                    )}

                    {/* Description */}
                    {input.description && (
                      <p className="text-xs text-[var(--text-secondary)]">{input.description}</p>
                    )}

                    {/* Error message */}
                    {error && (
                      <p id={errorId} className="text-xs text-[var(--accent-error)]">{error}</p>
                    )}
                  </div>
                );
              })}
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
