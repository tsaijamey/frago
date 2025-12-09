import { useEffect } from 'react';
import { useAppStore } from '@/stores/appStore';
import EmptyState from '@/components/ui/EmptyState';

export default function SkillList() {
  const { skills, loadSkills } = useAppStore();

  useEffect(() => {
    loadSkills();
  }, [loadSkills]);

  if (skills.length === 0) {
    return (
      <EmptyState
        icon="🎯"
        title="暂无技能"
        description="在 .claude/skills/ 目录下创建技能文件"
      />
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {skills.map((skill) => (
        <div key={skill.name} className="card">
          <div className="flex items-start gap-3">
            <span className="text-xl">{skill.icon || '📚'}</span>
            <div className="flex-1 min-w-0">
              <div className="font-medium text-[var(--text-primary)]">
                {skill.name}
              </div>
              {skill.description && (
                <p className="text-sm text-[var(--text-secondary)] mt-1">
                  {skill.description}
                </p>
              )}
              <div className="text-xs text-[var(--text-muted)] mt-2 font-mono">
                {skill.file_path}
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
