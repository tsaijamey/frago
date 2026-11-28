/**
 * EmployeeAvatar — 统一的数字员工圆形头像组件（16 / 24 / 28 / 32 / 48 / 52 / 72px）。
 *
 * - 内置 Micah 头像经 `data:image/svg+xml;utf8,...` 放入 `<img>` 渲染，彻底隔离 SVG 内部 ID 碰撞；
 * - 本地上传的栅格图（PNG / JPEG / WebP）走同一套 `<img>` 圆形裁切与双主题描边管线；
 * - 订阅 `useDataStore` 中对应员工的最新 `avatar_resolved`，实现左栏 / 顶栏 / 员工卡片三处实时联动；
 * - 任何上传图加载失败（缺失 / 损坏 / 不可读）均经 `onError` 自动平稳回退至默认确定性 Micah 头像，绝不出现破图图标。
 */

import { useEffect, useMemo, useState, type MouseEvent, type ReactNode } from 'react';
import { useDataStore } from '@/stores/dataStore';
import {
  defaultAvatarSpec,
  generateMicahDataUri,
  type AvatarDraft,
  type EmployeeAvatarResolved,
} from '@/utils/employeeAvatar';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

export type AvatarSize = 16 | 24 | 28 | 32 | 48 | 52 | 72;

export type AvatarStatusBadge =
  | 'running'
  | 'waiting'
  | 'error'
  | 'callback'
  | 'completed';

export interface EmployeeAvatarProps {
  employeeId: string;
  /** 显式传入的已解析头像；若 store 内已有最新更新则以 store 为准以实现全站三处即时同步。 */
  avatar?: EmployeeAvatarResolved | null;
  /** 弹窗内草稿实时预览（传入后跳过 store，直接渲染草稿）。 */
  previewDraft?: AvatarDraft | null;
  size?: AvatarSize;
  statusBadge?: AvatarStatusBadge | null;
  statusLabel?: string;
  /** 可选：与左栏状态信号点对齐的无障碍属性（替代重复圆点）。 */
  statusSignal?: 'pending' | 'running' | 'done';
  statusTestId?: string;
  asButton?: boolean;
  onClick?: (e: MouseEvent<HTMLButtonElement>) => void;
  title?: string;
  ariaLabel?: string;
  className?: string;
  testId?: string;
  overlay?: ReactNode;
}

function resolveUploadUrl(rawUrl: string): string {
  if (!rawUrl) return '';
  if (
    rawUrl.startsWith('data:') ||
    rawUrl.startsWith('blob:') ||
    rawUrl.startsWith('http://') ||
    rawUrl.startsWith('https://')
  ) {
    return rawUrl;
  }
  return `${API_BASE_URL}${rawUrl}`;
}

export default function EmployeeAvatar({
  employeeId,
  avatar = null,
  previewDraft = null,
  size = 24,
  statusBadge = null,
  statusLabel,
  statusSignal,
  statusTestId,
  asButton = false,
  onClick,
  title,
  ariaLabel,
  className = '',
  testId,
  overlay,
}: EmployeeAvatarProps) {
  // 订阅 store 中该员工的最新头像解析态：弹窗保存后全站三处无需刷新即可毫秒级同步。
  const storeAvatar = useDataStore((state) => {
    if (previewDraft) return null;
    const found = state.employees?.find((e) => e.member_post_id === employeeId);
    return found?.avatar_resolved ?? null;
  });

  const effectiveResolved = storeAvatar ?? avatar;

  const fallbackMicahUri = useMemo(() => {
    const def = defaultAvatarSpec(employeeId);
    return generateMicahDataUri(def.seed, def.bg_color);
  }, [employeeId]);

  const computed = useMemo(() => {
    if (previewDraft) {
      if (previewDraft.kind === 'upload') {
        if (previewDraft.dataUrl) {
          return {
            src: resolveUploadUrl(previewDraft.dataUrl),
            kind: 'upload' as const,
            isUpload: true,
          };
        }
        return {
          src: fallbackMicahUri,
          kind: 'default' as const,
          isUpload: false,
        };
      }
      return {
        src: generateMicahDataUri(previewDraft.seed, previewDraft.bgColor),
        kind: previewDraft.kind,
        isUpload: false,
      };
    }

    if (
      effectiveResolved &&
      effectiveResolved.effective_kind === 'upload' &&
      effectiveResolved.upload_url
    ) {
      return {
        src: resolveUploadUrl(effectiveResolved.upload_url),
        kind: 'upload' as const,
        isUpload: true,
      };
    }

    if (effectiveResolved && effectiveResolved.seed) {
      return {
        src: generateMicahDataUri(
          effectiveResolved.seed,
          effectiveResolved.bg_color || defaultAvatarSpec(employeeId).bg_color
        ),
        kind: effectiveResolved.effective_kind,
        isUpload: false,
      };
    }

    return {
      src: fallbackMicahUri,
      kind: 'default' as const,
      isUpload: false,
    };
  }, [previewDraft, effectiveResolved, employeeId, fallbackMicahUri]);

  const [uploadFailed, setUploadFailed] = useState(false);

  // 每当源 URL 变动时重置错误回退态，确保重新上传有效图后立刻恢复显示。
  useEffect(() => {
    setUploadFailed(false);
  }, [computed.src]);

  const imgSrc = computed.isUpload && uploadFailed ? fallbackMicahUri : computed.src;
  const effectiveKind = computed.isUpload && uploadFailed ? 'default' : computed.kind;

  const rootCls = `emp-av emp-av-${size} ${className}`.trim();

  const inner = (
    <>
      <img
        className="emp-av-img"
        src={imgSrc}
        alt={ariaLabel || title || employeeId}
        width={size}
        height={size}
        draggable={false}
        onError={() => {
          if (computed.isUpload && !uploadFailed) {
            setUploadFailed(true);
          }
        }}
      />
      {statusBadge ? (
        <span
          className={`emp-av-st st-${statusBadge}`}
          data-testid={statusTestId ?? (testId ? `${testId}-status` : undefined)}
          data-status-badge={statusBadge}
          data-signal={statusSignal}
          role={statusSignal ? 'img' : undefined}
          aria-label={statusSignal ? statusLabel : undefined}
          title={statusLabel}
          aria-hidden={statusSignal ? undefined : 'true'}
        />
      ) : null}
      {overlay}
    </>
  );

  if (asButton) {
    return (
      <button
        type="button"
        className={rootCls}
        onClick={onClick}
        title={title}
        aria-label={ariaLabel || title || employeeId}
        data-testid={testId}
        data-avatar-kind={effectiveKind}
        data-avatar-fallback={
          uploadFailed
            ? 'client-error'
            : effectiveResolved?.fallback_reason || undefined
        }
      >
        {inner}
      </button>
    );
  }

  return (
    <span
      className={rootCls}
      title={title}
      aria-label={ariaLabel}
      data-testid={testId}
      data-avatar-kind={effectiveKind}
      data-avatar-fallback={
        uploadFailed
          ? 'client-error'
          : effectiveResolved?.fallback_reason || undefined
      }
    >
      {inner}
    </span>
  );
}
