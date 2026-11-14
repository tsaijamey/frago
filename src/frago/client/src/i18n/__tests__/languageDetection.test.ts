import { afterEach, describe, expect, it, vi } from 'vitest';
import { detectBrowserLanguage, getInitialLanguage } from '../index';

describe('i18n zero-prior default language detection', () => {
  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('returns zh when browser navigator.language is zh-CN or zh-TW', () => {
    vi.spyOn(window.navigator, 'languages', 'get').mockReturnValue(['zh-CN', 'en-US']);
    vi.spyOn(window.navigator, 'language', 'get').mockReturnValue('zh-CN');
    expect(detectBrowserLanguage()).toBe('zh');
    expect(getInitialLanguage()).toBe('zh');

    vi.spyOn(window.navigator, 'languages', 'get').mockReturnValue(['zh-TW']);
    expect(detectBrowserLanguage()).toBe('zh');
  });

  it('returns en when browser navigator.language is explicitly non-Chinese', () => {
    vi.spyOn(window.navigator, 'languages', 'get').mockReturnValue(['en-US']);
    vi.spyOn(window.navigator, 'language', 'get').mockReturnValue('en-US');
    expect(detectBrowserLanguage()).toBe('en');
    expect(getInitialLanguage()).toBe('en');
  });

  it('falls back to zh when navigator provides no language hints', () => {
    vi.spyOn(window.navigator, 'languages', 'get').mockReturnValue([]);
    vi.spyOn(window.navigator, 'language', 'get').mockReturnValue('');
    expect(detectBrowserLanguage()).toBe('zh');
    expect(getInitialLanguage()).toBe('zh');
  });

  it('respects explicit localStorage preference over browser locale', () => {
    vi.spyOn(window.navigator, 'languages', 'get').mockReturnValue(['zh-CN']);
    localStorage.setItem('language', 'en');
    expect(getInitialLanguage()).toBe('en');

    localStorage.setItem('language', 'zh');
    vi.spyOn(window.navigator, 'languages', 'get').mockReturnValue(['en-US']);
    expect(getInitialLanguage()).toBe('zh');
  });
});
