/**
 * UpdateModal Component
 *
 * Modal dialog showing update progress during self-update.
 * Displays progress bar, status messages, and handles reconnection.
 */

import { useEffect, useState, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useAppStore } from '@/stores/appStore';
import { useWebSocket } from '@/hooks/useWebSocket';

interface UpdateModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function UpdateModal({ isOpen, onClose }: UpdateModalProps) {
  const { t } = useTranslation();
  const updateStatus = useAppStore((state) => state.updateStatus);
  const versionInfo = useAppStore((state) => state.versionInfo);
  const showToast = useAppStore((state) => state.showToast);
  const setUpdateStatus = useAppStore((state) => state.setUpdateStatus);
  const [reconnecting, setReconnecting] = useState(false);
  const wasDisconnectedRef = useRef(false);

  // Use WebSocket hook to monitor connection
  const { isConnected } = useWebSocket();

  // Handle WebSocket reconnection after server restart
  useEffect(() => {
    if (reconnecting) {
      if (!isConnected) {
        // Track that we were disconnected during update
        wasDisconnectedRef.current = true;
      } else if (wasDisconnectedRef.current && isConnected) {
        // Reconnected after being disconnected - update complete
        console.log('[UpdateModal] Reconnected after update, reloading page...');
        showToast(t('update.updatedTo', { version: versionInfo?.latest_version || 'latest' }), 'success');
        setReconnecting(false);
        setUpdateStatus(null);
        wasDisconnectedRef.current = false;
        // Reload page to ensure fresh state
        setTimeout(() => {
          window.location.reload();
        }, 500);
      }
    }
  }, [reconnecting, isConnected, versionInfo, showToast, setUpdateStatus, t]);

  // Handle restarting state - server will disconnect
  useEffect(() => {
    if (updateStatus?.status === 'restarting') {
      setReconnecting(true);
    }
  }, [updateStatus?.status]);

  // Handle error state
  useEffect(() => {
    if (updateStatus?.status === 'error') {
      showToast(`${t('update.failed')}: ${updateStatus.error || t('update.error')}`, 'error');
    }
  }, [updateStatus?.status, updateStatus?.error, showToast, t]);

  if (!isOpen) {
    return null;
  }

  const status = updateStatus?.status || 'updating';
  const progress = updateStatus?.progress || 0;
  const message = updateStatus?.message || t('update.preparing');

  // Determine display text based on status
  let title = t('update.updating');
  let statusMessage = message;

  if (status === 'restarting' || reconnecting) {
    title = t('update.restarting');
    statusMessage = reconnecting
      ? t('update.reconnecting')
      : t('update.complete');
  } else if (status === 'error') {
    title = t('update.failed');
    statusMessage = updateStatus?.error || t('update.error');
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
              {reconnecting ? t('update.reconnectingProgress') : `${progress}%`}
            </span>
          </div>
        )}

        <p className="update-modal-message">{statusMessage}</p>

        {reconnecting && (
          <p className="update-modal-hint">
            {t('update.autoReload')}
          </p>
        )}

        {canClose && (
          <div className="update-modal-actions">
            <button
              type="button"
              className="update-modal-close-btn"
              onClick={onClose}
            >
              {t('update.close')}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
