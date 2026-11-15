import { useMemo, useState } from 'react';
import type { TFunction } from 'i18next';
import { Eye, EyeOff, Plus, X } from 'lucide-react';
import type { RecipeInput } from '@/types/pywebview';

interface RecipeParamFieldProps {
  name: string;
  input: RecipeInput;
  value: unknown;
  error?: string;
  onChange: (name: string, value: unknown) => void;
  t: TFunction;
}

type ExtendedRecipeInput = RecipeInput & {
  options?: unknown;
  choices?: unknown;
  enum?: unknown;
  secret?: boolean;
  multiline?: boolean;
  min?: number;
  max?: number;
  step?: number;
};

/**
 * 参数定义里可选的候选项。
 * 支持 `enum`、`options`、`choices` 三种常见 schema 写法。
 */
function optionsOf(input: RecipeInput): string[] {
  const ext = input as ExtendedRecipeInput;
  const raw = ext.enum ?? ext.options ?? ext.choices;
  if (!Array.isArray(raw)) return [];
  return raw.filter((v): v is string | number => typeof v === 'string' || typeof v === 'number').map(String);
}

function parseArrayItems(value: unknown): { ok: boolean; items: string[] } {
  if (Array.isArray(value)) {
    const simple = value.every((v) => typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean');
    return simple ? { ok: true, items: value.map(String) } : { ok: false, items: [] };
  }
  if (typeof value !== 'string' || !value.trim()) {
    return { ok: true, items: [] };
  }
  try {
    const parsed: unknown = JSON.parse(value);
    if (!Array.isArray(parsed)) return { ok: false, items: [] };
    const simple = parsed.every((v) => typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean');
    return simple ? { ok: true, items: parsed.map(String) } : { ok: false, items: [] };
  } catch {
    return { ok: false, items: [] };
  }
}

function parseObjectEntries(value: unknown): { ok: boolean; entries: Array<[string, string]> } {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const entries = Object.entries(value as Record<string, unknown>);
    const simple = entries.every(([, v]) => typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean');
    return simple ? { ok: true, entries: entries.map(([k, v]) => [k, String(v)]) } : { ok: false, entries: [] };
  }
  if (typeof value !== 'string' || !value.trim()) {
    return { ok: true, entries: [] };
  }
  try {
    const parsed: unknown = JSON.parse(value);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return { ok: false, entries: [] };
    const entries = Object.entries(parsed as Record<string, unknown>);
    const simple = entries.every(([, v]) => typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean');
    return simple ? { ok: true, entries: entries.map(([k, v]) => [k, String(v)]) } : { ok: false, entries: [] };
  } catch {
    return { ok: false, entries: [] };
  }
}

function ArrayFieldEditor({
  inputId,
  value,
  errorId,
  hasError,
  onChangeValue,
  t,
}: {
  inputId: string;
  value: unknown;
  errorId: string;
  hasError: boolean;
  onChangeValue: (next: string) => void;
  t: TFunction;
}) {
  const parsed = useMemo(() => parseArrayItems(value), [value]);
  const [rawMode, setRawMode] = useState(() => !parsed.ok);
  const [items, setItems] = useState<string[]>(() => (parsed.ok ? parsed.items : []));

  const syncItems = (next: string[]) => {
    setItems(next);
    onChangeValue(next.length === 0 ? '' : JSON.stringify(next));
  };

  if (rawMode || !parsed.ok) {
    return (
      <div className="rcp-struct-box">
        <textarea
          id={inputId}
          value={typeof value === 'string' ? value : JSON.stringify(value ?? [], null, 2)}
          onChange={(e) => onChangeValue(e.target.value)}
          placeholder={t('recipes.enterJsonArray')}
          rows={3}
          className={`w-full px-3 py-2 bg-[var(--bg-base)] border rounded-md text-sm font-mono text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] ${
            hasError ? 'border-[var(--accent-error)]' : 'border-[var(--border-color)]'
          }`}
          aria-describedby={hasError ? errorId : undefined}
          aria-invalid={hasError ? 'true' : 'false'}
        />
        {parsed.ok && (
          <button
            type="button"
            className="rcp-struct-mode"
            onClick={() => {
              setItems(parsed.items);
              setRawMode(false);
            }}
          >
            {t('recipes.structuredMode', { defaultValue: 'Form view' })}
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="rcp-struct-box" id={inputId}>
      {items.length > 0 && (
        <div className="rcp-struct-list">
          {items.map((item, idx) => (
            <div key={idx} className="rcp-struct-row">
              <input
                type="text"
                value={item}
                onChange={(e) => {
                  const next = [...items];
                  next[idx] = e.target.value;
                  syncItems(next);
                }}
                placeholder={t('recipes.enterValue')}
                className="rcp-struct-input"
                aria-label={`${inputId} item ${idx + 1}`}
              />
              <button
                type="button"
                className="rcp-struct-del"
                onClick={() => syncItems(items.filter((_, i) => i !== idx))}
                aria-label={t('common.remove', { defaultValue: 'Remove' })}
              >
                <X size={12} />
              </button>
            </div>
          ))}
        </div>
      )}
      <div className="rcp-struct-foot">
        <button
          type="button"
          className="rcp-struct-add"
          onClick={() => syncItems([...items, ''])}
        >
          <Plus size={12} />
          {t('recipes.addItem', { defaultValue: 'Add item' })}
        </button>
        <button
          type="button"
          className="rcp-struct-mode"
          onClick={() => setRawMode(true)}
        >
          JSON
        </button>
      </div>
    </div>
  );
}

function ObjectFieldEditor({
  inputId,
  value,
  errorId,
  hasError,
  onChangeValue,
  t,
}: {
  inputId: string;
  value: unknown;
  errorId: string;
  hasError: boolean;
  onChangeValue: (next: string) => void;
  t: TFunction;
}) {
  const parsed = useMemo(() => parseObjectEntries(value), [value]);
  const [rawMode, setRawMode] = useState(() => !parsed.ok);
  const [entries, setEntries] = useState<Array<[string, string]>>(() =>
    parsed.ok ? parsed.entries : []
  );

  const syncEntries = (next: Array<[string, string]>) => {
    setEntries(next);
    if (next.length === 0) {
      onChangeValue('');
      return;
    }
    const obj: Record<string, string> = {};
    for (const [k, v] of next) {
      if (k.trim()) obj[k.trim()] = v;
    }
    onChangeValue(Object.keys(obj).length > 0 ? JSON.stringify(obj) : '');
  };

  if (rawMode || !parsed.ok) {
    return (
      <div className="rcp-struct-box">
        <textarea
          id={inputId}
          value={typeof value === 'string' ? value : JSON.stringify(value ?? {}, null, 2)}
          onChange={(e) => onChangeValue(e.target.value)}
          placeholder={t('recipes.enterJsonObject')}
          rows={3}
          className={`w-full px-3 py-2 bg-[var(--bg-base)] border rounded-md text-sm font-mono text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] ${
            hasError ? 'border-[var(--accent-error)]' : 'border-[var(--border-color)]'
          }`}
          aria-describedby={hasError ? errorId : undefined}
          aria-invalid={hasError ? 'true' : 'false'}
        />
        {parsed.ok && (
          <button
            type="button"
            className="rcp-struct-mode"
            onClick={() => {
              setEntries(parsed.entries);
              setRawMode(false);
            }}
          >
            {t('recipes.structuredMode', { defaultValue: 'Form view' })}
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="rcp-struct-box" id={inputId}>
      {entries.length > 0 && (
        <div className="rcp-struct-list">
          {entries.map(([k, v], idx) => (
            <div key={idx} className="rcp-struct-row rcp-struct-row--kv">
              <input
                type="text"
                value={k}
                onChange={(e) => {
                  const next = entries.map((pair, i) =>
                    i === idx ? ([e.target.value, pair[1]] as [string, string]) : pair
                  );
                  syncEntries(next);
                }}
                placeholder="key"
                className="rcp-struct-input font-mono"
                aria-label={`${inputId} key ${idx + 1}`}
              />
              <input
                type="text"
                value={v}
                onChange={(e) => {
                  const next = entries.map((pair, i) =>
                    i === idx ? ([pair[0], e.target.value] as [string, string]) : pair
                  );
                  syncEntries(next);
                }}
                placeholder="value"
                className="rcp-struct-input"
                aria-label={`${inputId} value ${idx + 1}`}
              />
              <button
                type="button"
                className="rcp-struct-del"
                onClick={() => syncEntries(entries.filter((_, i) => i !== idx))}
                aria-label={t('common.remove', { defaultValue: 'Remove' })}
              >
                <X size={12} />
              </button>
            </div>
          ))}
        </div>
      )}
      <div className="rcp-struct-foot">
        <button
          type="button"
          className="rcp-struct-add"
          onClick={() => syncEntries([...entries, ['', '']])}
        >
          <Plus size={12} />
          {t('recipes.addField', { defaultValue: 'Add field' })}
        </button>
        <button
          type="button"
          className="rcp-struct-mode"
          onClick={() => setRawMode(true)}
        >
          JSON
        </button>
      </div>
    </div>
  );
}

// Single parameter field (.rcp-form-row with .tp type badge, .req required tag, and .h hint)
export default function RecipeParamField({ name, input, value, error, onChange, t }: RecipeParamFieldProps) {
  const [secretVisible, setSecretVisible] = useState(false);
  const inputId = `param-${name}`;
  const errorId = `${inputId}-error`;
  const fieldClass = `w-full px-3 py-2 bg-[var(--bg-base)] border rounded-md text-sm
    text-[var(--text-primary)] placeholder-[var(--text-muted)]
    focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)]
    ${error ? 'border-[var(--accent-error)]' : 'border-[var(--border-color)]'}`;

  const ext = input as ExtendedRecipeInput;
  const options = optionsOf(input);
  const isBoolean = input.type === 'boolean';
  const isSecret = input.type === 'secret' || input.type === 'password' || ext.secret === true;
  const isNumber = input.type === 'number' || input.type === 'integer';
  const boolOn = Boolean(value);
  const typeLabel = options.length > 0 && input.type !== 'enum' ? `enum · ${input.type}` : input.type;
  const requiredLabel = t('recipes.required', { defaultValue: 'required' });

  return (
    <div className="rcp-form-row">
      {/* 布尔参数把开关和标签放在一起；非布尔参数统一渲染 .tp 与 .req */}
      {!isBoolean && (
        <label htmlFor={inputId}>
          <span className="font-mono">{name}</span>
          <span className="tp">{typeLabel}</span>
          {input.required && <span className="req">{requiredLabel}</span>}
        </label>
      )}
      {isBoolean ? (
        <>
          <div className="flex items-center justify-between gap-2">
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
              <span className="rd-switch-label font-mono">{name}</span>
              <span className="tp">{input.type}</span>
              {input.required && <span className="req">{requiredLabel}</span>}
            </label>
            <span className="text-xs text-[var(--text-muted)]">
              {boolOn ? t('recipes.yes') : t('recipes.no')}
            </span>
          </div>
          {input.description && <span className="h">{input.description}</span>}
        </>
      ) : (
        <>
          {input.description && <span className="h">{input.description}</span>}
          {options.length > 0 ? (
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
          ) : input.type === 'array' ? (
            <ArrayFieldEditor
              inputId={inputId}
              value={value}
              errorId={errorId}
              hasError={Boolean(error)}
              onChangeValue={(next) => onChange(name, next)}
              t={t}
            />
          ) : input.type === 'object' ? (
            <ObjectFieldEditor
              inputId={inputId}
              value={value}
              errorId={errorId}
              hasError={Boolean(error)}
              onChangeValue={(next) => onChange(name, next)}
              t={t}
            />
          ) : isNumber ? (
            <input
              id={inputId}
              type="number"
              step={ext.step ?? (input.type === 'integer' ? 1 : 'any')}
              min={ext.min}
              max={ext.max}
              value={value !== undefined && value !== '' ? String(value) : ''}
              onChange={(e) => onChange(name, e.target.value)}
              placeholder={t('recipes.enterValue')}
              className={fieldClass}
              aria-describedby={error ? errorId : undefined}
              aria-invalid={error ? 'true' : 'false'}
            />
          ) : isSecret ? (
            <div className="rcp-secret-wrap">
              <input
                id={inputId}
                type={secretVisible ? 'text' : 'password'}
                value={String(value ?? '')}
                onChange={(e) => onChange(name, e.target.value)}
                placeholder={t('recipes.enterValue')}
                className={`${fieldClass} font-mono`}
                aria-describedby={error ? errorId : undefined}
                aria-invalid={error ? 'true' : 'false'}
              />
              <button
                type="button"
                className="rcp-secret-eye"
                onClick={() => setSecretVisible((v) => !v)}
                aria-label={secretVisible ? t('recipes.hide') : t('recipes.show')}
                title={secretVisible ? t('recipes.hide') : t('recipes.show')}
              >
                {secretVisible ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
          ) : ext.multiline ? (
            <textarea
              id={inputId}
              rows={3}
              value={String(value ?? '')}
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
        </>
      )}
      {error && (
        <p id={errorId} className="text-xs text-[var(--accent-error)]">
          {error}
        </p>
      )}
    </div>
  );
}
