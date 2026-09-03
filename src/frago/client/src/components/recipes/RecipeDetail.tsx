import LoadingSpinner from '@/components/ui/LoadingSpinner';
import RecipeSecretsModal from './RecipeSecretsModal';
import RecipeOverview from './RecipeOverview';
import RecipeRunPanel from './RecipeRunPanel';
import { useRecipeDetail } from './useRecipeDetail';

export default function RecipeDetail() {
  const {
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
  } = useRecipeDetail();

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
        {t('recipes.recipeNotExist')}
      </div>
    );
  }

  return (
    /* 外框只留左右与顶上的边距，**不留底边**：底边归滚动区自己，
       否则内容滚到底时会停在一段死白之上，而最后一行仍然贴着滚动区的边。 */
    <div className="flex h-full flex-col gap-4 overflow-hidden px-5 pt-5">
      {/* Back button */}
      <button
        type="button"
        className="btn btn-ghost self-start shrink-0"
        onClick={() => switchPage('recipes')}
      >
        ← {t('recipes.backToRecipeList')}
      </button>

      {/* Two-column: intro on the left, action/parameters panel on the right */}
      <div className="flex-1 overflow-y-auto pb-10">
        <div className="rd-layout">
          <RecipeOverview recipe={recipe} showToast={showToast} t={t} />
          <RecipeRunPanel
            recipe={recipe}
            secretsData={secretsData}
            formValues={formValues}
            validationErrors={validationErrors}
            isRunning={isRunning}
            isInteractiveMode={isInteractiveMode}
            setIsInteractiveMode={setIsInteractiveMode}
            handleRun={handleRun}
            handleFieldChange={handleFieldChange}
            setShowSecretsModal={setShowSecretsModal}
            t={t}
          />
        </div>
      </div>

      {/* Secrets Configuration Modal */}
      {secretsData && (
        <RecipeSecretsModal
          isOpen={showSecretsModal}
          onClose={() => setShowSecretsModal(false)}
          recipeName={recipe.name}
          secretsData={secretsData}
          onSaved={() => {
            refreshSecrets();
            setShowSecretsModal(false);
            showToast(t('recipes.secretSaved'), 'success');
          }}
        />
      )}
    </div>
  );
}
