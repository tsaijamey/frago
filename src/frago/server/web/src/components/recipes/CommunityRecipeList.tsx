/**
 * Community Recipe List Component
 *
 * Displays a searchable grid of community recipes with install/update functionality.
 */

import { useState, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Search, X, Globe } from 'lucide-react';
import { useAppStore } from '@/stores/appStore';
import * as api from '@/api';
import CommunityRecipeCard from './CommunityRecipeCard';
import EmptyState from '@/components/ui/EmptyState';

export default function CommunityRecipeList() {
  const { t } = useTranslation();
  const { communityRecipes, loadCommunityRecipes, showToast } = useAppStore();
  const [search, setSearch] = useState('');
  const [installingRecipe, setInstallingRecipe] = useState<string | null>(null);

  // Load community recipes on mount if not already loaded
  useEffect(() => {
    if (communityRecipes.length === 0) {
      loadCommunityRecipes();
    }
  }, [communityRecipes.length, loadCommunityRecipes]);

  // Filter recipes by search
  const filteredRecipes = useMemo(() => {
    if (!search.trim()) return communityRecipes;
    const query = search.toLowerCase();
    return communityRecipes.filter(
      (r) =>
        r.name.toLowerCase().includes(query) ||
        r.description?.toLowerCase().includes(query) ||
        r.tags.some((tag) => tag.toLowerCase().includes(query))
    );
  }, [communityRecipes, search]);

  // Handle install
  const handleInstall = async (name: string, force: boolean) => {
    setInstallingRecipe(name);
    try {
      const result = await api.installCommunityRecipe(name, force);
      if (result.status === 'ok') {
        showToast(t('recipes.installSuccess', { name }), 'success');
        // Refresh the list to update install status
        await loadCommunityRecipes();
      } else {
        showToast(result.error || t('recipes.installFailed'), 'error');
      }
    } catch (err) {
      console.error('Failed to install recipe:', err);
      showToast(t('recipes.installFailed'), 'error');
    } finally {
      setInstallingRecipe(null);
    }
  };

  // Handle update
  const handleUpdate = async (name: string) => {
    setInstallingRecipe(name);
    try {
      const result = await api.updateCommunityRecipe(name);
      if (result.status === 'ok') {
        showToast(t('recipes.updateSuccess', { name }), 'success');
        // Refresh the list to update status
        await loadCommunityRecipes();
      } else {
        showToast(result.error || t('recipes.updateFailed'), 'error');
      }
    } catch (err) {
      console.error('Failed to update recipe:', err);
      showToast(t('recipes.updateFailed'), 'error');
    } finally {
      setInstallingRecipe(null);
    }
  };

  // Empty state
  if (communityRecipes.length === 0) {
    return (
      <EmptyState
        Icon={Globe}
        title={t('recipes.noCommunityRecipes')}
        description={t('recipes.noCommunityRecipesDescription')}
      />
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Search Box */}
      <div className="search-box mb-4">
        <Search size={16} className="search-icon" />
        <input
          type="text"
          className="search-input"
          placeholder={t('recipes.searchCommunity')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label={t('recipes.searchCommunity')}
        />
        {search && (
          <button
            type="button"
            className="search-clear"
            onClick={() => setSearch('')}
            aria-label="Clear search"
          >
            <X size={14} />
          </button>
        )}
      </div>

      {/* Recipe Grid */}
      <div className="page-scroll flex-1">
        {filteredRecipes.length === 0 ? (
          <div className="text-center py-8 text-[var(--text-muted)]">
            {t('recipes.noResults')}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {filteredRecipes.map((recipe) => (
              <CommunityRecipeCard
                key={recipe.name}
                recipe={recipe}
                onInstall={handleInstall}
                onUpdate={handleUpdate}
                isInstalling={installingRecipe === recipe.name}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
