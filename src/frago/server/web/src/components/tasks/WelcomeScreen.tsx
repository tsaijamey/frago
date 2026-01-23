import { useTranslation } from 'react-i18next';
import { Sparkles } from 'lucide-react';

export default function WelcomeScreen() {
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
    </div>
  );
}
