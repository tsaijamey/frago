/**
 * 编辑分类清单：增、删、改名、上下挪。
 *
 * 清单里的位置就是排序时的名次，所以「上下挪」不是整理观感，是在改事务清单的顺序。
 * 所有改动先落在本地草稿上，按「保存」才整张交给服务端——挪到一半的清单不该让事务
 * 页的顺序跟着跳。
 *
 * 已有分类的 id 锁死：事务文件里存的就是它，改了等于让那些事务失联。只有显示名能改。
 */

import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowDown, ArrowUp, Loader2, Plus, Trash2 } from 'lucide-react';
import * as api from '@/api';
import type { TodoCategory } from '@/api';
import {
  MAX_CATEGORIES,
  moveRow,
  validateCategoryDraft,
  type CategoryDraft,
} from './todoMeta';

interface TodoCategoryEditorProps {
  categories: TodoCategory[];
  /** 每个分类 id 正被几件事务引用，删之前要照实说。 */
  usage: Record<string, number>;
  onSaved: () => void;
  onCancel: () => void;
}

export default function TodoCategoryEditor({
  categories,
  usage,
  onSaved,
  onCancel,
}: TodoCategoryEditorProps) {
  const { t } = useTranslation();
  const [rows, setRows] = useState<CategoryDraft[]>(() =>
    categories.map((c) => ({ key: c.id, id: c.id, name: c.name, isNew: false }))
  );
  const nextKey = useRef(0);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const problem = validateCategoryDraft(rows);
  const full = rows.length >= MAX_CATEGORIES;
  // 删掉的分类里还有事务在用的，保存前摆出来：它们会按未分类排。
  const removedInUse = categories
    .filter((c) => !rows.some((r) => r.id === c.id) && (usage[c.id] ?? 0) > 0)
    .map((c) => ({ ...c, n: usage[c.id] }));

  const patch = (index: number, change: Partial<CategoryDraft>) =>
    setRows((prev) => prev.map((row, i) => (i === index ? { ...row, ...change } : row)));

  const save = async () => {
    if (problem || saving) return;
    setSaving(true);
    setSaveError(null);
    try {
      await api.updateTodoCategories(rows.map((r) => ({ id: r.id.trim(), name: r.name.trim() })));
      onSaved();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="td-composer td-cat-editor">
      <div className="td-cat-editor-head">
        <span className="td-cat-editor-title">{t('todos.categoryEditor.title')}</span>
        <span className="td-composer-hint">
          {t('todos.categoryEditor.desc', { n: rows.length, max: MAX_CATEGORIES })}
        </span>
      </div>

      <ol className="td-cat-rows">
        {rows.map((row, i) => {
          const used = usage[row.id] ?? 0;
          const invalid = problem?.index === i;
          return (
            <li key={row.key} className={`td-cat-row ${invalid ? 'td-cat-row--invalid' : ''}`}>
              <span className="td-cat-rank">{i + 1}</span>
              <input
                type="text"
                className="td-cat-input"
                value={row.name}
                onChange={(e) => patch(i, { name: e.target.value })}
                placeholder={t('todos.categoryEditor.namePlaceholder')}
                aria-label={t('todos.categoryEditor.namePlaceholder')}
              />
              {row.isNew ? (
                <input
                  type="text"
                  className="td-cat-input td-cat-input--id"
                  value={row.id}
                  onChange={(e) => patch(i, { id: e.target.value.toLowerCase() })}
                  placeholder={t('todos.categoryEditor.idPlaceholder')}
                  aria-label={t('todos.categoryEditor.idPlaceholder')}
                />
              ) : (
                <span className="td-cat-id" title={t('todos.categoryEditor.idLocked')}>
                  {row.id}
                </span>
              )}
              <span className="td-cat-usage">{t('todos.categoryEditor.usage', { n: used })}</span>
              <div className="td-cat-actions">
                <button
                  type="button"
                  className="td-close"
                  onClick={() => setRows((prev) => moveRow(prev, i, -1))}
                  disabled={i === 0}
                  aria-label={t('todos.categoryEditor.moveUp')}
                >
                  <ArrowUp size={14} />
                </button>
                <button
                  type="button"
                  className="td-close"
                  onClick={() => setRows((prev) => moveRow(prev, i, 1))}
                  disabled={i === rows.length - 1}
                  aria-label={t('todos.categoryEditor.moveDown')}
                >
                  <ArrowDown size={14} />
                </button>
                <button
                  type="button"
                  className="td-close"
                  onClick={() => setRows((prev) => prev.filter((_, j) => j !== i))}
                  aria-label={t('todos.categoryEditor.remove')}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </li>
          );
        })}
      </ol>

      <button
        type="button"
        className="td-filter td-cat-add"
        onClick={() =>
          setRows((prev) => [...prev, { key: `new-${nextKey.current++}`, id: '', name: '', isNew: true }])
        }
        disabled={full}
      >
        <Plus size={14} />
        {full ? t('todos.categoryEditor.full', { max: MAX_CATEGORIES }) : t('todos.categoryEditor.add')}
      </button>

      {removedInUse.map((c) => (
        <div key={c.id} className="td-error">
          {t('todos.categoryEditor.removedInUse', { name: c.name, n: c.n })}
        </div>
      ))}
      {problem && (
        <div className="td-error">
          {t(`todos.categoryEditor.errors.${problem.error}`, { row: problem.index + 1, max: MAX_CATEGORIES })}
        </div>
      )}
      {saveError && <div className="td-error">{t('todos.categoryEditor.failed', { message: saveError })}</div>}

      <div className="td-composer-foot">
        <button type="button" className="cs-refresh" onClick={onCancel} disabled={saving}>
          {t('todos.categoryEditor.cancel')}
        </button>
        <button
          type="button"
          className="td-composer-submit"
          onClick={() => void save()}
          disabled={saving || problem !== null}
        >
          {saving && <Loader2 size={14} className="animate-spin" />}
          {saving ? t('todos.categoryEditor.saving') : t('todos.categoryEditor.save')}
        </button>
      </div>
    </div>
  );
}
