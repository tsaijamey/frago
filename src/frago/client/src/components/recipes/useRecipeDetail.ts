import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useAppStore } from '@/stores/appStore';
import { getRecipeDetail, runRecipe, runRecipeAsync, getRecipeSecrets } from '@/api';
import { getExecution } from '@/api/client';
import { refusalOf, TERMINAL_EXECUTION_STATUSES } from '@/utils/recipeOutcome';
import type { RecipeDetail as RecipeDetailType, RecipeSecretsResponse } from '@/types/pywebview';

/** 后台运行的结局多久问一次、最多盯多久。盯不到头就算了，运行记录里还查得到。 */
const OUTCOME_POLL_MS = 1500;
const OUTCOME_WATCH_MS = 30 * 60 * 1000;

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
      // 有页面就按交互式起步：配方跑完要把页面交给人，同步等它跑完只会让按钮卡住。
      // 「有没有页面」是服务端看磁盘答的；interactive 标签是人手写的，带页面的配方
      // 里有 6 个没写，开关因此一直是关的。标签仍然认，给没有页面但要常驻运行的配方用。
      const hasInteractiveTag = recipe.tags?.includes('interactive') ?? false;
      setIsInteractiveMode(Boolean(recipe.has_page) || hasInteractiveTag);

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

  /**
   * 盯着一次后台运行，跑完告诉人结局。
   *
   * 从前按下运行只报一句「已启动」就撒手：配方拒绝了（比如还有一局没打完），人看到
   * 的是「已启动」然后什么也没发生。现在跑完再说一句——拒绝就把配方给的原因原样
   * 显示出来，失败就报错。成功不再多说：该打开的页面平台已经打开了。
   */
  const reportOutcome = async (executionId: string) => {
    const deadline = Date.now() + OUTCOME_WATCH_MS;
    while (Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, OUTCOME_POLL_MS));
      let execution;
      try {
        execution = await getExecution(executionId);
      } catch {
        continue; // 服务端一时没回，下一轮再问
      }
      if (!TERMINAL_EXECUTION_STATUSES.has(execution.status)) continue;

      const refusal = execution.status === 'succeeded' ? refusalOf(execution.data) : null;
      if (refusal) {
        showToast(refusal.message, 'warning');
      } else if (execution.status !== 'succeeded') {
        const err = execution.error;
        const message = typeof err === 'string' ? err : err?.message;
        showToast(message || t('recipes.executionFailed'), 'error');
      }
      return;
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
        const started = await runRecipeAsync(currentRecipeName, recipeParams);
        showToast(t('recipes.startedAsync'), 'success');
        // 不等它跑完再放开按钮——交互式配方可能要跑很久。结局在后台盯着，出来了再说。
        void reportOutcome(started.execution_id);
      } else {
        const result = await runRecipe(currentRecipeName, recipeParams);
        const refusal = result.status === 'ok' ? refusalOf(result.data) : null;
        if (refusal) {
          showToast(refusal.message, 'warning');
        } else if (result.status === 'ok') {
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
