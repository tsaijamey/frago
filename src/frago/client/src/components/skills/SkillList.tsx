import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Search, X, BookOpen, Target, FolderOpen, ExternalLink } from 'lucide-react';
import { useAppStore } from '@/stores/appStore';
import { useAutoRefresh } from '@/hooks/useAutoRefresh';
import { rawFileUrl } from '@/api';
import EmptyState from '@/components/ui/EmptyState';
import InlineMarkdown from '@/components/ui/InlineMarkdown';
import LoadingSpinner from '@/components/ui/LoadingSpinner';
import Modal from '@/components/ui/Modal';
import PageHeader from '@/components/layout/PageHeader';
import type { SkillItem } from '@/types/pywebview';

/** 技能目录里那份说明文件的标准名。 */
const SKILL_FILE = 'SKILL.md';

/**
 * 技能在哪一家 agent 的目录里。
 *
 * 同一个技能常常被好几家共用（Claude Code 的目录、Codex 的目录…），服务端把 `agents`
 * 报成一份名单。这一页按「谁看得见」给一档过滤，比按名字搜更好用——人找的往往是
 * 「我在 Codex 里能用哪些」。
 *
 * 这一栏不在 `SkillItem` 的契约里（pywebview 那一路就不带它），所以按可选字段读：
 * 读到就多一排过滤，读不到这一页照常是纯列表，不会因为字段缺失而报错。
 */
function agentsOf(skill: SkillItem): string[] {
  const raw = (skill as SkillItem & { agents?: unknown }).agents;
  if (!Array.isArray(raw)) return [];
  return raw.filter((a): a is string => typeof a === 'string' && a.length > 0);
}

/**
 * 技能列表页。
 *
 * 一屏最多几十个技能，每一个的第一句话（description）才是人决定「要不要用」的依据，
 * 所以卡片把名字、描述、路径三层排开，描述**严格 clamp 到 3 行**——长短不一的摘要会
 * 把卡片撑成一片参差的砖墙，clamp 之后每张卡高度接近，扫读的节奏才成立。
 *
 * 点开卡片不跳页：技能的内容就是一份 Markdown，为看一份文档离开这一页再回来，找不回
 * 刚才看到哪一行。所以用通用浮窗就地读全文。
 */
export default function SkillList() {
  const { t } = useTranslation();
  const { skills, loadSkills } = useAppStore();
  const [search, setSearch] = useState('');
  const [agentFilter, setAgentFilter] = useState<string>('all');
  const [open, setOpen] = useState<SkillItem | null>(null);

  // 技能目录在本机随时会被加减。挂载时取一次就不动的话，人装完一个技能回到这页
  // 会以为没装上。
  useAutoRefresh(loadSkills, { intervalMs: 30_000 });

  // 有哪些来源可筛，按出现次数从多到少排：人最常用的那一家排在最前。
  const agentCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const skill of skills) {
      for (const agent of agentsOf(skill)) {
        counts.set(agent, (counts.get(agent) ?? 0) + 1);
      }
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [skills]);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return skills.filter((skill) => {
      if (agentFilter !== 'all' && !agentsOf(skill).includes(agentFilter)) return false;
      if (!query) return true;
      return (
        skill.name.toLowerCase().includes(query) ||
        (skill.description ?? '').toLowerCase().includes(query)
      );
    });
  }, [skills, search, agentFilter]);

  if (skills.length === 0) {
    return (
      <EmptyState
        Icon={Target}
        title={t('skills.noSkills')}
        description={t('skills.createSkillHint')}
      />
    );
  }

  return (
    <div className="flex flex-col h-full tdp sk-page">
      {/* C1 页头：名字 + 短计数。计数跟的是「这一页一共收了几个」，不随筛选变——
          它是这页的规模，不是这次筛选的结果。 */}
      <PageHeader
        title={t('skills.title')}
        meta={t('skills.headerMeta', { count: skills.length })}
      />

      <div className="td-toolbar tdp-toolbar">
        <div className="ui-search-box td-search">
          <Search size={16} className="ui-search-box-icon" />
          <input
            type="text"
            placeholder={t('skills.searchPlaceholder')}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label={t('skills.searchPlaceholder')}
          />
          {search && (
            <button
              type="button"
              className="ui-search-box-clear"
              onClick={() => setSearch('')}
              aria-label={t('common.clear')}
            >
              <X size={14} />
            </button>
          )}
        </div>

        {/* C6 来源过滤胶囊：只在真有多家来源时出现。只有一家时这一排等于白占一行，
            筛不筛都是同一个结果。 */}
        {agentCounts.length > 1 && (
          <div className="ui-seg-group tdp-seg-group" role="group" aria-label={t('skills.filterByAgent')}>
            <button
              type="button"
              className={`ui-seg-pill ${agentFilter === 'all' ? 'ui-seg-pill--active' : ''}`}
              onClick={() => setAgentFilter('all')}
              aria-pressed={agentFilter === 'all'}
            >
              {t('skills.filterAll')}
              <span className="ui-seg-count">{skills.length}</span>
            </button>
            {agentCounts.map(([agent, count]) => (
              <button
                key={agent}
                type="button"
                className={`ui-seg-pill ${agentFilter === agent ? 'ui-seg-pill--active' : ''}`}
                onClick={() => setAgentFilter(agent)}
                aria-pressed={agentFilter === agent}
              >
                {agent}
                <span className="ui-seg-count">{count}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {filtered.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-[var(--text-muted)]">
          {t('skills.noResults')}
        </div>
      ) : (
        <div className="page-scroll grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 content-start">
          {filtered.map((skill) => (
            <button
              key={skill.name}
              type="button"
              className="ui-bezel-card ui-bezel-card--interactive sk-card"
              onClick={() => setOpen(skill)}
            >
              <div className="flex items-start gap-3">
                <BookOpen size={20} className="text-[var(--text-secondary)] flex-shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <div className="sk-card-name">{skill.name}</div>
                  {skill.description && (
                    /* 严格 clamp 3 行：摘要长短不一时，卡片高度接近，扫读才有节奏。 */
                    <p className="sk-card-desc line-clamp-3"><InlineMarkdown content={skill.description} /></p>
                  )}
                  <div className="sk-card-path">{skill.file_path}</div>
                </div>
              </div>
            </button>
          ))}
        </div>
      )}

      {open && <SkillDetailModal skill={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

/**
 * 技能详情浮窗：完整的 SKILL.md + 它在磁盘上的位置。
 *
 * 内容走 `rawFileUrl`——服务端把文件原样吐回来，跟 `frago view` 用的是同一条路，
 * 这里不重做一遍读取。纯报信、不承载输入，所以点遮罩可以关（`dismissOnBackdrop`）。
 */
function SkillDetailModal({ skill, onClose }: { skill: SkillItem; onClose: () => void }) {
  const { t } = useTranslation();
  const [body, setBody] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setBody(null);
    setError(null);
    if (!skill.file_path) {
      setError(t('skills.noFilePath'));
      return;
    }
    fetch(rawFileUrl(skill.file_path))
      .then((res) => {
        if (!res.ok) throw new Error(String(res.status));
        return res.text();
      })
      .then((text) => {
        if (alive) setBody(text);
      })
      .catch(() => {
        if (alive) setError(t('skills.readFailed'));
      });
    return () => {
      alive = false;
    };
  }, [skill.file_path, t]);

  return (
    <Modal
      isOpen
      onClose={onClose}
      title={skill.name}
      dismissOnBackdrop
      footer={
        skill.file_path ? (
          <a
            className="btn btn-secondary gap-2"
            href={rawFileUrl(skill.file_path)}
            target="_blank"
            rel="noopener noreferrer"
          >
            <ExternalLink size={14} />
            {t('skills.openRaw')}
          </a>
        ) : null
      }
    >
      <div className="space-y-3">
        {skill.description && (
          <p className="text-sm text-[var(--text-secondary)]"><InlineMarkdown content={skill.description} /></p>
        )}

        {/* 路径单独一块：人复制它去终端，所以用等宽字、可选中。 */}
        {skill.file_path && (
          <div className="flex items-start gap-2 p-2.5 rounded-md bg-[var(--bg-subtle)]">
            <FolderOpen size={14} className="text-[var(--text-muted)] mt-0.5 flex-shrink-0" />
            <code className="text-xs font-mono text-[var(--text-secondary)] break-all select-all">
              {skill.file_path}
            </code>
          </div>
        )}

        {agentsOf(skill).length > 0 && (
          <div className="flex items-center gap-1.5 flex-wrap text-xs text-[var(--text-muted)]">
            {agentsOf(skill).map((agent) => (
              <span key={agent} className="px-2 py-0.5 rounded bg-[var(--bg-subtle)]">
                {agent}
              </span>
            ))}
          </div>
        )}

        <div className="border-t border-[var(--border-color)] pt-3">
          <span className="text-xs font-medium text-[var(--text-secondary)]">
            {SKILL_FILE}
          </span>
          {error ? (
            <p className="text-sm text-[var(--accent-error)] mt-2">{error}</p>
          ) : body === null ? (
            <div className="flex items-center justify-center py-8">
              <LoadingSpinner size="lg" />
            </div>
          ) : (
            <pre className="mt-2 bg-[var(--bg-tertiary)] p-3 rounded text-xs font-mono overflow-auto max-h-[50vh] whitespace-pre-wrap break-words">
              {body}
            </pre>
          )}
        </div>
      </div>
    </Modal>
  );
}
