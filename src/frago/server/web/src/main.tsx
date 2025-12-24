import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles/globals.css';

// Theme initialization is handled by inline script in index.html
// which reads from localStorage before any CSS/JS loads.
// This prevents FOUC (Flash of Unstyled Content).

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
