import type { TFunction } from 'i18next';
import type { RecipeInput } from '@/types/pywebview';

interface RecipeParamFieldProps {
  name: string;
  input: RecipeInput;
  value: unknown;
  error?: string;
  onChange: (name: string, value: unknown) => void;
  t: TFunction;
}

// Single parameter field (de-alarmed styling: neutral, not warning-yellow)
export default function RecipeParamField({ name, input, value, error, onChange, t }: RecipeParamFieldProps) {
  const inputId = `param-${name}`;
  const errorId = `${inputId}-error`;
  const fieldClass = `w-full px-3 py-2 bg-[var(--bg-base)] border rounded-md text-sm
    text-[var(--text-primary)] placeholder-[var(--text-muted)]
    focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)]
    ${error ? 'border-[var(--accent-error)]' : 'border-[var(--border-color)]'}`;

  return (
    <div className="flex flex-col gap-1.5">
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
            checked={Boolean(value)}
            onChange={(e) => onChange(name, e.target.checked)}
            className="w-4 h-4 rounded border-[var(--border-color)] text-[var(--accent-primary)] focus:ring-[var(--accent-primary)]"
          />
          <span className="text-sm text-[var(--text-secondary)]">
            {value ? t('recipes.yes') : t('recipes.no')}
          </span>
        </label>
      ) : input.type === 'array' || input.type === 'object' ? (
        <textarea
          id={inputId}
          value={String(value ?? '')}
          onChange={(e) => onChange(name, e.target.value)}
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
          value={value !== undefined && value !== '' ? String(value) : ''}
          onChange={(e) => onChange(name, e.target.value)}
          placeholder={t('recipes.enterValue')}
          className={fieldClass}
          aria-describedby={error ? errorId : undefined}
          aria-invalid={error ? 'true' : 'false'}
        />
      ) : (
        <input
          id={inputId}
          type="text"
          value={String(value ?? '')}
          onChange={(e) => onChange(name, e.target.value)}
          placeholder={t('recipes.enterValue')}
          className={fieldClass}
          aria-describedby={error ? errorId : undefined}
          aria-invalid={error ? 'true' : 'false'}
        />
      )}
      {error && <p id={errorId} className="text-xs text-[var(--accent-error)]">{error}</p>}
    </div>
  );
}
