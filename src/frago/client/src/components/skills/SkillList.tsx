import { useTranslation } from 'react-i18next';
import { useAppStore } from '@/stores/appStore';
import { useAutoRefresh } from '@/hooks/useAutoRefresh';
import EmptyState from '@/components/ui/EmptyState';
import { Target, BookOpen } from 'lucide-react';

export default function SkillList() {
  const { t } = useTranslation();
  const { skills, loadSkills } = useAppStore();

  // 技能目录在本机随时会被加减。挂载时取一次就不动的话，人装完一个技能回到这页
  // 会以为没装上。
  useAutoRefresh(loadSkills, { intervalMs: 30_000 });

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
    <div className="page-scroll grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 content-start">
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
              <div className="text-xs text-[var(--text-muted)] mt-2 font-mono truncate">
                {skill.file_path}
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
