/**
 * Recipe Secrets Modal Component
 * Inline modal for configuring secrets required by a recipe
 */

import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { updateEnvVars } from '@/api';
import type { RecipeEnvRequirement } from '@/types/pywebview';
import { Check, AlertCircle, Eye, EyeOff } from 'lucide-react';
import Modal from '@/components/ui/Modal';

interface RecipeSecretsModalProps {
  isOpen: boolean;
  onClose: () => void;
  requirements: RecipeEnvRequirement[];
  onSaved: () => void;
}

export default function RecipeSecretsModal({
  isOpen,
  onClose,
  requirements,
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
    // Validate required fields (only unconfigured ones)
    const missingRequired = requirements.filter(
      req => req.required && !req.configured && !formValues[req.var_name]?.trim()
    );

    if (missingRequired.length > 0) {
      setError(t('recipes.secretsValidationError', {
        fields: missingRequired.map(r => r.var_name).join(', ')
      }));
      return;
    }

    // Only save fields that were modified and have values
    const updates: Record<string, string> = {};
    for (const [key, value] of Object.entries(formValues)) {
      if (modifiedFields.has(key) && value.trim()) {
        updates[key] = value.trim();
      }
    }

    // Allow saving empty updates (user may just want to confirm config)
    if (Object.keys(updates).length === 0) {
      onSaved();  // Refresh and close
      return;
    }

    setSaving(true);
    setError(null);

    try {
      const result = await updateEnvVars(updates);
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

        {/* Error message */}
        {error && (
          <div className="flex items-start gap-2 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-md">
            <AlertCircle size={16} className="text-red-600 dark:text-red-400 mt-0.5 flex-shrink-0" />
            <p className="text-sm text-red-700 dark:text-red-400">{error}</p>
          </div>
        )}

        {/* All credentials - unified editable form */}
        <div className="space-y-3">
          {requirements.map((req) => {
            const isVisible = visibleFields.has(req.var_name);
            const inputId = `secret-${req.var_name}`;

            return (
              <div
                key={req.var_name}
                className="p-3 bg-[var(--bg-subtle)] rounded-md border border-[var(--border-color)]"
              >
                {/* Header: variable name + status badges */}
                <div className="flex items-center gap-2 mb-2">
                  <code className="text-sm font-mono font-medium text-[var(--text-primary)]">
                    {req.var_name}
                  </code>
                  {req.required && (
                    <span className="text-xs px-1.5 py-0.5 rounded bg-[var(--accent-error)]/20 text-[var(--accent-error)]">
                      {t('recipes.required')}
                    </span>
                  )}
                  {req.configured && (
                    <span className="text-xs px-1.5 py-0.5 rounded bg-[var(--accent-success)]/20 text-[var(--accent-success)] flex items-center gap-1">
                      <Check size={12} />
                      {t('recipes.configured')}
                    </span>
                  )}
                </div>

                {/* Description */}
                {req.description && (
                  <p className="text-xs text-[var(--text-muted)] mb-2">{req.description}</p>
                )}

                {/* Input field with show/hide toggle */}
                <div className="flex gap-2">
                  <input
                    id={inputId}
                    type={isVisible ? "text" : "password"}
                    value={formValues[req.var_name] || ''}
                    onChange={(e) => {
                      setFormValues(prev => ({ ...prev, [req.var_name]: e.target.value }));
                      setModifiedFields(prev => new Set(prev).add(req.var_name));
                    }}
                    placeholder={
                      req.configured
                        ? t('recipes.leaveEmptyToKeep')
                        : t('recipes.enterValue')
                    }
                    className="flex-1 px-3 py-2 bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder:text-[var(--text-muted)] placeholder:opacity-40 focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] font-mono text-sm"
                    aria-label={req.var_name}
                  />
                  <button
                    type="button"
                    onClick={() => {
                      setVisibleFields(prev => {
                        const next = new Set(prev);
                        if (next.has(req.var_name)) {
                          next.delete(req.var_name);
                        } else {
                          next.add(req.var_name);
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
              </div>
            );
          })}
        </div>
      </div>
    </Modal>
  );
}
