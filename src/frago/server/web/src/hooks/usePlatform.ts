// Platform detection (static, won't change after page load)
export const isMac = typeof navigator !== 'undefined' && /Mac/.test(navigator.platform);

// Modifier key display
export const modKey = isMac ? '⌘' : 'Ctrl';
