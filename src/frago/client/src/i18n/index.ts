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

// Infer language from browser locale when user has no stored preference yet.
// Chinese locales (zh / zh-CN / zh-Hans / zh-TW / zh-HK) land on 'zh'; explicit
// non-Chinese locales land on 'en'; environments with no locale info fall back to 'zh'.
export function detectBrowserLanguage(): 'zh' | 'en' {
  try {
    const candidates: string[] = [];
    if (typeof navigator !== 'undefined') {
      if (Array.isArray(navigator.languages)) {
        candidates.push(...navigator.languages);
      }
      if (navigator.language) {
        candidates.push(navigator.language);
      }
    }
    for (const raw of candidates) {
      const normalized = raw?.trim().toLowerCase();
      if (!normalized) continue;
      if (normalized.startsWith('zh')) {
        return 'zh';
      }
      return 'en';
    }
  } catch {
    // navigator not available
  }
  return 'zh';
}

// Get initial language from localStorage (or browser locale on fresh install)
export function getInitialLanguage(): 'zh' | 'en' {
  try {
    const stored = localStorage.getItem('language');
    if (stored === 'en' || stored === 'zh') {
      return stored;
    }
  } catch {
    // localStorage not available
  }
  return detectBrowserLanguage();
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
