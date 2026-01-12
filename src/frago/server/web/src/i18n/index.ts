/**
 * i18n Initialization
 *
 * Configures i18next for multi-language support.
 * Supports English (en) and Chinese (zh).
 */

import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import en from './locales/en.json';
import zh from './locales/zh.json';

const resources = {
  en: { translation: en },
  zh: { translation: zh },
};

// Get initial language from localStorage to prevent FOUC (Flash of Unstyled Content)
function getInitialLanguage(): string {
  try {
    const stored = localStorage.getItem('language');
    if (stored === 'en' || stored === 'zh') {
      return stored;
    }
  } catch {
    // localStorage not available
  }
  return 'en';
}

i18n.use(initReactI18next).init({
  resources,
  lng: getInitialLanguage(),
  fallbackLng: 'en',
  interpolation: {
    escapeValue: false, // React already escapes values
  },
});

export default i18n;
