/**
 * Workspace Page - Browse run instance directories and files
 */

import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FolderOpen, RefreshCw } from 'lucide-react';
import { useAppStore } from '@/stores/appStore';
import { useAutoRefresh } from '@/hooks/useAutoRefresh';
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

  // 项目目录在本机随时会多出一份。挂载时取一次就不动的话，人跑完一个配方回到这
  // 页，新产出的那份不在清单里，而界面看起来一切正常。
  const firstLoad = useRef(true);
  useAutoRefresh(loadProjects, { intervalMs: 30_000 });

  async function loadProjects() {
    // 只有开局那一趟举「装载中」：定时那几趟一举起来，左栏每 30 秒空一次。
    const silent = !firstLoad.current;
    firstLoad.current = false;
    if (!silent) setLoading(true);
    try {
      const data = await api.getProjects();
      setProjects(data);
    } catch (error) {
      // 定时那几趟失手不弹提示——人什么都没做却蹦出一条报错，只会当界面坏了。
      if (!silent) showToast('Failed to load projects', 'error');
    } finally {
      if (!silent) setLoading(false);
    }
  }

  async function handleRefresh() {
    try {
      setRefreshing(true);
      const data = await api.refreshProjects();
      setProjects(data);
    } catch (error) {
      showToast('Failed to refresh projects', 'error');
    } finally {
      setRefreshing(false);
    }
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
        <div className="w-[480px] border-r border-border overflow-y-auto">
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
