/**
 * Project List Component - Shows all run instances
 */

import { useTranslation } from 'react-i18next';
import { Folder, ExternalLink, Clock } from 'lucide-react';
import type { ProjectInfo } from '@/api';

interface ProjectListProps {
  projects: ProjectInfo[];
  loading: boolean;
  selectedProjectId: string | null;
  onSelectProject: (runId: string) => void;
  onOpenInFileManager: (runId: string) => void;
}

export function ProjectList({
  projects,
  loading,
  selectedProjectId,
  onSelectProject,
  onOpenInFileManager,
}: ProjectListProps) {
  const { t } = useTranslation();

  if (loading) {
    return (
      <div className="p-4 space-y-3">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="animate-pulse">
            <div className="h-16 bg-muted rounded-lg" />
          </div>
        ))}
      </div>
    );
  }

  if (projects.length === 0) {
    return (
      <div className="p-8 text-center text-muted-foreground">
        <Folder className="w-12 h-12 mx-auto mb-4 opacity-50" />
        <p>{t('workspace.noProjects', 'No projects found')}</p>
      </div>
    );
  }

  return (
    <div className="p-2 space-y-1">
      {projects.map((project) => (
        <ProjectItem
          key={project.run_id}
          project={project}
          isSelected={selectedProjectId === project.run_id}
          onSelect={() => onSelectProject(project.run_id)}
          onOpenInFileManager={() => onOpenInFileManager(project.run_id)}
        />
      ))}
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

  // Get display name from run_id (remove date prefix if present)
  function getDisplayName(runId: string): string {
    // Pattern: YYYYMMDD-name or YYYY-MM-DD-name
    const match = runId.match(/^\d{4}-?\d{2}-?\d{2}-(.+)$/);
    if (match) {
      return match[1].replace(/-/g, ' ');
    }
    return runId.replace(/-/g, ' ');
  }

  return (
    <div
      className={`
        group p-3 rounded-lg cursor-pointer transition-colors
        ${isSelected
          ? 'bg-primary/10 border border-primary/30'
          : 'hover:bg-muted border border-transparent'
        }
      `}
      onClick={onSelect}
    >
      <div className="flex items-start gap-3">
        <Folder className={`w-5 h-5 mt-0.5 ${isSelected ? 'text-primary' : 'text-muted-foreground'}`} />
        <div className="flex-1 min-w-0">
          <div className="font-medium text-sm truncate" title={project.run_id}>
            {getDisplayName(project.run_id)}
          </div>
          {project.theme_description && (
            <div className="text-xs text-muted-foreground truncate mt-0.5" title={project.theme_description}>
              {project.theme_description}
            </div>
          )}
          <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
            <Clock className="w-3 h-3" />
            <span>{formatDate(project.last_accessed)}</span>
            <span className={`
              px-1.5 py-0.5 rounded text-[10px]
              ${project.status === 'active' ? 'bg-green-500/20 text-green-400' : 'bg-muted text-muted-foreground'}
            `}>
              {project.status}
            </span>
          </div>
        </div>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onOpenInFileManager();
          }}
          className="p-1.5 rounded opacity-0 group-hover:opacity-100 hover:bg-muted-foreground/20 transition-all"
          title={t('workspace.openInFileManager', 'Open in file manager')}
        >
          <ExternalLink className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
