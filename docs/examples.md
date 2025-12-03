[简体中文](examples.zh-CN.md)

# Frago Example Reference

This document provides practical examples of using Frago's three core systems (Run + Recipe + CDP) for various automation tasks.

---

## Example 1: Interactive Exploration with Run System

**Goal**: Explore YouTube subtitle extraction step-by-step while maintaining full context.

### Step 1: Create Run Instance

```bash
uv run frago run init "Research YouTube subtitle extraction methods"
# Output: Created Run instance: youtube-subtitle-research-abc123
```

### Step 2: Navigate and Explore

```bash
# Navigate to YouTube video
frago chrome navigate https://www.youtube.com/watch?v=dQw4w9WgXcQ

# Take initial screenshot
frago chrome screenshot initial_page.png
# Saved to: projects/youtube-subtitle-research-abc123/screenshots/

# Inspect page structure
frago chrome exec-js 'document.querySelector("button[aria-label*=\"transcript\"]")' --return-value
```

### Step 3: Record Findings

```bash
# Log successful selector discovery
uv run frago run log \
  --step "Located transcript button selector" \
  --status "success" \
  --action-type "dom_inspection" \
  --data '{"selector": "button[aria-label*=\"transcript\"]", "reliable": true}'

# Click button and verify
frago chrome click 'button[aria-label*="transcript"]'
frago chrome screenshot transcript_opened.png
```

### Step 4: Save Validated Script

```bash
cat > projects/youtube-subtitle-research-abc123/scripts/extract_transcript.js <<'EOF'
(async () => {
  const button = document.querySelector('button[aria-label*="transcript"]');
  if (button) button.click();
  await new Promise(r => setTimeout(r, 1000));

  const segments = document.querySelectorAll('.ytd-transcript-segment-renderer');
  return Array.from(segments).map(s => s.textContent.trim()).join('\n');
})();
EOF
```

### Step 5: Review Complete History

```bash
uv run frago run info youtube-subtitle-research-abc123
```

**Output**:
```
Run Instance: youtube-subtitle-research-abc123
Topic: Research YouTube subtitle extraction methods
Created: 2025-01-24 14:30:22
Status: Active

Files:
  - logs/execution.jsonl (15 operations)
  - screenshots/initial_page.png
  - screenshots/transcript_opened.png
  - scripts/extract_transcript.js

Recent Operations:
  [14:30:22] navigate → https://youtube.com/... (success)
  [14:30:25] screenshot → initial_page.png (success)
  [14:30:28] exec-js → Found button element (success)
  [14:30:30] log → Located transcript button selector (success)
  [14:30:33] click → button[aria-label*="transcript"] (success)
```

---

## Example 2: Creating Recipe from Exploration

**Goal**: Transform exploration results into reusable Recipe.

### Using CLI

```bash
# After completing exploration in Run instance
# Extract validated logic and create Recipe files

# 1. Create Recipe script
cat > ~/.frago/recipes/atomic/chrome/youtube_extract_video_transcript.js <<'EOF'
(async () => {
  const button = document.querySelector('button[aria-label*="transcript"]');
  if (button) {
    button.click();
    await new Promise(r => setTimeout(r, 1000));
  }

  const segments = document.querySelectorAll('.ytd-transcript-segment-renderer');
  const transcript = Array.from(segments).map(s => s.textContent.trim()).join('\n');

  return { transcript, segmentCount: segments.length };
})();
EOF

# 2. Create Recipe metadata
cat > ~/.frago/recipes/atomic/chrome/youtube_extract_video_transcript.md <<'EOF'
---
name: youtube_extract_video_transcript
type: atomic
runtime: chrome-js
version: "1.0.0"
description: "Extract complete subtitle content from YouTube video page"
use_cases:
  - "Get subtitles for translation"
  - "Create subtitle files"
  - "Analyze video content"
tags: ["youtube", "transcript", "web-scraping"]
output_targets: [stdout, file]
inputs:
  url:
    type: string
    description: "YouTube video URL"
    required: true
outputs:
  transcript:
    type: string
    description: "Complete subtitle text"
  segmentCount:
    type: integer
    description: "Number of subtitle segments"
---

# Function Description
Extract complete subtitle text from YouTube video page.

## Usage
\`\`\`bash
uv run frago recipe run youtube_extract_video_transcript \\
  --params '{"url": "https://youtube.com/watch?v=..."}' \\
  --output-file transcript.txt
\`\`\`

## Prerequisites
- Chrome launched via CDP (port 9222)
- Navigated to YouTube video page
- Video must have subtitles available
EOF
```

### Using Claude Code

```
/frago.recipe create "Extract YouTube video subtitles" from run youtube-subtitle-research-abc123
```

AI will:
1. Review Run instance logs and scripts
2. Extract validated selectors
3. Generate Recipe files (.js + .md)
4. Test Recipe execution

---

## Example 3: Executing Recipe

**Goal**: Use existing Recipe to extract subtitles quickly.

### CLI Method

```bash
# Discover available Recipes
uv run frago recipe list

# View Recipe details
uv run frago recipe info youtube_extract_video_transcript

# Execute Recipe
uv run frago recipe run youtube_extract_video_transcript \
  --params '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}' \
  --output-file transcript.txt

# Output to clipboard
uv run frago recipe run youtube_extract_video_transcript \
  --params '{"url": "..."}' \
  --output-clipboard
```

### Claude Code Method

```
/frago.run Extract subtitles from https://www.youtube.com/watch?v=dQw4w9WgXcQ
```

AI automatically:
1. Discovers `youtube_extract_video_transcript` Recipe
2. Executes Recipe with URL parameter
3. Saves output to file

---

## Example 4: Batch Processing with Workflow Recipe

**Goal**: Extract job details from multiple Upwork listings.

### Create Workflow Recipe

```python
# ~/.frago/recipes/workflows/upwork_batch_extract.py
import sys, json
from frago.recipes import RecipeRunner

def main():
    params = json.loads(sys.argv[1] if len(sys.argv) > 1 else '{}')
    job_urls = params.get('urls', [])

    runner = RecipeRunner()
    results = []

    for i, url in enumerate(job_urls, 1):
        print(f"Processing {i}/{len(job_urls)}...", file=sys.stderr)
        try:
            result = runner.run('upwork_extract_job_details_as_markdown', {'url': url})
            results.append({
                'url': url,
                'data': result['data'],
                'status': 'success'
            })
        except Exception as e:
            results.append({
                'url': url,
                'error': str(e),
                'status': 'failed'
            })

    output = {
        'total': len(job_urls),
        'success': sum(1 for r in results if r['status'] == 'success'),
        'failed': sum(1 for r in results if r['status'] == 'failed'),
        'results': results
    }
    print(json.dumps(output))

if __name__ == '__main__':
    main()
```

### Create Workflow Metadata

```yaml
---
# ~/.frago/recipes/workflows/upwork_batch_extract.md
name: upwork_batch_extract
type: workflow
runtime: python
version: "1.0.0"
description: "Batch extract job details from multiple Upwork listings"
use_cases:
  - "Analyze job market trends"
  - "Build job database"
tags: ["upwork", "batch", "workflow"]
output_targets: [stdout, file]
inputs:
  urls:
    type: array
    description: "List of Upwork job URLs"
    required: true
outputs:
  results:
    type: array
    description: "Array of job details"
dependencies:
  - upwork_extract_job_details_as_markdown
---
```

### Execute Workflow

```bash
# Create URL list
cat > job_urls.json <<'EOF'
{
  "urls": [
    "https://www.upwork.com/freelance-jobs/apply/...",
    "https://www.upwork.com/freelance-jobs/apply/...",
    "https://www.upwork.com/freelance-jobs/apply/..."
  ]
}
EOF

# Execute workflow within Run context
uv run frago run init "Batch extract Python jobs from Upwork"
uv run frago recipe run upwork_batch_extract \
  --params-file job_urls.json \
  --output-file jobs.json
```

**Output** (`jobs.json`):
```json
{
  "total": 3,
  "success": 3,
  "failed": 0,
  "results": [
    {
      "url": "https://www.upwork.com/...",
      "data": {
        "title": "Python Developer Needed",
        "budget": "$1000-$2000",
        "description": "..."
      },
      "status": "success"
    }
  ]
}
```

---

## Example 5: Complex Multi-Platform Task

**Goal**: Monitor iPhone 15 prices on Amazon and eBay, generate comparison report.

### Using Claude Code

```
/frago.run Monitor iPhone 15 prices on Amazon and eBay, generate comparison report and save as Markdown
```

AI will:
1. Create Run instance: `iphone-15-price-monitoring-abc123`
2. Discover or create Recipes:
   - `amazon_search_product`
   - `ebay_search_product`
3. Execute Workflow:
   ```
   ├─ Navigate to Amazon → Search "iPhone 15"
   ├─ Extract price data → $799
   ├─ Navigate to eBay → Search "iPhone 15"
   ├─ Extract price data → $749
   └─ Generate comparison report
   ```
4. Log all operations to JSONL
5. Generate Markdown report

**Generated Report** (`outputs/price_comparison.md`):
```markdown
# iPhone 15 Price Comparison

**Date**: 2025-01-24

## Amazon
- **Price**: $799
- **Availability**: In Stock
- **Shipping**: Free Prime Shipping

## eBay
- **Price**: $749
- **Availability**: Used - Like New
- **Shipping**: $15

## Recommendation
eBay offers $50 savings, but consider condition and shipping costs.
Total eBay cost: $764 (still $35 cheaper)

---
Generated with Frago | Run ID: iphone-15-price-monitoring-abc123
```

---

## Example 6: CDP Command Usage Patterns

### Basic Navigation and Interaction

```bash
# Launch Chrome with CDP
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=./chrome_profile

# Navigate to page
frago chrome navigate https://news.ycombinator.com/

# Wait for page load
frago chrome wait 2

# Click element
frago chrome click 'a.titlelink:first-child'

# Get page title
frago chrome exec-js 'document.title' --return-value
```

### Screenshots and Visual Effects

```bash
# Take full page screenshot
frago chrome screenshot hackernews_page.png

# Highlight specific element
frago chrome highlight '.storylink' --color "#FF6B6B" --duration 3

# Spotlight effect (dim surroundings)
frago chrome spotlight '.athing:first-child' --duration 5

# Add annotation
frago chrome annotate '.score' "Top story" --position top
```

### JavaScript Execution

```bash
# Extract all links
frago chrome exec-js 'Array.from(document.querySelectorAll("a")).map(a => a.href)' \
  --return-value

# Scroll to bottom
frago chrome exec-js 'window.scrollTo(0, document.body.scrollHeight)'

# Check element existence
frago chrome exec-js 'document.querySelector(".pagetop") !== null' \
  --return-value
```

---

## Example 7: Run System Advanced Usage

### Resume Previous Exploration

```bash
# List all Run instances
uv run frago run list

# AI auto-discovery (fuzzy matching)
# User says: "Continue YouTube subtitle research"
# AI executes:
uv run frago run list --format json
# AI finds: youtube-subtitle-research-abc123 (95% match)
# AI resumes:
uv run frago run set-context youtube-subtitle-research-abc123
```

### Export Run Logs

```bash
# View execution log
cat projects/youtube-subtitle-research-abc123/logs/execution.jsonl

# Parse log programmatically
uv run python <<'EOF'
import json

with open('projects/youtube-subtitle-research-abc123/logs/execution.jsonl') as f:
    for line in f:
        log = json.loads(line)
        if log['status'] == 'failure':
            print(f"Error at {log['timestamp']}: {log.get('error', {}).get('message')}")
EOF
```

### Archive Completed Runs

```bash
# Archive Run instance
uv run frago run archive youtube-subtitle-research-abc123

# Archived Runs move to projects/.archive/
```

---

## Common Patterns and Best Practices

### Pattern 1: Exploration → Recipe → Automation

```
1. Create Run instance
2. Explore page interactively (CDP commands)
3. Log successful approaches
4. Create Recipe from validated scripts
5. Reuse Recipe for similar tasks
```

### Pattern 2: Workflow Recipe Composition

```python
# Workflow Recipe structure
def main():
    runner = RecipeRunner()

    # Step 1: Atomic Recipe
    data1 = runner.run('atomic_recipe_1', params1)

    # Step 2: Process results
    processed = process_data(data1)

    # Step 3: Another Atomic Recipe
    data2 = runner.run('atomic_recipe_2', processed)

    # Step 4: Combine results
    final = combine(data1, data2)
    print(json.dumps(final))
```

### Pattern 3: Error Handling in Workflows

```python
def main():
    runner = RecipeRunner()
    results = []

    for item in items:
        try:
            result = runner.run('recipe_name', {'item': item})
            results.append({'item': item, 'status': 'success', 'data': result})
        except Exception as e:
            results.append({'item': item, 'status': 'failed', 'error': str(e)})
            # Log error but continue processing
            print(f"Warning: Failed to process {item}: {e}", file=sys.stderr)

    return {'total': len(items), 'results': results}
```

---

## Troubleshooting Examples

### Example: CDP Connection Issues

```bash
# Check if Chrome CDP is running
lsof -i :9222

# Launch Chrome if not running
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=./chrome_profile &

# Test connection
frago chrome status
```

### Example: Recipe Not Found

```bash
# List all available Recipes
uv run frago recipe list

# Check Recipe name (case-sensitive)
uv run frago recipe info youtube_extract_video_transcript

# If Recipe exists in examples/, copy to user-level
uv run frago recipe copy youtube_extract_video_transcript
```

### Example: Screenshot Path Issues

```bash
# ❌ Wrong: Relative path
frago chrome screenshot screenshot.png

# ✅ Correct: Absolute path
frago chrome screenshot $(pwd)/screenshot.png

# ✅ Correct: Within Run context
uv run frago run init "My task"
frago chrome screenshot screenshot.png  # Auto-saved to Run's screenshots/
```

---

## Next Steps

- **Learn core concepts**: Read [Use Cases](use-cases.md)
- **Understand architecture**: Check [Architecture](architecture.md)
- **Start developing**: Follow [Development Guide](development.md)
- **Create your own Recipes**: See [Recipe System Guide](recipes.md)

---

Created with Claude Code | 2025-11
