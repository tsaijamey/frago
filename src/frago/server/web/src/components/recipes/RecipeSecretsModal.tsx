/**
 * Recipe Secrets Modal Component
 * Inline modal for configuring secrets required by a recipe
 */

import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { updateEnvVars } from '@/api';
import type { RecipeEnvRequirement } from '@/types/pywebview';
import { Check, AlertCircle } from 'lucide-react';
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

  // Reset form when modal opens
  useEffect(() => {
    if (isOpen) {
      setFormValues({});
      setError(null);
    }
  }, [isOpen]);

  // Separate configured and unconfigured requirements
  const unconfiguredReqs = requirements.filter(req => !req.configured);
  const configuredReqs = requirements.filter(req => req.configured);
  const allConfigured = unconfiguredReqs.length === 0;

  const handleSave = async () => {
    // Validate required fields
    const missingRequired = unconfiguredReqs.filter(
      req => req.required && !formValues[req.var_name]?.trim()
    );

    if (missingRequired.length > 0) {
      setError(t('recipes.secretsValidationError', {
        fields: missingRequired.map(r => r.var_name).join(', ')
      }));
      return;
    }

    // Filter out empty values
    const updates: Record<string, string> = {};
    for (const [key, value] of Object.entries(formValues)) {
      if (value.trim()) {
        updates[key] = value.trim();
      }
    }

    if (Object.keys(updates).length === 0) {
      setError(t('recipes.secretsNoChanges'));
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
        allConfigured ? (
          <button onClick={onClose} className="btn btn-primary flex-1">
            {t('common.close')}
          </button>
        ) : (
          <>
            <button onClick={onClose} className="btn btn-ghost flex-1" disabled={saving}>
              {t('common.cancel')}
            </button>
            <button onClick={handleSave} className="btn btn-primary flex-1" disabled={saving}>
              {saving ? t('common.loading') : t('common.save')}
            </button>
          </>
        )
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

        {/* All configured message */}
        {allConfigured && (
          <div className="flex items-center gap-2 p-4 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-md">
            <Check size={20} className="text-green-600 dark:text-green-400" />
            <span className="text-sm text-green-700 dark:text-green-400 font-medium">
              {t('recipes.allConfigured')}
            </span>
          </div>
        )}

        {/* Unconfigured secrets - with input fields */}
        {unconfiguredReqs.length > 0 && (
          <div className="space-y-3">
            {unconfiguredReqs.map((req) => (
              <div
                key={req.var_name}
                className="p-3 bg-[var(--bg-subtle)] rounded-md border border-[var(--border-color)]"
              >
                <div className="flex items-center gap-2 mb-2">
                  <code className="text-sm font-mono font-medium text-[var(--text-primary)]">
                    {req.var_name}
                  </code>
                  {req.required && (
                    <span className="text-xs px-1.5 py-0.5 rounded bg-[var(--accent-error)]/20 text-[var(--accent-error)]">
                      {t('recipes.required')}
                    </span>
                  )}
                </div>
                {req.description && (
                  <p className="text-xs text-[var(--text-muted)] mb-2">{req.description}</p>
                )}
                <input
                  type="text"
                  value={formValues[req.var_name] || ''}
                  onChange={(e) => setFormValues(prev => ({
                    ...prev,
                    [req.var_name]: e.target.value
                  }))}
                  placeholder={t('recipes.enterValue')}
                  className="w-full px-3 py-2 bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] font-mono text-sm"
                  aria-label={req.var_name}
                />
              </div>
            ))}
          </div>
        )}

        {/* Configured secrets - read-only display */}
        {configuredReqs.length > 0 && (
          <div className="space-y-2">
            {unconfiguredReqs.length > 0 && (
              <h4 className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wide">
                {t('recipes.configured')}
              </h4>
            )}
            {configuredReqs.map((req) => (
              <div
                key={req.var_name}
                className="flex items-center justify-between p-3 bg-[var(--bg-subtle)] rounded-md"
              >
                <div className="flex-1 min-w-0">
                  <code className="text-sm font-mono text-[var(--text-primary)]">
                    {req.var_name}
                  </code>
                  {req.description && (
                    <p className="text-xs text-[var(--text-muted)] mt-1 truncate">{req.description}</p>
                  )}
                </div>
                <Check size={18} className="text-[var(--accent-success)] ml-3 flex-shrink-0" />
              </div>
            ))}
          </div>
        )}
      </div>
    </Modal>
  );
}
