/**
 * Community Recipe List Component
 *
 * Displays a searchable grid of community recipes with install/update functionality.
 */

import { useState, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Globe, AlertCircle, ExternalLink, Loader2 } from 'lucide-react';
import { useAppStore } from '@/stores/appStore';
import { useAsync } from '@/hooks/useAsync';
import * as api from '@/api';
import CommunityRecipeCard from './CommunityRecipeCard';
import EmptyState from '@/components/ui/EmptyState';
import type { GhCliStatus } from '@/types/pywebview';

interface CommunityRecipeListProps {
  /** 搜索框在配方页共用的工具栏里，这里只拿搜索词来筛。 */
  search: string;
}

export default function CommunityRecipeList({ search }: CommunityRecipeListProps) {
  const { t } = useTranslation();
  const { communityRecipes, loadCommunityRecipes, showToast } = useAppStore();
  const [installingRecipe, setInstallingRecipe] = useState<string | null>(null);
  const [loginLoading, setLoginLoading] = useState(false);

  // Check GitHub CLI status (loading/error handled by useAsync)
  const { data: ghStatus, loading: ghLoading, run: checkGhStatus } = useAsync<GhCliStatus>(
    api.checkGhCli
  );

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  // Show warning if gh CLI is not authenticated
  const showGhWarning = ghStatus && (!ghStatus.installed || !ghStatus.authenticated);

  // Only sent while nobody is logged in. An exhausted anonymous budget is the
  // usual reason this list comes back empty, so the numbers stay on screen
  // even when there is nothing to list.
  const quota = ghStatus?.rate_limit;

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* GitHub CLI Warning——配色走主题令牌里的琥珀色，深浅两套主题各自对得上。 */}
      {showGhWarning && (
        <div className="rl-notice">
          <AlertCircle size={16} className="rl-notice-icon" />
          <div className="flex-1 min-w-0">
            <h3 className="rl-notice-title">
              {!ghStatus.installed ? t('recipes.ghNotInstalled') : t('recipes.ghNotAuthenticated')}
            </h3>
            <p className="rl-notice-text">
              {!ghStatus.installed
                ? t('recipes.ghNotInstalledDesc')
                : t('recipes.ghNotAuthenticatedDesc')}
            </p>
            {quota && (
              <p className="rl-notice-text">
                {t('recipes.ghAnonQuota', {
                  remaining: quota.remaining,
                  limit: quota.limit,
                  minutes: Math.max(1, Math.ceil(quota.reset_in_seconds / 60)),
                })}
              </p>
            )}
            <div className="rl-notice-actions">
              {!ghStatus.installed ? (
                <a
                  href="https://cli.github.com/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="rl-notice-link"
                >
                  {t('recipes.installGhCli')}
                  <ExternalLink size={13} />
                </a>
              ) : (
                <button
                  type="button"
                  onClick={handleLogin}
                  disabled={loginLoading}
                  className="rl-btn rl-btn--warning"
                >
                  {loginLoading && <Loader2 size={14} className="animate-spin" />}
                  {t('recipes.loginToGitHub')}
                </button>
              )}
              <button
                type="button"
                onClick={checkGhStatus}
                disabled={ghLoading}
                className="rl-notice-link"
              >
                {ghLoading ? t('common.checking') : t('common.refresh')}
              </button>
            </div>
          </div>
        </div>
      )}

      {communityRecipes.length === 0 ? (
        // Nothing to list — but the warning above still explains why, so this
        // renders under it rather than in place of the whole page.
        <EmptyState
          Icon={Globe}
          title={t('recipes.noCommunityRecipes')}
          description={t('recipes.noCommunityRecipesDescription')}
        />
      ) : (
        <>
          {/* Recipe Grid */}
          <div className="page-scroll flex-1">
            {filteredRecipes.length === 0 ? (
              <div className="text-center py-8 text-[var(--text-muted)]">
                {t('recipes.noResults')}
              </div>
            ) : (
              <div className="rl-grid">
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
        </>
      )}
    </div>
  );
}
