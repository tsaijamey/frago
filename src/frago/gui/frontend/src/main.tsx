import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles/globals.css';

// 安全地获取 localStorage（兼容 pywebview 环境）
function safeLocalStorage() {
  try {
    if (typeof localStorage !== 'undefined' && localStorage !== null) {
      return localStorage;
    }
  } catch {
    // localStorage 不可用
  }
  return null;
}

// 初始化主题（防止 FOUC）
function initTheme() {
  const storage = safeLocalStorage();
  const saved = storage?.getItem('theme') ?? null;
  const system = window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light';
  const theme = saved || system;
  document.documentElement.setAttribute('data-theme', theme);
  document.documentElement.style.colorScheme = theme;
}

initTheme();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
