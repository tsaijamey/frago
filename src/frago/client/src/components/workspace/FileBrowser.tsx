/**
 * File Browser Component - Browse files in a project directory
 *
 * 右栏这一块此前只有一个「向上」图标和「外部打开」图标，没有面包屑；空目录态是
 * 一套自画的居中大图标，与未选项目时的空态是两套尺寸。现在面包屑常驻、两级空态
 * 都走全站统一的 EmptyState。
 */

import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Folder,
  File,
  ChevronRight,
  Home,
  ExternalLink,
  Eye,
  Download,
  Image,
  Video,
  Music,
  FileText,
  FileCode,
  FileJson,
  Box,
} from 'lucide-react';
import { useAppStore } from '@/stores/appStore';
import * as api from '@/api';
import type { FileInfo, ProjectDetail } from '@/api';
import EmptyState from '@/components/ui/EmptyState';

interface FileBrowserProps {
  projectId: string;
}

export function FileBrowser({ projectId }: FileBrowserProps) {
  const { t } = useTranslation();
  const { showToast } = useAppStore();

  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [files, setFiles] = useState<FileInfo[]>([]);
  const [currentPath, setCurrentPath] = useState('');
  const [loading, setLoading] = useState(true);

  // Load project details and files
  useEffect(() => {
    loadProject();
    loadFiles('');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  async function loadProject() {
    try {
      const data = await api.getProject(projectId);
      setProject(data);
    } catch (error) {
      showToast('Failed to load project details', 'error');
    }
  }

  async function loadFiles(path: string) {
    try {
      setLoading(true);
      const data = await api.getProjectFiles(projectId, path);
      setFiles(data);
      setCurrentPath(path);
    } catch (error) {
      showToast('Failed to load files', 'error');
    } finally {
      setLoading(false);
    }
  }

  function handleNavigate(file: FileInfo) {
    if (file.is_directory) {
      loadFiles(file.path);
    }
  }

  function handleNavigateToPath(path: string) {
    loadFiles(path);
  }

  async function handleOpenInFileManager() {
    try {
      const result = await api.openProjectInFileManager(projectId, currentPath);
      if (result.success) {
        showToast(result.message, 'success');
      } else {
        showToast(result.message, 'error');
      }
    } catch (error) {
      showToast('Failed to open in file manager', 'error');
    }
  }

  async function handleViewFile(file: FileInfo) {
    try {
      const result = await api.viewProjectFile(projectId, file.path);
      if (result.success && result.url) {
        window.open(result.url, '_blank');
      } else {
        showToast(result.message, 'error');
      }
    } catch (error) {
      showToast('Failed to open file viewer', 'error');
    }
  }

  function handleDownloadFile(file: FileInfo) {
    const url = api.getFileDownloadUrl(projectId, file.path);
    const a = document.createElement('a');
    a.href = url;
    a.download = file.name;
    a.click();
  }

  // Build breadcrumb path segments
  function getBreadcrumbs(): { name: string; path: string }[] {
    const breadcrumbs = [{ name: 'Root', path: '' }];
    if (currentPath) {
      const parts = currentPath.split('/');
      let accumulated = '';
      for (const part of parts) {
        accumulated = accumulated ? `${accumulated}/${part}` : part;
        breadcrumbs.push({ name: part, path: accumulated });
      }
    }
    return breadcrumbs;
  }

  // Format file size
  function formatSize(bytes: number): string {
    if (bytes === 0) return '-';
    const units = ['B', 'KB', 'MB', 'GB'];
    let size = bytes;
    let unitIndex = 0;
    while (size >= 1024 && unitIndex < units.length - 1) {
      size /= 1024;
      unitIndex++;
    }
    return `${size.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
  }

  // Get file icon based on type. 一律走同一套中性描边；不再按扩展名分配八种彩字，
  // 那让一份文件清单看起来像调色板，且颜色在这里不承载任何语义。
  function getFileIcon(file: FileInfo) {
    const cls = 'ws-file-icon';
    if (file.is_directory) {
      return <Folder className={cls} size={16} strokeWidth={1.75} />;
    }

    const ext = file.name.split('.').pop()?.toLowerCase() || '';

    if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'ico'].includes(ext)) {
      return <Image className={cls} size={16} strokeWidth={1.75} />;
    }
    if (['mp4', 'webm', 'mov', 'avi', 'mkv'].includes(ext)) {
      return <Video className={cls} size={16} strokeWidth={1.75} />;
    }
    if (['mp3', 'wav', 'ogg', 'm4a', 'flac'].includes(ext)) {
      return <Music className={cls} size={16} strokeWidth={1.75} />;
    }
    if (['gltf', 'glb', 'obj'].includes(ext)) {
      return <Box className={cls} size={16} strokeWidth={1.75} />;
    }
    if (ext === 'json') {
      return <FileJson className={cls} size={16} strokeWidth={1.75} />;
    }
    if (['js', 'ts', 'jsx', 'tsx', 'py', 'sh', 'bash', 'css', 'html', 'md'].includes(ext)) {
      return <FileCode className={cls} size={16} strokeWidth={1.75} />;
    }
    if (['txt', 'log', 'pdf'].includes(ext)) {
      return <FileText className={cls} size={16} strokeWidth={1.75} />;
    }
    return <File className={cls} size={16} strokeWidth={1.75} />;
  }

  const breadcrumbs = getBreadcrumbs();

  return (
    <div className="ws-browser">
      {/* 面包屑栏：常驻在顶，路径随时可见可点。 */}
      <div className="ws-crumbs">
        <nav className="ws-crumbs-path" aria-label={t('workspace.path', 'Path')}>
          {breadcrumbs.map((crumb, index) => {
            const isLast = index === breadcrumbs.length - 1;
            return (
              <span key={crumb.path || 'root'} className="ws-crumb">
                {index > 0 && <ChevronRight className="ws-crumb-sep" size={13} strokeWidth={1.75} />}
                <button
                  type="button"
                  onClick={() => handleNavigateToPath(crumb.path)}
                  className={`ws-crumb-btn ${isLast ? 'is-current' : ''}`}
                  aria-current={isLast ? 'location' : undefined}
                >
                  {index === 0 ? <Home size={14} strokeWidth={1.75} /> : crumb.name}
                </button>
              </span>
            );
          })}
        </nav>

        <div className="ws-crumbs-actions">
          {project && (
            <span className="ws-crumbs-meta">
              {project.file_count} {t('workspace.files', 'files')} · {formatSize(project.total_size)}
            </span>
          )}
          <button
            type="button"
            onClick={handleOpenInFileManager}
            className="ui-icon-btn"
            title={t('workspace.openInFileManager', 'Open in file manager')}
            aria-label={t('workspace.openInFileManager', 'Open in file manager')}
          >
            <ExternalLink size={16} strokeWidth={1.75} />
          </button>
        </div>
      </div>

      {/* File list */}
      <div className="ws-file-list">
        {loading ? (
          <div className="ws-list">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="ws-skeleton ws-skeleton--row" />
            ))}
          </div>
        ) : files.length === 0 ? (
          <div className="ws-empty">
            <EmptyState
              Icon={Folder}
              title={t('workspace.emptyDirectory', 'This directory is empty')}
            />
          </div>
        ) : (
          files.map((file) => (
            <FileItem
              key={file.path}
              file={file}
              onNavigate={() => handleNavigate(file)}
              onView={() => handleViewFile(file)}
              onDownload={() => handleDownloadFile(file)}
              formatSize={formatSize}
              getIcon={() => getFileIcon(file)}
            />
          ))
        )}
      </div>
    </div>
  );
}

interface FileItemProps {
  file: FileInfo;
  onNavigate: () => void;
  onView: () => void;
  onDownload: () => void;
  formatSize: (bytes: number) => string;
  getIcon: () => React.ReactNode;
}

function FileItem({
  file,
  onNavigate,
  onView,
  onDownload,
  formatSize,
  getIcon,
}: FileItemProps) {
  const { t } = useTranslation();

  return (
    <div
      className={`ws-file-row ${file.is_directory ? 'is-dir' : ''}`}
      onClick={onNavigate}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if ((e.key === 'Enter' || e.key === ' ') && file.is_directory) {
          e.preventDefault();
          onNavigate();
        }
      }}
    >
      <span className="ws-file-glyph">{getIcon()}</span>
      <div className="ws-file-body">
        <div className="ws-file-name" title={file.name}>
          {file.name}
        </div>
        <div className="ws-file-meta">
          {file.is_directory ? (
            t('workspace.directory', 'Directory')
          ) : (
            <>
              {formatSize(file.size)}
              {file.mime_type && <span className="ws-file-mime">{file.mime_type}</span>}
            </>
          )}
        </div>
      </div>
      {!file.is_directory && (
        <div className="ws-file-actions">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onView();
            }}
            className="ui-icon-btn"
            title={t('workspace.view', 'View')}
            aria-label={t('workspace.view', 'View')}
          >
            <Eye size={15} strokeWidth={1.75} />
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onDownload();
            }}
            className="ui-icon-btn"
            title={t('workspace.download', 'Download')}
            aria-label={t('workspace.download', 'Download')}
          >
            <Download size={15} strokeWidth={1.75} />
          </button>
        </div>
      )}
    </div>
  );
}
