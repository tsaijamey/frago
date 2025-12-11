import { useEffect, useState } from 'react';
import { useAppStore } from '@/stores/appStore';
import { getRecipeDetail, runRecipe } from '@/api/pywebview';
import LoadingSpinner from '@/components/ui/LoadingSpinner';
import type { RecipeDetail as RecipeDetailType } from '@/types/pywebview.d';

export default function RecipeDetail() {
  const { currentRecipeName, switchPage, showToast } = useAppStore();
  const [recipe, setRecipe] = useState<RecipeDetailType | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRunning, setIsRunning] = useState(false);

  useEffect(() => {
    if (!currentRecipeName) return;

    setIsLoading(true);
    getRecipeDetail(currentRecipeName)
      .then(setRecipe)
      .catch((err) => {
        console.error('Failed to load recipe:', err);
        showToast('加载配方详情失败', 'error');
      })
      .finally(() => setIsLoading(false));
  }, [currentRecipeName, showToast]);

  const handleRun = async () => {
    if (!currentRecipeName || isRunning) return;

    setIsRunning(true);
    try {
      const result = await runRecipe(currentRecipeName);
      if (result.status === 'ok') {
        showToast('配方执行成功', 'success');
      } else {
        showToast(result.error || '执行失败', 'error');
      }
    } catch (err) {
      console.error('Failed to run recipe:', err);
      showToast('执行配方失败', 'error');
    } finally {
      setIsRunning(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  if (!recipe) {
    return (
      <div className="text-[var(--text-muted)] text-center py-8">
        配方不存在
      </div>
    );
  }

  return (
    <div className="page-scroll flex flex-col gap-4 h-full">
      {/* 返回按钮 */}
      <button
        className="btn btn-ghost self-start"
        onClick={() => switchPage('recipes')}
      >
        ← 返回配方列表
      </button>

      {/* 配方信息 */}
      <div className="card">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-lg font-medium text-[var(--text-primary)]">
              {recipe.name}
            </h2>
            {recipe.description && (
              <p className="text-[var(--text-secondary)] mt-1">
                {recipe.description}
              </p>
            )}
          </div>
          <button
            className="btn btn-primary"
            onClick={handleRun}
            disabled={isRunning}
          >
            {isRunning ? <LoadingSpinner size="sm" /> : '运行'}
          </button>
        </div>

        <div className="grid grid-cols-2 gap-4 mt-4 text-sm">
          <div>
            <span className="text-[var(--text-muted)]">类型：</span>
            <span className="ml-2">{recipe.category}</span>
          </div>
          <div>
            <span className="text-[var(--text-muted)]">来源：</span>
            <span className="ml-2">{recipe.source || '-'}</span>
          </div>
          <div>
            <span className="text-[var(--text-muted)]">运行时：</span>
            <span className="ml-2">{recipe.runtime || '-'}</span>
          </div>
          {recipe.path && (
            <div className="col-span-2">
              <span className="text-[var(--text-muted)]">路径：</span>
              <span className="ml-2 font-mono text-xs">{recipe.path}</span>
            </div>
          )}
        </div>

        {recipe.tags.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-4">
            {recipe.tags.map((tag) => (
              <span
                key={tag}
                className="text-xs bg-[var(--bg-subtle)] text-[var(--text-muted)] px-2 py-0.5 rounded"
              >
                {tag}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* 元数据内容 */}
      {recipe.metadata_content && (
        <div className="card">
          <h3 className="font-medium mb-3 text-[var(--accent-primary)]">
            配置内容
          </h3>
          <pre className="bg-[var(--bg-tertiary)] p-3 rounded text-sm font-mono overflow-x-auto">
            {recipe.metadata_content}
          </pre>
        </div>
      )}
    </div>
  );
}
