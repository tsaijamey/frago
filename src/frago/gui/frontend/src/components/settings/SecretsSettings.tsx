/**
 * Secrets Settings 组件
 * 环境变量管理：Recipe 变量提示 + 分组显示 + CRUD
 */

import { useEffect, useState } from 'react';
import { getEnvVars, updateEnvVars, getRecipeEnvRequirements } from '@/api/pywebview';
import type { RecipeEnvRequirement } from '@/types/pywebview.d';
import { Key, Plus, Edit2, Trash2, Eye, EyeOff } from 'lucide-react';
import Modal from '@/components/ui/Modal';

interface EnvVarGroup {
  [group: string]: Array<[string, string]>;
}

export default function SecretsSettings() {
  const [envVars, setEnvVars] = useState<Record<string, string>>({});
  const [recipeRequirements, setRecipeRequirements] = useState<RecipeEnvRequirement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [formKey, setFormKey] = useState('');
  const [formValue, setFormValue] = useState('');
  const [formError, setFormError] = useState<string | null>(null);
  const [visibleVars, setVisibleVars] = useState<Set<string>>(new Set());

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      setLoading(true);
      const [envResult, recipeResult] = await Promise.all([
        getEnvVars(),
        getRecipeEnvRequirements(),
      ]);
      setEnvVars(envResult.vars || {});
      setRecipeRequirements(recipeResult);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  };

  const groupEnvVars = (
    vars: Record<string, string>,
    recipeReqs: RecipeEnvRequirement[]
  ): EnvVarGroup => {
    const recipeVarNames = new Set(recipeReqs.map(r => r.var_name));

    const groups: EnvVarGroup = {
      Recipe: [],
      GitHub: [],
      'AI APIs': [],
      Database: [],
      Other: [],
    };

    Object.entries(vars).forEach(([key, value]) => {
      // 优先检查是否是 Recipe 变量
      if (recipeVarNames.has(key)) {
        groups['Recipe'].push([key, value]);
      } else if (key.startsWith('GITHUB_') || key.startsWith('GH_')) {
        groups['GitHub'].push([key, value]);
      } else if (key.includes('API_KEY') || key.includes('TOKEN') || key.includes('KEY')) {
        groups['AI APIs'].push([key, value]);
      } else if (key.includes('DB_') || key.includes('DATABASE_')) {
        groups['Database'].push([key, value]);
      } else {
        groups['Other'].push([key, value]);
      }
    });

    // 移除空分组
    return Object.fromEntries(
      Object.entries(groups).filter(([_, vars]) => vars.length > 0)
    ) as EnvVarGroup;
  };

  const maskValue = (value: string, key: string): string => {
    if (visibleVars.has(key)) {
      return value;
    }
    if (value.length <= 8) {
      return '••••••';
    }
    return value.slice(0, 4) + '••••••' + value.slice(-4);
  };

  const toggleVisibility = (key: string) => {
    setVisibleVars((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(key)) {
        newSet.delete(key);
      } else {
        newSet.add(key);
      }
      return newSet;
    });
  };

  const handleAdd = () => {
    setEditingKey(null);
    setFormKey('');
    setFormValue('');
    setFormError(null);
    setShowModal(true);
  };

  const handleEdit = (key: string, value: string) => {
    setEditingKey(key);
    setFormKey(key);
    setFormValue(value);
    setFormError(null);
    setShowModal(true);
  };

  const handleDelete = async (key: string) => {
    if (!confirm(`确定要删除环境变量 ${key} 吗？`)) {
      return;
    }

    try {
      const result = await updateEnvVars({ [key]: null });
      if (result.status === 'ok' && result.vars) {
        setEnvVars(result.vars);
        // 重新加载 recipe 需求以更新 configured 状态
        const recipeResult = await getRecipeEnvRequirements();
        setRecipeRequirements(recipeResult);
      } else {
        setError(result.error || '删除失败');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败');
    }
  };

  const handleSave = async () => {
    // 验证
    if (!formKey.trim()) {
      setFormError('变量名不能为空');
      return;
    }
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(formKey)) {
      setFormError('变量名只能包含字母、数字和下划线，且不能以数字开头');
      return;
    }
    if (!formValue.trim()) {
      setFormError('变量值不能为空');
      return;
    }

    // 检查冲突
    if (!editingKey && formKey in envVars) {
      if (!confirm(`变量 ${formKey} 已存在，是否覆盖？`)) {
        return;
      }
    }

    try {
      const result = await updateEnvVars({ [formKey]: formValue });
      if (result.status === 'ok' && result.vars) {
        setEnvVars(result.vars);
        setShowModal(false);
        setError(null);
        // 重新加载 recipe 需求以更新 configured 状态
        const recipeResult = await getRecipeEnvRequirements();
        setRecipeRequirements(recipeResult);
      } else {
        setFormError(result.error || '保存失败');
      }
    } catch (err) {
      setFormError(err instanceof Error ? err.message : '保存失败');
    }
  };

  const handleQuickAdd = async (requirement: RecipeEnvRequirement) => {
    setEditingKey(null);
    setFormKey(requirement.var_name);
    setFormValue('');
    setFormError(null);
    setShowModal(true);
  };

  if (loading) {
    return (
      <div className="text-[var(--text-muted)] text-center py-8">正在加载...</div>
    );
  }

  // 按变量名去重，合并多个 recipe 使用同一变量的情况
  const groupedRequirements = recipeRequirements.reduce((acc, req) => {
    if (!acc[req.var_name]) {
      acc[req.var_name] = {
        var_name: req.var_name,
        required: req.required,
        description: req.description,
        configured: req.configured,
        recipes: [req.recipe_name]
      };
    } else {
      acc[req.var_name].recipes.push(req.recipe_name);
      // 如果任一 recipe 标记为必需，则整体标记为必需
      if (req.required) {
        acc[req.var_name].required = true;
      }
    }
    return acc;
  }, {} as Record<string, {
    var_name: string;
    required: boolean;
    description: string;
    configured: boolean;
    recipes: string[];
  }>);

  // 只显示未配置的 recipe 需求
  const unconfiguredRequirements = Object.values(groupedRequirements).filter(
    req => !req.configured
  );

  const groupedVars = groupEnvVars(envVars, recipeRequirements);

  return (
    <div className="space-y-4">
      {error && (
        <div className="card bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800">
          <p className="text-sm text-red-700 dark:text-red-400">{error}</p>
        </div>
      )}

      {/* 环境变量 - 大卡片 */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-[var(--accent-primary)]">环境变量</h2>
          <button onClick={handleAdd} className="btn btn-primary btn-sm flex items-center gap-2">
            <Plus size={16} />
            添加
          </button>
        </div>

        <div className="space-y-4">
          {/* Recipe 环境变量需求 - 只显示未配置的 */}
          {unconfiguredRequirements.length > 0 && (
            <div className="p-4 bg-[var(--bg-tertiary)] rounded-md border border-[var(--border-color)]">
              <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-2">
                Recipe 环境变量需求
              </h3>
              <p className="text-xs text-[var(--text-muted)] mb-3">
                以下环境变量被 Recipe 使用但尚未配置：
              </p>
              <div className="space-y-2">
                {unconfiguredRequirements.map((req) => (
                  <div
                    key={req.var_name}
                    className="flex items-start justify-between gap-2 p-3 bg-[var(--bg-base)] rounded-md"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <code className="text-sm font-mono text-[var(--text-primary)]">
                          {req.var_name}
                        </code>
                        <span className="text-xs px-1.5 py-0.5 bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400 rounded">
                          ⚠ 未配置
                        </span>
                        {req.required && (
                          <span className="text-xs px-1.5 py-0.5 bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 rounded">
                            必需
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-[var(--text-secondary)] mb-1">
                        {req.description}
                      </p>
                      <p className="text-xs text-[var(--text-muted)]">
                        使用者: {req.recipes.join(', ')}
                      </p>
                    </div>

                    <button
                      onClick={() => handleQuickAdd({ ...req, recipe_name: req.recipes[0] })}
                      className="btn btn-ghost btn-sm text-xs"
                    >
                      添加
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 已配置的环境变量 - 按分组显示 */}
          {Object.keys(envVars).length === 0 ? (
            <p className="text-sm text-[var(--text-muted)] text-center py-8">
              暂无环境变量，点击"添加"创建
            </p>
          ) : (
            <div className="space-y-4">
              {Object.entries(groupedVars).map(([group, vars]) => (
                <div key={group}>
                  <h3 className="text-sm font-medium text-[var(--text-primary)] mb-2 flex items-center gap-2">
                    <Key size={14} />
                    {group === 'Recipe' ? 'Recipe 环境变量' : group}
                  </h3>
                  <div className="space-y-2">
                    {vars.map(([key, value]) => (
                      <div
                        key={key}
                        className="flex items-center gap-2 p-3 bg-[var(--bg-subtle)] rounded-md"
                      >
                        <div className="flex-1 min-w-0">
                          <div className="text-sm font-mono text-[var(--text-primary)] mb-1">
                            {key}
                          </div>
                          <div className="text-sm font-mono text-[var(--text-secondary)] flex items-center gap-2">
                            <span className="truncate">{maskValue(value, key)}</span>
                            <button
                              onClick={() => toggleVisibility(key)}
                              className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
                            >
                              {visibleVars.has(key) ? (
                                <EyeOff size={14} />
                              ) : (
                                <Eye size={14} />
                              )}
                            </button>
                          </div>
                        </div>
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => handleEdit(key, value)}
                            className="btn btn-ghost btn-sm p-2"
                            title="编辑"
                          >
                            <Edit2 size={14} />
                          </button>
                          <button
                            onClick={() => handleDelete(key)}
                            className="btn btn-ghost btn-sm p-2 text-red-600 dark:text-red-400"
                            title="删除"
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* 添加/编辑模态框 */}
      <Modal
        isOpen={showModal}
        onClose={() => setShowModal(false)}
        title={editingKey ? '编辑环境变量' : '添加环境变量'}
        footer={
          <>
            <button onClick={() => setShowModal(false)} className="btn btn-ghost flex-1">
              取消
            </button>
            <button onClick={handleSave} className="btn btn-primary flex-1">
              保存
            </button>
          </>
        }
      >
        {formError && (
          <div className="mb-4 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-md">
            <p className="text-sm text-red-700 dark:text-red-400">{formError}</p>
          </div>
        )}

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-[var(--text-primary)] mb-2">
              变量名
            </label>
            <input
              type="text"
              value={formKey}
              onChange={(e) => setFormKey(e.target.value)}
              placeholder="例如: GITHUB_TOKEN"
              disabled={!!editingKey}
              className="w-full px-3 py-2 bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] disabled:opacity-50 font-mono"
            />
            <p className="mt-1 text-xs text-[var(--text-muted)]">
              只能包含字母、数字和下划线，不能以数字开头
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--text-primary)] mb-2">
              变量值
            </label>
            <textarea
              value={formValue}
              onChange={(e) => setFormValue(e.target.value)}
              placeholder="输入变量值"
              rows={3}
              className="w-full px-3 py-2 bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] font-mono resize-none"
            />
          </div>
        </div>
      </Modal>
    </div>
  );
}
