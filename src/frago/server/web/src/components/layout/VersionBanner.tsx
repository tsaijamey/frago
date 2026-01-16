/**
 * VersionBanner Component
 *
 * Displays a banner at the top of the page when a new version is available.
 * Shows the update command, an Update Now button, and allows dismissing the banner.
 */

import { useState } from 'react';
import { useAppStore } from '@/stores/appStore';
import * as api from '@/api';
import UpdateModal from '@/components/update/UpdateModal';

export default function VersionBanner() {
  const versionInfo = useAppStore((state) => state.versionInfo);
  const updateStatus = useAppStore((state) => state.updateStatus);
  const showToast = useAppStore((state) => state.showToast);
  const [dismissed, setDismissed] = useState(false);
  const [showModal, setShowModal] = useState(false);

  // Show modal when update is in progress
  const isUpdating = updateStatus?.status === 'updating' || updateStatus?.status === 'restarting';

  // Don't show banner if no version info, no update available, or dismissed
  // But always show if updating (even after dismiss)
  if ((!versionInfo?.update_available || dismissed) && !isUpdating) {
    return null;
  }

  const handleUpdateClick = async () => {
    try {
      setShowModal(true);
      await api.startSelfUpdate();
    } catch (error) {
      console.error('Failed to start update:', error);
      showToast('Failed to start update', 'error');
      setShowModal(false);
    }
  };

  const handleDismiss = () => {
    setDismissed(true);
  };

  // When updating, just show the modal
  if (isUpdating && !showModal) {
    setShowModal(true);
  }

  return (
    <>
      {!isUpdating && (
        <div className="version-banner">
          <div className="version-banner-content">
            <span className="version-banner-text">
              New version <strong>{versionInfo?.latest_version}</strong> available
            </span>
            <code className="version-banner-command">
              uv tool upgrade frago-cli
            </code>
          </div>
          <div className="version-banner-actions">
            <button
              type="button"
              className="version-banner-update-btn"
              onClick={handleUpdateClick}
            >
              Update Now
            </button>
            <button
              type="button"
              className="version-banner-dismiss"
              onClick={handleDismiss}
              aria-label="Dismiss update banner"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
        </div>
      )}
      <UpdateModal isOpen={showModal} onClose={() => setShowModal(false)} />
    </>
  );
}
