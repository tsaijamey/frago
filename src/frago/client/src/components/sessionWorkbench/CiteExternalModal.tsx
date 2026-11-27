import { useTranslation } from 'react-i18next';
import { ExternalLink, Globe, X } from 'lucide-react';
import type { CiteDefinition } from '@/components/ui/citations';

export interface CiteExternalModalProps {
  def: CiteDefinition;
  onClose: () => void;
}

export default function CiteExternalModal({ def, onClose }: CiteExternalModalProps) {
  const { t } = useTranslation();

  const handleOpenExternal = () => {
    if (def.uri) {
      window.open(def.uri, '_blank', 'noopener,noreferrer');
    }
    onClose();
  };

  return (
    <div
      className="cite-ext-modal-bd open"
      data-testid="cite-ext-modal"
      role="dialog"
      aria-modal="true"
      aria-label={t('workbench.citations.extModalTitle')}
      onClick={onClose}
    >
      <div
        className="cite-ext-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="cite-ext-head">
          <Globe size={15} className="shrink-0 text-accent-secondary" />
          <span className="cite-pop-num">[{def.label}]</span>
          <span className="min-w-0 flex-1 truncate font-semibold text-text-primary">
            {def.title}
          </span>
          <span className="cite-pop-kind web">{t('workbench.citations.webBadge')}</span>
          <button
            type="button"
            className="cite-drawer-btn"
            data-testid="cite-ext-close"
            onClick={onClose}
            aria-label={t('workbench.citations.extClose')}
          >
            <X size={13} />
          </button>
        </div>

        <div className="cite-ext-body">
          <div className="cite-ext-url" data-testid="cite-ext-url">
            {def.uri}
          </div>
          {def.excerpt ? (
            <div className="cite-pop-excerpt">
              <span className="font-semibold text-text-secondary">
                {t('workbench.citations.extExcerptLabel')}
              </span>
              {def.excerpt}
            </div>
          ) : null}
          <p className="m-0 text-[12px] leading-[1.55] text-text-muted">
            {t('workbench.citations.extModalNote')}
          </p>
        </div>

        <div className="cite-ext-foot">
          <button
            type="button"
            className="cite-drawer-btn"
            data-testid="cite-ext-cancel"
            onClick={onClose}
          >
            {t('workbench.citations.extBack')}
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-[7px] bg-accent-primary px-3 py-1.5 text-[12px] font-medium text-white hover:opacity-90"
            data-testid="cite-ext-confirm"
            onClick={handleOpenExternal}
          >
            <ExternalLink size={13} />
            <span>{t('workbench.citations.extOpenNewTab')}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
