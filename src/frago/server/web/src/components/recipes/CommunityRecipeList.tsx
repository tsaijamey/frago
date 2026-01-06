/**
 * Community Recipe List Component
 *
 * Displays a searchable grid of community recipes with install/update functionality.
 */

import { useState, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Search, X, Globe, AlertCircle, ExternalLink, Loader2 } from 'lucide-react';
import { useAppStore } from '@/stores/appStore';
import * as api from '@/api';
import CommunityRecipeCard from './CommunityRecipeCard';
import EmptyState from '@/components/ui/EmptyState';
import type { GhCliStatus } from '@/types/pywebview';

export default function CommunityRecipeList() {
  const { t } = useTranslation();
  const { communityRecipes, loadCommunityRecipes, showToast } = useAppStore();
  const [search, setSearch] = useState('');
  const [installingRecipe, setInstallingRecipe] = useState<string | null>(null);
  const [ghStatus, setGhStatus] = useState<GhCliStatus | null>(null);
  const [ghLoading, setGhLoading] = useState(false);
  const [loginLoading, setLoginLoading] = useState(false);

  // Check GitHub CLI status
  const checkGhStatus = async () => {
    try {
      setGhLoading(true);
      const status = await api.checkGhCli();
      setGhStatus(status);
    } catch (err) {
      console.error('Failed to check gh status:', err);
    } finally {
      setGhLoading(false);
    }
  };

  // Handle GitHub login
  const handleLogin = async () => {
    try {
      setLoginLoading(true);
      const result = await api.ghAuthLogin();
      if (result.status === 'ok') {
        showToast(t('recipes.ghLoginStarted'), 'info');
        // Poll for auth status after a delay
        setTimeout(async () => {
          await checkGhStatus();
          await loadCommunityRecipes();
          setLoginLoading(false);
        }, 5000);
      } else {
        showToast(result.error || t('recipes.ghLoginFailed'), 'error');
        setLoginLoading(false);
      }
    } catch (err) {
      console.error('Failed to start gh login:', err);
      showToast(t('recipes.ghLoginFailed'), 'error');
      setLoginLoading(false);
    }
  };

  // Load community recipes and check gh status on mount
  useEffect(() => {
    checkGhStatus();
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

  // Handle uninstall
  const handleUninstall = async (name: string) => {
    setInstallingRecipe(name);
    try {
      const result = await api.uninstallCommunityRecipe(name);
      if (result.status === 'ok') {
        showToast(t('recipes.uninstallSuccess', { name }), 'success');
        // Refresh the list to update status
        await loadCommunityRecipes();
      } else {
        showToast(result.error || t('recipes.uninstallFailed'), 'error');
      }
    } catch (err) {
      console.error('Failed to uninstall recipe:', err);
      showToast(t('recipes.uninstallFailed'), 'error');
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

  // Show warning if gh CLI is not authenticated
  const showGhWarning = ghStatus && (!ghStatus.installed || !ghStatus.authenticated);

  return (
    <div className="flex flex-col h-full">
      {/* GitHub CLI Warning */}
      {showGhWarning && (
        <div className="mb-4 p-3 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg">
          <div className="flex items-start gap-3">
            <AlertCircle size={18} className="text-yellow-600 dark:text-yellow-400 mt-0.5 flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <h3 className="text-sm font-medium text-yellow-800 dark:text-yellow-200">
                {!ghStatus.installed
                  ? t('recipes.ghNotInstalled')
                  : t('recipes.ghNotAuthenticated')}
              </h3>
              <p className="mt-1 text-sm text-yellow-700 dark:text-yellow-300">
                {!ghStatus.installed
                  ? t('recipes.ghNotInstalledDesc')
                  : t('recipes.ghNotAuthenticatedDesc')}
              </p>
              <div className="mt-2 flex items-center gap-2">
                {!ghStatus.installed ? (
                  <a
                    href="https://cli.github.com/"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-sm text-yellow-700 dark:text-yellow-300 hover:underline"
                  >
                    {t('recipes.installGhCli')}
                    <ExternalLink size={14} />
                  </a>
                ) : (
                  <button
                    type="button"
                    onClick={handleLogin}
                    disabled={loginLoading}
                    className="inline-flex items-center gap-1 px-3 py-1 text-sm bg-yellow-600 hover:bg-yellow-700 text-white rounded-md disabled:opacity-50"
                  >
                    {loginLoading && <Loader2 size={14} className="animate-spin" />}
                    {t('recipes.loginToGitHub')}
                  </button>
                )}
                <button
                  type="button"
                  onClick={checkGhStatus}
                  disabled={ghLoading}
                  className="text-sm text-yellow-600 dark:text-yellow-400 hover:underline disabled:opacity-50"
                >
                  {ghLoading ? t('common.checking') : t('common.refresh')}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

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
                onUninstall={handleUninstall}
                isInstalling={installingRecipe === recipe.name}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
