# Selector Priority Rules

Applies to: `/frago.recipe`

## Priority Ranking

When generating JavaScript, rank selectors by this priority (5 is highest, 1 is lowest):

| Priority | Type | Example | Stability | Notes |
|--------|------|------|--------|------|
| **5** | ARIA labels | `[aria-label="Button"]` | ✅ Very stable | Accessibility attributes, rarely change |
| **5** | data attributes | `[data-testid="submit"]` | ✅ Very stable | Specifically for testing |
| **4** | Stable ID | `#main-button` | ✅ Stable | Semantic ID names |
| **3** | Semantic class names | `.btn-primary` | ⚠️ Medium | BEM convention class names |
| **3** | HTML5 semantic tags | `button`, `nav` | ⚠️ Medium | Standard semantic tags |
| **2** | Structural selectors | `div > button` | ⚠️ Fragile | Depends on DOM structure |
| **1** | Generated class names | `.css-abc123` | ❌ Very fragile | CSS-in-JS, changes anytime |

## Identifying Fragile Selectors

The following selectors should be **avoided** or used as **last fallback option**:

- `.css-*` or `._*` prefixed class names (CSS-in-JS generated)
- Pure numeric IDs: `#12345`
- Overly long ID/class names (>20 characters)
- Deeply nested structural selectors: `div > div > div > span`

## Using Fallback Selectors in Recipes

```javascript
// Helper function: Try multiple selectors by priority
function findElement(selectors, description) {
  for (const sel of selectors) {
    const elem = document.querySelector(sel.selector);
    if (elem) return elem;
  }
  throw new Error(`Unable to find ${description}`);
}

// Usage example: Provide 2-3 fallback selectors
const elem = findElement([
  { selector: '[aria-label="Submit"]', priority: 5 },      // Most stable
  { selector: '[data-testid="submit-btn"]', priority: 5 },
  { selector: '#submit-button', priority: 4 },             // Fallback
  { selector: '.btn-submit', priority: 3 }                 // Further fallback
], 'submit button');
```

## Validating Selectors During Exploration

Before creating a recipe, validate selector validity using frago commands:

```bash
# Verify if selector exists
frago chrome exec-js "document.querySelector('[aria-label=\"Submit\"]') !== null" --return-value

# Highlight element to confirm position
frago chrome highlight '[aria-label="Submit"]'

# Get element text to confirm content
frago chrome exec-js "document.querySelector('[aria-label=\"Submit\"]')?.textContent" --return-value
```

## Validation Waits in Recipes

After each operation step, use `waitForElement` to validate results:

```javascript
// Helper function: Wait for and validate element appearance
async function waitForElement(selector, description, timeout = 5000) {
  const startTime = Date.now();
  while (Date.now() - startTime < timeout) {
    const elem = document.querySelector(selector);
    if (elem) return elem;
    await new Promise(r => setTimeout(r, 100));
  }
  throw new Error(`Wait timeout: ${description} (${selector})`);
}

// Usage example
elem.click();
await waitForElement('.result-panel', 'result panel appears');
```

## Selector Characteristics for Common Sites

| Site | Recommended Selector Types | Notes |
|------|---------------|---------|
| YouTube | `aria-label`, `data-*` | Most class names are generated |
| Twitter/X | `data-testid`, `aria-label` | Class names extremely unstable |
| GitHub | ID, semantic class names | Relatively stable |
| Upwork | `data-*`, semantic class names | Some generated class names |
