import { useEffect } from 'react';
import { useAppStore } from '@/stores/appStore';

export default function StatusBar() {
  const { systemStatus, loadSystemStatus, config } = useAppStore();

  useEffect(() => {
    // 初始加载
    loadSystemStatus();

    // 定期更新
    const interval = setInterval(() => {
      loadSystemStatus();
    }, 5000);

    return () => clearInterval(interval);
  }, [loadSystemStatus]);

  return (
    <div className="status-bar">
      <div className="flex items-center gap-4">
        {config?.show_system_status && systemStatus && (
          <>
            <span>CPU: {systemStatus.cpu_percent.toFixed(1)}%</span>
            <span>内存: {systemStatus.memory_percent.toFixed(1)}%</span>
          </>
        )}
        <span
          className={
            systemStatus?.chrome_connected
              ? 'text-[var(--accent-success)]'
              : 'text-[var(--text-muted)]'
          }
        >
          Chrome: {systemStatus?.chrome_connected ? '已连接' : '未连接'}
        </span>
      </div>
    </div>
  );
}
