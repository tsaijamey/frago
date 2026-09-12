import { StrictMode, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import './i18n'; // Initialize i18n before App
import App from './App';
import './styles/globals.css';
import './styles/timeline.css';
import { installConnectionMonitor } from './api/connection';
import { registerShellWorker } from './utils/shellWorker';

// Theme initialization is handled by inline script in index.html
// which reads from localStorage before any CSS/JS loads.
// This prevents FOUC (Flash of Unstyled Content).

// 抢在第一个请求之前装上：本机服务不在时，页面上任何请求失败都要落到那张重连遮罩上，
// 而不是各处各报各的错（判定与遮罩见 api/connection.ts 与 ui/ReconnectOverlay.tsx）。
installConnectionMonitor();

// 再留一层外壳：服务停了的时候按 F5，浏览器连端口就被拒，页面上那些判定与遮罩全都轮不到
// 执行。worker 把首屏几份文件留在本地，页面进得来，剩下的归上面那套管（utils/shellWorker.ts）。
registerShellWorker();

// Wrapper component to hide loading screen after mount
function AppWithLoading() {
  useEffect(() => {
    // Hide loading screen when React app is mounted
    if (typeof (window as any).fragoHideLoading === 'function') {
      (window as any).fragoHideLoading();
    }
  }, []);

  return <App />;
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppWithLoading />
  </StrictMode>
);
