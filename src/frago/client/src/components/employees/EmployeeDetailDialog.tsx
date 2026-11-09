/**
 * 员工详情与数据管理弹窗。
 *
 * ## 卡片表面只放一行，岗位说明与底账住在这里
 *
 * `work_scope` 是几百字的岗位说明，`data_slots` 是一串绝对路径。这两样铺在卡片上，一屏就
 * 只剩两三张卡，人扫不出本机有几个岗位。它们住在这个窗里：想细看的人点进来看，只想挑一个
 * 起会话的人在卡片上就够。
 *
 * ## 新建时只问岗位本身，资源由员工自己去认
 *
 * 「这个员工该管哪几块数据目录、哪些知识域、哪些配方」——这句话在岗位刚建、还没巡检过的
 * 那一刻，人给不出答案，员工自己也没查过。所以新建这一态只收六样人真正知道的东西（编号、
 * 内核、名称、一句话职责、工作范畴、默认工作目录），资源栏整个不出现。建完立刻转成详情态，
 * 把员工刚巡检出什么摆出来给人确认——**先有事实，再有判断**。
 *
 * ## 认领结果做成可增删的芯片，而不是一串路径文本
 *
 * 从前的三个手填框要人默写路径与配方名，写错了没人拦。现在每一栏是「员工已经认下的几项」
 * 加上「本机还有什么可以补」。删一项、补一项都是点一下的事，误认领项当场剔得掉。
 *
 * ## 领地底账是「看得见」的，不是「说一句有」
 *
 * 「这个员工管着三块 `~/.frago/data` 目录」这句话，与「这三块目录里各有几件东西、最近几件
 * 叫什么」是两件事。后者才是人在决定「该不该把这份材料交给他」时要看的。所以这里列的是
 * 服务端实时扫出来的那一层（`managed_data.data_slots`），不是编制里存着的那串路径。
 *
 * ## 新建归档目录走契约，不走文件系统
 *
 * 登记目录调 `POST /api/employees/{id}/data`，越界由服务端的领地契约当场拒绝（员工只能写进
 * 自己纳管的槽位）。这一侧 NEVER 自己拼路径去写——那正是契约要拦的那件事。
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, ChevronDown, ChevronRight, FolderPlus, Loader2, RefreshCw, X } from 'lucide-react';
import DialogShell from './DialogShell';
import {
  EMPLOYEE_COLORS,
  getEmployeeColorMeta,
  resolveEmployeeColor,
  type EmployeeColorId,
} from './employeeMeta';
import {
  fetchEmployee,
  registerEmployeeData,
  saveEmployee,
  syncEmployeeLedger,
  type ClaimedSlot,
  type EmployeeDetail,
  type EmployeePost,
} from '@/hooks/useEmployees';
import { useAgentClients } from '@/hooks/useAgentClients';
import { useDataStore } from '@/stores/dataStore';

interface EmployeeDetailDialogProps {
  /** 正看的是哪个员工。null 表示窗没开着。 */
  post: EmployeePost | null;
  /** 新建时没有 `post`，用这个标记；有 `post` 就是改。 */
  creating?: boolean;
  onClose: () => void;
  /** 存完、登记完或巡检完，让页面重取清单。 */
  onSaved: () => void;
  /**
   * 新建成功、服务端已跑完首次巡检时把那份编制交出去，由页面切到它的详情态。
   *
   * 页面上「正在新建」与「正在看某个员工」是两个互斥的态，切换这件事归页面管——弹窗自己
   * 改不了宿主的状态。给不出这个回调时（弹窗单独被挂起来用），退回弹窗内部切态。
   */
  onCreated?: (post: EmployeePost) => void;
}

/** 新建时默认工作目录的初值：员工的家在 `~/.frago`，巡检的也是那一棵。 */
const DEFAULT_CWD = '~/.frago';

/** 逗号/换行分隔的清单栏，读进来一个数组。 */
function parseList(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((s) => s.trim())
    .filter(Boolean);
}

/** 一个可移除的芯片。名字旁边那句说明走悬停提示，不铺在标签上——标签一长就扫不动了。 */
function Chip({
  label,
  hint,
  removeLabel,
  testId,
  onRemove,
}: {
  label: string;
  hint?: string;
  removeLabel: string;
  testId: string;
  onRemove: () => void;
}) {
  return (
    <span
      className="inline-flex max-w-full items-center gap-1 rounded-full border border-border-color bg-bg-secondary py-[3px] pl-2.5 pr-1 text-[11.5px] text-text-primary"
      title={hint || undefined}
      data-testid={testId}
    >
      <span className="max-w-[240px] truncate">{label}</span>
      <button
        type="button"
        className="flex h-[16px] w-[16px] shrink-0 items-center justify-center rounded-full text-text-muted transition-colors hover:bg-bg-hover hover:text-accent-error"
        aria-label={removeLabel}
        data-testid={`${testId}-remove`}
        onClick={onRemove}
      >
        <X size={11} strokeWidth={2} />
      </button>
    </span>
  );
}

export default function EmployeeDetailDialog({
  post,
  creating = false,
  onClose,
  onSaved,
  onCreated,
}: EmployeeDetailDialogProps) {
  const { t } = useTranslation();
  const open = post !== null || creating;

  /** 宿主没接手时，新建成功就由这里自己把弹窗切成详情态。 */
  const [createdPost, setCreatedPost] = useState<EmployeePost | null>(null);
  const activePost = post ?? createdPost;
  const isCreate = activePost === null;

  const [detail, setDetail] = useState<EmployeeDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  const [memberPostId, setMemberPostId] = useState('');
  const [title, setTitle] = useState('');
  const [kernel, setKernel] = useState('claude');
  const [color, setColor] = useState<EmployeeColorId>('ocean');
  const [colorTouched, setColorTouched] = useState(false);
  const [description, setDescription] = useState('');
  const [workScope, setWorkScope] = useState('');
  const [cwd, setCwd] = useState('');

  // 三栏认领清单存的是数组，不是一串要人自己敲分隔符的文本。
  const [slotList, setSlotList] = useState<string[]>([]);
  const [domainList, setDomainList] = useState<string[]>([]);
  const [recipeList, setRecipeList] = useState<string[]>([]);
  const [skillList, setSkillList] = useState<string[]>([]);
  const [customSlot, setCustomSlot] = useState('');
  const [customDomain, setCustomDomain] = useState('');
  const [customRecipe, setCustomRecipe] = useState('');
  const [customSkill, setCustomSkill] = useState('');

  const allSkills = useDataStore((s) => s.skills);
  const loadSkills = useDataStore((s) => s.loadSkills);

  useEffect(() => {
    if (open && (!allSkills || allSkills.length === 0)) {
      void loadSkills();
    }
  }, [open, allSkills, loadSkills]);

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedNote, setSavedNote] = useState<string | null>(null);
  /** 刚建好的是哪一个：提示只在它自己的详情态上出现，换一个人就不该再挂着了。 */
  const [justCreatedId, setJustCreatedId] = useState<string | null>(null);

  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [syncNote, setSyncNote] = useState<string | null>(null);
  const [discoveryOpen, setDiscoveryOpen] = useState(false);

  const [folderName, setFolderName] = useState('');
  const [folderSummary, setFolderSummary] = useState('');
  const [folderSlot, setFolderSlot] = useState('');
  const [registering, setRegistering] = useState(false);
  const [dataError, setDataError] = useState<string | null>(null);
  const [dataNote, setDataNote] = useState<string | null>(null);

  const clients = useAgentClients(open);
  // 内核候选以服务端认得的那几家为准。认得的清单取不到时退回编制里那个值，至少不会让人
  // 看见一个空的下拉。
  const kernelOptions = useMemo(() => {
    const known = clients.agents.map((a) => a.agent_type);
    if (activePost && !known.includes(activePost.agent_kernel)) {
      return [activePost.agent_kernel, ...known];
    }
    return known.length ? known : [kernel || 'claude'];
  }, [clients.agents, activePost, kernel]);

  // 换一个员工就把整块重建：上一个人的领地路径留在框里，人一按保存就把它写到新的那个
  // 员工名下了。
  useEffect(() => {
    if (!open) {
      // 窗关了就丢掉「刚建好」的标记：下次再开这个窗是另一件事，不该还挂着上一轮的提示。
      setJustCreatedId(null);
      return;
    }
    setSaveError(null);
    setSavedNote(null);
    setDataError(null);
    setDataNote(null);
    setSyncError(null);
    setSyncNote(null);
    setDiscoveryOpen(false);
    setFolderName('');
    setFolderSummary('');
    setFolderSlot('');
    setSaving(false);
    setRegistering(false);
    setSyncing(false);
    setCustomSlot('');
    setCustomDomain('');
    setCustomRecipe('');
    setCustomSkill('');

    if (!activePost) {
      setDetail(null);
      setDetailError(null);
      setMemberPostId('');
      setTitle('');
      setKernel('claude');
      setColor('ocean');
      setColorTouched(false);
      setDescription('');
      setWorkScope('');
      // 默认工作目录预填家目录：这一栏留空本来就等价于用 `~/.frago`，那不如直接写出来。
      setCwd(DEFAULT_CWD);
      setSlotList([]);
      setDomainList([]);
      setRecipeList([]);
      setSkillList([]);
      return;
    }

    setDetail(null);
    setDetailError(null);
    setMemberPostId(activePost.member_post_id);
    setTitle(activePost.title);
    setKernel(activePost.agent_kernel);
    setColor(resolveEmployeeColor(activePost.color, activePost.member_post_id));
    setColorTouched(true);
    setDescription(activePost.description);
    setWorkScope(activePost.work_scope);
    setCwd(activePost.cwd);
    setSlotList([...activePost.data_slots]);
    setDomainList([...activePost.knowledge_domains]);
    setRecipeList([...activePost.recipes]);
    setSkillList([...(activePost.skills ?? [])]);
  }, [open, activePost]);

  // 详情只在窗开着、且正看着某个员工时取。取不到时上半部分照常可编（编制本来就在 `post`
  // 里），只有领地那一段说取不到——整块拦下来会让人连改个说明都做不成。
  useEffect(() => {
    if (!open || !activePost) return;
    let alive = true;
    fetchEmployee(activePost.member_post_id)
      .then((d) => {
        if (!alive) return;
        setDetail(d);
        setDetailError(null);
        // 槽位清单以服务端扫出来的那份为准：编制里存着而磁盘上已经没了的目录，这里不列。
        setFolderSlot((prev) => prev || d.managed_data.data_slots[0]?.slot_path || '');
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setDetailError(e instanceof Error ? e.message : t('employees.errors.detailFailedPlain'));
      });
    return () => {
      alive = false;
    };
  }, [open, activePost, t]);

  const canSave = !saving && title.trim().length > 0 && (isCreate ? memberPostId.trim().length > 0 : true);

  const handleSave = async () => {
    if (!canSave) return;
    setSaving(true);
    setSaveError(null);
    setSavedNote(null);
    try {
      const saved = await saveEmployee(
        {
          member_post_id: memberPostId.trim(),
          title: title.trim(),
          agent_kernel: kernel,
          description: description.trim(),
          // 这两栏给空串就是「清空」；给 null 才是「这一栏不动」。编辑时人看见的就是当前值，
          // 所以这里照他框里的写。
          work_scope: workScope,
          cwd: cwd.trim(),
          knowledge_domains: domainList,
          recipes: recipeList,
          data_slots: slotList,
          schedule_ids: activePost?.schedule_ids ?? [],
          allowed_commands: activePost?.allowed_commands ?? [],
          skills: skillList,
          color,
        },
        { create: isCreate }
      );
      onSaved();
      if (isCreate) {
        // 服务端在返回之前已经跑完首次巡检，所以这份编制里就带着刚认下的资源。立刻切到它的
        // 详情态，人当场能看见「员工自己查到了什么」——而不是被留在原地自己再找回来。
        setJustCreatedId(saved.member_post_id);
        if (onCreated) {
          onCreated(saved);
        } else {
          setCreatedPost(saved);
        }
      } else {
        setSavedNote(t('employees.detail.saved'));
      }
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : t('employees.errors.saveFailedPlain'));
    } finally {
      setSaving(false);
    }
  };

  /** 重新巡检：让员工拿当前的职责与工作范畴重扫一遍 `~/.frago`，再把结果拉回来摆上。 */
  const handleSync = async () => {
    if (!activePost) return;
    setSyncing(true);
    setSyncError(null);
    setSyncNote(null);
    try {
      await syncEmployeeLedger(activePost.member_post_id, true);
      const fresh = await fetchEmployee(activePost.member_post_id);
      setDetail(fresh);
      // 表单里那三栏跟着巡检结果走：这一趟新认下的要出现在芯片里，人才看得见它干了活。
      setSlotList([...fresh.employee.data_slots]);
      setDomainList([...fresh.employee.knowledge_domains]);
      setRecipeList([...fresh.employee.recipes]);
      setSkillList([...(fresh.employee.skills ?? [])]);
      setSyncNote(t('employees.detail.synced'));
      onSaved();
    } catch (e) {
      setSyncError(e instanceof Error ? e.message : t('employees.errors.syncFailedPlain'));
    } finally {
      setSyncing(false);
    }
  };

  const handleRegister = async () => {
    const name = folderName.trim();
    if (!name || !activePost) return;
    setRegistering(true);
    setDataError(null);
    setDataNote(null);
    try {
      await registerEmployeeData(activePost.member_post_id, {
        folder_name: name,
        summary: folderSummary.trim(),
        ...(folderSlot ? { slot_path: folderSlot } : {}),
      });
      setFolderName('');
      setFolderSummary('');
      setDataNote(t('employees.detail.dataRegistered', { name }));
      // 重新取一遍详情：刚建的目录要出现在下面那份底账里，人才看得出这一下确实落地了。
      const fresh = await fetchEmployee(activePost.member_post_id);
      setDetail(fresh);
      onSaved();
    } catch (e) {
      setDataError(e instanceof Error ? e.message : t('employees.errors.dataFailedPlain'));
    } finally {
      setRegistering(false);
    }
  };

  const ledger = detail?.ledger ?? null;
  const available = detail?.available_resources;

  /** 一栏的候选：本机现有资源里还没被认领的那些。 */
  const slotOptions = useMemo(
    () =>
      (available?.data_slots ?? []).filter((s) => !slotList.includes(s.path) && !slotList.includes(s.name)),
    [available, slotList]
  );
  const domainOptions = useMemo(
    () => (available?.knowledge_domains ?? []).filter((d) => !domainList.includes(d.name)),
    [available, domainList]
  );
  const recipeOptions = useMemo(
    () => (available?.recipes ?? []).filter((r) => !recipeList.includes(r.name)),
    [available, recipeList]
  );
  const skillOptions = useMemo(
    () => (allSkills ?? []).filter((s) => !skillList.includes(s.name)),
    [allSkills, skillList]
  );

  /** 认领依据：芯片上悬停看的那句话，让人能核对「凭什么说这块归他」。 */
  const slotHint = (value: string): string => {
    const found: ClaimedSlot | undefined = ledger?.claimed_details?.data_slots?.find(
      (s) => s.path === value || s.name === value
    );
    if (!found) return '';
    return [found.evidence, found.discovered_by ? t('employees.detail.discoveredBy', { by: found.discovered_by }) : '']
      .filter(Boolean)
      .join(' · ');
  };
  const domainHint = (name: string): string => {
    const found = ledger?.claimed_details?.knowledge_domains?.find((d) => d.name === name);
    if (found) return [found.purpose, found.doc_count ? t('employees.detail.docCount', { n: found.doc_count }) : ''].filter(Boolean).join(' · ');
    return available?.knowledge_domains?.find((d) => d.name === name)?.purpose ?? '';
  };
  const recipeHint = (name: string): string => {
    const found = ledger?.claimed_details?.recipes?.find((r) => r.name === name);
    if (found) return [found.display_title, found.description].filter(Boolean).join(' · ');
    const opt = available?.recipes?.find((r) => r.name === name);
    return opt ? [opt.display_title, opt.description].filter(Boolean).join(' · ') : '';
  };
  const skillHint = (name: string): string => {
    const found = allSkills?.find((s) => s.name === name);
    return found?.description ?? '';
  };

  if (!open) return null;

  const heading = isCreate
    ? t('employees.detail.newTitle')
    : t('employees.detail.title', { name: activePost?.title ?? memberPostId });

  const sessions = ledger?.claimed_details?.matched_sessions ?? [];
  const glossary = ledger?.claimed_details?.glossary ?? [];
  const hasDiscovery = sessions.length > 0 || glossary.length > 0;
  const counts = {
    slots: ledger ? ledger.claimed_resources.data_slots.length : slotList.length,
    domains: ledger ? ledger.claimed_resources.knowledge_domain_count : domainList.length,
    recipes: ledger ? ledger.claimed_resources.recipe_count : recipeList.length,
    sessions: ledger?.claimed_resources.matched_session_count ?? 0,
    glossary: glossary.length,
  };

  return (
    <DialogShell
      title={heading}
      onClose={onClose}
      width={620}
      closable={!saving && !registering && !syncing}
      footer={
        <>
          <button type="button" className="page-header-btn" onClick={onClose} disabled={saving}>
            {t('common.close')}
          </button>
          <button
            type="button"
            className="page-header-btn page-header-primary"
            onClick={handleSave}
            disabled={!canSave}
            data-testid="employee-save"
          >
            {saving ? <Loader2 size={14} className="cs-spin" /> : null}
            {isCreate ? t('employees.detail.create') : t('employees.detail.save')}
          </button>
        </>
      }
    >
      <div className="fgrid2">
        <div className="fgrp">
          <label htmlFor="employee-id">{t('employees.detail.idLabel')}</label>
          <input
            id="employee-id"
            type="text"
            className="sinput mono"
            value={memberPostId}
            onChange={(e) => {
              const nextId = e.target.value;
              setMemberPostId(nextId);
              if (isCreate && !colorTouched) {
                setColor(resolveEmployeeColor(undefined, nextId));
              }
            }}
            disabled={!isCreate}
            spellCheck={false}
            placeholder="stock"
          />
          {/* 编号是这一份编制在磁盘上的文件名，也是起会话时对得上的那个 key，改了等于换一个岗位。 */}
          <p className="hint">
            {isCreate ? t('employees.detail.idHint') : t('employees.detail.idLocked')}
          </p>
        </div>
        <div className="fgrp">
          <label htmlFor="employee-kernel">{t('employees.detail.kernelLabel')}</label>
          <select
            id="employee-kernel"
            className="sselect"
            value={kernel}
            onChange={(e) => setKernel(e.target.value)}
          >
            {kernelOptions.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="fgrp">
        <label htmlFor="employee-title">{t('employees.detail.titleLabel')}</label>
        <input
          id="employee-title"
          type="text"
          className="sinput"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
      </div>

      {/* 外观颜色配置：模仿 Chrome/Edge 外观主题选色，深浅主题分别给两套色彩体系但建立 1:1 映射关系 */}
      <div className="fgrp" data-testid="employee-color-picker">
        <div className="flex items-center justify-between gap-2">
          <label>{t('employees.detail.colorLabel')}</label>
          <span
            className="font-mono text-[11px] text-text-secondary"
            data-testid="employee-color-current-label"
          >
            {(() => {
              const meta = getEmployeeColorMeta(color, memberPostId);
              const translated = t(meta.labelKey, { defaultValue: meta.defaultLabel });
              return `${translated} (${meta.id})`;
            })()}
          </span>
        </div>
        <div
          className="emp-swatch-grid"
          role="radiogroup"
          aria-label={t('employees.detail.colorLabel')}
        >
          {EMPLOYEE_COLORS.map((c) => {
            const selected = c.id === color;
            const swatchName = t(c.labelKey, { defaultValue: c.defaultLabel });
            return (
              <button
                key={c.id}
                type="button"
                role="radio"
                aria-checked={selected}
                aria-label={swatchName}
                title={`${swatchName} · Dark ${c.darkBg} ↔ Light ${c.lightBg}`}
                data-testid={`employee-color-swatch-${c.id}`}
                data-color-id={c.id}
                className={`emp-swatch ${selected ? 'on' : ''}`}
                onClick={() => {
                  setColor(c.id);
                  setColorTouched(true);
                }}
              >
                <span
                  className="emp-swatch-split"
                  style={{
                    background: `linear-gradient(135deg, ${c.darkBg} 0% 50%, ${c.lightBg} 50% 100%)`,
                  }}
                />
                <span className="emp-swatch-check" aria-hidden="true">
                  <Check size={13} strokeWidth={2.5} />
                </span>
              </button>
            );
          })}
        </div>
        {(() => {
          const meta = getEmployeeColorMeta(color, memberPostId);
          const previewName = title.trim() || memberPostId.trim() || 'Employee';
          return (
            <div className="emp-map-preview" data-testid="employee-color-map-preview">
              <div className="emp-map-card dark-preview">
                <div className="emp-map-head">
                  <span>{t('employees.detail.darkPalette')}</span>
                  <span>{meta.darkBg}</span>
                </div>
                <div className="emp-map-sample">
                  <div
                    className="bar"
                    style={{
                      background: meta.darkBg,
                      color: meta.darkFg,
                      borderBottom: `1px solid ${meta.darkBorder}`,
                    }}
                  >
                    {previewName}
                  </div>
                  <div className="sbody">{t('employees.detail.sampleSessionTitle')}</div>
                </div>
              </div>
              <div className="emp-map-card light-preview">
                <div className="emp-map-head">
                  <span>{t('employees.detail.lightPalette')}</span>
                  <span>{meta.lightBg}</span>
                </div>
                <div className="emp-map-sample">
                  <div
                    className="bar"
                    style={{
                      background: meta.lightBg,
                      color: meta.lightFg,
                      borderBottom: `1px solid ${meta.lightBorder}`,
                    }}
                  >
                    {previewName}
                  </div>
                  <div className="sbody">{t('employees.detail.sampleSessionTitle')}</div>
                </div>
              </div>
            </div>
          );
        })()}
        <p className="hint">{t('employees.detail.colorHint')}</p>
      </div>

      <div className="fgrp">
        <label htmlFor="employee-desc">{t('employees.detail.descLabel')}</label>
        <input
          id="employee-desc"
          type="text"
          className="sinput"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder={t('employees.detail.descPlaceholder')}
        />
        {/* 卡片上那一行摘要取的就是这一栏的第一句。写清这一句，卡片才好认。 */}
        <p className="hint">{t('employees.detail.descHint')}</p>
      </div>

      <div className="fgrp">
        <label htmlFor="employee-scope">{t('employees.detail.scopeLabel')}</label>
        <textarea
          id="employee-scope"
          className="sinput"
          style={{ minHeight: 96, padding: '7px 9px', resize: 'vertical', lineHeight: 1.5 }}
          value={workScope}
          onChange={(e) => setWorkScope(e.target.value)}
          placeholder={t('employees.detail.scopePlaceholder')}
        />
        <p className="hint">{t('employees.detail.scopeHint')}</p>
      </div>

      <div className="fgrp">
        <label htmlFor="employee-cwd">{t('employees.detail.cwdLabel')}</label>
        <input
          id="employee-cwd"
          type="text"
          className="sinput mono"
          value={cwd}
          onChange={(e) => setCwd(e.target.value)}
          spellCheck={false}
          placeholder="~/.frago"
        />
        <p className="hint">{t('employees.detail.cwdHint')}</p>
      </div>

      {/* 新建这一态不出现资源栏：员工还没查过，问人等于让人替它猜。 */}
      {isCreate ? (
        <p className="rounded-[8px] bg-bg-secondary px-3 py-2 text-[11.5px] leading-relaxed text-text-secondary">
          {t('employees.detail.autoDiscoverHint')}
        </p>
      ) : null}

      {saveError ? (
        <p className="break-words rounded-[8px] bg-accent-error-10 px-3 py-2 text-[12px] text-accent-error">
          {t('employees.detail.saveFailed', { reason: saveError })}
        </p>
      ) : null}
      {justCreatedId && activePost?.member_post_id === justCreatedId ? (
        <p className="rounded-[8px] bg-bg-secondary px-3 py-2 text-[12px] text-text-secondary">
          {t('employees.detail.created')}
        </p>
      ) : null}
      {savedNote ? (
        <p className="rounded-[8px] bg-bg-secondary px-3 py-2 text-[12px] text-text-secondary">
          {savedNote}
        </p>
      ) : null}

      {/* 巡检认领与资源管理：员工自己查到的东西摆在这里，人确认、剔除、补绑。 */}
      {!isCreate ? (
        <div className="fbox" data-testid="employee-claimed">
          <div className="flex flex-wrap items-center gap-2">
            <span className="fbox-h min-w-0 flex-1">{t('employees.detail.claimedTitle')}</span>
            <button
              type="button"
              className="page-header-btn"
              onClick={handleSync}
              disabled={syncing}
              data-testid="employee-sync-ledger"
            >
              {syncing ? (
                <Loader2 size={13} className="cs-spin" />
              ) : (
                <RefreshCw size={13} strokeWidth={1.5} />
              )}
              {t('employees.detail.sync')}
            </button>
          </div>

          {ledger ? (
            <p className="text-[11.5px] text-text-secondary" data-testid="employee-ledger-summary">
              {t('employees.detail.claimedSummary', counts)}
            </p>
          ) : (
            <p className="text-[11.5px] text-text-muted">{t('employees.detail.neverSynced')}</p>
          )}
          {ledger?.last_synced_at ? (
            <p className="text-[10.5px] text-text-muted">
              {t('employees.detail.lastSynced', { at: ledger.last_synced_at })}
            </p>
          ) : null}

          {syncError ? (
            <p className="break-words text-[11px] text-accent-error">
              {t('employees.detail.syncFailed', { reason: syncError })}
            </p>
          ) : null}
          {syncNote ? <p className="text-[11px] text-text-secondary">{syncNote}</p> : null}

          <p className="hint">{t('employees.detail.claimedHint')}</p>

          {/* 数据目录 */}
          <div className="flex flex-col gap-1.5">
            <label className="text-[11.5px] font-medium text-text-secondary" htmlFor="employee-slots">
              {t('employees.detail.slotsLabel')}
            </label>
            {slotList.length ? (
              <div className="flex flex-wrap gap-1.5">
                {slotList.map((slot) => (
                  <Chip
                    key={slot}
                    label={slot}
                    hint={slotHint(slot)}
                    testId={`employee-chip-slot-${slot}`}
                    removeLabel={t('employees.detail.removeItem', { name: slot })}
                    onRemove={() => setSlotList((prev) => prev.filter((s) => s !== slot))}
                  />
                ))}
              </div>
            ) : (
              <p className="text-[11px] text-text-muted">{t('employees.detail.emptySlots')}</p>
            )}
            <div className="flex flex-wrap items-center gap-1.5">
              {slotOptions.length ? (
                <select
                  className="sselect min-w-[160px] flex-1"
                  value=""
                  aria-label={t('employees.detail.addSlot')}
                  onChange={(e) => {
                    if (e.target.value) setSlotList((prev) => [...prev, e.target.value]);
                  }}
                >
                  <option value="">{t('employees.detail.addSlot')}</option>
                  {slotOptions.map((s) => (
                    <option key={s.path} value={s.path}>
                      {s.name}（{s.path}）
                    </option>
                  ))}
                </select>
              ) : null}
              <input
                id="employee-slots"
                type="text"
                className="sinput mono min-w-[160px] flex-1"
                value={customSlot}
                onChange={(e) => setCustomSlot(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key !== 'Enter') return;
                  e.preventDefault();
                  const add = parseList(customSlot);
                  if (add.length) setSlotList((prev) => [...prev, ...add]);
                  setCustomSlot('');
                }}
                spellCheck={false}
                placeholder="~/.frago/data/stock"
                aria-label={t('employees.detail.customSlot')}
              />
              <button
                type="button"
                className="page-header-btn"
                disabled={!parseList(customSlot).length}
                data-testid="employee-add-slot"
                onClick={() => {
                  const add = parseList(customSlot);
                  if (add.length) setSlotList((prev) => [...prev, ...add]);
                  setCustomSlot('');
                }}
              >
                {t('employees.detail.add')}
              </button>
            </div>
          </div>

          {/* 知识域 */}
          <div className="flex flex-col gap-1.5">
            <label className="text-[11.5px] font-medium text-text-secondary" htmlFor="employee-domains">
              {t('employees.detail.domainsLabel')}
            </label>
            {domainList.length ? (
              <div className="flex flex-wrap gap-1.5">
                {domainList.map((name) => (
                  <Chip
                    key={name}
                    label={name}
                    hint={domainHint(name)}
                    testId={`employee-chip-domain-${name}`}
                    removeLabel={t('employees.detail.removeItem', { name })}
                    onRemove={() => setDomainList((prev) => prev.filter((d) => d !== name))}
                  />
                ))}
              </div>
            ) : (
              <p className="text-[11px] text-text-muted">{t('employees.detail.emptyDomains')}</p>
            )}
            <div className="flex flex-wrap items-center gap-1.5">
              {domainOptions.length ? (
                <select
                  className="sselect min-w-[160px] flex-1"
                  value=""
                  aria-label={t('employees.detail.addDomain')}
                  onChange={(e) => {
                    if (e.target.value) setDomainList((prev) => [...prev, e.target.value]);
                  }}
                >
                  <option value="">{t('employees.detail.addDomain')}</option>
                  {domainOptions.map((d) => (
                    <option key={d.name} value={d.name} title={d.purpose}>
                      {d.name}
                    </option>
                  ))}
                </select>
              ) : null}
              <input
                id="employee-domains"
                type="text"
                className="sinput mono min-w-[160px] flex-1"
                value={customDomain}
                onChange={(e) => setCustomDomain(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key !== 'Enter') return;
                  e.preventDefault();
                  const add = parseList(customDomain);
                  if (add.length) setDomainList((prev) => [...prev, ...add]);
                  setCustomDomain('');
                }}
                spellCheck={false}
                placeholder="etf-research"
                aria-label={t('employees.detail.customDomain')}
              />
              <button
                type="button"
                className="page-header-btn"
                disabled={!parseList(customDomain).length}
                data-testid="employee-add-domain"
                onClick={() => {
                  const add = parseList(customDomain);
                  if (add.length) setDomainList((prev) => [...prev, ...add]);
                  setCustomDomain('');
                }}
              >
                {t('employees.detail.add')}
              </button>
            </div>
          </div>

          {/* 配方 */}
          <div className="flex flex-col gap-1.5">
            <label className="text-[11.5px] font-medium text-text-secondary" htmlFor="employee-recipes">
              {t('employees.detail.recipesLabel')}
            </label>
            {recipeList.length ? (
              <div className="flex flex-wrap gap-1.5">
                {recipeList.map((name) => (
                  <Chip
                    key={name}
                    label={name}
                    hint={recipeHint(name)}
                    testId={`employee-chip-recipe-${name}`}
                    removeLabel={t('employees.detail.removeItem', { name })}
                    onRemove={() => setRecipeList((prev) => prev.filter((r) => r !== name))}
                  />
                ))}
              </div>
            ) : (
              <p className="text-[11px] text-text-muted">{t('employees.detail.emptyRecipes')}</p>
            )}
            <div className="flex flex-wrap items-center gap-1.5">
              {recipeOptions.length ? (
                <select
                  className="sselect min-w-[160px] flex-1"
                  value=""
                  aria-label={t('employees.detail.addRecipe')}
                  onChange={(e) => {
                    if (e.target.value) setRecipeList((prev) => [...prev, e.target.value]);
                  }}
                >
                  <option value="">{t('employees.detail.addRecipe')}</option>
                  {recipeOptions.map((r) => (
                    <option key={r.name} value={r.name} title={r.description}>
                      {r.display_title || r.name}
                    </option>
                  ))}
                </select>
              ) : null}
              <input
                id="employee-recipes"
                type="text"
                className="sinput mono min-w-[160px] flex-1"
                value={customRecipe}
                onChange={(e) => setCustomRecipe(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key !== 'Enter') return;
                  e.preventDefault();
                  const add = parseList(customRecipe);
                  if (add.length) setRecipeList((prev) => [...prev, ...add]);
                  setCustomRecipe('');
                }}
                spellCheck={false}
                placeholder="cn_stock_data_feed"
                aria-label={t('employees.detail.customRecipe')}
              />
              <button
                type="button"
                className="page-header-btn"
                disabled={!parseList(customRecipe).length}
                data-testid="employee-add-recipe"
                onClick={() => {
                  const add = parseList(customRecipe);
                  if (add.length) setRecipeList((prev) => [...prev, ...add]);
                  setCustomRecipe('');
                }}
              >
                {t('employees.detail.add')}
              </button>
            </div>
          </div>

          {/* 默认技能 */}
          <div className="flex flex-col gap-1.5">
            <label className="text-[11.5px] font-medium text-text-secondary" htmlFor="employee-skills">
              {t('employees.detail.skillsLabel')}
            </label>
            {skillList.length ? (
              <div className="flex flex-wrap gap-1.5">
                {skillList.map((name) => (
                  <Chip
                    key={name}
                    label={name}
                    hint={skillHint(name)}
                    testId={`employee-chip-skill-${name}`}
                    removeLabel={t('employees.detail.removeItem', { name })}
                    onRemove={() => setSkillList((prev) => prev.filter((s) => s !== name))}
                  />
                ))}
              </div>
            ) : (
              <p className="text-[11px] text-text-muted">{t('employees.detail.emptySkills')}</p>
            )}
            <div className="flex flex-wrap items-center gap-1.5">
              {skillOptions.length ? (
                <select
                  className="sselect min-w-[160px] flex-1"
                  value=""
                  aria-label={t('employees.detail.addSkill')}
                  onChange={(e) => {
                    if (e.target.value) setSkillList((prev) => [...prev, e.target.value]);
                  }}
                >
                  <option value="">{t('employees.detail.addSkill')}</option>
                  {skillOptions.map((s) => (
                    <option key={s.name} value={s.name} title={s.description || ''}>
                      {s.name}
                    </option>
                  ))}
                </select>
              ) : null}
              <input
                id="employee-skills"
                type="text"
                className="sinput mono min-w-[160px] flex-1"
                value={customSkill}
                onChange={(e) => setCustomSkill(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key !== 'Enter') return;
                  e.preventDefault();
                  const add = parseList(customSkill);
                  if (add.length) setSkillList((prev) => [...prev, ...add]);
                  setCustomSkill('');
                }}
                spellCheck={false}
                placeholder="git-push"
                aria-label={t('employees.detail.customSkill')}
              />
              <button
                type="button"
                className="page-header-btn"
                disabled={!parseList(customSkill).length}
                data-testid="employee-add-skill"
                onClick={() => {
                  const add = parseList(customSkill);
                  if (add.length) setSkillList((prev) => [...prev, ...add]);
                  setCustomSkill('');
                }}
              >
                {t('employees.detail.add')}
              </button>
            </div>
          </div>

          {/* 员工从历史记录里学到什么：会话与词条摊开给人看，不用去命令行翻账本。 */}
          {hasDiscovery ? (
            <div className="border-t border-border-color pt-2">
              <button
                type="button"
                className="flex w-full items-center gap-1.5 text-left text-[11.5px] font-medium text-text-secondary transition-colors hover:text-text-primary"
                onClick={() => setDiscoveryOpen((v) => !v)}
                aria-expanded={discoveryOpen}
                data-testid="employee-discovery-toggle"
              >
                {discoveryOpen ? (
                  <ChevronDown size={13} strokeWidth={1.5} />
                ) : (
                  <ChevronRight size={13} strokeWidth={1.5} />
                )}
                {t('employees.detail.drawerTitle')}
              </button>

              {discoveryOpen ? (
                <div className="mt-1.5 flex flex-col gap-2" data-testid="employee-discovery-body">
                  {sessions.length ? (
                    <div className="flex flex-col gap-1">
                      <span className="text-[11px] text-text-muted">
                        {t('employees.detail.drawerSessions')}
                      </span>
                      <ul className="flex flex-col gap-0.5">
                        {sessions.slice(0, 5).map((s) => (
                          <li
                            key={s.session_id}
                            className="truncate text-[11px] text-text-secondary"
                            title={s.first_prompt_summary || s.title}
                          >
                            {s.title}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}

                  {glossary.length ? (
                    <div className="flex flex-col gap-1">
                      <span className="text-[11px] text-text-muted">
                        {t('employees.detail.drawerGlossary')}
                      </span>
                      <ul className="flex flex-col gap-0.5">
                        {glossary.slice(0, 8).map((g) => (
                          <li key={g.term} className="text-[11px] text-text-secondary">
                            <span className="text-text-primary">{g.term}</span>
                            <span className="text-text-muted"> — {g.meaning}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}

                  {sessions.length > 5 || glossary.length > 8 ? (
                    <p className="text-[10.5px] text-text-muted">
                      {t('employees.detail.drawerMore', {
                        n: Math.max(sessions.length - 5, 0) + Math.max(glossary.length - 8, 0),
                      })}
                    </p>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}

      {/* 领地底账：服务端实时扫出来的那一层。只有改的时候才有得看——新建的岗位还没有领地。 */}
      {!isCreate ? (
        <div className="fbox">
          <div className="flex items-center gap-2">
            <span className="fbox-h">{t('employees.detail.territoryTitle')}</span>
            {detailError ? (
              <span className="text-[11px] text-accent-error">{t('employees.detail.territoryFailed')}</span>
            ) : null}
          </div>

          {detail ? (
            detail.managed_data.data_slots.length ? (
              <div className="flex flex-col gap-2.5">
                {detail.managed_data.data_slots.map((slot) => (
                  <div key={slot.slot_path} className="flex flex-col gap-1">
                    <div className="flex items-baseline gap-2">
                      <span className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-text-primary" title={slot.resolved_path}>
                        {slot.slot_path}
                      </span>
                      <span className="shrink-0 text-[11px] text-text-muted">
                        {slot.exists
                          ? t('employees.detail.slotCount', { n: slot.total_count })
                          : t('employees.detail.slotMissing')}
                      </span>
                    </div>
                    {slot.entries.length ? (
                      <ul className="grid grid-cols-2 gap-x-2.5 gap-y-0.5">
                        {slot.entries.map((entry) => (
                          <li
                            key={entry.name}
                            className="truncate font-mono text-[10.5px] text-text-secondary"
                            title={entry.summary || entry.name}
                          >
                            {entry.name}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-[11.5px] text-text-muted">{t('employees.detail.territoryEmpty')}</p>
            )
          ) : (
            <p className="flex items-center gap-1.5 text-[11.5px] text-text-muted">
              {detailError ? null : <RefreshCw size={12} className="cs-spin" />}
              {detailError ?? t('employees.detail.territoryLoading')}
            </p>
          )}

          {/* 在领地里登记一个新归档目录 */}
          <div className="flex flex-col gap-2 border-t border-border-color pt-2.5">
            <span className="text-[11.5px] font-medium text-text-secondary">
              {t('employees.detail.registerTitle')}
            </span>
            <div className="flex flex-wrap items-center gap-1.5">
              <input
                type="text"
                className="sinput mono min-w-[140px] flex-1"
                value={folderName}
                onChange={(e) => setFolderName(e.target.value)}
                spellCheck={false}
                placeholder="20261101-signal-review"
                aria-label={t('employees.detail.registerName')}
              />
              <select
                className="sselect"
                value={folderSlot}
                onChange={(e) => setFolderSlot(e.target.value)}
                aria-label={t('employees.detail.registerSlot')}
              >
                {(detail?.managed_data.data_slots ?? []).map((s) => (
                  <option key={s.slot_path} value={s.slot_path}>
                    {s.slot_path}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="page-header-btn"
                onClick={handleRegister}
                disabled={registering || !folderName.trim() || !folderSlot}
                data-testid="employee-register-data"
              >
                {registering ? <Loader2 size={14} className="cs-spin" /> : <FolderPlus size={14} strokeWidth={1.5} />}
                {t('employees.detail.register')}
              </button>
            </div>
            <input
              type="text"
              className="sinput"
              value={folderSummary}
              onChange={(e) => setFolderSummary(e.target.value)}
              placeholder={t('employees.detail.registerSummary')}
              aria-label={t('employees.detail.registerSummary')}
            />
            <p className="hint">{t('employees.detail.registerHint')}</p>
            {dataError ? (
              <p className="break-words text-[11px] text-accent-error">
                {t('employees.detail.dataFailed', { reason: dataError })}
              </p>
            ) : null}
            {dataNote ? <p className="text-[11px] text-text-secondary">{dataNote}</p> : null}
          </div>
        </div>
      ) : null}
    </DialogShell>
  );
}
