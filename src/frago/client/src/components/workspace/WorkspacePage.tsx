/**
 * Workspace Page - Browse run instance directories and files
 *
 * 页头走 C1 契约：标题 + 空格分隔的计数（此前是 `(1 projects)` 括号形式，与全站
 * 其余页面的 `122 local` 不一致）。右栏未选项目时的空态复用全站统一的 EmptyState，
 * 不再自画一套居中大图标。
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
import EmptyState from '@/components/ui/EmptyState';

export function WorkspacePage() {
  const { t, i18n } = useTranslation();
  const { currentProjectId, switchPage, showToast } = useAppStore();
  const currentLang = i18n.language?.startsWith('zh') ? 'zh' : 'en';

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

  // 计数与标题空格分隔，禁括号——与配方页的 `122 local` 同一形式。
  // 英文下单复数有别（1 project / 2 projects），中文的「项目」不分单复数。
  const projectWord = t('workspace.projects', 'projects');
  const countLabel =
    currentLang === 'zh'
      ? `${projects.length} ${projectWord}`
      : `${projects.length} ${projects.length === 1 ? 'project' : projectWord}`;

  return (
    <div className="ws-page">
      <header className="ui-page-header">
        <div className="ui-page-header-titles">
          <h1 className="ui-page-header-title">{t('workspace.title', 'Workspace')}</h1>
          {!loading && <span className="ui-page-header-meta">{countLabel}</span>}
        </div>
        <div className="ui-page-header-actions">
          <button
            type="button"
            onClick={handleRefresh}
            disabled={refreshing}
            className="ui-icon-btn"
            title={t('common.refresh', 'Refresh')}
            aria-label={t('common.refresh', 'Refresh')}
          >
            <RefreshCw size={16} strokeWidth={1.75} className={refreshing ? 'animate-spin' : ''} />
          </button>
        </div>
      </header>

      <div className="ws-split">
        <div className="ws-list-pane">
          <ProjectList
            projects={projects}
            loading={loading}
            selectedProjectId={currentProjectId}
            onSelectProject={handleSelectProject}
            onOpenInFileManager={handleOpenInFileManager}
          />
        </div>

        <div className="ws-detail-pane">
          {currentProjectId ? (
            <FileBrowser projectId={currentProjectId} />
          ) : (
            <div className="ws-empty">
              <EmptyState
                Icon={FolderOpen}
                title={t('workspace.selectProject', 'Select a project to browse files')}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
