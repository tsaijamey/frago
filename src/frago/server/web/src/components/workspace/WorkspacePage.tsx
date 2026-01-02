/**
 * Workspace Page - Browse run instance directories and files
 */

import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { FolderOpen, RefreshCw } from 'lucide-react';
import { useAppStore } from '@/stores/appStore';
import * as api from '@/api';
import type { ProjectInfo } from '@/api';
import { ProjectList } from './ProjectList';
import { FileBrowser } from './FileBrowser';

export function WorkspacePage() {
  const { t } = useTranslation();
  const { currentProjectId, switchPage, showToast } = useAppStore();

  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  // Load projects on mount
  useEffect(() => {
    loadProjects();
  }, []);

  async function loadProjects() {
    try {
      setLoading(true);
      const data = await api.getProjects();
      setProjects(data);
    } catch (error) {
      showToast('Failed to load projects', 'error');
    } finally {
      setLoading(false);
    }
  }

  async function handleRefresh() {
    setRefreshing(true);
    await loadProjects();
    setRefreshing(false);
  }

  function handleSelectProject(runId: string) {
    switchPage('project_detail', runId);
  }

  async function handleOpenInFileManager(runId: string) {
    try {
      const result = await api.openProjectInFileManager(runId);
      if (result.success) {
        showToast(result.message, 'success');
      } else {
        showToast(result.message, 'error');
      }
    } catch (error) {
      showToast('Failed to open in file manager', 'error');
    }
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-border">
        <div className="flex items-center gap-2">
          <FolderOpen className="w-5 h-5 text-muted-foreground" />
          <h1 className="text-lg font-semibold">{t('workspace.title', 'Workspace')}</h1>
          <span className="text-sm text-muted-foreground">
            ({projects.length} {t('workspace.projects', 'projects')})
          </span>
        </div>
        <button
          type="button"
          onClick={handleRefresh}
          disabled={refreshing}
          className="p-2 rounded-lg hover:bg-muted transition-colors disabled:opacity-50"
          title={t('common.refresh', 'Refresh')}
        >
          <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Project List - Left Panel */}
        <div className="w-80 border-r border-border overflow-y-auto">
          <ProjectList
            projects={projects}
            loading={loading}
            selectedProjectId={currentProjectId}
            onSelectProject={handleSelectProject}
            onOpenInFileManager={handleOpenInFileManager}
          />
        </div>

        {/* File Browser - Right Panel */}
        <div className="flex-1 overflow-hidden">
          {currentProjectId ? (
            <FileBrowser projectId={currentProjectId} />
          ) : (
            <div className="h-full flex items-center justify-center text-muted-foreground">
              <div className="text-center">
                <FolderOpen className="w-12 h-12 mx-auto mb-4 opacity-50" />
                <p>{t('workspace.selectProject', 'Select a project to browse files')}</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
