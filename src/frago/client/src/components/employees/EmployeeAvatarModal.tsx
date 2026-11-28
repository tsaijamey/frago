/**
 * EmployeeAvatarModal — 数字员工自定义头像弹窗（1:1 对齐主原型与双主题规格）。
 *
 * - 72 / 48 / 28 / 24px 四尺寸实时联动预览（24px 含运行态镂空角标）；
 * - 本地安全栅格图片上传预览与替换（仅允许 PNG / JPG / WebP，≤ 2 MB，前端+服务端双重拦截 SVG/HTML 等）；
 * - 内置 DiceBear Micah 4×2「换一批」离线挑选（零外网请求）；
 * - 一键「恢复默认」与「取消 / ESC / 点遮罩」不污染已保存状态；
 * - 保存成功后调用后端 API 持久化并同步全局 store，驱动全站三处（左栏、顶栏、员工卡片）实时更新。
 */

import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { AlertCircle, Check, Loader2, Paperclip, RefreshCw, X } from 'lucide-react';
import EmployeeAvatar from './EmployeeAvatar';
import {
  resetEmployeeAvatar,
  updateEmployeeAvatarMicah,
  uploadEmployeeAvatarFile,
  type EmployeeAvatarResolved,
  type EmployeePost,
} from '@/hooks/useEmployees';
import {
  avatarDraftFromResolved,
  defaultAvatarSpec,
  findPaletteEntry,
  generateShuffleBatch,
  isDraftDefault,
  readFileAsDataUrl,
  validateAvatarFileClient,
  type AvatarCandidate,
  type AvatarDraft,
} from '@/utils/employeeAvatar';

export interface EmployeeAvatarTarget {
  member_post_id: string;
  title: string;
  avatar_resolved?: EmployeeAvatarResolved | null;
}

export interface EmployeeAvatarModalProps {
  employee: EmployeeAvatarTarget | null;
  onClose: () => void;
  onSaved?: (updated: EmployeePost) => void;
}

export default function EmployeeAvatarModal({
  employee,
  onClose,
  onSaved,
}: EmployeeAvatarModalProps) {
  const { t, i18n } = useTranslation();
  const isZh = i18n.language?.startsWith('zh');

  const [draft, setDraft] = useState<AvatarDraft | null>(null);
  const [batch, setBatch] = useState(0);
  const [saving, setSaving] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [toastMsg, setToastMsg] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // 打开弹窗或切换员工时初始化草稿，关闭时彻底重置。
  useEffect(() => {
    if (!employee) {
      setDraft(null);
      setBatch(0);
      setSaving(false);
      setErrorMsg(null);
      setToastMsg(null);
      return;
    }
    setDraft(avatarDraftFromResolved(employee.member_post_id, employee.avatar_resolved));
    setBatch(0);
    setSaving(false);
    setErrorMsg(null);
    setToastMsg(null);
  }, [employee]);

  // ESC 键关闭弹窗且不污染原状态。
  useEffect(() => {
    if (!employee) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !saving) {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [employee, saving, onClose]);

  const candidates = useMemo<AvatarCandidate[]>(() => {
    if (!employee) return [];
    return generateShuffleBatch(employee.member_post_id, batch);
  }, [employee, batch]);

  const handleFileChange = useCallback(
    async (e: ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      // 允许连续重复选同一文件名重新触发 change
      e.target.value = '';
      if (!file || !employee) return;

      setErrorMsg(null);
      setToastMsg(null);

      const check = validateAvatarFileClient(file);
      if (!check.ok) {
        if (check.error === 'file_too_large') {
          setErrorMsg(t('employees.avatar.errors.fileTooLarge'));
        } else if (check.error === 'empty_file') {
          setErrorMsg(t('employees.avatar.errors.emptyFile'));
        } else {
          setErrorMsg(t('employees.avatar.errors.unsupportedType'));
        }
        return;
      }

      try {
        const dataUrl = await readFileAsDataUrl(file);
        setDraft({
          kind: 'upload',
          dataUrl,
          fileName: file.name,
          mimeType: check.mimeType,
        });
        setToastMsg(t('employees.avatar.toastUploadReady'));
      } catch {
        setErrorMsg(t('employees.avatar.errors.readFailed'));
      }
    },
    [employee, t]
  );

  const handlePickCandidate = useCallback(
    (cand: AvatarCandidate) => {
      setErrorMsg(null);
      setToastMsg(null);
      setDraft({
        kind: 'micah',
        seed: cand.seed,
        bgColor: cand.bgColor,
        paletteId: cand.paletteId,
      });
    },
    []
  );

  const handleShuffle = useCallback(() => {
    setErrorMsg(null);
    setBatch((b) => b + 1);
  }, []);

  const handleResetDraft = useCallback(() => {
    if (!employee) return;
    const def = defaultAvatarSpec(employee.member_post_id);
    setErrorMsg(null);
    setDraft({
      kind: 'default',
      seed: def.seed,
      bgColor: def.bg_color,
      paletteId: def.palette_id,
    });
    setToastMsg(t('employees.avatar.toastResetDraft'));
  }, [employee, t]);

  const handleSave = useCallback(async () => {
    if (!employee || !draft || saving) return;
    setSaving(true);
    setErrorMsg(null);
    try {
      let updated: EmployeePost;
      if (draft.kind === 'upload') {
        if (draft.existingUrl && draft.dataUrl === draft.existingUrl) {
          onClose();
          return;
        }
        updated = await uploadEmployeeAvatarFile(employee.member_post_id, {
          data_url: draft.dataUrl,
          filename: draft.fileName,
          content_type: draft.mimeType,
        });
      } else if (isDraftDefault(employee.member_post_id, draft)) {
        updated = await resetEmployeeAvatar(employee.member_post_id);
      } else {
        updated = await updateEmployeeAvatarMicah(employee.member_post_id, {
          seed: draft.seed,
          bg_color: draft.bgColor,
          palette_id: draft.paletteId,
        });
      }
      onSaved?.(updated);
      onClose();
    } catch (e) {
      setErrorMsg(
        e instanceof Error ? e.message : t('employees.avatar.errors.saveFailedPlain')
      );
    } finally {
      setSaving(false);
    }
  }, [employee, draft, saving, onClose, onSaved, t]);

  if (!employee || !draft) return null;

  const isDef = isDraftDefault(employee.member_post_id, draft);
  const activePalette =
    draft.kind !== 'upload'
      ? findPaletteEntry(draft.bgColor, draft.paletteId)
      : undefined;
  const paletteLabel = activePalette
    ? isZh
      ? activePalette.labelZh
      : activePalette.labelEn
    : draft.kind !== 'upload'
      ? draft.bgColor
      : '';

  const content = (
    <div
      className="avmodal show"
      data-testid="avatar-picker-modal"
      role="dialog"
      aria-modal="true"
      aria-label={t('employees.avatar.modalTitle')}
    >
      <div
        className="avbd"
        data-testid="avatar-modal-backdrop"
        onClick={() => {
          if (!saving) onClose();
        }}
      />

      <div className="avwin" data-testid="avatar-modal-window">
        <div className="avh">
          <h3>{t('employees.avatar.modalTitle')}</h3>
          <span className="av-emp-tag">@{employee.member_post_id}</span>
          <button
            type="button"
            className="av-icon-btn avclose"
            data-testid="avatar-modal-close"
            title={t('employees.avatar.closeTitle')}
            aria-label={t('common.close')}
            disabled={saving}
            onClick={onClose}
          >
            <X size={15} strokeWidth={1.7} />
          </button>
        </div>

        <div className="avb">
          {/* 四尺寸实时联动预览区：72px 主预览 + 48px 卡片 + 28px 顶栏 + 24px 左栏（含运行角标） */}
          <div className="av-preview-box">
            <div className="av-preview-main">
              <EmployeeAvatar
                employeeId={employee.member_post_id}
                previewDraft={draft}
                size={72}
                testId="avatar-preview-main"
                ariaLabel={employee.title}
              />
              <div className="av-preview-info">
                <div className="av-preview-name truncate">{employee.title}</div>
                <div className="av-preview-src">
                  {draft.kind === 'upload' ? (
                    <>
                      <span className="av-src-pill is-custom">
                        {t('employees.avatar.sourceUpload')}
                      </span>
                      <span className="truncate">{draft.fileName}</span>
                    </>
                  ) : isDef ? (
                    <>
                      <span className="av-src-pill">
                        {t('employees.avatar.sourceDefault')}
                      </span>
                      <span>{t('employees.avatar.sourceDefaultDesc')}</span>
                    </>
                  ) : (
                    <>
                      <span className="av-src-pill">
                        {t('employees.avatar.sourceMicah')}
                      </span>
                      <span>
                        {paletteLabel} · {draft.bgColor}
                      </span>
                    </>
                  )}
                </div>
              </div>
            </div>

            <div
              className="av-scales"
              title={t('employees.avatar.previewScalesHint')}
            >
              <div className="av-scale-item">
                <EmployeeAvatar
                  employeeId={employee.member_post_id}
                  previewDraft={draft}
                  size={48}
                  testId="avatar-preview-48"
                />
                <span>{t('employees.avatar.scaleCard')}</span>
              </div>
              <div className="av-scale-item">
                <EmployeeAvatar
                  employeeId={employee.member_post_id}
                  previewDraft={draft}
                  size={28}
                  testId="avatar-preview-28"
                />
                <span>{t('employees.avatar.scaleHeader')}</span>
              </div>
              <div className="av-scale-item">
                <EmployeeAvatar
                  employeeId={employee.member_post_id}
                  previewDraft={draft}
                  size={24}
                  statusBadge="running"
                  statusLabel={t('employees.sessions.running')}
                  testId="avatar-preview-24"
                />
                <span>{t('employees.avatar.scaleRail')}</span>
              </div>
            </div>
          </div>

          {/* 区段 1：本地图片安全上传预览替换 */}
          <div className="av-sec">
            <div className="av-sec-h">
              <span className="av-sec-t">{t('employees.avatar.uploadSectionTitle')}</span>
              <span className="av-sec-sub">{t('employees.avatar.uploadSectionSub')}</span>
            </div>
            <div className="av-upload-row">
              <input
                ref={fileInputRef}
                type="file"
                data-testid="avatar-file-input"
                accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp"
                className="hidden"
                onChange={(e) => void handleFileChange(e)}
              />
              <button
                type="button"
                className="emp-btn"
                data-testid="avatar-upload-btn"
                disabled={saving}
                onClick={() => fileInputRef.current?.click()}
              >
                <Paperclip size={13} strokeWidth={1.6} />
                {t('employees.avatar.uploadChoose')}
              </button>
              <div className="av-upload-meta">
                <div className="t truncate">
                  {draft.kind === 'upload'
                    ? draft.fileName
                    : t('employees.avatar.uploadNone')}
                </div>
                <div className="d">{t('employees.avatar.uploadHint')}</div>
              </div>
            </div>
          </div>

          {/* 区段 2：内置 DiceBear Micah 4×2 换一批挑选 */}
          <div className="av-sec">
            <div className="av-sec-h">
              <span className="av-sec-t">{t('employees.avatar.micahSectionTitle')}</span>
              <button
                type="button"
                className="emp-btn av-shuffle-btn"
                data-testid="avatar-shuffle-btn"
                disabled={saving}
                onClick={handleShuffle}
              >
                <RefreshCw size={12} strokeWidth={1.7} />
                {t('employees.avatar.shuffle')}
              </button>
            </div>
            <div
              className="av-cand-grid"
              data-testid="avatar-candidate-grid"
              data-batch={batch}
            >
              {candidates.map((cand, idx) => {
                const isSelected =
                  draft.kind !== 'upload' &&
                  draft.seed === cand.seed &&
                  draft.bgColor.toLowerCase() === cand.bgColor.toLowerCase();
                const candDraft: AvatarDraft = {
                  kind: 'micah',
                  seed: cand.seed,
                  bgColor: cand.bgColor,
                  paletteId: cand.paletteId,
                };
                return (
                  <button
                    key={`${cand.seed}|${cand.bgColor}`}
                    type="button"
                    className={`av-cand ${isSelected ? 'on' : ''}`}
                    data-testid={`avatar-cand-${idx}`}
                    data-cand-key={`${cand.seed}|${cand.bgColor}`}
                    aria-pressed={isSelected}
                    disabled={saving}
                    onClick={() => handlePickCandidate(cand)}
                  >
                    <EmployeeAvatar
                      employeeId={employee.member_post_id}
                      previewDraft={candDraft}
                      size={52}
                    />
                    <span className="av-cand-lbl">
                      <i
                        className="av-cand-swatch"
                        style={{ background: cand.bgColor }}
                        aria-hidden="true"
                      />
                      {isZh ? cand.labelZh : cand.labelEn}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {errorMsg ? (
            <div
              className="av-error"
              role="alert"
              data-testid="avatar-modal-error"
            >
              <AlertCircle size={13} strokeWidth={1.8} className="shrink-0" />
              <span>{errorMsg}</span>
            </div>
          ) : null}

          {toastMsg && !errorMsg ? (
            <div className="av-toast" data-testid="avatar-modal-toast">
              <Check size={13} strokeWidth={2} className="shrink-0" />
              <span>{toastMsg}</span>
            </div>
          ) : null}
        </div>

        <div className="avf">
          <button
            type="button"
            className="emp-btn av-ghost-btn"
            data-testid="avatar-reset-btn"
            title={t('employees.avatar.resetTitle')}
            disabled={saving}
            onClick={handleResetDraft}
          >
            <RefreshCw size={12} strokeWidth={1.7} />
            {t('employees.avatar.reset')}
          </button>
          <span className="grow" />
          <button
            type="button"
            className="emp-btn av-ghost-btn"
            data-testid="avatar-cancel-btn"
            disabled={saving}
            onClick={onClose}
          >
            {t('common.cancel')}
          </button>
          <button
            type="button"
            className="emp-btn emp-btn-primary"
            data-testid="avatar-save-btn"
            disabled={saving}
            onClick={() => void handleSave()}
          >
            {saving ? (
              <Loader2 size={13} className="cs-spin" />
            ) : (
              <Check size={13} strokeWidth={2} />
            )}
            {t('employees.avatar.save')}
          </button>
        </div>
      </div>
    </div>
  );

  if (typeof document !== 'undefined' && document.body) {
    return createPortal(content, document.body);
  }
  return content;
}
