import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles/globals.css';

// Initialize theme (prevent FOUC)
// Note: localStorage may not persist in pywebview environment
// Actual theme restoration is done by loadConfig() in App.tsx
function initTheme() {
  // Use system preference as initial theme by default
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
