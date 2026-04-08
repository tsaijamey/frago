/**
 * Recipe Secrets Modal Component
 * Inline modal for configuring secrets required by a recipe
 */

import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { updateRecipeSecrets } from '@/api';
import type { RecipeSecretsResponse } from '@/types/pywebview';
import { Check, AlertCircle, Eye, EyeOff, Link2 } from 'lucide-react';
import Modal from '@/components/ui/Modal';

interface RecipeSecretsModalProps {
  isOpen: boolean;
  onClose: () => void;
  recipeName: string;
  secretsData: RecipeSecretsResponse;
  onSaved: () => void;
}

export default function RecipeSecretsModal({
  isOpen,
  onClose,
  recipeName,
  secretsData,
  onSaved,
}: RecipeSecretsModalProps) {
  const { t } = useTranslation();
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [modifiedFields, setModifiedFields] = useState<Set<string>>(new Set());
  const [visibleFields, setVisibleFields] = useState<Set<string>>(new Set());

  // Reset form when modal opens
  useEffect(() => {
    if (isOpen) {
      setFormValues({});
      setModifiedFields(new Set());
      setVisibleFields(new Set());
      setError(null);
    }
  }, [isOpen]);

  const handleSave = async () => {
    // Validate required fields that don't have values yet
    const missingRequired = secretsData.fields.filter(
      f => f.required && !f.has_value && !formValues[f.key]?.trim()
    );

    if (missingRequired.length > 0) {
      setError(t('recipes.secretsValidationError', {
        fields: missingRequired.map(f => f.key).join(', ')
      }));
      return;
    }

    // Only save fields that were modified and have values
    const updates: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(formValues)) {
      if (modifiedFields.has(key) && value.trim()) {
        // For object type fields, try to parse JSON
        const field = secretsData.fields.find(f => f.key === key);
        if (field?.type === 'object') {
          try {
            updates[key] = JSON.parse(value.trim());
          } catch {
            setError(t('recipes.validation.invalidJson') + `: ${key}`);
            return;
          }
        } else {
          updates[key] = value.trim();
        }
      }
    }

    // Allow saving empty updates
    if (Object.keys(updates).length === 0) {
      onSaved();
      return;
    }

    setSaving(true);
    setError(null);

    try {
      const result = await updateRecipeSecrets(recipeName, updates);
      if (result.status === 'ok') {
        onSaved();
      } else {
        setError(result.error || t('recipes.secretSaveFailed'));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('recipes.secretSaveFailed'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={t('recipes.secretsModalTitle')}
      footer={
        <>
          <button onClick={onClose} className="btn btn-ghost flex-1" disabled={saving}>
            {t('common.cancel')}
          </button>
          <button onClick={handleSave} className="btn btn-primary flex-1" disabled={saving}>
            {saving ? t('common.loading') : t('common.save')}
          </button>
        </>
      }
    >
      <div className="space-y-4">
        {/* Description */}
        <p className="text-sm text-[var(--text-muted)]">
          {t('recipes.secretsModalDesc')}
        </p>

        {/* $ref shared hint */}
        {secretsData.is_ref && secretsData.ref_target && (
          <div className="flex items-start gap-2 p-3 bg-[var(--accent-primary)]/10 border border-[var(--accent-primary)]/20 rounded-md">
            <Link2 size={16} className="text-[var(--accent-primary)] mt-0.5 flex-shrink-0" />
            <p className="text-sm text-[var(--accent-primary)]">
              {t('recipes.sharedSecretsHint', { target: secretsData.ref_target })}
            </p>
          </div>
        )}

        {/* Error message */}
        {error && (
          <div className="flex items-start gap-2 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-md">
            <AlertCircle size={16} className="text-red-600 dark:text-red-400 mt-0.5 flex-shrink-0" />
            <p className="text-sm text-red-700 dark:text-red-400">{error}</p>
          </div>
        )}

        {/* All credentials - unified editable form */}
        <div className="space-y-3">
          {secretsData.fields.map((field) => {
            const isVisible = visibleFields.has(field.key);
            const inputId = `secret-${field.key}`;
            const isObjectType = field.type === 'object';

            return (
              <div
                key={field.key}
                className="p-3 bg-[var(--bg-subtle)] rounded-md border border-[var(--border-color)]"
              >
                {/* Header: field key + type + status badges */}
                <div className="flex items-center gap-2 mb-2">
                  <code className="text-sm font-mono font-medium text-[var(--text-primary)]">
                    {field.key}
                  </code>
                  <span className="text-xs text-[var(--text-muted)]">({field.type})</span>
                  {field.required && (
                    <span className="text-xs px-1.5 py-0.5 rounded bg-[var(--accent-error)]/20 text-[var(--accent-error)]">
                      {t('recipes.required')}
                    </span>
                  )}
                  {field.has_value && (
                    <span className="text-xs px-1.5 py-0.5 rounded bg-[var(--accent-success)]/20 text-[var(--accent-success)] flex items-center gap-1">
                      <Check size={12} />
                      {t('recipes.configured')}
                    </span>
                  )}
                </div>

                {/* Description */}
                {field.description && (
                  <p className="text-xs text-[var(--text-muted)] mb-2">{field.description}</p>
                )}

                {/* Input field */}
                {isObjectType ? (
                  <textarea
                    id={inputId}
                    value={formValues[field.key] || ''}
                    onChange={(e) => {
                      setFormValues(prev => ({ ...prev, [field.key]: e.target.value }));
                      setModifiedFields(prev => new Set(prev).add(field.key));
                    }}
                    placeholder={
                      field.has_value
                        ? t('recipes.leaveEmptyToKeep')
                        : t('recipes.enterJsonObject')
                    }
                    rows={3}
                    className="w-full px-3 py-2 bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder:text-[var(--text-muted)] placeholder:opacity-40 focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] font-mono text-sm"
                    aria-label={field.key}
                  />
                ) : (
                  <div className="flex gap-2">
                    <input
                      id={inputId}
                      type={isVisible ? "text" : "password"}
                      value={formValues[field.key] || ''}
                      onChange={(e) => {
                        setFormValues(prev => ({ ...prev, [field.key]: e.target.value }));
                        setModifiedFields(prev => new Set(prev).add(field.key));
                      }}
                      placeholder={
                        field.has_value
                          ? t('recipes.leaveEmptyToKeep')
                          : t('recipes.enterValue')
                      }
                      className="flex-1 px-3 py-2 bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder:text-[var(--text-muted)] placeholder:opacity-40 focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] font-mono text-sm"
                      aria-label={field.key}
                    />
                    <button
                      type="button"
                      onClick={() => {
                        setVisibleFields(prev => {
                          const next = new Set(prev);
                          if (next.has(field.key)) {
                            next.delete(field.key);
                          } else {
                            next.add(field.key);
                          }
                          return next;
                        });
                      }}
                      className="btn btn-ghost btn-sm p-2"
                      title={isVisible ? t('recipes.hide') : t('recipes.show')}
                    >
                      {isVisible ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </Modal>
  );
}
