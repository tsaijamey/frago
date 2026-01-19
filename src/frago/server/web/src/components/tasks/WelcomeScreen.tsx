import { useTranslation } from 'react-i18next';
import {
  Sparkles,
  Globe,
  Code,
  FolderOpen,
  TableProperties,
  Workflow,
  FileText,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import ExampleCard from './ExampleCard';

interface ExampleItem {
  key: string;
  icon: LucideIcon;
}

const EXAMPLES: ExampleItem[] = [
  { key: 'webResearch', icon: Globe },
  { key: 'codeReview', icon: Code },
  { key: 'fileOrganize', icon: FolderOpen },
  { key: 'dataExtract', icon: TableProperties },
  { key: 'workflow', icon: Workflow },
  { key: 'docGenerate', icon: FileText },
];

interface WelcomeScreenProps {
  onExampleClick: (prompt: string) => void;
  children: React.ReactNode;
}

export default function WelcomeScreen({
  onExampleClick,
  children,
}: WelcomeScreenProps) {
  const { t } = useTranslation();

  return (
    <div className="welcome-screen">
      <div className="welcome-header">
        <div className="welcome-icon">
          <Sparkles size={32} />
        </div>
        <h1 className="welcome-headline">{t('tasks.welcomeHeadline')}</h1>
        <p className="welcome-subheadline">{t('tasks.welcomeSubheadline')}</p>
      </div>

      <div className="welcome-input-container">{children}</div>

      <div className="welcome-examples-section">
        <div className="welcome-examples-label">{t('tasks.tryExamples')}</div>
        <div className="welcome-examples-grid">
          {EXAMPLES.map(({ key, icon }) => (
            <ExampleCard
              key={key}
              icon={icon}
              title={t(`tasks.examples.${key}.title`)}
              description={t(`tasks.examples.${key}.description`)}
              onClick={() => onExampleClick(t(`tasks.examples.${key}.prompt`))}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
