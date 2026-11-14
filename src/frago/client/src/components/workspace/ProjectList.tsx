/**
 * Project List Component - Shows all run instances
 *
 * 每条项目的第二行此前是 `theme_description`，而它常常与第一行的项目名一字不差，
 * 于是同一行字上下重复两遍（基线截图 `21-workspace-detail-light.png` 可见）。
 * 现在只在描述确实提供了新信息时才显示它，否则显示目录路径这类能区分项目的内容。
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Folder, FolderOpen, ExternalLink, Clock, Search, X } from 'lucide-react';
import type { ProjectInfo } from '@/api';
import EmptyState from '@/components/ui/EmptyState';

interface ProjectListProps {
  projects: ProjectInfo[];
  loading: boolean;
  selectedProjectId: string | null;
  onSelectProject: (runId: string) => void;
  onOpenInFileManager: (runId: string) => void;
}

/** 从 run_id 里去掉日期前缀，得到可读的项目名。 */
function getDisplayName(runId: string): string {
  const match = runId.match(/^\d{4}-?\d{2}-?\d{2}-(.+)$/);
  if (match) return match[1].replace(/-/g, ' ');
  return runId.replace(/-/g, ' ');
}

/**
 * 第二行要显示什么。
 *
 * 描述与项目名实质相同时（去掉空格、大小写、连字符后相等）就不显示——那是在
 * 原地重复，占一行却不给任何新信息。这种情况改显示目录名，至少能区分两个项目。
 */
function getSubtitle(project: ProjectInfo): string {
  const name = getDisplayName(project.run_id);
  const description = (project.theme_description || '').trim();
  const normalize = (text: string) => text.toLowerCase().replace(/[\s\-_]/g, '');
  if (description && normalize(description) !== normalize(name)) {
    return description;
  }
  return project.run_id;
}

export function ProjectList({
  projects,
  loading,
  selectedProjectId,
  onSelectProject,
  onOpenInFileManager,
}: ProjectListProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return projects;
    return projects.filter((project) => {
      const haystack = `${project.run_id} ${project.theme_description || ''}`.toLowerCase();
      return haystack.includes(q);
    });
  }, [projects, query]);

  if (loading) {
    return (
      <div className="ws-list">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="ws-skeleton" />
        ))}
      </div>
    );
  }

  if (projects.length === 0) {
    return (
      <div className="ws-empty">
        <EmptyState
          Icon={Folder}
          title={t('workspace.noProjects', 'No projects found')}
        />
      </div>
    );
  }

  return (
    <div className="ws-list-wrap">
      <div className="ws-filter">
        <div className="ui-search-box ws-filter-box">
          <Search size={16} strokeWidth={1.75} className="ui-search-box-icon" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('workspace.searchPlaceholder', 'Search projects…')}
            aria-label={t('workspace.searchPlaceholder', 'Search projects…')}
          />
          {query && (
            <button
              type="button"
              className="ui-search-box-clear"
              onClick={() => setQuery('')}
              aria-label={t('common.clear', 'Clear')}
            >
              <X size={14} strokeWidth={1.75} />
            </button>
          )}
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="ws-empty">
          <EmptyState Icon={Search} title={t('workspace.noMatches', 'Nothing matches that')} />
        </div>
      ) : (
        <div className="ws-list">
          {filtered.map((project) => (
            <ProjectItem
              key={project.run_id}
              project={project}
              isSelected={selectedProjectId === project.run_id}
              onSelect={() => onSelectProject(project.run_id)}
              onOpenInFileManager={() => onOpenInFileManager(project.run_id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface ProjectItemProps {
  project: ProjectInfo;
  isSelected: boolean;
  onSelect: () => void;
  onOpenInFileManager: () => void;
}

function ProjectItem({
  project,
  isSelected,
  onSelect,
  onOpenInFileManager,
}: ProjectItemProps) {
  const { t } = useTranslation();

  // Format date for display
  function formatDate(dateStr: string): string {
    if (!dateStr) return '';
    try {
      const date = new Date(dateStr);
      const now = new Date();
      const diffMs = now.getTime() - date.getTime();
      const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

      if (diffDays === 0) {
        return t('time.today', 'Today');
      } else if (diffDays === 1) {
        return t('time.yesterday', 'Yesterday');
      } else if (diffDays < 7) {
        return t('time.daysAgo', '{{count}} days ago', { count: diffDays });
      } else {
        return date.toLocaleDateString();
      }
    } catch {
      return dateStr;
    }
  }

  const subtitle = getSubtitle(project);
  const isActive = project.status === 'active';

  return (
    <div
      className={`ws-item ${isSelected ? 'is-selected' : ''}`}
      onClick={onSelect}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onSelect();
        }
      }}
    >
      <span className="ws-item-icon">
        {isSelected ? <FolderOpen size={17} strokeWidth={1.75} /> : <Folder size={17} strokeWidth={1.75} />}
      </span>

      <div className="ws-item-body">
        <div className="ws-item-title" title={project.run_id}>
          {getDisplayName(project.run_id)}
        </div>
        <div className="ws-item-subtitle" title={subtitle}>
          {subtitle}
        </div>
        <div className="ws-item-meta">
          <Clock size={12} strokeWidth={1.75} />
          <span>{formatDate(project.last_accessed)}</span>
          <span className={`ws-status ${isActive ? 'is-active' : ''}`}>
            {isActive ? t('workspace.statusActive', 'active') : project.status}
          </span>
        </div>
      </div>

      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onOpenInFileManager();
        }}
        className="ui-icon-btn ws-item-open"
        title={t('workspace.openInFileManager', 'Open in file manager')}
        aria-label={t('workspace.openInFileManager', 'Open in file manager')}
      >
        <ExternalLink size={15} strokeWidth={1.75} />
      </button>
    </div>
  );
}
