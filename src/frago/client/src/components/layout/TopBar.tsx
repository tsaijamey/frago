/**
 * TopBar Component
 *
 * Minimal top status bar with logo and system status.
 * Replaces the sidebar header in the new layout.
 */

import { useAppStore } from '@/stores/appStore';

export default function TopBar() {
  const { systemStatus } = useAppStore();

  const isRunning = systemStatus?.cpu_percent !== undefined;
  const now = new Date();
  const timeStr = `${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}  ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;

  return (
    <div className="topbar">
      <div className="topbar-logo">{'> frago'}</div>
      <div className="topbar-right">
        <span className={`topbar-status ${isRunning ? 'topbar-status--active' : ''}`}>
          {isRunning ? '● 运行中' : '○ 空闲'}
        </span>
        <span className="topbar-time">{timeStr}</span>
      </div>
    </div>
  );
}
