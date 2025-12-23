import { useEffect } from 'react';
import { useAppStore } from '@/stores/appStore';
import ConnectionStatus from '@/components/ui/ConnectionStatus';

export default function StatusBar() {
  const { systemStatus, loadSystemStatus, config } = useAppStore();

  useEffect(() => {
    // Initial load
    loadSystemStatus();

    // Periodic update
    const interval = setInterval(() => {
      loadSystemStatus();
    }, 5000);

    return () => clearInterval(interval);
  }, [loadSystemStatus]);

  return (
    <div className="status-bar">
      <div className="flex items-center gap-4">
        {/* WebSocket connection status (only shown in HTTP mode) */}
        <ConnectionStatus showLabel />

        {config?.show_system_status && systemStatus && (
          <>
            <span>CPU: {systemStatus.cpu_percent.toFixed(1)}%</span>
            <span>Memory: {systemStatus.memory_percent.toFixed(1)}%</span>
          </>
        )}
        <span
          className={
            systemStatus?.chrome_connected
              ? 'text-[var(--accent-success)]'
              : 'text-[var(--text-muted)]'
          }
        >
          Chrome: {systemStatus?.chrome_connected ? 'Connected' : 'Disconnected'}
        </span>
      </div>
    </div>
  );
}
