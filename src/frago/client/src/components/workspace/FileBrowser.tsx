/**
 * File Browser Component - Browse files in a project directory
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

  // Get file icon based on type
  function getFileIcon(file: FileInfo) {
    if (file.is_directory) {
      return <Folder className="w-5 h-5 text-blue-400" />;
    }

    const ext = file.name.split('.').pop()?.toLowerCase() || '';

    // Images
    if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'ico'].includes(ext)) {
      return <Image className="w-5 h-5 text-green-400" />;
    }

    // Videos
    if (['mp4', 'webm', 'mov', 'avi', 'mkv'].includes(ext)) {
      return <Video className="w-5 h-5 text-purple-400" />;
    }

    // Audio
    if (['mp3', 'wav', 'ogg', 'm4a', 'flac'].includes(ext)) {
      return <Music className="w-5 h-5 text-pink-400" />;
    }

    // 3D models
    if (['gltf', 'glb', 'obj'].includes(ext)) {
      return <Box className="w-5 h-5 text-orange-400" />;
    }

    // JSON
    if (ext === 'json') {
      return <FileJson className="w-5 h-5 text-yellow-400" />;
    }

    // Code files
    if (['js', 'ts', 'jsx', 'tsx', 'py', 'sh', 'bash', 'css', 'html', 'md'].includes(ext)) {
      return <FileCode className="w-5 h-5 text-cyan-400" />;
    }

    // Text/documents
    if (['txt', 'log', 'pdf'].includes(ext)) {
      return <FileText className="w-5 h-5 text-gray-400" />;
    }

    return <File className="w-5 h-5 text-muted-foreground" />;
  }

  const breadcrumbs = getBreadcrumbs();

  return (
    <div className="h-full flex flex-col">
      {/* Header with breadcrumb */}
      <div className="p-3 border-b border-border">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1 text-sm overflow-x-auto">
            {breadcrumbs.map((crumb, index) => (
              <span key={crumb.path} className="flex items-center">
                {index > 0 && <ChevronRight className="w-4 h-4 text-muted-foreground mx-1" />}
                <button
                  type="button"
                  onClick={() => handleNavigateToPath(crumb.path)}
                  className={`
                    px-2 py-1 rounded hover:bg-muted transition-colors whitespace-nowrap
                    ${index === breadcrumbs.length - 1 ? 'font-medium' : 'text-muted-foreground'}
                  `}
                >
                  {index === 0 ? <Home className="w-4 h-4" /> : crumb.name}
                </button>
              </span>
            ))}
          </div>
          <button
            type="button"
            onClick={handleOpenInFileManager}
            className="p-2 rounded-lg hover:bg-muted transition-colors"
            title={t('workspace.openInFileManager', 'Open in file manager')}
          >
            <ExternalLink className="w-4 h-4" />
          </button>
        </div>

        {/* Project info */}
        {project && (
          <div className="mt-2 flex items-center gap-4 text-xs text-muted-foreground">
            <span>{project.file_count} files</span>
            <span>{formatSize(project.total_size)}</span>
          </div>
        )}
      </div>

      {/* File list */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="p-4 space-y-2">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="animate-pulse h-10 bg-muted rounded" />
            ))}
          </div>
        ) : files.length === 0 ? (
          <div className="p-8 text-center text-muted-foreground">
            <Folder className="w-12 h-12 mx-auto mb-4 opacity-50" />
            <p>{t('workspace.emptyDirectory', 'This directory is empty')}</p>
          </div>
        ) : (
          <div className="divide-y divide-border">
            {files.map((file) => (
              <FileItem
                key={file.path}
                file={file}
                onNavigate={() => handleNavigate(file)}
                onView={() => handleViewFile(file)}
                onDownload={() => handleDownloadFile(file)}
                formatSize={formatSize}
                getIcon={() => getFileIcon(file)}
              />
            ))}
          </div>
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
      className="group flex items-center gap-3 px-4 py-2 hover:bg-muted/50 cursor-pointer"
      onClick={onNavigate}
    >
      <div className="flex-shrink-0">{getIcon()}</div>
      <div className="flex-1 min-w-0">
        <div className="text-sm truncate" title={file.name}>
          {file.name}
        </div>
        <div className="text-xs text-muted-foreground">
          {file.is_directory ? (
            t('workspace.directory', 'Directory')
          ) : (
            <>
              {formatSize(file.size)}
              {file.mime_type && <span className="ml-2">{file.mime_type}</span>}
            </>
          )}
        </div>
      </div>
      {!file.is_directory && (
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onView();
            }}
            className="p-1.5 rounded hover:bg-muted-foreground/20"
            title={t('workspace.view', 'View')}
          >
            <Eye className="w-4 h-4" />
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onDownload();
            }}
            className="p-1.5 rounded hover:bg-muted-foreground/20"
            title={t('workspace.download', 'Download')}
          >
            <Download className="w-4 h-4" />
          </button>
        </div>
      )}
    </div>
  );
}
