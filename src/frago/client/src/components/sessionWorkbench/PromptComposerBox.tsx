/**
 * PromptComposerBox — 会话详情底部输入区（Composer）与内联新建会话起始页（NewSessionModal）
 * 共用的统一提示词输入盒组件。
 *
 * 统一承载以下交互能力，避免两处重复维护或体验不一致：
 * 1. 行首或空白后敲 `/` 触发 `SkillMenu` 候选菜单（支持键盘上下移动、Enter/Tab 挑中、Esc 关闭）；
 * 2. 挑中的 skill 转为输入框顶部的 `SkillQuote` 圆角签，可逐个移除；
 * 3. 文本域随内容自动伸缩高度（`minLines` ~ `maxLines`），支持 `Cmd/Ctrl + Enter` 提交；
 * 4. 统一处理粘贴截图/文件（拦截二进制避免乱码落入文本框）、点击选文件、拖拽文件上传。
 */

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ClipboardEvent,
  type KeyboardEvent,
  type MutableRefObject,
  type ReactNode,
} from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, Paperclip, Plus, SendHorizontal } from 'lucide-react';
import { MAX_ATTACHMENTS } from '@/hooks/useAttachments';
import { useDataStore } from '@/stores/dataStore';
import type { SkillItem } from '@/types/api';
import SkillMenu, { filterSkills } from './SkillMenu';
import { SkillQuote } from './SkillQuote';

const LINE_PX = 24;

/**
 * 光标前面那一截是不是正在点名 skill：行首或空白后的一个 `/`，后面跟着还没打空格的几个字。
 *
 * 要求 `/` 前面是行首或空白，是为了不把 `src/frago` 这种路径里的斜杠当成要挑 skill。
 * 对上了回 `/` 所在的位置与后面那几个字，对不上回 null。
 */
export function slashQuery(text: string, caret: number): { start: number; query: string } | null {
  const before = text.slice(0, caret);
  const m = /(^|\s)\/([^\s/]*)$/.exec(before);
  if (!m) return null;
  return { start: before.length - m[2].length - 1, query: m[2] };
}

export interface PromptComposerBoxProps {
  text: string;
  onChangeText: (value: string) => void;
  skills: SkillItem[];
  onAddSkill: (skill: SkillItem) => void;
  onRemoveSkill: (name: string) => void;
  onAddFiles: (files: FileList | File[]) => void | Promise<void>;
  attachCount: number;
  canSubmit: boolean;
  submitting?: boolean;
  onSubmit: () => void | Promise<void>;
  /** 技能菜单未打开时按 Esc 的回调（如浮窗内取消或收起）。 */
  onCancel?: () => void;
  autoFocus?: boolean;
  disabled?: boolean;
  placeholder?: string;
  /** 测试与无障碍标识前缀：详情输入区传 `'composer'`，新建会话传 `'new-session'`。 */
  idPrefix?: string;
  textareaId?: string;
  ariaLabelledBy?: string;
  minLines?: number;
  maxLines?: number;
  /** `/` 技能菜单弹出方向：底部栏传 `'above'`，新建会话中部卡片传 `'below'`。 */
  menuPlacement?: 'above' | 'below';
  /** 外部（如引用、批注打包填入）需要控制光标落点时传入。 */
  caretToRef?: MutableRefObject<number | null>;
  /** 框内顶部标题或提示插槽（如新建会话的标题行）。 */
  headerSlot?: ReactNode;
  /** 文本框上方横幅插槽（如文档批注打包提示条）。 */
  bannerSlot?: ReactNode;
  /** 文本框与底部操作栏之间的附件条插槽。 */
  attachmentSlot?: ReactNode;
  /** 附件按钮文案：不传时画紧凑 `+` 图标按钮，传入时画带文字的回形针按钮。 */
  attachButtonLabel?: string;
  /** 底部操作栏右侧（提交按钮左侧）的附加操作插槽。 */
  rightActionsSlot?: ReactNode;
  submitLabel: string;
  submittingLabel?: string;
  submitAriaLabel?: string;
  submitTestId?: string;
  className?: string;
}

export default function PromptComposerBox({
  text,
  onChangeText,
  skills,
  onAddSkill,
  onRemoveSkill,
  onAddFiles,
  attachCount,
  canSubmit,
  submitting = false,
  onSubmit,
  onCancel,
  autoFocus = false,
  disabled = false,
  placeholder = '',
  idPrefix = 'composer',
  textareaId,
  ariaLabelledBy,
  minLines = 2,
  maxLines = 9,
  menuPlacement = 'above',
  caretToRef,
  headerSlot,
  bannerSlot,
  attachmentSlot,
  attachButtonLabel,
  rightActionsSlot,
  submitLabel,
  submittingLabel,
  submitAriaLabel,
  submitTestId,
  className = '',
}: PromptComposerBoxProps) {
  const { t } = useTranslation();
  const box = useRef<HTMLTextAreaElement>(null);
  const internalCaretTo = useRef<number | null>(null);
  const caretTo = caretToRef ?? internalCaretTo;
  const filePicker = useRef<HTMLInputElement>(null);
  const [focused, setFocused] = useState(autoFocus);

  useEffect(() => {
    if (autoFocus) box.current?.focus();
  }, [autoFocus]);

  // ── 敲 `/` 挑 skill ──
  const allSkills = useDataStore((s) => s.skills);
  const loadSkills = useDataStore((s) => s.loadSkills);
  const [caret, setCaret] = useState(0);
  const [menuActive, setMenuActive] = useState(0);
  // Esc 关掉的是"这一个 `/`"：记下它的位置，光标还停在它后面就不再弹；换一个 `/` 照弹。
  const [dismissedAt, setDismissedAt] = useState<number | null>(null);
  const slash = focused && !disabled ? slashQuery(text, caret) : null;
  const menuOpen = slash !== null && slash.start !== dismissedAt;
  const menuQuery = slash?.query ?? '';
  const menuItems = useMemo(
    () => (menuOpen ? filterSkills(allSkills, menuQuery) : []),
    [menuOpen, allSkills, menuQuery]
  );

  useEffect(() => setMenuActive(0), [menuQuery]);

  const slashGone = slash === null;
  useEffect(() => {
    if (slashGone) setDismissedAt(null);
  }, [slashGone]);

  const menuWanted = menuOpen && allSkills.length === 0;
  useEffect(() => {
    if (menuWanted) void loadSkills();
  }, [menuWanted, loadSkills]);

  const pickSkill = useCallback(
    (skill: SkillItem) => {
      if (!slash) return;
      const next = text.slice(0, slash.start) + text.slice(caret);
      onAddSkill(skill);
      caretTo.current = slash.start;
      setCaret(slash.start);
      onChangeText(next);
    },
    [slash, text, caret, onAddSkill, onChangeText, caretTo]
  );

  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = 'auto';
    const content = el.scrollHeight;
    const ceiling = maxLines * LINE_PX;
    el.style.height = `${Math.min(Math.max(content, minLines * LINE_PX), ceiling)}px`;
    el.style.overflowY = content > ceiling ? 'auto' : 'hidden';
    if (caretTo.current !== null) {
      const at = caretTo.current;
      caretTo.current = null;
      el.focus();
      el.setSelectionRange(at, at);
      el.scrollTop = el.scrollHeight;
    }
  }, [text, minLines, maxLines, caretTo]);

  const takeFiles = useCallback(
    (files: FileList | null) => {
      if (!files || files.length === 0) return;
      void onAddFiles(files);
    },
    [onAddFiles]
  );

  const handlePaste = useCallback(
    (e: ClipboardEvent<HTMLTextAreaElement>) => {
      const files = e.clipboardData?.files;
      if (!files || files.length === 0) return;
      e.preventDefault();
      takeFiles(files);
    },
    [takeFiles]
  );

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (menuOpen && !e.nativeEvent.isComposing) {
        if (e.key === 'Escape') {
          e.preventDefault();
          setDismissedAt(slash?.start ?? null);
          return;
        }
        if (menuItems.length) {
          if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            const step = e.key === 'ArrowDown' ? 1 : -1;
            setMenuActive((i) => (i + step + menuItems.length) % menuItems.length);
            return;
          }
          if ((e.key === 'Enter' && !e.metaKey && !e.ctrlKey && !e.shiftKey) || e.key === 'Tab') {
            e.preventDefault();
            pickSkill(menuItems[Math.min(menuActive, menuItems.length - 1)]);
            return;
          }
        }
      }
      if (e.key === 'Escape' && onCancel && !e.nativeEvent.isComposing) {
        e.preventDefault();
        onCancel();
        return;
      }
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        if (canSubmit) void onSubmit();
      }
    },
    [canSubmit, onSubmit, onCancel, menuOpen, menuItems, menuActive, slash, pickSkill]
  );

  return (
    <div
      className={`relative rounded-[12px] border transition-colors ${
        focused || submitting ? 'border-text-muted' : 'border-border-strong'
      } ${className}`}
    >
      {menuOpen ? (
        <SkillMenu
          items={menuItems}
          active={Math.min(menuActive, Math.max(menuItems.length - 1, 0))}
          onPick={pickSkill}
          onHover={setMenuActive}
          placement={menuPlacement}
        />
      ) : null}

      <div className="relative min-w-0 rounded-[12px] bg-bg-card px-3 py-2.5">
        <input
          ref={filePicker}
          type="file"
          multiple
          hidden
          data-testid={`${idPrefix}-file`}
          onChange={(e) => {
            takeFiles(e.target.files);
            e.target.value = '';
          }}
        />

        {headerSlot ? <div className="mb-1.5">{headerSlot}</div> : null}

        {skills.length ? (
          <div data-testid={`${idPrefix}-skills`} className="mb-1.5 flex flex-wrap gap-1.5">
            {skills.map((skill) => (
              <SkillQuote
                key={skill.name}
                name={skill.name}
                description={skill.description}
                onRemove={() => onRemoveSkill(skill.name)}
              />
            ))}
          </div>
        ) : null}

        {bannerSlot}

        <textarea
          ref={box}
          id={textareaId}
          aria-labelledby={ariaLabelledBy}
          data-testid={`${idPrefix}-input`}
          autoFocus={autoFocus}
          value={text}
          onChange={(e) => {
            onChangeText(e.target.value);
            setCaret(e.target.selectionStart ?? e.target.value.length);
          }}
          onSelect={(e) => setCaret(e.currentTarget.selectionStart ?? 0)}
          onPaste={handlePaste}
          onKeyDown={handleKeyDown}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          disabled={disabled}
          rows={minLines}
          placeholder={placeholder}
          className="min-h-[48px] w-full resize-none bg-transparent text-[13px] leading-6 text-text-primary outline-none focus-visible:shadow-none placeholder:text-text-muted disabled:cursor-not-allowed"
        />

        {attachmentSlot ? <div className="mt-1.5">{attachmentSlot}</div> : null}

        <div className="mt-1 flex items-center gap-2">
          {attachButtonLabel ? (
            <button
              type="button"
              data-testid={`${idPrefix}-pick`}
              disabled={disabled || attachCount >= MAX_ATTACHMENTS}
              onClick={() => filePicker.current?.click()}
              className="inline-flex h-7 items-center gap-1.5 rounded-[8px] px-2.5 text-[12px] text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary disabled:opacity-40"
            >
              <Paperclip size={13} strokeWidth={1.5} />
              {attachButtonLabel}
            </button>
          ) : (
            <button
              type="button"
              data-testid={`${idPrefix}-pick`}
              aria-label={t('workbench.composer.addAttachment')}
              title={t('workbench.composer.addAttachment')}
              disabled={disabled || attachCount >= MAX_ATTACHMENTS}
              onClick={() => filePicker.current?.click()}
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[8px] text-text-muted transition-colors hover:bg-bg-hover hover:text-text-primary disabled:opacity-40"
            >
              <Plus size={16} strokeWidth={1.5} />
            </button>
          )}

          <span className="flex-1" />

          {rightActionsSlot}

          <button
            type="button"
            data-testid={submitTestId ?? `${idPrefix}-send`}
            aria-label={submitAriaLabel ?? submitLabel}
            disabled={!canSubmit}
            onClick={() => void onSubmit()}
            className={`flex h-7 shrink-0 items-center gap-1.5 rounded-[8px] px-3 text-[12px] font-medium disabled:cursor-not-allowed disabled:opacity-40 ${
              submitting
                ? 'bg-bg-active text-text-secondary'
                : 'bg-accent-primary text-[var(--text-on-accent)]'
            }`}
          >
            {submitting ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <SendHorizontal size={13} />
            )}
            {submitting ? (submittingLabel ?? submitLabel) : submitLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
