/**
 * Secrets Settings Component
 * Environment variable management: Recipe variable hints + grouped display + CRUD
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { getEnvVars, updateEnvVars, getRecipeEnvRequirements } from '@/api';
import type { RecipeEnvRequirement } from '@/types/pywebview';
import { Key, Plus, Edit2, Trash2, Eye, EyeOff } from 'lucide-react';
import Modal from '@/components/ui/Modal';

interface EnvVarGroup {
  [group: string]: Array<[string, string]>;
}

export default function SecretsSettings() {
  const { t } = useTranslation();
  const [envVars, setEnvVars] = useState<Record<string, string>>({});
  const [recipeRequirements, setRecipeRequirements] = useState<RecipeEnvRequirement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [formKey, setFormKey] = useState('');
  const [formValue, setFormValue] = useState('');
  const [formError, setFormError] = useState<string | null>(null);
  const [visibleVars, setVisibleVars] = useState<Set<string>>(new Set());

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      setLoading(true);
      const [envResult, recipeResult] = await Promise.all([
        getEnvVars(),
        getRecipeEnvRequirements(),
      ]);
      setEnvVars(envResult.vars || {});
      setRecipeRequirements(recipeResult);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('errors.loadFailed'));
    } finally {
      setLoading(false);
    }
  };

  const groupEnvVars = (
    vars: Record<string, string>,
    recipeReqs: RecipeEnvRequirement[]
  ): EnvVarGroup => {
    const recipeVarNames = new Set(recipeReqs.map(r => r.var_name));

    const groups: EnvVarGroup = {
      Recipe: [],
      GitHub: [],
      'AI APIs': [],
      Database: [],
      Other: [],
    };

    Object.entries(vars).forEach(([key, value]) => {
      // Check if it's a Recipe variable first
      if (recipeVarNames.has(key)) {
        groups['Recipe'].push([key, value]);
      } else if (key.startsWith('GITHUB_') || key.startsWith('GH_')) {
        groups['GitHub'].push([key, value]);
      } else if (key.includes('API_KEY') || key.includes('TOKEN') || key.includes('KEY')) {
        groups['AI APIs'].push([key, value]);
      } else if (key.includes('DB_') || key.includes('DATABASE_')) {
        groups['Database'].push([key, value]);
      } else {
        groups['Other'].push([key, value]);
      }
    });

    // Remove empty groups
    return Object.fromEntries(
      Object.entries(groups).filter(([_, vars]) => vars.length > 0)
    ) as EnvVarGroup;
  };

  const maskValue = (value: string, key: string): string => {
    if (visibleVars.has(key)) {
      return value;
    }
    if (value.length <= 8) {
      return '••••••';
    }
    return value.slice(0, 4) + '••••••' + value.slice(-4);
  };

  const toggleVisibility = (key: string) => {
    setVisibleVars((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(key)) {
        newSet.delete(key);
      } else {
        newSet.add(key);
      }
      return newSet;
    });
  };

  const handleAdd = () => {
    setEditingKey(null);
    setFormKey('');
    setFormValue('');
    setFormError(null);
    setShowModal(true);
  };

  const handleEdit = (key: string, value: string) => {
    setEditingKey(key);
    setFormKey(key);
    setFormValue(value);
    setFormError(null);
    setShowModal(true);
  };

  const handleDelete = async (key: string) => {
    if (!confirm(t('secrets.deleteConfirm', { name: key }))) {
      return;
    }

    try {
      const result = await updateEnvVars({ [key]: null });
      if (result.status === 'ok' && result.vars) {
        setEnvVars(result.vars);
        // Reload recipe requirements to update configured status
        const recipeResult = await getRecipeEnvRequirements();
        setRecipeRequirements(recipeResult);
      } else {
        setError(result.error || t('secrets.deleteFailed'));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('secrets.deleteFailed'));
    }
  };

  const handleSave = async () => {
    // Validation
    if (!formKey.trim()) {
      setFormError(t('secrets.varNameEmpty'));
      return;
    }
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(formKey)) {
      setFormError(t('secrets.varNameInvalid'));
      return;
    }
    if (!formValue.trim()) {
      setFormError(t('secrets.varValueEmpty'));
      return;
    }

    // Check for conflicts
    if (!editingKey && formKey in envVars) {
      if (!confirm(t('secrets.varExistsConfirm', { name: formKey }))) {
        return;
      }
    }

    try {
      const result = await updateEnvVars({ [formKey]: formValue });
      if (result.status === 'ok' && result.vars) {
        setEnvVars(result.vars);
        setShowModal(false);
        setError(null);
        // Reload recipe requirements to update configured status
        const recipeResult = await getRecipeEnvRequirements();
        setRecipeRequirements(recipeResult);
      } else {
        setFormError(result.error || t('secrets.saveFailed'));
      }
    } catch (err) {
      setFormError(err instanceof Error ? err.message : t('secrets.saveFailed'));
    }
  };

  const handleQuickAdd = async (requirement: RecipeEnvRequirement) => {
    setEditingKey(null);
    setFormKey(requirement.var_name);
    setFormValue('');
    setFormError(null);
    setShowModal(true);
  };

  if (loading) {
    return (
      <div className="text-[var(--text-muted)] text-center py-8">{t('common.loading')}</div>
    );
  }

  // Deduplicate by variable name, merging cases where multiple recipes use the same variable
  const groupedRequirements = recipeRequirements.reduce((acc, req) => {
    if (!acc[req.var_name]) {
      acc[req.var_name] = {
        var_name: req.var_name,
        required: req.required,
        description: req.description,
        configured: req.configured,
        recipes: [req.recipe_name]
      };
    } else {
      acc[req.var_name].recipes.push(req.recipe_name);
      // If any recipe marks it as required, mark the whole as required
      if (req.required) {
        acc[req.var_name].required = true;
      }
    }
    return acc;
  }, {} as Record<string, {
    var_name: string;
    required: boolean;
    description: string;
    configured: boolean;
    recipes: string[];
  }>);

  // Only show unconfigured recipe requirements
  const unconfiguredRequirements = Object.values(groupedRequirements).filter(
    req => !req.configured
  );

  const groupedVars = groupEnvVars(envVars, recipeRequirements);

  return (
    <div className="space-y-4">
      {error && (
        <div className="card bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800">
          <p className="text-sm text-red-700 dark:text-red-400">{error}</p>
        </div>
      )}

      {/* Environment Variables - Large Card */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-[var(--accent-primary)]">{t('secrets.envVars')}</h2>
          <button onClick={handleAdd} className="btn btn-primary btn-sm flex items-center gap-2">
            <Plus size={16} />
            {t('secrets.add')}
          </button>
        </div>

        <div className="space-y-4">
          {/* Recipe Environment Variable Requirements - Only show unconfigured */}
          {unconfiguredRequirements.length > 0 && (
            <div className="p-4 bg-[var(--bg-tertiary)] rounded-md border border-[var(--border-color)]">
              <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-2">
                {t('secrets.recipeEnvRequirements')}
              </h3>
              <p className="text-xs text-[var(--text-muted)] mb-3">
                {t('secrets.envVarsNotConfigured')}
              </p>
              <div className="space-y-2">
                {unconfiguredRequirements.map((req) => (
                  <div
                    key={req.var_name}
                    className="flex items-start justify-between gap-2 p-3 bg-[var(--bg-base)] rounded-md"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="mb-1">
                        <code className="text-sm font-mono text-[var(--text-primary)]">
                          {req.var_name}
                        </code>
                      </div>
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-xs px-1.5 py-0.5 bg-amber-500 text-white rounded">
                          {t('secrets.notConfiguredBadge')}
                        </span>
                        {req.required && (
                          <span className="text-xs px-1.5 py-0.5 bg-red-500 text-white rounded">
                            {t('secrets.requiredBadge')}
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-[var(--text-secondary)] mb-1">
                        {req.description}
                      </p>
                      <p className="text-xs text-[var(--text-muted)]">
                        {t('secrets.usedBy')}: {req.recipes.join(', ')}
                      </p>
                    </div>

                    <button
                      onClick={() => handleQuickAdd({ ...req, recipe_name: req.recipes[0] })}
                      className="btn btn-ghost btn-sm text-xs"
                    >
                      {t('secrets.add')}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Configured Environment Variables - Grouped Display */}
          {Object.keys(envVars).length === 0 ? (
            <p className="text-sm text-[var(--text-muted)] text-center py-8">
              {t('secrets.noEnvVars')}
            </p>
          ) : (
            <div className="space-y-4">
              {Object.entries(groupedVars).map(([group, vars]) => (
                <div key={group}>
                  <h3 className="text-sm font-medium text-[var(--text-primary)] mb-2 flex items-center gap-2">
                    <Key size={14} />
                    {group === 'Recipe' ? t('secrets.recipeEnvVars') : group}
                  </h3>
                  <div className="space-y-2">
                    {vars.map(([key, value]) => {
                      // Find recipe info for this variable
                      const recipeInfo = groupedRequirements[key];
                      // Handle both array and comma-separated string formats
                      const usedByRecipes = recipeInfo?.recipes
                        ?.flatMap(r => r.split(',').map(s => s.trim()))
                        ?.filter(Boolean) || [];

                      return (
                        <div
                          key={key}
                          className="flex items-center gap-2 p-3 bg-[var(--bg-subtle)] rounded-md"
                        >
                          <div className="flex-1 min-w-0">
                            <div className="text-sm font-mono text-[var(--text-primary)] mb-1">
                              {key}
                            </div>
                            <div className="text-sm font-mono text-[var(--text-secondary)] flex items-center gap-2">
                              <span className="truncate">{maskValue(value, key)}</span>
                              <button
                                onClick={() => toggleVisibility(key)}
                                className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
                              >
                                {visibleVars.has(key) ? (
                                  <EyeOff size={14} />
                                ) : (
                                  <Eye size={14} />
                                )}
                              </button>
                            </div>
                            {group === 'Recipe' && usedByRecipes.length > 0 && (
                              <div className="text-xs text-[var(--text-muted)] mt-2 flex items-center gap-1.5 flex-wrap">
                                <span className="text-[var(--text-muted)]">{t('secrets.usedBy')}</span>
                                {usedByRecipes.map((recipe, idx) => (
                                  <span
                                    key={idx}
                                    className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300 border border-blue-200 dark:border-blue-800"
                                  >
                                    {recipe}
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                          <div className="flex items-center gap-1">
                            <button
                              onClick={() => handleEdit(key, value)}
                              className="btn btn-ghost btn-sm p-2"
                              title={t('common.edit')}
                            >
                              <Edit2 size={14} />
                            </button>
                            <button
                              onClick={() => handleDelete(key)}
                              className="btn btn-ghost btn-sm p-2 text-red-600 dark:text-red-400"
                              title={t('common.delete')}
                            >
                              <Trash2 size={14} />
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Add/Edit Modal */}
      <Modal
        isOpen={showModal}
        onClose={() => setShowModal(false)}
        title={editingKey ? t('secrets.editEnvVar') : t('secrets.addEnvVar')}
        footer={
          <>
            <button onClick={() => setShowModal(false)} className="btn btn-ghost flex-1">
              {t('common.cancel')}
            </button>
            <button onClick={handleSave} className="btn btn-primary flex-1">
              {t('common.save')}
            </button>
          </>
        }
      >
        {formError && (
          <div className="mb-4 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-md">
            <p className="text-sm text-red-700 dark:text-red-400">{formError}</p>
          </div>
        )}

        <div className="space-y-4">
          <div>
            <label htmlFor="env-var-name" className="block text-sm font-medium text-[var(--text-primary)] mb-2">
              {t('secrets.variableName')}
            </label>
            <input
              id="env-var-name"
              type="text"
              value={formKey}
              onChange={(e) => setFormKey(e.target.value)}
              placeholder="e.g., GITHUB_TOKEN"
              disabled={!!editingKey}
              className="w-full px-3 py-2 bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] disabled:opacity-50 font-mono"
            />
            <p className="mt-1 text-xs text-[var(--text-muted)]">
              {t('secrets.varNameHint')}
            </p>
          </div>

          <div>
            <label htmlFor="env-var-value" className="block text-sm font-medium text-[var(--text-primary)] mb-2">
              {t('secrets.variableValue')}
            </label>
            <textarea
              id="env-var-value"
              value={formValue}
              onChange={(e) => setFormValue(e.target.value)}
              placeholder={t('secrets.enterVarValue')}
              rows={3}
              className="w-full px-3 py-2 bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] font-mono resize-none"
            />
          </div>
        </div>
      </Modal>
    </div>
  );
}
