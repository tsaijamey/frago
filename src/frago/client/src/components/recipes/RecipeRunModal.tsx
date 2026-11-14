/**
 * RecipeRunModal — Modal with parameter form for running a recipe.
 *
 * Reuses the parameter validation/form logic from RecipeDetail.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Play, X } from 'lucide-react';
import { useAppStore } from '@/stores/appStore';
import { getRecipeDetail, runRecipe, runRecipeAsync } from '@/api';
import LoadingSpinner from '@/components/ui/LoadingSpinner';
import RecipeParamField from './RecipeParamField';
import type { RecipeDetail } from '@/types/pywebview';

interface RecipeRunModalProps {
  recipeName: string;
  onClose: () => void;
}

export default function RecipeRunModal({ recipeName, onClose }: RecipeRunModalProps) {
  const { t } = useTranslation();
  const { showToast } = useAppStore();
  const [recipe, setRecipe] = useState<RecipeDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRunning, setIsRunning] = useState(false);
  const [formValues, setFormValues] = useState<Record<string, unknown>>({});
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    setIsLoading(true);
    getRecipeDetail(recipeName)
      .then((r) => {
        setRecipe(r);
        // Initialize form values
        if (r.inputs) {
          const initial: Record<string, unknown> = {};
          Object.entries(r.inputs).forEach(([name, input]) => {
            if (input.default !== undefined) {
              if (input.type === 'array' || input.type === 'object') {
                initial[name] = typeof input.default === 'string'
                  ? input.default
                  : JSON.stringify(input.default, null, 2);
              } else {
                initial[name] = input.default;
              }
            } else {
              initial[name] = input.type === 'boolean' ? false : '';
            }
          });
          setFormValues(initial);
        }
      })
      .catch(() => {
        showToast('配方加载失败', 'error');
        onClose();
      })
      .finally(() => setIsLoading(false));
  }, [recipeName, showToast, onClose]);

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleEsc);
    return () => document.removeEventListener('keydown', handleEsc);
  }, [onClose]);

  const validateParameters = (): boolean => {
    if (!recipe?.inputs) return true;
    const errors: Record<string, string> = {};
    Object.entries(recipe.inputs).forEach(([name, input]) => {
      const value = formValues[name];
      if (input.required && (value === undefined || value === null || value === '')) {
        errors[name] = '此参数必填';
      }
      if (value && (input.type === 'array' || input.type === 'object')) {
        try { JSON.parse(String(value)); } catch { errors[name] = '无效 JSON'; }
      }
    });
    setValidationErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const prepareParams = (): Record<string, unknown> => {
    if (!recipe?.inputs) return {};
    const params: Record<string, unknown> = {};
    Object.entries(recipe.inputs).forEach(([name, input]) => {
      const value = formValues[name];
      if ((value === undefined || value === null || value === '') && !input.required) return;
      switch (input.type) {
        case 'number': params[name] = Number(value); break;
        case 'boolean': params[name] = Boolean(value); break;
        case 'array':
        case 'object': params[name] = JSON.parse(String(value)); break;
        default: params[name] = value;
      }
    });
    return params;
  };

  const handleRun = async () => {
    if (isRunning) return;
    const hasInputs = recipe?.inputs && Object.keys(recipe.inputs).length > 0;
    if (hasInputs && !validateParameters()) return;

    const params = prepareParams();
    setIsRunning(true);
    try {
      const recipeParams = Object.keys(params).length > 0 ? params : undefined;
      const isInteractive = recipe?.tags?.includes('interactive');
      if (isInteractive) {
        await runRecipeAsync(recipeName, recipeParams);
        showToast('配方已启动', 'success');
      } else {
        const result = await runRecipe(recipeName, recipeParams);
        if (result.status === 'ok') {
          showToast('配方执行成功', 'success');
        } else {
          showToast(result.error || '执行失败', 'error');
        }
      }
      onClose();
    } catch {
      showToast('配方执行失败', 'error');
    } finally {
      setIsRunning(false);
    }
  };

  // If no parameters, run directly without modal
  useEffect(() => {
    if (recipe && (!recipe.inputs || Object.keys(recipe.inputs).length === 0)) {
      handleRun();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recipe]);

  if (isLoading) {
    return (
      <div className="ui-modal-backdrop">
        <div className="ui-modal-frame">
          <div className="flex items-center justify-center py-10">
            <LoadingSpinner size="lg" />
          </div>
        </div>
      </div>
    );
  }

  if (!recipe || !recipe.inputs || Object.keys(recipe.inputs).length === 0) {
    return null;
  }

  return (
    // 点遮罩不关窗：这扇窗里有人正在填参数，手一滑点到旁边就把刚填的东西丢掉，
    // 而且丢得没有任何提示。关窗走右上角的 × 或 Esc。与通用 Modal 组件同一口径。
    <div className="ui-modal-backdrop">
      <div className="ui-modal-frame" role="dialog" aria-modal="true" aria-labelledby="recipe-run-title">
        {/* Header */}
        <div className="ui-modal-head">
          <div className="min-w-0">
            <h3 id="recipe-run-title" className="ui-modal-title">{recipe.name.replace(/_/g, ' ')}</h3>
            <p className="text-xs font-mono text-[var(--text-muted)] truncate">{recipe.name}</p>
          </div>
          <button
            type="button"
            className="ui-icon-btn ui-modal-close"
            onClick={onClose}
            aria-label="Close modal"
          >
            <X size={20} />
          </button>
        </div>

        <div className="ui-modal-body space-y-4">
          {/* Description */}
          {recipe.description && (
            <div>
              <span className="text-xs font-medium text-[var(--text-secondary)]">{t('recipes.description')}</span>
              <p className="text-sm text-[var(--text-secondary)] mt-1">{recipe.description}</p>
            </div>
          )}

          {/* Parameters Form */}
          <div className="space-y-4">
            <span className="text-xs font-medium text-[var(--text-secondary)]">{t('recipes.parameters')}</span>
            <div className="space-y-4">
              {Object.entries(recipe.inputs).map(([name, input]) => (
                <RecipeParamField
                  key={name}
                  name={name}
                  input={input}
                  value={formValues[name]}
                  error={validationErrors[name]}
                  onChange={(field, value) => setFormValues((p) => ({ ...p, [field]: value }))}
                  t={t}
                />
              ))}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="ui-modal-foot">
          <button className="btn btn-secondary" onClick={onClose}>
            {t('common.cancel')}
          </button>
          <button
            className="btn btn-primary gap-2"
            onClick={handleRun}
            disabled={isRunning}
          >
            {isRunning ? <LoadingSpinner size="sm" /> : <Play size={14} />}
            {t('recipes.run')}
          </button>
        </div>
      </div>
    </div>
  );
}
