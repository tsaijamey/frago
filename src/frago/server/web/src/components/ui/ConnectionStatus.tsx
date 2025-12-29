/**
 * Connection Status Indicator
 *
 * Shows WebSocket connection status in the UI.
 */

import { useWebSocket } from '@/hooks/useWebSocket';
import { getApiMode } from '@/api';
import { Wifi, WifiOff } from 'lucide-react';

interface ConnectionStatusProps {
  /** Show label text (default: false) */
  showLabel?: boolean;
  /** Custom class name */
  className?: string;
}

export default function ConnectionStatus({
  showLabel = false,
  className = '',
}: ConnectionStatusProps) {
  const { isConnected } = useWebSocket({ autoConnect: true });
  const apiMode = getApiMode();

  // Don't show in pywebview mode
  if (apiMode === 'pywebview') {
    return null;
  }

  return (
    <div
      className={`flex items-center gap-1.5 ${className}`}
      title={isConnected ? 'Connected to server' : 'Disconnected from server'}
    >
      {isConnected ? (
        <>
          <Wifi size={14} className="text-green-500" />
          {showLabel && (
            <span className="text-xs text-green-500">Server</span>
          )}
        </>
      ) : (
        <>
          <WifiOff size={14} className="text-red-500" />
          {showLabel && (
            <span className="text-xs text-red-500">Offline</span>
          )}
        </>
      )}
    </div>
  );
}
