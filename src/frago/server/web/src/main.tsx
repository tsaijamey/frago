import { StrictMode, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import './i18n'; // Initialize i18n before App
import App from './App';
import './styles/globals.css';

// Theme initialization is handled by inline script in index.html
// which reads from localStorage before any CSS/JS loads.
// This prevents FOUC (Flash of Unstyled Content).

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
