# Prohibition of Hallucinated Navigation

Applies to: `/frago.run`, `/frago.do`

## Core Rule

**Strictly prohibit guessing URLs and navigating directly.**

Claude easily constructs seemingly reasonable but non-existent links out of thin air.

## Wrong Examples

```bash
# ❌ Prohibited: How do you know there's a v2?
frago chrome navigate "https://example.com/api/v2/docs"

# ❌ Prohibited: Have you verified the parameters?
frago chrome navigate "https://upwork.com/search?q=python&sort=relevance"

# ❌ Prohibited: Fabricated user page
frago chrome navigate "https://twitter.com/elonmusk/status/123456789"
```

## Correct Approach: Onion-Peeling Layer by Layer

```bash
# ✅ Step 1: Navigate to known homepage
frago chrome navigate "https://example.com"

# ✅ Step 2: Extract real links from the page
frago chrome exec-js "Array.from(document.querySelectorAll('a')).map(a => ({text: a.textContent.trim(), href: a.href})).filter(a => a.text)" --return-value

# ✅ Step 3: Use the real URL obtained from the previous step
frago chrome navigate "<real URL from previous step>"
```

## Allowed URL Sources for Direct Navigation

| Source | Example |
|------|------|
| User explicitly provided | "Please open https://example.com/specific-page" |
| Link in context | URL pasted by user in previous conversation |
| Obtained from page | `href` extracted via `exec-js` |
| Search results | Links from Google search results |
| Recipe output | URL field returned by Recipe |

## Correct Way to Search

```bash
# ✅ Use Google search
frago chrome navigate "https://google.com/search?q=site:example.com+api+documentation"

# Then extract links from search results
frago chrome exec-js "Array.from(document.querySelectorAll('a[href]')).filter(a => a.href.includes('example.com')).map(a => a.href)" --return-value
```
