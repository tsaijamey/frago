import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useAppStore } from '@/stores/appStore';
import { getRecipeDetail, runRecipe, runRecipeAsync, getRecipeSecrets } from '@/api';
import type { RecipeDetail as RecipeDetailType, RecipeSecretsResponse } from '@/types/pywebview';

/**
 * useRecipeDetail — owns all RecipeDetail state and behavior:
 * recipe loading, form values + validation, interactive mode,
 * secrets fetching, and the run handler. The component reads this
 * and renders; no behavior lives in the view.
 */
export function useRecipeDetail() {
  const { t } = useTranslation();
  const { currentRecipeName, switchPage, showToast } = useAppStore();
  const [recipe, setRecipe] = useState<RecipeDetailType | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRunning, setIsRunning] = useState(false);
  const [formValues, setFormValues] = useState<Record<string, unknown>>({});
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({});
  const [isInteractiveMode, setIsInteractiveMode] = useState(false);
  const [secretsData, setSecretsData] = useState<RecipeSecretsResponse | null>(null);
  const [showSecretsModal, setShowSecretsModal] = useState(false);

  useEffect(() => {
    if (!currentRecipeName) return;

    setIsLoading(true);
    getRecipeDetail(currentRecipeName)
      .then(setRecipe)
      .catch((err) => {
        console.error('Failed to load recipe:', err);
        showToast(t('recipes.failedToLoad'), 'error');
      })
      .finally(() => setIsLoading(false));
  }, [currentRecipeName, showToast, t]);

  // Initialize form values and interactive mode from recipe
  useEffect(() => {
    if (recipe) {
      const hasInteractiveTag = recipe.tags?.includes('interactive') ?? false;
      setIsInteractiveMode(hasInteractiveTag);

      if (recipe.inputs) {
        const initialValues: Record<string, unknown> = {};
        Object.entries(recipe.inputs).forEach(([name, input]) => {
          // 后端把"没有默认值"序列化成 null，而 null !== undefined 为真。
          // 只判 undefined 会让 array/object 字段被填进字面量 "null"，
          // 用户什么都没输入却被判"必须是 JSON 数组"。
          if (input.default !== undefined && input.default !== null) {
            if (input.type === 'array' || input.type === 'object') {
              initialValues[name] = typeof input.default === 'string'
                ? input.default
                : JSON.stringify(input.default, null, 2);
            } else {
              initialValues[name] = input.default;
            }
          } else if (input.type === 'boolean') {
            // 配方没声明默认值时留空，让 prepareParameters 跳过这个参数，
            // 由配方脚本自己的默认值生效。填 false 会被当成用户显式关闭发下去，
            // 把描述里写着"默认 true"的开关强行关掉。
            initialValues[name] = undefined;
          } else {
            initialValues[name] = '';
          }
        });
        setFormValues(initialValues);
        setValidationErrors({});
      }
    }
  }, [recipe]);

  // Fetch secrets when recipe loads
  useEffect(() => {
    if (!recipe) return;

    getRecipeSecrets(recipe.name)
      .then(setSecretsData)
      .catch((err) => {
        console.error('Failed to load recipe secrets:', err);
      });
  }, [recipe]);

  const refreshSecrets = async () => {
    if (!recipe) return;
    try {
      const data = await getRecipeSecrets(recipe.name);
      setSecretsData(data);
    } catch (err) {
      console.error('Failed to refresh recipe secrets:', err);
    }
  };

  const validateParameters = (): boolean => {
    if (!recipe?.inputs) return true;

    const errors: Record<string, string> = {};

    Object.entries(recipe.inputs).forEach(([name, input]) => {
      const value = formValues[name];

      if (input.required) {
        if (value === undefined || value === null || value === '') {
          errors[name] = t('recipes.validation.required');
          return;
        }
      }

      if (value === undefined || value === null || value === '') {
        return;
      }

      // integer 也要按数字校验：配方里确实在用这个类型（如 video_story_studio 的 fps），
      // 漏掉它等于该字段填任何字母都能通过前端进到后端。
      if (input.type === 'number' || input.type === 'integer') {
        if (isNaN(Number(value))) {
          errors[name] = t('recipes.validation.invalidNumber');
        }
      } else if (input.type === 'array' || input.type === 'object') {
        try {
          const parsed = JSON.parse(String(value));
          if (input.type === 'array' && !Array.isArray(parsed)) {
            errors[name] = t('recipes.validation.mustBeArray');
          }
          if (input.type === 'object' && (typeof parsed !== 'object' || Array.isArray(parsed) || parsed === null)) {
            errors[name] = t('recipes.validation.mustBeObject');
          }
        } catch {
          errors[name] = t('recipes.validation.invalidJson');
        }
      }
    });

    setValidationErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const prepareParameters = (): Record<string, unknown> => {
    if (!recipe?.inputs) return {};

    const params: Record<string, unknown> = {};

    Object.entries(recipe.inputs).forEach(([name, input]) => {
      const value = formValues[name];

      if ((value === undefined || value === null || value === '') && !input.required) {
        return;
      }

      switch (input.type) {
        case 'number':
          params[name] = Number(value);
          break;
        case 'boolean':
          params[name] = Boolean(value);
          break;
        case 'array':
        case 'object':
          params[name] = JSON.parse(String(value));
          break;
        default:
          params[name] = value;
      }
    });

    return params;
  };

  const handleFieldChange = (name: string, value: unknown) => {
    setFormValues(prev => ({ ...prev, [name]: value }));
    if (validationErrors[name]) {
      setValidationErrors(prev => {
        const next = { ...prev };
        delete next[name];
        return next;
      });
    }
  };

  const handleRun = async () => {
    if (!currentRecipeName || isRunning) return;

    const missingRequired = secretsData?.fields.filter(
      f => f.required && !f.has_value
    ) ?? [];
    if (missingRequired.length > 0) {
      showToast(t('recipes.missingEnvVars', { count: missingRequired.length }), 'warning');
      return;
    }

    const hasParams = recipe?.inputs && Object.keys(recipe.inputs).length > 0;
    if (hasParams && !validateParameters()) {
      showToast(t('recipes.validation.fixErrors'), 'error');
      return;
    }

    const params = prepareParameters();

    setIsRunning(true);
    try {
      const recipeParams = Object.keys(params).length > 0 ? params : undefined;
      if (isInteractiveMode) {
        await runRecipeAsync(currentRecipeName, recipeParams);
        showToast(t('recipes.startedAsync'), 'success');
      } else {
        const result = await runRecipe(currentRecipeName, recipeParams);
        if (result.status === 'ok') {
          showToast(t('recipes.executedSuccess'), 'success');
        } else {
          showToast(result.error || t('recipes.executionFailed'), 'error');
        }
      }
    } catch (err) {
      console.error('Failed to run recipe:', err);
      showToast(t('recipes.failedToExecute'), 'error');
    } finally {
      setIsRunning(false);
    }
  };

  return {
    t,
    switchPage,
    showToast,
    recipe,
    isLoading,
    isRunning,
    formValues,
    validationErrors,
    isInteractiveMode,
    setIsInteractiveMode,
    secretsData,
    showSecretsModal,
    setShowSecretsModal,
    refreshSecrets,
    handleFieldChange,
    handleRun,
  };
}
