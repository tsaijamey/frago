import { RefObject } from 'react';
import { useTranslation } from 'react-i18next';
import { Sparkles } from 'lucide-react';
import MessageItem from './MessageItem';
import type { ConsoleMessage } from '@/types/console';

interface MessageListProps {
  messages: ConsoleMessage[];
  messagesEndRef: RefObject<HTMLDivElement>;
}

export default function MessageList({ messages, messagesEndRef }: MessageListProps) {
  const { t } = useTranslation();

  if (messages.length === 0) {
    return (
      <div className="welcome-screen">
        <div className="welcome-header">
          <div className="welcome-icon">
            <Sparkles size={32} />
          </div>
          <h1 className="welcome-headline">{t('console.welcomeHeadline')}</h1>
          <p className="welcome-subheadline">{t('console.welcomeSubheadline')}</p>
        </div>

        {/* Capsule toggle button */}
        <div className="approval-toggle mt-scaled-6">
          <button type="button" className="approval-toggle-option active">
            {t('console.autoApprove')}
          </button>
          <button
            type="button"
            className="approval-toggle-option disabled"
            title={t('console.manualApproveDisabledHint')}
            disabled
          >
            {t('console.manualApprove')}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-scaled-4 space-y-4">
      {messages.map((msg, index) => (
        <MessageItem key={index} message={msg} />
      ))}
      <div ref={messagesEndRef} />
    </div>
  );
}
