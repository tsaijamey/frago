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
import type { TodoItem } from '@/api';
import { PRIORITY_TONE, STATUS_TONE } from './todoMeta';

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

interface TodoDetailProps {
  todo: TodoItem;
  onClose: () => void;
}

export default function TodoDetail({ todo, onClose }: TodoDetailProps) {
  const { t } = useTranslation();
  const statusTone = STATUS_TONE[todo.status];
  const priorityTone = PRIORITY_TONE[todo.priority];

  return (
    <div className="td-panel">
      <div className="td-head">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`td-chip ${statusTone.className}`}>
              {t(`todos.status.${todo.status}`)}
            </span>
            <span className={`td-chip ${priorityTone.className}`}>
              {t(`todos.priority.${todo.priority}`)}
            </span>
          </div>
          <h2 className="td-title">{todo.title}</h2>
          <div className="td-id">{todo.id}</div>
        </div>
        <button type="button" className="td-close" onClick={onClose} aria-label={t('common.close')}>
          <X size={16} />
        </button>
      </div>

      <div className="td-body">
        <Section title={t('todos.detail.dates')}>
          <div className="td-dates">
            <span>
              {t('todos.detail.created')}: {todo.created}
            </span>
            <span>
              {t('todos.detail.updated')}: {todo.updated}
            </span>
            {todo.done_at && (
              <span>
                {t('todos.detail.doneAt')}: {todo.done_at}
              </span>
            )}
          </div>
        </Section>

        {todo.tags.length > 0 && (
          <Section title={t('todos.detail.tags')}>
            <div className="flex flex-wrap gap-1">
              {todo.tags.map((tag) => (
                <span key={tag} className="td-tag">
                  {tag}
                </span>
              ))}
            </div>
          </Section>
        )}

        {todo.summary && <Section title={t('todos.detail.summary')}>
          <p className="td-text">{todo.summary}</p>
        </Section>}

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
