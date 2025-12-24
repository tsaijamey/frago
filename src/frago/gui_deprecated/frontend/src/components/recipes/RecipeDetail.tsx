import { useEffect, useState } from 'react';
import { useAppStore } from '@/stores/appStore';
import { getRecipeDetail, runRecipe, openPath } from '@/api';
import LoadingSpinner from '@/components/ui/LoadingSpinner';
import { ExternalLink } from 'lucide-react';
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
        showToast('Failed to load recipe details', 'error');
      })
      .finally(() => setIsLoading(false));
  }, [currentRecipeName, showToast]);

  const handleRun = async () => {
    if (!currentRecipeName || isRunning) return;

    setIsRunning(true);
    try {
      const result = await runRecipe(currentRecipeName);
      if (result.status === 'ok') {
        showToast('Recipe executed successfully', 'success');
      } else {
        showToast(result.error || 'Execution failed', 'error');
      }
    } catch (err) {
      console.error('Failed to run recipe:', err);
      showToast('Failed to execute recipe', 'error');
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
      <div className="text-[var(--text-muted)] text-center py-scaled-8">
        Recipe does not exist
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-scaled-3 h-full overflow-hidden p-scaled-4">
      {/* Back button */}
      <button
        className="btn btn-ghost self-start shrink-0"
        onClick={() => switchPage('recipes')}
      >
        ← Back to Recipe List
      </button>

      {/* Recipe information */}
      <div className="card shrink-0">
        <div className="flex items-start justify-between gap-scaled-3">
          <div className="flex-1 min-w-0">
            <h2 className="text-scaled-base font-medium text-[var(--text-primary)] break-words">
              {recipe.name}
            </h2>
            {recipe.description && (
              <p className="text-scaled-sm text-[var(--text-secondary)] mt-scaled-1">
                {recipe.description}
              </p>
            )}
          </div>
          <button
            className="btn btn-primary shrink-0"
            onClick={handleRun}
            disabled={isRunning}
          >
            {isRunning ? <LoadingSpinner size="sm" /> : 'Run'}
          </button>
        </div>

        <div className="space-y-1 mt-scaled-3 text-scaled-sm">
          <div className="flex">
            <span className="text-[var(--text-muted)] w-16 shrink-0">Type:</span>
            <span>{recipe.category}</span>
          </div>
          <div className="flex">
            <span className="text-[var(--text-muted)] w-16 shrink-0">Source:</span>
            <span>{recipe.source || '-'}</span>
          </div>
          {recipe.runtime && (
            <div className="flex">
              <span className="text-[var(--text-muted)] w-16 shrink-0">Runtime:</span>
              <span>{recipe.runtime}</span>
            </div>
          )}
          {recipe.path && (
            <div className="flex">
              <span className="text-[var(--text-muted)] w-16 shrink-0">Path:</span>
              <button
                className="font-mono text-scaled-xs break-all text-left text-[var(--accent-primary)] hover:underline inline-flex items-start gap-1"
                onClick={async () => {
                  const result = await openPath(recipe.path!, true);
                  if (result.status !== 'ok') {
                    showToast(result.error || 'Unable to open path', 'error');
                  }
                }}
                title="Show in Finder"
              >
                {recipe.path}
                <ExternalLink className="icon-scaled-xs shrink-0 mt-0.5" />
              </button>
            </div>
          )}
        </div>

        {recipe.tags.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-scaled-3">
            {recipe.tags.map((tag) => (
              <span
                key={tag}
                className="text-scaled-xs bg-[var(--bg-subtle)] text-[var(--text-muted)] px-2 py-0.5 rounded"
              >
                {tag}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Metadata content - takes remaining space */}
      {recipe.metadata_content && (
        <div className="card flex-1 min-h-0 flex flex-col overflow-hidden">
          <h3 className="font-medium mb-scaled-2 text-[var(--accent-primary)] shrink-0 text-scaled-sm">
            Configuration Content
          </h3>
          <pre className="bg-[var(--bg-tertiary)] p-scaled-3 rounded text-scaled-xs font-mono overflow-auto flex-1 min-h-0 whitespace-pre-wrap break-words">
            {recipe.metadata_content}
          </pre>
        </div>
      )}
    </div>
  );
}
