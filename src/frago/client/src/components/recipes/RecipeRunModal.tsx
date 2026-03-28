/**
 * RecipeRunModal — Modal with parameter form for running a recipe.
 *
 * Reuses the parameter validation/form logic from RecipeDetail.
 */

import { useEffect, useState } from 'react';
import { useAppStore } from '@/stores/appStore';
import { getRecipeDetail, runRecipe, runRecipeAsync } from '@/api';
import LoadingSpinner from '@/components/ui/LoadingSpinner';
import type { RecipeDetail } from '@/types/pywebview';

interface RecipeRunModalProps {
  recipeName: string;
  onClose: () => void;
}

export default function RecipeRunModal({ recipeName, onClose }: RecipeRunModalProps) {
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
        showToast('配方已异步启动', 'success');
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
  }, [recipe]);

  if (isLoading) {
    return (
      <div className="sa-modal-overlay" onClick={onClose}>
        <div className="recipe-run-modal" onClick={(e) => e.stopPropagation()}>
          <div className="recipe-run-modal-loading">
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
    <div className="sa-modal-overlay" onClick={onClose}>
      <div className="recipe-run-modal" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="recipe-run-modal-header">
          <div>
            <h3 className="recipe-run-modal-title">{recipe.name.replace(/_/g, ' ')}</h3>
            <p className="recipe-run-modal-slug">{recipe.name}</p>
          </div>
          <button className="sa-modal-close" onClick={onClose}>×</button>
        </div>

        {/* Description */}
        {recipe.description && (
          <div className="recipe-run-modal-desc">
            <span className="recipe-run-modal-label">描述</span>
            <p>{recipe.description}</p>
          </div>
        )}

        {/* Parameters Form */}
        <div className="recipe-run-modal-body">
          <span className="recipe-run-modal-label">运行参数</span>
          <div className="recipe-run-modal-fields">
            {Object.entries(recipe.inputs).map(([name, input]) => {
              const error = validationErrors[name];
              return (
                <div key={name} className="recipe-run-modal-field">
                  <label className="recipe-run-modal-field-label">
                    {name}
                    {input.required && <span className="recipe-run-modal-required">*</span>}
                  </label>
                  {input.type === 'boolean' ? (
                    <label className="recipe-run-modal-checkbox">
                      <input
                        type="checkbox"
                        checked={Boolean(formValues[name])}
                        onChange={(e) => setFormValues((p) => ({ ...p, [name]: e.target.checked }))}
                      />
                      <span>{formValues[name] ? '是' : '否'}</span>
                    </label>
                  ) : input.type === 'array' || input.type === 'object' ? (
                    <textarea
                      value={String(formValues[name] ?? '')}
                      onChange={(e) => setFormValues((p) => ({ ...p, [name]: e.target.value }))}
                      placeholder={input.type === 'array' ? '输入 JSON 数组' : '输入 JSON 对象'}
                      rows={3}
                      className={`recipe-run-modal-input recipe-run-modal-textarea ${error ? 'recipe-run-modal-input--error' : ''}`}
                    />
                  ) : (
                    <input
                      type={input.type === 'number' ? 'number' : 'text'}
                      value={formValues[name] !== undefined ? String(formValues[name]) : ''}
                      onChange={(e) => setFormValues((p) => ({ ...p, [name]: e.target.value }))}
                      placeholder={input.default !== undefined ? String(input.default) : '输入值'}
                      className={`recipe-run-modal-input ${error ? 'recipe-run-modal-input--error' : ''}`}
                    />
                  )}
                  {input.description && (
                    <p className="recipe-run-modal-field-desc">{input.description}</p>
                  )}
                  {error && <p className="recipe-run-modal-error">{error}</p>}
                </div>
              );
            })}
          </div>
        </div>

        {/* Footer */}
        <div className="recipe-run-modal-footer">
          <button className="recipe-run-modal-cancel" onClick={onClose}>
            取消
          </button>
          <button
            className="recipe-run-modal-submit"
            onClick={handleRun}
            disabled={isRunning}
          >
            {isRunning ? <LoadingSpinner size="sm" /> : '▶ 运行'}
          </button>
        </div>
      </div>
    </div>
  );
}
