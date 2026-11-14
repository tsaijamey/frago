/**
 * PromptComposerBox — 工作台统一的提示词输入盒组件（Composer、NewSessionModal、SelectionQuote 共用）。
 *
 * 统一承载以下交互能力，避免多处重复维护或体验不一致：
 * 1. 行首或空白后敲 `/`（挑 skill）或 `@`（挑员工）触发统一的 `DirectiveMenu` 候选菜单
 *    （支持键盘上下移动、Enter/Tab 挑中、Esc 关闭）；
 * 2. 挑中的员工或 skill 转为输入框顶部的 `EmployeeQuote` / `SkillQuote`（共用 `DirectiveQuote`）圆角签，可逐个移除；
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
import type { EmployeeItem, SkillItem } from '@/types/api';
import DirectiveMenu, {
  directiveQuery,
  filterEmployees,
  filterSkills,
  mentionQuery,
  slashQuery,
  type DirectiveMenuEntry,
} from './DirectiveMenu';
import { EmployeeQuote } from './EmployeeQuote';
import { SkillQuote } from './SkillQuote';

const LINE_PX = 24;

export { directiveQuery, mentionQuery, slashQuery };

/**
 * 从剪贴板事件数据中提取文件列表：优先读取 `files`，若为空则回退遍历 `items`（`kind === 'file'`），
 * 兼容不同浏览器/系统截图粘贴入剪贴板时的载体差异。
 */
export function extractClipboardFiles(
  data: Pick<DataTransfer, 'files' | 'items'> | null | undefined
): File[] {
  if (!data) return [];
  if (data.files && data.files.length > 0) {
    return Array.from(data.files);
  }
  if (data.items && data.items.length > 0) {
    const out: File[] = [];
    for (let i = 0; i < data.items.length; i += 1) {
      const item = data.items[i];
      if (item && item.kind === 'file') {
        const file = item.getAsFile?.() ?? null;
        if (file) out.push(file);
      }
    }
    return out;
  }
  return [];
}

export interface PromptComposerBoxProps {
  text: string;
  onChangeText: (value: string) => void;
  skills: SkillItem[];
  onAddSkill: (skill: SkillItem) => void;
  onRemoveSkill: (name: string) => void;
  employees?: EmployeeItem[];
  onAddEmployee?: (employee: EmployeeItem) => void;
  onRemoveEmployee?: (id: string) => void;
  employeesCatalog?: EmployeeItem[];
  onAddFiles: (files: FileList | File[]) => void | Promise<void>;
  attachCount: number;
  canSubmit: boolean;
  submitting?: boolean;
  onSubmit: () => void | Promise<void>;
  /** 技能/员工菜单未打开时按 Esc 的回调（如浮窗内取消或收起）。 */
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
  /** `/` 与 `@` 候选菜单弹出方向：底部栏传 `'above'`，新建会话中部卡片传 `'below'`。 */
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
  employees = [],
  onAddEmployee,
  onRemoveEmployee,
  employeesCatalog,
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

  // ── 敲 `/` 挑 skill 与敲 `@` 挑员工（统一走 DirectiveMenu） ──
  const allSkills = useDataStore((s) => s.skills);
  const loadSkills = useDataStore((s) => s.loadSkills);
  const storeEmployees = useDataStore((s) => s.employees);
  const loadEmployees = useDataStore((s) => s.loadEmployees);

  const allEmployees = useMemo(
    () => (employeesCatalog && employeesCatalog.length > 0 ? employeesCatalog : storeEmployees),
    [employeesCatalog, storeEmployees]
  );

  const [caret, setCaret] = useState(0);
  const [menuActive, setMenuActive] = useState(0);
  // Esc 关掉的是"这一个 `/` 或 `@`"：记下它的位置，光标还停在它后面就不再弹；换一个位置照弹。
  const [dismissedAt, setDismissedAt] = useState<string | null>(null);

  const rawDirective = focused && !disabled ? directiveQuery(text, caret) : null;
  const directive =
    rawDirective && (rawDirective.trigger === '/' || Boolean(onAddEmployee))
      ? rawDirective
      : null;
  const directiveId = directive ? `${directive.trigger}:${directive.start}` : null;
  const menuOpen = directive !== null && directiveId !== dismissedAt;
  const menuQuery = directive?.query ?? '';

  const menuEntries = useMemo<DirectiveMenuEntry<SkillItem | EmployeeItem>[]>(() => {
    if (!menuOpen || !directive) return [];
    if (directive.trigger === '/') {
      return filterSkills(allSkills, menuQuery).map((item) => ({
        key: item.name,
        trigger: '/',
        name: item.name,
        description: item.description,
        raw: item,
      }));
    }
    return filterEmployees(allEmployees, menuQuery).map((item) => ({
      key: item.member_post_id,
      trigger: '@',
      name: item.member_post_id,
      title: item.title,
      badge: item.agent_kernel,
      description: item.work_scope || item.description,
      raw: item,
    }));
  }, [menuOpen, directive, allSkills, allEmployees, menuQuery]);

  useEffect(() => setMenuActive(0), [directive?.trigger, menuQuery]);

  const directiveGone = directive === null;
  useEffect(() => {
    if (directiveGone) setDismissedAt(null);
  }, [directiveGone]);

  const skillsWanted = menuOpen && directive?.trigger === '/' && allSkills.length === 0;
  useEffect(() => {
    if (skillsWanted) void loadSkills();
  }, [skillsWanted, loadSkills]);

  const employeesWanted =
    menuOpen &&
    directive?.trigger === '@' &&
    Boolean(onAddEmployee) &&
    allEmployees.length === 0;
  useEffect(() => {
    if (employeesWanted) void loadEmployees();
  }, [employeesWanted, loadEmployees]);

  const pickDirectiveEntry = useCallback(
    (entry: DirectiveMenuEntry<SkillItem | EmployeeItem>) => {
      if (!directive) return;
      const next = text.slice(0, directive.start) + text.slice(caret);
      if (entry.trigger === '/') {
        onAddSkill(entry.raw as SkillItem);
      } else if (onAddEmployee) {
        onAddEmployee(entry.raw as EmployeeItem);
      }
      caretTo.current = directive.start;
      setCaret(directive.start);
      onChangeText(next);
    },
    [directive, text, caret, onAddSkill, onAddEmployee, onChangeText, caretTo]
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
    (files: FileList | File[] | null) => {
      if (!files || files.length === 0) return;
      void onAddFiles(files);
    },
    [onAddFiles]
  );

  const handlePaste = useCallback(
    (e: ClipboardEvent<HTMLTextAreaElement>) => {
      const extracted = extractClipboardFiles(e.clipboardData);
      if (extracted.length === 0) return;
      e.preventDefault();
      takeFiles(e.clipboardData?.files?.length ? e.clipboardData.files : extracted);
    },
    [takeFiles]
  );

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (menuOpen && !e.nativeEvent.isComposing) {
        if (e.key === 'Escape') {
          e.preventDefault();
          setDismissedAt(directiveId);
          return;
        }
        if (menuEntries.length) {
          if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            const step = e.key === 'ArrowDown' ? 1 : -1;
            setMenuActive((i) => (i + step + menuEntries.length) % menuEntries.length);
            return;
          }
          if ((e.key === 'Enter' && !e.metaKey && !e.ctrlKey && !e.shiftKey) || e.key === 'Tab') {
            e.preventDefault();
            pickDirectiveEntry(menuEntries[Math.min(menuActive, menuEntries.length - 1)]);
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
    [
      canSubmit,
      onSubmit,
      onCancel,
      menuOpen,
      menuEntries,
      menuActive,
      directiveId,
      pickDirectiveEntry,
    ]
  );

  const hasDirectives = employees.length > 0 || skills.length > 0;

  return (
    <div
      className={`relative rounded-[12px] border transition-[border-color,box-shadow] ${
        submitting
          ? 'border-border-strong'
          : focused
            ? 'border-[var(--border-accent)] [box-shadow:var(--focus-ring)]'
            : 'border-border-strong'
      } ${className}`}
    >
      {menuOpen && directive ? (
        <DirectiveMenu
          trigger={directive.trigger}
          entries={menuEntries}
          activeIndex={Math.min(menuActive, Math.max(menuEntries.length - 1, 0))}
          placement={menuPlacement}
          titleText={
            directive.trigger === '@'
              ? t('workbench.employees.menuTitle')
              : t('workbench.skills.menuTitle')
          }
          testId={directive.trigger === '@' ? 'employee-menu' : 'skill-menu'}
          itemTestId={directive.trigger === '@' ? 'employee-menu-item' : 'skill-menu-item'}
          emptyTestId={directive.trigger === '@' ? 'employee-menu-empty' : 'skill-menu-empty'}
          emptyText={
            directive.trigger === '@'
              ? t('workbench.employees.noMatch')
              : t('workbench.skills.noMatch')
          }
          onSelect={pickDirectiveEntry}
          onHover={setMenuActive}
        />
      ) : null}

      {/* 内描边与决策卡同一套：浅色下把白底卡片从白底页面上勾出来，box-shadow 不参与布局。 */}
      <div className="relative min-w-0 rounded-[12px] bg-bg-card px-3 py-2.5 [box-shadow:inset_0_0_0_1px_var(--border-card)]">
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

        {hasDirectives ? (
          <div
            data-testid={`${idPrefix}-skills`}
            data-has-employees={employees.length > 0 ? 'yes' : 'no'}
            data-has-skills={skills.length > 0 ? 'yes' : 'no'}
            className="mb-1.5 flex flex-wrap gap-1.5"
          >
            {employees.map((emp) => (
              <EmployeeQuote
                key={emp.member_post_id}
                id={emp.member_post_id}
                title={emp.title}
                kernel={emp.agent_kernel}
                description={emp.work_scope || emp.description}
                onRemove={onRemoveEmployee ? () => onRemoveEmployee(emp.member_post_id) : undefined}
              />
            ))}
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
          className="min-h-[48px] w-full resize-none bg-transparent text-[16px] leading-6 text-text-primary outline-none focus-visible:shadow-none placeholder:text-text-muted disabled:cursor-not-allowed"
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
