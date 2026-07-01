/**
 * ProfileManager - Modal for managing API endpoint profiles
 *
 * Provides CRUD operations and quick-switch for saved API configurations.
 * State and behavior live in useProfiles; this file is the modal shell that
 * composes the list and form views.
 */

import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { useProfiles } from './useProfiles';
import ProfileList from './ProfileList';
import ProfileForm from './ProfileForm';

interface ProfileManagerProps {
  isOpen: boolean;
  onClose: () => void;
  onProfileActivated?: () => void;
  hasCustomConfig?: boolean; // Whether a custom API config is currently active
}

export default function ProfileManager({
  isOpen,
  onClose,
  onProfileActivated,
  hasCustomConfig,
}: ProfileManagerProps) {
  const pm = useProfiles({ isOpen, onClose, onProfileActivated });
  const { t, loading, viewMode } = pm;

  if (!isOpen) return null;

  return createPortal(
    <div
      className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-[1100]"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="bg-[var(--bg-base)] rounded-lg shadow-xl max-w-lg w-full mx-4 border border-[var(--border-color)] max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-[var(--border-color)] shrink-0">
          <h3 className="text-lg font-semibold text-[var(--text-primary)]">
            {viewMode === 'add'
              ? t('settings.profiles.addProfile')
              : viewMode === 'edit'
                ? t('settings.profiles.edit')
                : t('settings.profiles.title')}
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
            aria-label="Close modal"
          >
            <X size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="p-4 overflow-y-auto">
          {loading ? (
            <div className="text-[var(--text-muted)] text-center py-8 text-sm">
              Loading...
            </div>
          ) : viewMode === 'list' ? (
            <ProfileList pm={pm} hasCustomConfig={hasCustomConfig} />
          ) : (
            <ProfileForm pm={pm} />
          )}
        </div>

        {/* Footer */}
        {viewMode === 'list' && (
          <div className="flex justify-end p-4 border-t border-[var(--border-color)] shrink-0">
            <button
              type="button"
              onClick={onClose}
              className="btn btn-ghost btn-sm"
            >
              {t('settings.profiles.close')}
            </button>
          </div>
        )}
      </div>
    </div>,
    document.body
  );
}
