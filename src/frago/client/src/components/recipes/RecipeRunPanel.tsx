import type { TFunction } from 'i18next';
import { Key, Check, X, Play } from 'lucide-react';
import LoadingSpinner from '@/components/ui/LoadingSpinner';
import type { RecipeDetail as RecipeDetailType, RecipeSecretsResponse } from '@/types/pywebview';
import RecipeParamField from './RecipeParamField';

interface RecipeRunPanelProps {
  recipe: RecipeDetailType;
  secretsData: RecipeSecretsResponse | null;
  formValues: Record<string, unknown>;
  validationErrors: Record<string, string>;
  isRunning: boolean;
  isInteractiveMode: boolean;
  setIsInteractiveMode: (v: boolean) => void;
  handleRun: () => void;
  handleFieldChange: (name: string, value: unknown) => void;
  setShowSecretsModal: (v: boolean) => void;
  t: TFunction;
}

// Right column — run action pinned at top, then secrets and parameters.
export default function RecipeRunPanel({
  recipe,
  secretsData,
  formValues,
  validationErrors,
  isRunning,
  isInteractiveMode,
  setIsInteractiveMode,
  handleRun,
  handleFieldChange,
  setShowSecretsModal,
  t,
}: RecipeRunPanelProps) {
  const hasInputs = recipe.inputs && Object.keys(recipe.inputs).length > 0;
  const hasSecrets = secretsData !== null && secretsData.fields.length > 0;

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

  return (
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
            {Object.entries(recipe.inputs!).map(([name, input]) => (
              <RecipeParamField
                key={name}
                name={name}
                input={input}
                value={formValues[name]}
                error={validationErrors[name]}
                onChange={handleFieldChange}
                t={t}
              />
            ))}
          </div>
        ) : (
          !hasSecrets && (
            <p className="text-xs text-[var(--text-muted)]">{t('recipes.noParamsNeeded')}</p>
          )
        )}
      </div>
    </aside>
  );
}
