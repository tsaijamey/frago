import { useEffect } from 'react';
import { useAppStore } from '@/stores/appStore';
import EmptyState from '@/components/ui/EmptyState';
import { Target, BookOpen } from 'lucide-react';

export default function SkillList() {
  const { skills, loadSkills } = useAppStore();

  useEffect(() => {
    loadSkills();
  }, [loadSkills]);

  if (skills.length === 0) {
    return (
      <EmptyState
        Icon={Target}
        title="暂无技能"
        description="在 .claude/skills/ 目录下创建技能文件"
      />
    );
  }

  return (
    <div className="page-scroll flex flex-col gap-2 h-full">
      {skills.map((skill) => (
        <div key={skill.name} className="card">
          <div className="flex items-start gap-3">
            <BookOpen size={20} className="text-[var(--text-secondary)] flex-shrink-0 mt-0.5" />
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
