import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles/globals.css';

// 初始化主题（防止 FOUC）
// 注意：pywebview 环境下 localStorage 可能不持久化
// 真正的主题恢复由 App.tsx 中 loadConfig() 完成
function initTheme() {
  // 默认使用系统偏好作为初始主题
  const system = window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light';
  document.documentElement.setAttribute('data-theme', system);
  document.documentElement.style.colorScheme = system;
}

initTheme();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
