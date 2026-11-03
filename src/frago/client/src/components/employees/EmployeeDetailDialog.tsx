/**
 * 员工详情与数据管理弹窗。
 *
 * ## 卡片表面只放一行，岗位说明与底账住在这里
 *
 * `work_scope` 是几百字的岗位说明，`data_slots` 是一串绝对路径。这两样铺在卡片上，一屏就
 * 只剩两三张卡，人扫不出本机有几个岗位。它们住在这个窗里：想细看的人点进来看，只想挑一个
 * 起会话的人在卡片上就够。
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
import { FolderPlus, Loader2, RefreshCw } from 'lucide-react';
import DialogShell from './DialogShell';
import {
  fetchEmployee,
  registerEmployeeData,
  saveEmployee,
  type EmployeeDetail,
  type EmployeePost,
} from '@/hooks/useEmployees';
import { useAgentClients } from '@/hooks/useAgentClients';

interface EmployeeDetailDialogProps {
  /** 正看的是哪个员工。null 表示窗没开着。 */
  post: EmployeePost | null;
  /** 新建时没有 `post`，用这个标记；有 `post` 就是改。 */
  creating?: boolean;
  onClose: () => void;
  /** 存完或登记完，让页面重取清单。 */
  onSaved: () => void;
}

/** 逗号/换行/空格分隔的清单栏，读进来一个数组，写回去仍是字符串。 */
function parseList(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export default function EmployeeDetailDialog({
  post,
  creating = false,
  onClose,
  onSaved,
}: EmployeeDetailDialogProps) {
  const { t } = useTranslation();
  const open = post !== null || creating;

  const [detail, setDetail] = useState<EmployeeDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  const [memberPostId, setMemberPostId] = useState('');
  const [title, setTitle] = useState('');
  const [kernel, setKernel] = useState('claude');
  const [description, setDescription] = useState('');
  const [workScope, setWorkScope] = useState('');
  const [cwd, setCwd] = useState('');
  const [domains, setDomains] = useState('');
  const [recipes, setRecipes] = useState('');
  const [slots, setSlots] = useState('');

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedNote, setSavedNote] = useState<string | null>(null);

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
    if (post && !known.includes(post.agent_kernel)) return [post.agent_kernel, ...known];
    return known.length ? known : [kernel || 'claude'];
  }, [clients.agents, post, kernel]);

  // 换一个员工就把整块重建：上一个人的领地路径留在框里，人一按保存就把它写到新的那个
  // 员工名下了。
  useEffect(() => {
    if (!open) return;
    setSaveError(null);
    setSavedNote(null);
    setDataError(null);
    setDataNote(null);
    setFolderName('');
    setFolderSummary('');
    setFolderSlot('');
    setSaving(false);
    setRegistering(false);

    if (creating || !post) {
      setDetail(null);
      setDetailError(null);
      setMemberPostId('');
      setTitle('');
      setKernel('claude');
      setDescription('');
      setWorkScope('');
      setCwd('');
      setDomains('');
      setRecipes('');
      setSlots('');
      return;
    }

    setDetail(null);
    setDetailError(null);
    setMemberPostId(post.member_post_id);
    setTitle(post.title);
    setKernel(post.agent_kernel);
    setDescription(post.description);
    setWorkScope(post.work_scope);
    setCwd(post.cwd);
    setDomains(post.knowledge_domains.join(', '));
    setRecipes(post.recipes.join(', '));
    setSlots(post.data_slots.join('\n'));
  }, [open, creating, post]);

  // 详情只在窗开着时取。取不到时上半部分照常可编（编制本来就在 `post` 里），只有领地那一段
  // 说取不到——整块拦下来会让人连改个说明都做不成。
  useEffect(() => {
    if (!open || creating || !post) return;
    let alive = true;
    fetchEmployee(post.member_post_id)
      .then((d) => {
        if (!alive) return;
        setDetail(d);
        setDetailError(null);
        // 槽位清单以服务端扫出来的那份为准：编制里存着而磁盘上已经没了的目录，这里不列。
        if (!folderSlot) setFolderSlot(d.managed_data.data_slots[0]?.slot_path ?? '');
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setDetailError(e instanceof Error ? e.message : t('employees.errors.detailFailedPlain'));
      });
    return () => {
      alive = false;
    };
    // folderSlot 不进依赖：它是从这一趟结果里落一次的，进依赖会跟着每次选择重取一遍。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, creating, post, t]);

  const isCreate = creating || !post;
  const canSave = !saving && title.trim().length > 0 && (isCreate ? memberPostId.trim().length > 0 : true);

  const handleSave = async () => {
    if (!canSave) return;
    setSaving(true);
    setSaveError(null);
    setSavedNote(null);
    try {
      await saveEmployee(
        {
          member_post_id: memberPostId.trim(),
          title: title.trim(),
          agent_kernel: kernel,
          description: description.trim(),
          // 这两栏给空串就是「清空」；给 null 才是「这一栏不动」。编辑时人看见的就是当前值，
          // 所以这里照他框里的写。
          work_scope: workScope,
          cwd: cwd.trim(),
          knowledge_domains: parseList(domains),
          recipes: parseList(recipes),
          data_slots: parseList(slots),
          schedule_ids: post?.schedule_ids ?? [],
          allowed_commands: post?.allowed_commands ?? [],
        },
        { create: isCreate }
      );
      onSaved();
      if (isCreate) {
        // 新建完留在窗里、换成「改」的形态：刚建的岗位还没配完领地，直接关掉人得再找回来。
        setSavedNote(t('employees.detail.created'));
      } else {
        setSavedNote(t('employees.detail.saved'));
      }
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : t('employees.errors.saveFailedPlain'));
    } finally {
      setSaving(false);
    }
  };

  const handleRegister = async () => {
    const name = folderName.trim();
    if (!name || !post) return;
    setRegistering(true);
    setDataError(null);
    setDataNote(null);
    try {
      await registerEmployeeData(post.member_post_id, {
        folder_name: name,
        summary: folderSummary.trim(),
        ...(folderSlot ? { slot_path: folderSlot } : {}),
      });
      setFolderName('');
      setFolderSummary('');
      setDataNote(t('employees.detail.dataRegistered', { name }));
      // 重新取一遍详情：刚建的目录要出现在下面那份底账里，人才看得出这一下确实落地了。
      const fresh = await fetchEmployee(post.member_post_id);
      setDetail(fresh);
      onSaved();
    } catch (e) {
      setDataError(e instanceof Error ? e.message : t('employees.errors.dataFailedPlain'));
    } finally {
      setRegistering(false);
    }
  };

  if (!open) return null;

  const heading = isCreate
    ? t('employees.detail.newTitle')
    : t('employees.detail.title', { name: post?.title ?? memberPostId });

  return (
    <DialogShell
      title={heading}
      onClose={onClose}
      width={560}
      closable={!saving && !registering}
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
            onChange={(e) => setMemberPostId(e.target.value)}
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
          placeholder="~/Repos/…"
        />
        <p className="hint">{t('employees.detail.cwdHint')}</p>
      </div>

      <div className="fgrp">
        <label htmlFor="employee-slots">{t('employees.detail.slotsLabel')}</label>
        <textarea
          id="employee-slots"
          className="sinput mono"
          style={{ minHeight: 60, padding: '7px 9px', resize: 'vertical', lineHeight: 1.5 }}
          value={slots}
          onChange={(e) => setSlots(e.target.value)}
          spellCheck={false}
          placeholder="~/.frago/data/stock"
        />
        <p className="hint">{t('employees.detail.slotsHint')}</p>
      </div>

      <div className="fgrid2">
        <div className="fgrp">
          <label htmlFor="employee-domains">{t('employees.detail.domainsLabel')}</label>
          <input
            id="employee-domains"
            type="text"
            className="sinput mono"
            value={domains}
            onChange={(e) => setDomains(e.target.value)}
            spellCheck={false}
            placeholder="etf-research"
          />
        </div>
        <div className="fgrp">
          <label htmlFor="employee-recipes">{t('employees.detail.recipesLabel')}</label>
          <input
            id="employee-recipes"
            type="text"
            className="sinput mono"
            value={recipes}
            onChange={(e) => setRecipes(e.target.value)}
            spellCheck={false}
            placeholder="cn_stock_data_feed"
          />
        </div>
      </div>

      {saveError ? (
        <p className="break-words rounded-[8px] bg-accent-error-10 px-3 py-2 text-[12px] text-accent-error">
          {t('employees.detail.saveFailed', { reason: saveError })}
        </p>
      ) : null}
      {savedNote ? (
        <p className="rounded-[8px] bg-bg-secondary px-3 py-2 text-[12px] text-text-secondary">
          {savedNote}
        </p>
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
