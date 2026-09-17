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

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { CircleSlash, ExternalLink, Loader2, X } from 'lucide-react';
import * as api from '@/api';
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
  /** 弃置成功之后叫一声，由清单那边重新取一遍。 */
  onDropped: () => void;
}

/**
 * 「弃置」填理由那一段。
 *
 * 界面上此前一个改动事务的入口都没有——事务全在命令行那头改。弃置是第一个：人翻到
 * 一件不打算做的事，当场就能把它放下。理由必填，而且是在这里输入的原话，服务端一个
 * 字不改地交给 `frago todo drop` 记进事务文件。
 *
 * 按钮不直接执行，要先展开这一段：弃置是终态，命令那边不让改口（已弃置的再弃置会被
 * 拒），所以按下去之前必须有一次停顿。要跑的那条命令就印在输入框下面——看不见执行了
 * 什么的按钮，没人敢按第二次。
 *
 * 它紧跟在标题那一行下面，与触发它的按钮挨着。摆到面板末尾去，正文一长就整段落在屏幕
 * 外，人按了一下会以为什么都没发生。
 */
function DropForm({
  todo,
  onCancel,
  onDropped,
}: {
  todo: TodoItem;
  onCancel: () => void;
  onDropped: () => void;
}) {
  const { t } = useTranslation();
  const [reason, setReason] = useState('');
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    const text = reason.trim();
    if (!text || working) return;
    setWorking(true);
    setError(null);
    try {
      await api.dropTodo(todo.id, text);
      setReason('');
      onDropped();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setWorking(false);
    }
  };

  return (
    <div className="tdp-drop-form">
      <p className="tdp-drop-desc">{t('todos.drop.desc')}</p>
      <textarea
        autoFocus
        className="td-composer-input tdp-drop-input"
        rows={2}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        onKeyDown={(e) => {
          // 理由常常要换行，所以回车留给换行，提交走 Cmd/Ctrl+Enter——与「添一件」同一套手势。
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            void submit();
          }
          if (e.key === 'Escape' && !working) onCancel();
        }}
        placeholder={t('todos.drop.placeholder')}
        disabled={working}
        aria-label={t('todos.drop.placeholder')}
      />
      <code className="td-composer-command tdp-drop-command">
        {`frago todo drop ${todo.id} --reason "…"`}
      </code>
      <div className="tdp-drop-foot">
        <button type="button" className="cs-refresh" onClick={onCancel} disabled={working}>
          {t('common.cancel')}
        </button>
        <button
          type="button"
          className="td-composer-submit tdp-drop-submit"
          onClick={() => void submit()}
          disabled={working || reason.trim() === ''}
        >
          {working && <Loader2 size={14} className="animate-spin" />}
          {working ? t('todos.drop.working') : t('todos.drop.submit')}
        </button>
      </div>
      {error && <div className="td-error">{t('todos.drop.failed', { message: error })}</div>}
    </div>
  );
}

export default function TodoDetail({ todo, categories, onClose, onDropped }: TodoDetailProps) {
  const { t } = useTranslation();
  const [dropping, setDropping] = useState(false);
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
        {/* 弃置摆在标题这一行：它是这块面板上唯一一个会改动事务的动作，得在人一眼看得见
            的地方，而不是等他把正文滚到底。已经弃置的不出现——命令那边也拒绝第二次弃置。 */}
        {todo.status !== 'dropped' && !dropping && (
          <button
            type="button"
            className="tdp-drop-open"
            onClick={() => setDropping(true)}
            title={t('todos.drop.button')}
          >
            <CircleSlash size={14} />
            {t('todos.drop.button')}
          </button>
        )}
        <button type="button" className="td-close" onClick={onClose} aria-label={t('common.close')}>
          <X size={16} />
        </button>
      </div>

      {dropping && (
        <DropForm
          todo={todo}
          onCancel={() => setDropping(false)}
          onDropped={() => {
            setDropping(false);
            onDropped();
          }}
        />
      )}

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
        {todo.dropped_at && <Prop label={t('todos.detail.droppedAt')}>{todo.dropped_at}</Prop>}
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
        {/* 弃置理由排在所有正文之前：这件事已经不做了，先看见为什么，再看它原本要做什么。 */}
        {todo.drop_reason && (
          <Section title={t('todos.detail.dropReason')}>
            <p className="td-text td-text--pre">{todo.drop_reason}</p>
          </Section>
        )}

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
