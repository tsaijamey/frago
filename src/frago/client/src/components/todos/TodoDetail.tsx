/**
 * 一件事务摊开看。
 *
 * 清单那一行只放得下标题和几个状态；真要判断"这件到底要做什么、做到什么算完"，
 * 靠的是背景、步骤、完成条件这三段——它们在 JSON 里，命令行 `frago todo show`
 * 看得到，界面上此前一个字都没有。
 *
 * 空的段落直接不出现，NEVER 摆一个"暂无"的空壳：三段里有两段是空的时候，满屏的
 * "暂无"会把仅有的那段真内容淹掉。
 */

import { useTranslation } from 'react-i18next';
import { ExternalLink, X } from 'lucide-react';
import type { TodoCategory, TodoItem } from '@/api';
import TodoStatusIcon from './TodoStatusIcon';
import { PRIORITY_TONE, STATUS_TONE, effectiveCategory } from './todoMeta';

interface SectionProps {
  title: string;
  children: React.ReactNode;
}

function Section({ title, children }: SectionProps) {
  return (
    <div className="td-section">
      <div className="td-section-title">{title}</div>
      {children}
    </div>
  );
}

/** 属性表的一行：左边名字，右边值。 */
function Prop({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="tdp-prop-label">{label}</dt>
      <dd className="tdp-prop-value">{children}</dd>
    </>
  );
}

interface TodoDetailProps {
  todo: TodoItem;
  categories: TodoCategory[];
  onClose: () => void;
}

export default function TodoDetail({ todo, categories, onClose }: TodoDetailProps) {
  const { t } = useTranslation();
  const statusTone = STATUS_TONE[todo.status];
  const priorityTone = PRIORITY_TONE[todo.priority];
  const category = categories.find((c) => c.id === effectiveCategory(todo.category, categories));
  // 分类被删了、事务里还留着旧 id：显示成未分类（它就是这么排的），但把旧 id 说出来，
  // 人才知道把那个分类加回来它就会归位。
  const orphanId = todo.category && !category ? todo.category : null;

  return (
    <div className="td-panel tdp-panel">
      <div className="td-head">
        <div className="min-w-0 flex-1">
          <h2 className="td-title">{todo.title}</h2>
          <div className="td-id">{todo.id}</div>
        </div>
        <button type="button" className="td-close" onClick={onClose} aria-label={t('common.close')}>
          <X size={16} />
        </button>
      </div>

      {/* 「这件现在什么情况」的几项答案排成一张两列表，眼睛只沿一条竖线往下扫；
          正文三段（背景、步骤、完成条件）放在表下面，要读的时候再往下读。 */}
      <dl className="tdp-props">
        <Prop label={t('todos.detail.status')}>
          <span className={`td-chip tdp-status-chip ${statusTone.className}`}>
            <TodoStatusIcon status={todo.status} decorative />
            {t(`todos.status.${todo.status}`)}
          </span>
        </Prop>
        <Prop label={t('todos.detail.priority')}>
          <span className={`td-chip ${priorityTone.className}`}>{t(`todos.priority.${todo.priority}`)}</span>
        </Prop>
        <Prop label={t('todos.category.label')}>
          <span className={category ? '' : 'tdp-prop-muted'}>
            {category
              ? category.name
              : orphanId
                ? t('todos.category.removed', { id: orphanId })
                : t('todos.category.none')}
          </span>
        </Prop>
        <Prop label={t('todos.detail.created')}>{todo.created}</Prop>
        <Prop label={t('todos.detail.updated')}>{todo.updated}</Prop>
        {todo.done_at && <Prop label={t('todos.detail.doneAt')}>{todo.done_at}</Prop>}
        {todo.tags.length > 0 && (
          <Prop label={t('todos.detail.tags')}>
            <span className="flex flex-wrap gap-1">
              {todo.tags.map((tag) => (
                <span key={tag} className="td-tag">
                  {tag}
                </span>
              ))}
            </span>
          </Prop>
        )}
      </dl>

      <div className="td-body">
        {todo.summary && (
          <Section title={t('todos.detail.summary')}>
            <p className="td-text tdp-lead">{todo.summary}</p>
          </Section>
        )}

        {todo.context && (
          <Section title={t('todos.detail.context')}>
            <p className="td-text td-text--pre">{todo.context}</p>
          </Section>
        )}

        {todo.steps.length > 0 && (
          <Section title={t('todos.detail.steps')}>
            <ol className="td-list td-list--numbered">
              {todo.steps.map((step, i) => (
                <li key={`${i}-${step}`}>{step}</li>
              ))}
            </ol>
          </Section>
        )}

        {todo.done_when.length > 0 && (
          <Section title={t('todos.detail.doneWhen')}>
            <ul className="td-list">
              {todo.done_when.map((cond, i) => (
                <li key={`${i}-${cond}`}>{cond}</li>
              ))}
            </ul>
          </Section>
        )}

        {todo.sessions.length > 0 && (
          <Section title={t('todos.detail.sessions')}>
            {/* 会话 id 是回到原话的钥匙：细节都在那场对话里，事务正文不复述。 */}
            <ul className="td-list td-list--plain">
              {todo.sessions.map((sid) => (
                <li key={sid} className="td-id">
                  {sid}
                </li>
              ))}
            </ul>
          </Section>
        )}

        {todo.links.length > 0 && (
          <Section title={t('todos.detail.links')}>
            <ul className="td-list td-list--plain">
              {todo.links.map((link) => (
                <li key={link}>
                  <a className="td-link" href={link} target="_blank" rel="noreferrer">
                    <ExternalLink size={12} />
                    <span className="truncate">{link}</span>
                  </a>
                </li>
              ))}
            </ul>
          </Section>
        )}
      </div>
    </div>
  );
}
