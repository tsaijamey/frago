/**
 * UpdateModal Component
 *
 * Modal dialog showing update progress during self-update.
 * Displays progress bar, status messages, and handles reconnection.
 */

import { useEffect, useState } from 'react';
import { useAppStore } from '@/stores/appStore';

interface UpdateModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function UpdateModal({ isOpen, onClose }: UpdateModalProps) {
  const updateStatus = useAppStore((state) => state.updateStatus);
  const versionInfo = useAppStore((state) => state.versionInfo);
  const showToast = useAppStore((state) => state.showToast);
  const setUpdateStatus = useAppStore((state) => state.setUpdateStatus);
  const [reconnecting, setReconnecting] = useState(false);

  // Handle successful update completion after reconnect
  useEffect(() => {
    if (reconnecting && updateStatus === null) {
      // WebSocket reconnected, update likely completed
      showToast(`Updated to version ${versionInfo?.latest_version || 'latest'}`, 'success');
      setReconnecting(false);
      setUpdateStatus(null);
      onClose();
    }
  }, [reconnecting, updateStatus, versionInfo, showToast, setUpdateStatus, onClose]);

  // Handle restarting state - server will disconnect
  useEffect(() => {
    if (updateStatus?.status === 'restarting') {
      setReconnecting(true);
    }
  }, [updateStatus?.status]);

  // Handle error state
  useEffect(() => {
    if (updateStatus?.status === 'error') {
      showToast(`Update failed: ${updateStatus.error || 'Unknown error'}`, 'error');
    }
  }, [updateStatus?.status, updateStatus?.error, showToast]);

  if (!isOpen) {
    return null;
  }

  const status = updateStatus?.status || 'updating';
  const progress = updateStatus?.progress || 0;
  const message = updateStatus?.message || 'Preparing update...';

  // Determine display text based on status
  let title = 'Updating frago...';
  let statusMessage = message;

  if (status === 'restarting' || reconnecting) {
    title = 'Restarting server...';
    statusMessage = reconnecting
      ? 'Reconnecting to server...'
      : 'Update complete, restarting server...';
  } else if (status === 'error') {
    title = 'Update failed';
    statusMessage = updateStatus?.error || 'An error occurred during update';
  }

  const canClose = status === 'error' || status === 'idle';

  return (
    <div className="update-modal-overlay">
      <div className="update-modal">
        <h2 className="update-modal-title">{title}</h2>

        {status !== 'error' && (
          <div className="update-modal-progress">
            <div className="update-modal-progress-bar">
              <div
                className="update-modal-progress-fill"
                style={{ width: `${reconnecting ? 100 : progress}%` }}
              />
            </div>
            <span className="update-modal-progress-text">
              {reconnecting ? 'Reconnecting...' : `${progress}%`}
            </span>
          </div>
        )}

        <p className="update-modal-message">{statusMessage}</p>

        {reconnecting && (
          <p className="update-modal-hint">
            The page will automatically reload when the server is ready.
          </p>
        )}

        {canClose && (
          <div className="update-modal-actions">
            <button
              type="button"
              className="update-modal-close-btn"
              onClick={onClose}
            >
              Close
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
