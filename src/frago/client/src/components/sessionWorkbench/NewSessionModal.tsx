/**
 * NewSessionModal — 从浏览器起一场会话，并且**由人来挑用哪个客户端**。
 *
 * 建出来的是一场**普通会话**，不是什么网页专用的东西：它跟着各家自己的规矩起，记录写到
 * 各家自己该去的地方，下一次扫描它就是左栏里一行普通会话——同一个详情面板、同一条发送
 * 路径、同一份数据。
 *
 * ## 对话框在问三件事，标题就得是这三句问话
 *
 * 从前三块的标题是「用哪个客户端」「起始目录」「第一句话」——每一句都在说这一格**装的
 * 是什么**，没有一句在说**人该据此拿什么主意**。第一次打开的人于是要自己去猜：client 是
 * 谁？为什么非要挑个目录？下面那个框是必填的吗？三格并排、字重相同、没有分隔，看上去
 * 像三道无来由的填空题。
 *
 * 现在三块的标题是三句并列的问话——「交给哪个 agent 跑」「在哪个项目里干活」「想让它做
 * 什么」——各自跟一句灰字说清挑错了会怎样，块与块之间拿一道分隔线断开。人从上往下读一
 * 遍就知道自己在做什么决定，不必先理解 frago 的内部构造。
 *
 * ## 客户端怎么挑：为什么是一排可换行的按钮，而不是下拉框
 *
 * 从前这里只会起 claude。人本机装着 codex、装着 opencode，一个都挑不到——不是有意的
 * 取舍，是这条路上根本没有"挑一家"这个概念。
 *
 * 补的时候要先想清楚一件事：**将来这个数字会长。** 所以三个候选形态各自摆一摆：
 *
 * - 下拉框。省地方，但把"本机现在有几家可用"这件事藏进了一次点击。这恰恰是人第一次
 *   打开这个对话框最想知道的一句话。
 * - 一排单选按钮。看得见，但没装的那几家要么占着位置、要么整个消失；后者会让人以为
 *   frago 不支持它。
 * - **一排可换行的按钮，能挑的在前，用不了的折在一句话后面。** 选的是这个。可用的通常
 *   只有一两家，一眼看完；将来接到八家十家也只是多换一行，不会把对话框撑爆。用不了的
 *   一个不丢，点开就看得见"为什么用不了"——是没装，还是记录读不进工作台。
 *
 * 名单一个字都不写死在这里，来自 `/api/workbench/agents`（见 `useAgentClients`）。
 * 前端再抄一份的话，接新家的人改完 driver 会发现界面上它根本不出现。
 *
 * ## 工作目录：最近用过的那几个之外还得有路
 *
 * 后端一直收这个参数，只是从前界面从没送过，于是浏览器起的会话全落在家目录。挑它正是
 * 这个对话框存在的另一半理由。
 *
 * 但从前能挑的只有"最近开过会话的那几个目录"，外加家目录。**第一次用 frago 的人那份清
 * 单是空的**，于是唯一的出路是照着记忆手打一整条绝对路径——打错一个字就落进一个空目
 * 录，而人当场看不出来。所以这里补了一条翻目录的路（`browseDirectories`）：一层一层点
 * 进去，停在哪一层就是选了哪一层，子目录多的时候还能打字筛。
 *
 * 翻目录与最近用过的是**同一块地方的两个面**，不是上下堆着的两份清单：对话框一共就这么
 * 高，两份都摊开会把第一句话那一块挤出屏幕。
 *
 * ## 第一句话可以带图，也可以不写
 *
 * 从前这里只收文字。人开一场会话十有八九是为了说"照着这张图改"，而那张图在这一步贴不
 * 进来——只能先随便打一句、等会话起来、再到中栏输入区补发一次，而第一句话恰恰是最需要
 * 它的那一句。三条路（粘贴、拖入、选文件）与中栏输入区共用同一份判据（`useAttachments`）
 * 和同一条展示条（`AttachmentStrip`）：同一个动作在两处得是同一个结果。
 *
 * 它一直都是可以留空的（有图就能建），但界面从来没说过这件事，看上去跟上面两格一样是
 * 必填。那句"可以留空"现在写在框底下。
 *
 * ## 创建之后：编号未必当场就有
 *
 * claude 接受由调用方指定编号，点完创建当场就知道这一场叫什么，直接跳进去。codex 与
 * opencode 的编号由它们自己分配，frago 要等会话起来后认领——那一段空窗如实说出来，
 * 由 `useSessionLaunch` 拿着把手去等（见 `waitForSession`）。假装编号已经有了，界面会
 * 跳进一场并不存在的会话，人看到一片空记录流，以为刚开的会话丢了。
 *
 * **这个对话框只管建，不管等。** 建出去之后它自己关掉，等待那一段由左栏的启动卡与中栏
 * 的启动面板接手——对话框继续挂在屏幕上会挡住新会话本身，而人此刻要看的正是它。
 */

import { useCallback, useEffect, useMemo, useRef, useState, type ClipboardEvent, type DragEvent } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CornerLeftUp,
  Folder,
  FolderSearch,
  Home,
  Info,
  Search,
  Sparkles,
  SquareTerminal,
  X,
} from 'lucide-react';
import { browseDirectories, getSystemDirectories } from '../../api/client';
import { getRecentDirectories, addRecentDirectory } from '../../utils/recentDirectories';
import AttachmentStrip from '@/components/ui/AttachmentStrip';
import { useAttachments } from '@/hooks/useAttachments';
import { modKey } from '@/hooks/usePlatform';
import { useDataStore } from '@/stores/dataStore';
import { usePageStore } from '@/stores/pageStore';
import {
  employeeInitials,
  employeeSummary,
  kernelLabel,
  resolveEmployeeColor,
} from '@/components/employees/employeeMeta';
import {
  fetchEmployee,
  useEmployeeList,
  type EmployeeDetail,
  type EmployeePost,
} from '@/hooks/useEmployees';
import { withTilde } from './filePaths';
import PromptComposerBox, { extractClipboardFiles } from './PromptComposerBox';
import type { DirectoryListing, EmployeeItem, SkillItem } from '@/types/api';
import {
  createSession,
  pickDefaultAgent,
  rememberLastAgent,
  useAgentClients,
  agentReasonText,
  type PendingLaunch,
} from '@/hooks/useAgentClients';

const LAST_EMPLOYEE_KEY = 'frago-workbench-last-employee';
const DEFAULT_EMPLOYEE_CWD = '~/.frago';
/** 顶栏单行最多直接露出的快捷员工胶囊数；其余全部收进可搜索下拉面板，保证 100 个员工也不撑爆版面。 */
const MAX_QUICK_EMPLOYEES = 3;
/** 目录卡片内联展示的最近目录上限，更多目录走「翻目录挑」。 */
const MAX_INLINE_DIR_CHOICES = 6;

function readLastEmployee(): string | null {
  try {
    return localStorage.getItem(LAST_EMPLOYEE_KEY);
  } catch {
    return null;
  }
}

function rememberLastEmployee(memberPostId: string): void {
  try {
    localStorage.setItem(LAST_EMPLOYEE_KEY, memberPostId);
  } catch {
    // 隐私模式或配额满了写不进就算了
  }
}

interface NewSessionModalProps {
  isOpen: boolean;
  onClose: () => void;
  /**
   * 建出去了。第二个参数是人刚打的那第一句话——面板交接后就没别的地方存了，而接下来
   * 那十几秒的等待要靠它告诉人"你在等的是哪一句"。
   */
  onCreated: (launch: PendingLaunch, text: string) => void;
}

interface DirChoice {
  path: string;
  hint?: string;
}

export default function NewSessionModal({ isOpen, onClose, onCreated }: NewSessionModalProps) {
  const { t } = useTranslation();
  const switchPage = usePageStore((s) => s.switchPage);
  const allSkills = useDataStore((s) => s.skills);
  const [choices, setChoices] = useState<DirChoice[]>([]);
  const [dir, setDir] = useState('');
  const [text, setText] = useState('');
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [agent, setAgent] = useState<string | null>(null);
  const [showUnavailable, setShowUnavailable] = useState(false);
  const [browsing, setBrowsing] = useState(false);
  const [listing, setListing] = useState<DirectoryListing | null>(null);
  const [browseLoading, setBrowseLoading] = useState(false);
  const [filter, setFilter] = useState('');
  /**
   * 选中的员工岗位编号：
   * - `null`：尚未根据员工列表完成初始化；
   * - `''`：用户明确切到了「普通会话（不带员工）」；
   * - 非空字符串：选中的 `member_post_id`。
   */
  const [selectedEmployeeId, setSelectedEmployeeId] = useState<string | null>(null);
  const [empDetail, setEmpDetail] = useState<EmployeeDetail | null>(null);
  const [empDetailError, setEmpDetailError] = useState<string | null>(null);
  const [ctxOpen, setCtxOpen] = useState(false);
  const [empPickerOpen, setEmpPickerOpen] = useState(false);
  const [empQuery, setEmpQuery] = useState('');
  const empPickerRef = useRef<HTMLDivElement | null>(null);
  const empSearchRef = useRef<HTMLInputElement | null>(null);
  const { images, documents, addFiles, removeImage, removeDocument, clear, count } =
    useAttachments();
  /** 连点几层，回来的顺序未必是点下去的顺序。只认最后一次点的那一层。 */
  const browseSeq = useRef(0);

  const addSkill = useCallback((skill: SkillItem) => {
    setSkills((prev) => (prev.some((s) => s.name === skill.name) ? prev : [...prev, skill]));
  }, []);
  const removeSkill = useCallback((name: string) => {
    setSkills((prev) => prev.filter((s) => s.name !== name));
  }, []);

  const empState = useEmployeeList(isOpen);
  const selectedEmployee = useMemo<EmployeePost | null>(() => {
    if (!selectedEmployeeId) return null;
    return empState.employees.find((e) => e.member_post_id === selectedEmployeeId) ?? null;
  }, [empState.employees, selectedEmployeeId]);

  /**
   * 顶栏单行快捷员工胶囊（最多 3 个）：若当前选中的员工不在前 3 个里，把它置顶到第 1 位，
   * 保证人刚从 100 个员工的搜索面板里挑中的那一位当场出现在顶栏上。
   */
  const quickEmployees = useMemo<EmployeePost[]>(() => {
    const list = empState.employees;
    if (list.length <= MAX_QUICK_EMPLOYEES) return list;
    const head = list.slice(0, MAX_QUICK_EMPLOYEES);
    if (!selectedEmployee) return head;
    if (head.some((e) => e.member_post_id === selectedEmployee.member_post_id)) return head;
    return [selectedEmployee, ...head.slice(0, MAX_QUICK_EMPLOYEES - 1)];
  }, [empState.employees, selectedEmployee]);

  /** 可搜索下拉面板里的过滤结果（支持按名称、编号、职责描述、内核名筛选）。 */
  const filteredEmployees = useMemo<EmployeePost[]>(() => {
    const q = empQuery.trim().toLowerCase();
    if (!q) return empState.employees;
    return empState.employees.filter(
      (e) =>
        e.title.toLowerCase().includes(q) ||
        e.member_post_id.toLowerCase().includes(q) ||
        (e.description || '').toLowerCase().includes(q) ||
        (e.work_scope || '').toLowerCase().includes(q) ||
        (e.agent_kernel || '').toLowerCase().includes(q)
    );
  }, [empState.employees, empQuery]);

  const clients = useAgentClients(isOpen);
  const selectable = useMemo(() => clients.agents.filter((a) => a.selectable), [clients.agents]);
  const unavailable = useMemo(() => clients.agents.filter((a) => !a.selectable), [clients.agents]);
  const chosen = useMemo(
    () => selectable.find((a) => a.agent_type === agent) ?? null,
    [selectable, agent]
  );

  const applyEmployee = useCallback(
    (post: EmployeeItem | null, persist = false) => {
      setCtxOpen(false);
      setEmpDetail(null);
      setEmpDetailError(null);
      setEmpPickerOpen(false);
      setEmpQuery('');
      if (!post) {
        setSelectedEmployeeId('');
        if (persist) rememberLastEmployee('');
        setSkills([]);
        if (choices.length > 0) {
          setDir(choices[0].path);
        }
        if (clients.agents.length > 0) {
          setAgent(pickDefaultAgent(clients.agents, clients.fallbackDefault));
        }
        return;
      }
      setSelectedEmployeeId(post.member_post_id);
      if (persist) rememberLastEmployee(post.member_post_id);
      setDir(post.cwd || DEFAULT_EMPLOYEE_CWD);
      setSkills(
        (post.skills ?? []).map((name) => {
          const matched = allSkills.find((s) => s.name === name);
          return matched ?? { name, description: '', file_path: '' };
        })
      );
      if (clients.agents.length > 0) {
        const own = clients.agents.find((a) => a.agent_type === post.agent_kernel && a.selectable);
        setAgent(own?.agent_type ?? pickDefaultAgent(clients.agents, clients.fallbackDefault));
      } else {
        setAgent(null);
      }
    },
    [allSkills, choices, clients.agents, clients.fallbackDefault]
  );

  const selectEmployeeMode = useCallback(() => {
    if (selectedEmployee) return;
    const saved = readLastEmployee();
    const target =
      (saved ? empState.employees.find((e) => e.member_post_id === saved) : null) ??
      empState.employees[0] ??
      null;
    if (target) applyEmployee(target, true);
  }, [selectedEmployee, empState.employees, applyEmployee]);

  useEffect(() => {
    if (!empPickerOpen) return;
    const tId = window.setTimeout(() => empSearchRef.current?.focus(), 0);
    const onDocMouseDown = (e: MouseEvent) => {
      if (empPickerRef.current && !empPickerRef.current.contains(e.target as Node)) {
        setEmpPickerOpen(false);
      }
    };
    const onDocKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setEmpPickerOpen(false);
      }
    };
    document.addEventListener('mousedown', onDocMouseDown);
    document.addEventListener('keydown', onDocKeyDown);
    return () => {
      window.clearTimeout(tId);
      document.removeEventListener('mousedown', onDocMouseDown);
      document.removeEventListener('keydown', onDocKeyDown);
    };
  }, [empPickerOpen]);

  useEffect(() => {
    if (!isOpen) return;
    setText('');
    setSkills([]);
    setError(null);
    setCreating(false);
    setShowUnavailable(false);
    setBrowsing(false);
    setListing(null);
    setFilter('');
    setSelectedEmployeeId(null);
    setEmpDetail(null);
    setEmpDetailError(null);
    setCtxOpen(false);
    setEmpPickerOpen(false);
    setEmpQuery('');
    clear();

    let cancelled = false;

    const load = async () => {
      const recent = getRecentDirectories().map((r) => ({ path: r.path, hint: 'recent' }));
      let system: DirChoice[] = [];

      try {
        const dirs = await getSystemDirectories();
        if (dirs.home) system.push({ path: dirs.home, hint: 'home' });
        if (dirs.cwd && dirs.cwd !== dirs.home) system.push({ path: dirs.cwd, hint: 'cwd' });
      } catch {
        // Directory service unreachable — recents alone still allow a pick,
        // and the free-text field always works.
        system = [];
      }

      const seen = new Set(recent.map((r) => r.path));
      const merged = [...recent, ...system.filter((s) => !seen.has(s.path))];

      if (cancelled) return;
      setChoices(merged);
      setDir((prev) => prev || merged[0]?.path || '');
    };

    load();
    return () => {
      cancelled = true;
    };
  }, [isOpen, clear]);

  /**
   * 员工列表加载完成后，默认选中上次挑过的员工（或第一位员工）。
   * 若用户上次明确选了「普通会话」（`saved === ''`），则保持普通会话模式。
   */
  useEffect(() => {
    if (!isOpen || selectedEmployeeId !== null || !empState.employees.length) return;
    const saved = readLastEmployee();
    if (saved === '') {
      setSelectedEmployeeId('');
      return;
    }
    const target =
      (saved ? empState.employees.find((e) => e.member_post_id === saved) : null) ??
      empState.employees[0];
    if (target) {
      applyEmployee(target);
    }
  }, [isOpen, selectedEmployeeId, empState.employees, applyEmployee]);

  /**
   * 选中员工后拉取详情（拿到自动注入的业务语境原文与领地统计）。
   */
  useEffect(() => {
    if (!isOpen || !selectedEmployee) {
      setEmpDetail(null);
      setEmpDetailError(null);
      return;
    }
    let alive = true;
    fetchEmployee(selectedEmployee.member_post_id)
      .then((d) => {
        if (alive) setEmpDetail(d);
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setEmpDetailError(
          e instanceof Error ? e.message : t('employees.errors.detailFailedPlain')
        );
      });
    return () => {
      alive = false;
    };
  }, [isOpen, selectedEmployee, t]);

  /**
   * 清单一到就把默认那一家选上：若当前选了员工，优先用员工配置的 `agent_kernel`；
   * 否则上次挑的优先——换机位是有惯性的。
   */
  useEffect(() => {
    if (!clients.agents.length) return;
    setAgent((prev) => {
      if (prev) return prev;
      if (selectedEmployee) {
        const own = clients.agents.find(
          (a) => a.agent_type === selectedEmployee.agent_kernel && a.selectable
        );
        if (own) return own.agent_type;
      }
      return pickDefaultAgent(clients.agents, clients.fallbackDefault);
    });
  }, [clients.agents, clients.fallbackDefault, selectedEmployee]);

  /**
   * 翻进某一层。**停在哪一层就是选了哪一层**——翻到了想要的目录还得再点一次"就用这个"，
   * 是白白多出来的一步，而且那一步没做的人会以为自己已经选好了。
   */
  const openFolder = async (path: string) => {
    const seq = ++browseSeq.current;
    setBrowseLoading(true);
    try {
      const next = await browseDirectories(path);
      if (seq !== browseSeq.current) return;
      setListing(next);
      setFilter('');
      setDir(next.path);
    } catch {
      // 读不动就停在原地：清单整个消失，人会以为这条路根本走不通。
      if (seq === browseSeq.current) setListing(null);
    } finally {
      if (seq === browseSeq.current) setBrowseLoading(false);
    }
  };

  const toggleBrowsing = () => {
    const next = !browsing;
    setBrowsing(next);
    if (next) void openFolder(dir.trim());
  };

  const visibleEntries = useMemo(() => {
    const entries = listing?.entries ?? [];
    const needle = filter.trim().toLowerCase();
    return needle ? entries.filter((e) => e.name.toLowerCase().includes(needle)) : entries;
  }, [listing, filter]);

  const defaultSkillCount = selectedEmployee?.skills?.length ?? 0;
  // 只有图或只挑了 skill、一个字没打也算数：与会话详情输入区（Composer）同一条判据，服务端那边也认这一档。
  const canSubmit =
    !creating &&
    !!chosen &&
    dir.trim().length > 0 &&
    (text.trim().length > 0 || count > 0 || skills.length > defaultSkillCount);

  const ctx = empDetail?.business_context_block ?? '';
  const slots = empDetail?.managed_data.data_slots ?? [];
  const folderCount = slots.length || selectedEmployee?.data_summary.slot_count || 0;
  const entryCount =
    slots.reduce((n, s) => n + s.total_count, 0) ||
    selectedEmployee?.data_summary.entry_count ||
    0;

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    const files = e.dataTransfer?.files;
    if (!files || files.length === 0) return;
    e.preventDefault();
    void addFiles(files);
  };

  const handleContainerPaste = (e: ClipboardEvent<HTMLDivElement>) => {
    if (e.defaultPrevented) return;
    const extracted = extractClipboardFiles(e.clipboardData);
    if (extracted.length === 0) return;
    e.preventDefault();
    void addFiles(e.clipboardData?.files?.length ? e.clipboardData.files : extracted);
  };

  const handleCreate = async () => {
    if (!canSubmit || !chosen) return;
    setError(null);
    setCreating(true);
    try {
      const first = text.trim();
      const launch = await createSession({
        agent: chosen.agent_type,
        cwd: dir.trim(),
        text: first,
        images: images.map((im) => im.dataUrl),
        documents: documents.map((d) => ({ name: d.name, data: d.dataUrl })),
        ...(skills.length ? { skills: skills.map((s) => s.name) } : {}),
        ...(selectedEmployee ? { employee: selectedEmployee.member_post_id } : {}),
      });
      rememberLastAgent(chosen.agent_type);
      if (empState.employees.length > 0) {
        rememberLastEmployee(selectedEmployee ? selectedEmployee.member_post_id : '');
      }
      addRecentDirectory(dir.trim());
      const enrichedLaunch: PendingLaunch = selectedEmployee
        ? {
            ...launch,
            employee_id: selectedEmployee.member_post_id,
            employee_title: selectedEmployee.title,
            employee_color: resolveEmployeeColor(
              selectedEmployee.color,
              selectedEmployee.member_post_id
            ),
          }
        : launch;
      onCreated(enrichedLaunch, first);
      onClose();
    } catch (e) {
      // 建不起来就**留在起始页里**并把话原样摆出来。关掉再弹一句提示，人打的那段话
      // 就没了，还得从头再敲一遍。
      setError(e instanceof Error ? e.message : t('workbench.errors.createFailedPlain'));
      setCreating(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div
      data-testid="new-session-inline"
      className="flex h-full min-h-0 min-w-0 flex-1 flex-col bg-bg-primary"
      onDragOver={(e) => e.preventDefault()}
      onDrop={handleDrop}
      onPaste={handleContainerPaste}
    >
      {/* 顶部栏：与会话详情页头同高（52px），实时反映当前挑中的员工岗位、CLI Agent 与工作目录 */}
      <header className="flex h-[52px] shrink-0 items-center gap-2.5 border-b border-border-color px-4">
        <button
          type="button"
          onClick={onClose}
          className="hidden shrink-0 text-text-muted hover:text-text-primary phone:block"
          aria-label={t('workbench.page.backToList')}
        >
          <ChevronLeft size={16} />
        </button>
        <div className="flex min-w-0 flex-1 flex-col justify-center">
          <h1 className="min-w-0 truncate text-[14px] font-semibold leading-[1.3] text-text-primary">
            {selectedEmployee
              ? t('workbench.newSession.titleWithEmployee', { name: selectedEmployee.title })
              : t('workbench.newSession.title')}
          </h1>
          <div className="flex min-w-0 items-center gap-1.5 text-[11px] leading-[1.4] text-text-muted">
            {selectedEmployee ? (
              <>
                <span
                  data-emp-color={resolveEmployeeColor(
                    selectedEmployee.color,
                    selectedEmployee.member_post_id
                  )}
                  className="inline-flex shrink-0 items-center gap-1 font-medium text-[var(--emp-fg,var(--text-secondary))]"
                >
                  <span
                    aria-hidden
                    className="h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--emp-fg,var(--accent-primary))]"
                  />
                  <span>{selectedEmployee.title}</span>
                </span>
                {(chosen || dir.trim()) ? (
                  <span aria-hidden className="shrink-0 text-text-dim">·</span>
                ) : null}
              </>
            ) : null}
            {chosen ? (
              <>
                <span className="shrink-0 whitespace-nowrap text-text-secondary">
                  {chosen.display_name}
                </span>
                {dir.trim() ? <span aria-hidden className="shrink-0 text-text-dim">·</span> : null}
              </>
            ) : null}
            {dir.trim() ? (
              <span className="min-w-[56px] truncate font-mono" title={dir.trim()}>
                {withTilde(dir.trim())}
              </span>
            ) : null}
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="h-7 shrink-0 rounded-[7px] px-2.5 text-[12px] text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary"
        >
          {t('workbench.newSession.cancel')}
        </button>
      </header>

      {/* 居中 New Chat 风格起始舞台（宽松大气的纵向节奏与清晰的两级模式引导） */}
      <div className="flex min-h-0 flex-1 flex-col items-center overflow-y-auto px-8 pb-12 pt-[clamp(32px,6.5vh,72px)]">
        <div className="flex w-full max-w-[720px] flex-col gap-6">
          {/* 1. 会话模式引导（「员工会话（推荐）」 vs 「普通会话」分明对比 + 专职员工选择区） */}
          {empState.employees.length > 0 ? (
            <div className="flex flex-col gap-3.5 px-0.5" data-testid="new-session-employee-section">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
                  <h2
                    id="new-session-employee"
                    className="text-[16px] font-semibold leading-[1.3] tracking-[-0.015em] text-text-primary"
                  >
                    {t('workbench.newSession.employeeLabel')}
                  </h2>
                  <span className="text-[12.5px] text-text-muted">
                    {t('workbench.newSession.employeeHint')}
                  </span>
                </div>
                <button
                  type="button"
                  data-testid="manage-employees"
                  onClick={() => {
                    onClose();
                    switchPage('employees');
                  }}
                  className="shrink-0 text-[12px] font-medium text-text-secondary transition-colors hover:text-text-primary"
                >
                  {t('workbench.newSession.manageEmployees')} →
                </button>
              </div>

              {/* 顶层模式二选一卡片：一眼看懂「员工会话」与「普通会话」的区别 */}
              <div
                role="radiogroup"
                aria-labelledby="new-session-employee"
                className="grid grid-cols-1 gap-3 sm:grid-cols-2"
              >
                <button
                  type="button"
                  role="radio"
                  aria-checked={selectedEmployee !== null}
                  data-testid="new-session-mode-employee"
                  onClick={selectEmployeeMode}
                  className={`flex items-start gap-3 rounded-[12px] border p-3.5 text-left transition-all ${
                    selectedEmployee !== null
                      ? 'border-[var(--sel-border)] bg-[var(--sel-bg)] [box-shadow:var(--sel-shadow)]'
                      : 'border-border-color bg-bg-secondary/70 hover:border-border-strong hover:bg-bg-hover'
                  }`}
                >
                  <span
                    className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-[8px] border ${
                      selectedEmployee !== null
                        ? 'border-border-accent bg-accent-primary-10 text-accent-primary'
                        : 'border-border-color bg-bg-primary text-text-muted'
                    }`}
                  >
                    <Sparkles size={15} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-[13.5px] font-semibold text-text-primary">
                        {t('workbench.newSession.employeeModeTitle')}
                      </span>
                      <span className="rounded-[5px] bg-accent-primary-10 px-1.5 py-0.5 text-[10.5px] font-medium text-accent-primary">
                        {t('workbench.newSession.employeeModeBadge')}
                      </span>
                    </div>
                    <p className="mt-1 text-[12px] leading-[1.45] text-text-muted">
                      {t('workbench.newSession.employeeModeDesc')}
                    </p>
                  </div>
                </button>

                <button
                  type="button"
                  role="radio"
                  aria-checked={selectedEmployee === null}
                  data-testid="new-session-employee-plain"
                  onClick={() => applyEmployee(null, true)}
                  title={t('workbench.newSession.plainSessionDesc')}
                  className={`flex items-start gap-3 rounded-[12px] border p-3.5 text-left transition-all ${
                    selectedEmployee === null
                      ? 'border-[var(--sel-border)] bg-[var(--sel-bg)] [box-shadow:var(--sel-shadow)]'
                      : 'border-border-color bg-bg-secondary/70 hover:border-border-strong hover:bg-bg-hover'
                  }`}
                >
                  <span
                    className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-[8px] border ${
                      selectedEmployee === null
                        ? 'border-border-strong bg-bg-primary text-text-primary'
                        : 'border-border-color bg-bg-primary text-text-muted'
                    }`}
                  >
                    <SquareTerminal size={15} strokeWidth={1.7} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-[13.5px] font-semibold text-text-primary">
                        {t('workbench.newSession.plainSession')}
                      </span>
                    </div>
                    <p className="mt-1 text-[12px] leading-[1.45] text-text-muted">
                      {t('workbench.newSession.plainSessionDesc')}
                    </p>
                  </div>
                </button>
              </div>

              {/* 专职员工选择与语境摘要区：将员工胶囊与所选员工的业务语境合为一块宽松容器 */}
              <div
                data-emp-color={
                  selectedEmployee
                    ? resolveEmployeeColor(selectedEmployee.color, selectedEmployee.member_post_id)
                    : undefined
                }
                className={`flex flex-col gap-3 rounded-[12px] border p-3.5 transition-colors ${
                  selectedEmployee
                    ? 'border-[var(--emp-border,var(--border-color))] bg-bg-secondary'
                    : 'border-dashed border-border-color bg-bg-secondary/40'
                }`}
              >
                <div
                  ref={empPickerRef}
                  className="relative flex flex-wrap items-center gap-2"
                >
                  <span className="mr-1 text-[11.5px] font-medium text-text-muted">
                    {selectedEmployee
                      ? t('workbench.newSession.employeeRosterLabel')
                      : t('workbench.newSession.employeeRosterPlainHint')}
                  </span>

                  {/* 常用/当前选中的最多 3 个员工快捷胶囊 */}
                  {quickEmployees.map((post) => {
                    const selected = selectedEmployee?.member_post_id === post.member_post_id;
                    const empColor = resolveEmployeeColor(post.color, post.member_post_id);
                    return (
                      <button
                        key={post.member_post_id}
                        type="button"
                        role="radio"
                        aria-checked={selected}
                        data-testid={`new-session-employee-${post.member_post_id}`}
                        data-emp-color={empColor}
                        onClick={() => applyEmployee(post, true)}
                        title={employeeSummary(post) || post.title}
                        className={`inline-flex h-8 max-w-[210px] items-center gap-1.5 rounded-[8px] border px-3 text-[12.5px] transition-colors ${
                          selected
                            ? 'border-[var(--emp-border,var(--sel-border))] bg-[color-mix(in_srgb,var(--emp-bg,var(--sel-bg))_42%,var(--bg-secondary))] font-semibold text-text-primary [box-shadow:inset_0_2px_0_0_var(--emp-fg,var(--accent-primary))]'
                            : 'border-border-color bg-bg-primary text-text-secondary hover:border-border-strong hover:bg-bg-hover hover:text-text-primary'
                        }`}
                      >
                        <span
                          className="flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-[4px] border font-mono text-[9.5px] font-semibold"
                          style={{
                            background: 'var(--emp-bg, var(--bg-primary))',
                            color: 'var(--emp-fg, var(--text-primary))',
                            borderColor: 'var(--emp-border, var(--border-color))',
                          }}
                        >
                          {employeeInitials(post.member_post_id)}
                        </span>
                        <span className="truncate">{post.title}</span>
                      </button>
                    );
                  })}

                  {/* 可搜索的全部员工选择器（支持 100+ 员工瞬时过滤） */}
                  <button
                    type="button"
                    data-testid="employee-picker-trigger"
                    aria-expanded={empPickerOpen}
                    onClick={() => setEmpPickerOpen((v) => !v)}
                    className={`inline-flex h-8 shrink-0 items-center gap-1.5 rounded-[8px] border px-3 text-[12px] transition-colors ${
                      empPickerOpen
                        ? 'border-[var(--sel-border)] bg-[var(--sel-bg)] font-medium text-text-primary'
                        : 'border-border-color bg-bg-primary text-text-secondary hover:bg-bg-hover hover:text-text-primary'
                    }`}
                  >
                    <Search size={12.5} className="shrink-0 text-text-muted" />
                    <span>
                      {t('workbench.newSession.allEmployees', { n: empState.employees.length })}
                    </span>
                    <ChevronDown size={12.5} className="shrink-0 text-text-muted" />
                  </button>

                  {/* 可搜索下拉面板：最大高度 260px 滚动，100 个员工也不撑高页面 */}
                  {empPickerOpen ? (
                    <div
                      data-testid="employee-picker-popover"
                      className="absolute left-0 top-[calc(100%+6px)] z-30 flex w-full max-w-[460px] flex-col overflow-hidden rounded-[10px] border border-border-strong bg-bg-secondary shadow-[0_12px_32px_rgba(0,0,0,0.38)]"
                    >
                      <div className="flex items-center gap-2 border-b border-border-color bg-bg-primary px-3 py-2">
                        <Search size={13} className="shrink-0 text-text-muted" />
                        <input
                          ref={empSearchRef}
                          type="text"
                          value={empQuery}
                          onChange={(e) => setEmpQuery(e.target.value)}
                          placeholder={t('workbench.newSession.searchEmployeesPlaceholder')}
                          data-testid="employee-picker-search"
                          className="min-w-0 flex-1 bg-transparent text-[12.5px] text-text-primary outline-none placeholder:text-text-muted"
                        />
                        {empQuery ? (
                          <button
                            type="button"
                            onClick={() => setEmpQuery('')}
                            className="rounded p-0.5 text-text-muted hover:text-text-primary"
                          >
                            <X size={12} />
                          </button>
                        ) : null}
                      </div>

                      <div className="flex max-h-[260px] flex-col divide-y divide-border-color overflow-y-auto">
                        {/* 下拉顶部固定「普通会话」入口 */}
                        <button
                          type="button"
                          onClick={() => applyEmployee(null, true)}
                          className={`flex items-center gap-2.5 px-3 py-2 text-left transition-colors ${
                            selectedEmployee === null
                              ? 'bg-[var(--sel-bg)] text-text-primary'
                              : 'hover:bg-bg-hover'
                          }`}
                        >
                          <span className="flex h-[24px] w-[24px] shrink-0 items-center justify-center rounded-[5px] border border-border-color bg-bg-primary text-text-secondary">
                            <SquareTerminal size={12} />
                          </span>
                          <div className="min-w-0 flex-1">
                            <div className="truncate text-[12.5px] font-medium text-text-primary">
                              {t('workbench.newSession.plainSession')}
                            </div>
                            <div className="truncate text-[11px] text-text-muted">
                              {t('workbench.newSession.plainSessionDesc')}
                            </div>
                          </div>
                        </button>

                        {filteredEmployees.length ? (
                          filteredEmployees.map((post) => {
                            const selected =
                              selectedEmployee?.member_post_id === post.member_post_id;
                            const empColor = resolveEmployeeColor(post.color, post.member_post_id);
                            const summary = employeeSummary(post);
                            return (
                              <button
                                key={post.member_post_id}
                                type="button"
                                data-testid={`picker-employee-${post.member_post_id}`}
                                data-emp-color={empColor}
                                onClick={() => applyEmployee(post, true)}
                                className={`flex items-center gap-2.5 px-3 py-2 text-left transition-colors ${
                                  selected
                                    ? 'bg-[var(--sel-bg)] text-text-primary'
                                    : 'hover:bg-bg-hover'
                                }`}
                              >
                                <span
                                  className="flex h-[24px] w-[24px] shrink-0 items-center justify-center rounded-[5px] border font-mono text-[10px] font-semibold"
                                  style={{
                                    background: 'var(--emp-bg, var(--bg-primary))',
                                    color: 'var(--emp-fg, var(--text-primary))',
                                    borderColor: 'var(--emp-border, var(--border-color))',
                                  }}
                                >
                                  {employeeInitials(post.member_post_id)}
                                </span>
                                <div className="min-w-0 flex-1">
                                  <div className="flex items-center justify-between gap-2">
                                    <span className="truncate text-[12.5px] font-semibold text-text-primary">
                                      {post.title}
                                    </span>
                                    <span className="shrink-0 rounded-[4px] border border-border-color bg-bg-primary px-1.5 font-mono text-[10px] text-text-secondary">
                                      {kernelLabel(post.agent_kernel)}
                                    </span>
                                  </div>
                                  {summary ? (
                                    <div className="truncate text-[11px] text-text-muted">
                                      {summary}
                                    </div>
                                  ) : null}
                                </div>
                              </button>
                            );
                          })
                        ) : (
                          <p className="px-3 py-4 text-center text-[12px] text-text-muted">
                            {t('workbench.newSession.noEmployeeMatch')}
                          </p>
                        )}
                      </div>
                    </div>
                  ) : null}
                </div>

                {/* 选中员工时的精简职责与业务语境预览栏 */}
                {selectedEmployee ? (
                  <div className="flex flex-col gap-2 border-t border-border-color pt-2.5">
                    <div className="flex items-center justify-between gap-2 text-[12px]">
                      <span className="min-w-0 flex-1 truncate text-text-secondary">
                        {employeeSummary(selectedEmployee)}
                      </span>
                      <span className="shrink-0 rounded-[4px] border border-border-color bg-bg-primary px-1.5 py-0.5 font-mono text-[10px] text-text-secondary">
                        {kernelLabel(selectedEmployee.agent_kernel)}
                      </span>
                    </div>

                    <button
                      type="button"
                      className="flex h-7 w-full min-w-0 items-center gap-2 rounded-[7px] bg-bg-primary/60 px-2.5 text-left transition-colors hover:bg-bg-hover"
                      onClick={() => setCtxOpen((v) => !v)}
                      aria-expanded={ctxOpen}
                      data-testid="employee-context-toggle"
                    >
                      {ctxOpen ? (
                        <ChevronDown size={13} className="shrink-0 text-text-muted" />
                      ) : (
                        <ChevronRight size={13} className="shrink-0 text-text-muted" />
                      )}
                      <Sparkles size={12.5} className="shrink-0 text-text-muted" />
                      <span className="shrink-0 text-[11.5px] font-semibold text-text-primary">
                        {t('employees.launch.contextTitle')}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-[11.5px] text-text-muted">
                        {empDetailError
                          ? t('employees.launch.contextFailed')
                          : t('employees.launch.contextSummary', {
                              folders: folderCount,
                              entries: entryCount,
                              domains: empDetail?.managed_data.knowledge_domains.length ?? 0,
                              recipes: empDetail?.managed_data.recipes.length ?? 0,
                            })}
                      </span>
                      <span className="shrink-0 text-[11.5px] text-text-secondary">
                        {ctxOpen
                          ? t('employees.launch.contextHide')
                          : t('employees.launch.contextPreview')}
                      </span>
                    </button>

                    {ctxOpen ? (
                      <div className="rounded-[8px] border border-border-color bg-bg-primary px-3 py-2.5">
                        {ctx ? (
                          <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-[1.55] text-text-secondary">
                            {ctx}
                          </pre>
                        ) : (
                          <p className="text-[11.5px] text-text-muted">
                            {empDetailError ?? t('employees.launch.contextLoading')}
                          </p>
                        )}
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            </div>
          ) : null}

          {/* 2. CLI Agent 选择条（选中员工时自动对齐该岗位默认内核，也可按需临时改派） */}
          <div className="flex flex-col gap-2.5 px-0.5">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
              <h2
                id="new-session-client"
                className={`${
                  empState.employees.length > 0
                    ? 'text-[13.5px] font-semibold text-text-secondary'
                    : 'text-[20px] font-semibold leading-[1.25] tracking-[-0.015em] text-text-primary'
                }`}
              >
                {t('workbench.newSession.clientLabel')}
              </h2>
              <span className="text-[12px] text-text-muted">
                {t('workbench.newSession.clientHint')}
              </span>
            </div>

            {clients.loading && !clients.agents.length ? (
              <p className="text-[11.5px] text-text-muted">
                {t('workbench.newSession.probing')}
              </p>
            ) : clients.error ? (
              <p className="break-words text-xs text-accent-error">{clients.error}</p>
            ) : !selectable.length ? (
              <p className="break-words text-xs text-accent-error">
                {t('workbench.newSession.noneAvailable')}
              </p>
            ) : (
              <div
                className="flex flex-wrap items-center gap-2"
                role="radiogroup"
                aria-labelledby="new-session-client"
              >
                {selectable.map((c) => {
                  const selected = c.agent_type === agent;
                  return (
                    <button
                      key={c.agent_type}
                      type="button"
                      role="radio"
                      aria-checked={selected}
                      data-testid={`agent-${c.agent_type}`}
                      onClick={() => setAgent(c.agent_type)}
                      title={c.path ?? undefined}
                      className={`inline-flex h-8 items-center gap-1.5 rounded-[8px] border px-3 text-[12.5px] transition-colors ${
                        selected
                          ? 'border-[var(--sel-border)] bg-[var(--sel-bg)] font-medium text-text-primary'
                          : 'border-border-color bg-bg-secondary text-text-secondary hover:bg-bg-hover hover:text-text-primary'
                      }`}
                    >
                      <span
                        aria-hidden
                        className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                          selected ? 'bg-accent-primary' : 'bg-text-dim'
                        }`}
                      />
                      {c.display_name}
                    </button>
                  );
                })}

                {/* 用不了的那几家不藏：折在一句话后面，点开看原因 */}
                {unavailable.length ? (
                  <button
                    type="button"
                    onClick={() => setShowUnavailable((v) => !v)}
                    aria-expanded={showUnavailable}
                    data-testid="toggle-unavailable-agents"
                    className="inline-flex h-7 items-center gap-1 rounded-[6px] px-2.5 text-[11.5px] text-text-muted transition-colors hover:bg-bg-hover hover:text-text-secondary"
                  >
                    {showUnavailable ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                    <span>
                      {t('workbench.newSession.unavailableCount', { n: unavailable.length })}
                    </span>
                  </button>
                ) : null}
              </div>
            )}

            {/* 编号要等认领的那两家，把这段空窗先说在前头 */}
            {chosen?.id_origin === 'claimed' ? (
              <p className="flex items-center gap-1.5 pt-0.5 text-[11.5px] leading-[1.45] text-text-muted">
                <Info size={13} className="shrink-0 text-text-dim" />
                <span>{t('workbench.newSession.claimedHint', { name: chosen.display_name })}</span>
              </p>
            ) : null}

            {showUnavailable && unavailable.length ? (
              <div className="flex flex-col gap-1 rounded-[8px] border border-dashed border-border-strong bg-bg-secondary px-3 py-2.5 text-[11.5px] text-text-muted">
                {unavailable.map((c) => (
                  <p key={c.agent_type} className="leading-relaxed">
                    <span className="font-medium text-text-secondary">{c.display_name}</span>
                    {' — '}
                    {agentReasonText(c.reason)}
                  </p>
                ))}
              </div>
            ) : null}
          </div>

          {/* 3. 核心首条消息输入框卡片（复用统一的 PromptComposerBox，支持 `@` 挑员工、`/` 挑 skill、自动增高、粘贴/拖拽附件） */}
          <PromptComposerBox
            text={text}
            onChangeText={setText}
            skills={skills}
            onAddSkill={addSkill}
            onRemoveSkill={removeSkill}
            employees={selectedEmployee ? [selectedEmployee] : []}
            employeesCatalog={empState.employees}
            onAddEmployee={(emp) => applyEmployee(emp, true)}
            onRemoveEmployee={() => applyEmployee(null, true)}
            onAddFiles={addFiles}
            attachCount={count}
            canSubmit={canSubmit}
            submitting={creating}
            onSubmit={handleCreate}
            placeholder={t('workbench.newSession.firstMessagePlaceholder')}
            idPrefix="new-session"
            textareaId="new-session-input-box"
            ariaLabelledBy="new-session-first"
            minLines={4}
            maxLines={9}
            menuPlacement="below"
            className="shadow-[0_6px_24px_rgba(0,0,0,0.14)]"
            headerSlot={
              <div className="mb-1 flex items-baseline justify-between gap-2">
                <label
                  id="new-session-first"
                  htmlFor="new-session-input-box"
                  className="text-[12.5px] font-medium text-text-secondary"
                >
                  {t('workbench.newSession.firstMessage')}
                </label>
                <span className="text-[11.5px] text-text-muted">
                  {t('workbench.newSession.firstMessageOptional')}
                </span>
              </div>
            }
            attachmentSlot={
              <AttachmentStrip
                images={images}
                documents={documents}
                onRemoveImage={removeImage}
                onRemoveDocument={removeDocument}
                idPrefix="new-session"
              />
            }
            attachButtonLabel={t('workbench.newSession.attach')}
            rightActionsSlot={
              <span className="mr-1 font-mono text-[11px] text-text-dim">{modKey}↵</span>
            }
            submitLabel={t('workbench.newSession.create')}
          />

          {error && (
            <p className="break-words rounded-[8px] bg-accent-error-10 px-3 py-2 text-xs text-accent-error">
              {t('workbench.newSession.createFailed', { reason: error })}
            </p>
          )}

          {/* 4. 启动目录（Working folder）内联配置卡 */}
          <div className="flex flex-col gap-2.5 rounded-[12px] border border-border-color bg-bg-secondary px-4 py-3.5">
            <div className="flex flex-wrap items-center gap-2">
              <label
                id="new-session-cwd"
                htmlFor="new-session-cwd-path"
                className="inline-flex shrink-0 items-center gap-1.5 text-[11.5px] font-medium text-text-secondary"
                title={t('workbench.newSession.cwdHint')}
              >
                <Folder size={14} className="text-text-muted" />
                {t('workbench.newSession.cwdLabel')}
              </label>

              <input
                id="new-session-cwd-path"
                type="text"
                value={dir}
                onChange={(e) => setDir(e.target.value)}
                placeholder="/absolute/path"
                aria-label={t('workbench.newSession.cwdPathLabel')}
                className="h-7 min-w-[160px] flex-1 rounded-[7px] border border-border-color bg-bg-primary px-2.5 font-mono text-[12px] text-text-primary outline-none focus:border-[var(--sel-border)]"
              />

              <button
                type="button"
                data-testid="toggle-browse-dirs"
                onClick={toggleBrowsing}
                aria-expanded={browsing}
                className={`inline-flex h-7 shrink-0 items-center gap-1.5 rounded-[7px] border px-2.5 text-[11.5px] transition-colors ${
                  browsing
                    ? 'border-[var(--sel-border)] bg-[var(--sel-bg)] text-text-primary'
                    : 'border-border-color bg-bg-primary text-text-secondary hover:bg-bg-hover hover:text-text-primary'
                }`}
              >
                <FolderSearch size={13} strokeWidth={1.5} />
                {browsing
                  ? t('workbench.newSession.cwdBrowseClose')
                  : t('workbench.newSession.cwdBrowse')}
              </button>
            </div>

            {browsing ? (
              <div className="flex flex-col gap-2 border-t border-border-color pt-2.5">
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    data-testid="browse-up"
                    disabled={!listing?.parent || browseLoading}
                    onClick={() => listing?.parent && void openFolder(listing.parent)}
                    title={t('workbench.newSession.cwdUp')}
                    aria-label={t('workbench.newSession.cwdUp')}
                    className="inline-flex h-7 shrink-0 items-center gap-1.5 rounded-[7px] border border-border-color bg-bg-primary px-2.5 text-[12px] text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary disabled:opacity-40"
                  >
                    <CornerLeftUp size={13} strokeWidth={1.5} />
                    <span>{t('workbench.newSession.cwdUp')}</span>
                  </button>
                  <input
                    type="text"
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                    placeholder={t('workbench.newSession.cwdFilter')}
                    data-testid="browse-filter"
                    className="h-7 min-w-0 flex-1 rounded-[7px] border border-border-color bg-bg-primary px-2.5 text-[12px] text-text-primary outline-none focus:border-[var(--sel-border)]"
                  />
                </div>

                <div
                  className="flex max-h-80 flex-col divide-y divide-border-color overflow-y-auto rounded-[8px] border border-border-color bg-bg-primary"
                  data-testid="browse-list"
                >
                  {browseLoading && !listing ? (
                    <p className="px-3 py-3 text-[12px] text-text-muted">
                      {t('workbench.newSession.cwdLoading')}
                    </p>
                  ) : visibleEntries.length ? (
                    visibleEntries.map((e) => (
                      <button
                        key={e.path}
                        type="button"
                        onClick={() => void openFolder(e.path)}
                        title={e.path}
                        className="flex h-8 w-full shrink-0 items-center gap-2.5 px-3 text-left font-mono text-[12.5px] text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary"
                      >
                        <Folder size={14} className="shrink-0 text-text-muted" />
                        <span className="min-w-0 flex-1 truncate">{e.name}</span>
                        <ChevronRight size={13} className="shrink-0 text-text-dim" />
                      </button>
                    ))
                  ) : (
                    <p className="px-3 py-3 text-center text-[12px] text-text-muted">
                      {t('workbench.newSession.cwdEmpty')}
                    </p>
                  )}
                </div>
              </div>
            ) : choices.length ? (
              <div className="flex flex-wrap items-center gap-1.5">
                {choices.slice(0, MAX_INLINE_DIR_CHOICES).map((c) => {
                  const active = c.path === dir;
                  return (
                    <button
                      key={c.path}
                      type="button"
                      onClick={() => setDir(c.path)}
                      title={c.path}
                      className={`inline-flex h-[25px] max-w-full items-center gap-1.5 rounded-[7px] border px-2.5 font-mono text-[11.5px] transition-colors ${
                        active
                          ? 'border-[var(--sel-border)] bg-[var(--sel-bg)] text-text-primary'
                          : 'border-border-color bg-bg-primary text-text-secondary hover:bg-bg-hover hover:text-text-primary'
                      }`}
                    >
                      {c.hint === 'home' ? (
                        <Home size={12} className="shrink-0 text-text-muted" />
                      ) : (
                        <Folder size={12} className="shrink-0 text-text-muted" />
                      )}
                      <span className="truncate">{withTilde(c.path)}</span>
                      {c.hint && (
                        <span className="shrink-0 font-sans text-[10px] uppercase tracking-[0.03em] text-text-dim">
                          {c.hint}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
