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

/**
 * 参数定义里可选的候选项。
 *
 * 契约上 `RecipeInput` 只声明了 type / required / default / description，没有候选值这
 * 一栏；但配方作者在 `inputs` 里写 `options`（或 `choices`）是常见做法，服务端原样带
 * 过来。这里按可选字段读，读到就渲染成一组胶囊，读不到就照旧走文本框——**不认识的字
 * 段不会让界面出错，也不会把它吞掉**。
 */
function optionsOf(input: RecipeInput): string[] {
  const raw = (input as RecipeInput & { options?: unknown; choices?: unknown }).options
    ?? (input as RecipeInput & { choices?: unknown }).choices;
  if (!Array.isArray(raw)) return [];
  return raw.filter((v): v is string => typeof v === 'string');
}

// Single parameter field (de-alarmed styling: neutral, not warning-yellow)
export default function RecipeParamField({ name, input, value, error, onChange, t }: RecipeParamFieldProps) {
  const inputId = `param-${name}`;
  const errorId = `${inputId}-error`;
  const fieldClass = `w-full px-3 py-2 bg-[var(--bg-base)] border rounded-md text-sm
    text-[var(--text-primary)] placeholder-[var(--text-muted)]
    focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)]
    ${error ? 'border-[var(--accent-error)]' : 'border-[var(--border-color)]'}`;

  const options = optionsOf(input);
  const isBoolean = input.type === 'boolean';
  const boolOn = Boolean(value);

  return (
    <div className="flex flex-col gap-1.5">
      {/* 布尔参数不摆标题行：下面那颗开关自己就带名字，再挂一行等于把同一个词说两遍。 */}
      {!isBoolean && (
        <div className="flex items-center gap-2">
          <label htmlFor={inputId} className="font-mono text-sm text-[var(--text-primary)] font-medium">
            {name}
            {input.required && <span className="text-[var(--accent-error)] ml-0.5">*</span>}
          </label>
          <span className="text-xs text-[var(--text-muted)]">{input.type}</span>
        </div>
      )}
      {input.description && (
        <p className="text-xs text-[var(--text-secondary)] leading-relaxed">{input.description}</p>
      )}
      {isBoolean ? (
        /* 布尔走开关，不走勾选框：开关的形态本身就说清了「开着还是关着」，
           不必再让人在旁边读一个「是 / 否」。开着时也只有中性实底，不刷品牌绿。 */
        <label className={`rd-switch ${boolOn ? 'rd-switch--on' : ''}`}>
          <input
            id={inputId}
            type="checkbox"
            role="switch"
            checked={boolOn}
            onChange={(e) => onChange(name, e.target.checked)}
            className="sr-only"
            aria-describedby={error ? errorId : undefined}
          />
          <span className="rd-switch-track" aria-hidden="true" />
          <span className="rd-switch-label">
            {name}
            {input.required && <span className="text-[var(--accent-error)] ml-0.5">*</span>}
            <span className="text-[var(--text-muted)] ml-2">
              {boolOn ? t('recipes.yes') : t('recipes.no')}
            </span>
          </span>
        </label>
      ) : options.length > 0 ? (
        /* 候选值自己一颗小胶囊：有底、有内距、选中的整颗浮起来。
           它是「从几档里挑一个」，形态上就该和一段文字分开。 */
        <div className="rd-options" role="radiogroup" aria-label={name}>
          {options.map((opt) => {
            const active = String(value ?? '') === opt;
            return (
              <button
                key={opt}
                type="button"
                role="radio"
                aria-checked={active}
                className={`rd-option ${active ? 'rd-option--active' : ''}`}
                onClick={() => onChange(name, opt)}
              >
                {opt}
              </button>
            );
          })}
        </div>
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
