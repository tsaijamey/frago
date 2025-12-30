# frago i18n (Internationalization) Guide

## Overview

frago supports bilingual interface (English/Chinese) with:
- Web UI language switching via react-i18next
- Language preference stored in `~/.frago/gui_config.json`
- AI prompts output respecting user's language preference

## Translation Files Location

```
src/frago/server/web/src/i18n/
├── index.ts              # i18n initialization
└── locales/
    ├── en.json           # English translations
    └── zh.json           # Chinese translations
```

## Adding New Translations

### Step 1: Update Translation Files

Add the new key to **both** locale files:

**en.json:**
```json
{
  "myFeature": {
    "title": "My Feature",
    "description": "This is my new feature"
  }
}
```

**zh.json:**
```json
{
  "myFeature": {
    "title": "我的功能",
    "description": "这是我的新功能"
  }
}
```

### Step 2: Use in React Component

```tsx
import { useTranslation } from 'react-i18next';

function MyComponent() {
  const { t } = useTranslation();

  return (
    <div>
      <h1>{t('myFeature.title')}</h1>
      <p>{t('myFeature.description')}</p>
    </div>
  );
}
```

### Step 3: Build Frontend

```bash
cd src/frago/server/web && pnpm run build
```

## Translation Key Naming Convention

Use dot-notation keys organized by feature/component:

| Prefix | Usage |
|--------|-------|
| `sidebar.*` | Sidebar navigation items |
| `dashboard.*` | Dashboard page content |
| `tasks.*` | Tasks page content |
| `recipes.*` | Recipes page content |
| `skills.*` | Skills page content |
| `console.*` | Console page content |
| `sync.*` | Sync page content |
| `secrets.*` | Secrets page content |
| `settings.*` | Settings page content |
| `common.*` | Shared UI elements (buttons, labels, etc.) |
| `errors.*` | Error messages |

## When Code Changes Are Required

### Scenario 1: Adding text to existing translated component

**Code change: NO** - Only update JSON files

Just add new keys to `en.json` and `zh.json`, then use `t('newKey')` in the component.

### Scenario 2: Translating a new component

**Code change: YES** - Import `useTranslation` hook

```tsx
// Before (hardcoded)
function MyComponent() {
  return <h1>My Title</h1>;
}

// After (translated)
import { useTranslation } from 'react-i18next';

function MyComponent() {
  const { t } = useTranslation();
  return <h1>{t('myComponent.title')}</h1>;
}
```

### Scenario 3: Adding a new language

**Code change: YES** - Multiple files need updates

1. Create new locale file: `src/i18n/locales/ja.json`
2. Update `src/i18n/index.ts`:
   ```typescript
   import ja from './locales/ja.json';

   const resources = {
     en: { translation: en },
     zh: { translation: zh },
     ja: { translation: ja },  // Add new language
   };
   ```
3. Update `src/types/pywebview.d.ts`:
   ```typescript
   export type Language = 'en' | 'zh' | 'ja';
   ```
4. Update backend `src/frago/server/services/config_service.py`:
   ```python
   if self.language not in ("en", "zh", "ja"):
       errors.append(...)
   ```
5. Update `AppearanceSettings.tsx` to add new option in selector

### Scenario 4: Translating AI prompts

**Code change: YES** - Update Python files

AI prompts with language support are in:
- `src/frago/session/title_manager.py` - Title generation
- `src/frago/cli/agent_command.py` - Agent routing

Pattern for language-aware prompts:
```python
from frago.server.services.config_service import ConfigService

language = ConfigService.get_user_language()
lang_instruction = (
    "Generate in Chinese (中文)."
    if language == "zh"
    else "Generate in English."
)
```

## Checklist for Adding Translations

- [ ] Key added to `en.json`
- [ ] Key added to `zh.json`
- [ ] Component imports `useTranslation` (if new component)
- [ ] Component uses `t('key')` instead of hardcoded text
- [ ] Run `pnpm run build` to verify no TypeScript errors
- [ ] Test language switching in UI

## Important Notes

1. **Always update both files** - Missing keys will fallback to English
2. **Use nested keys** - Organize by feature for maintainability
3. **Avoid HTML in translations** - Use interpolation if needed
4. **Test both languages** - Switch language and verify all text renders correctly
5. **Build after changes** - Run `pnpm run build` to catch any issues

## Related Files

| File | Purpose |
|------|---------|
| `src/frago/server/services/config_service.py` | Language preference storage |
| `src/frago/server/web/src/stores/appStore.ts` | Frontend language state management |
| `src/frago/server/web/src/components/settings/AppearanceSettings.tsx` | Language selector UI |
