[简体中文](examples.zh-CN.md)

# frago Example Reference

This document provides practical examples of using frago's core capabilities (browser automation + Recipe + knowledge domains) for various automation tasks.

---

## Example 1: Interactive Exploration, Then Capture What You Learned

**Goal**: Explore YouTube subtitle extraction step-by-step, land the artifacts in a task directory, and store the lessons in a knowledge domain.

### Step 1: Look for an Existing Landing Spot, Then Create the Task Directory

```bash
# Check whether this work already has a home — don't invent a directory
frago context data:youtube

# Nothing matched, so create one. Both levels are mandatory: <subject>/<YYYYMMDD>-<slug>
mkdir -p ~/.frago/data/youtube/20260813-subtitle-extraction/scripts
```

### Step 2: Navigate and Explore

```bash
# Navigate to YouTube video
frago browser navigate https://www.youtube.com/watch?v=dQw4w9WgXcQ --group youtube-subtitle

# Take initial screenshot — absolute path, straight into the task directory
frago browser screenshot ~/.frago/data/youtube/20260813-subtitle-extraction/initial_page.png --group youtube-subtitle

# Inspect page structure
frago browser exec-js 'document.querySelector("button[aria-label*=\"transcript\"]")' --return-value --group youtube-subtitle
```

### Step 3: Verify the Selector Works

```bash
# Click button and verify
frago browser click 'button[aria-label*="transcript"]' --group youtube-subtitle
frago browser screenshot ~/.frago/data/youtube/20260813-subtitle-extraction/transcript_opened.png --group youtube-subtitle
```

### Step 4: Save Validated Script

```bash
cat > ~/.frago/data/youtube/20260813-subtitle-extraction/scripts/extract_transcript.js <<'EOF'
(async () => {
  const button = document.querySelector('button[aria-label*="transcript"]');
  if (button) button.click();
  await new Promise(r => setTimeout(r, 1000));

  const segments = document.querySelectorAll('.ytd-transcript-segment-renderer');
  return Array.from(segments).map(s => s.textContent.trim()).join('\n');
})();
EOF
```

### Step 5: Store the Lessons in a Knowledge Domain

```bash
# See which domains exist and what is already in one — don't store duplicates
frago def list
frago browser-automation find

# Save as a document; saving the same name again updates it
frago browser-automation save \
  --name=youtube-transcript-extraction \
  --data='{"tags": ["youtube", "transcript", "dom"]}' \
  --content='["[[[sequence]]][[Click the transcript button]][[Wait 1s, then read .ytd-transcript-segment-renderer nodes]]", "[[[constraint]]][[The YouTube transcript panel is lazy-loaded]][[Querying without waiting returns an empty list]]"]'
```

**Where the artifacts land**:
```
~/.frago/data/youtube/20260813-subtitle-extraction/
├── session-id.yaml          # Written when the first file lands; append, never overwrite
├── initial_page.png
├── transcript_opened.png
└── scripts/
    └── extract_transcript.js
```

Next time the same problem comes up: `frago context data:youtube` finds this directory,
`frago browser-automation find` pulls up what you learned.

---

## Example 2: Creating Recipe from Exploration

**Goal**: Transform exploration results into reusable Recipe.

### Using CLI

```bash
# After the exploration is done
# Extract validated logic and create Recipe files

# 1. Create Recipe script
mkdir -p ~/.frago/recipes/atomic/browser/youtube_extract_video_transcript
cat > ~/.frago/recipes/atomic/browser/youtube_extract_video_transcript/recipe.js <<'EOF'
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
cat > ~/.frago/recipes/atomic/browser/youtube_extract_video_transcript/recipe.md <<'EOF'
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
frago recipe run youtube_extract_video_transcript \\
  --params '{"url": "https://youtube.com/watch?v=..."}' \\
  --output-file transcript.txt
\`\`\`

## Prerequisites
- A browser backend is running — the default extension backend, or `frago browser -b cdp start`
- Navigated to YouTube video page
- Video must have subtitles available
EOF
```

### Using Claude Code

```
/frago.recipe create "Extract YouTube video subtitles" from ~/.frago/data/youtube/20260813-subtitle-extraction/
```

AI will:
1. Review the scripts/ directory and artifacts in the task directory
2. Extract validated selectors
3. Generate Recipe files (.js + .md)
4. Test Recipe execution

---

## Example 3: Executing Recipe

**Goal**: Use existing Recipe to extract subtitles quickly.

### CLI Method

```bash
# Discover available Recipes
frago recipe list

# View Recipe details
frago recipe info youtube_extract_video_transcript

# Execute Recipe
frago recipe run youtube_extract_video_transcript \
  --params '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}' \
  --output-file transcript.txt

# Output to clipboard
frago recipe run youtube_extract_video_transcript \
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

**Goal**: Extract subtitles from multiple YouTube videos.

### Create Workflow Recipe

```python
# ~/.frago/recipes/workflows/youtube_batch_extract/recipe.py
import sys, json
from frago.recipes import RecipeRunner

def main():
    params = json.loads(sys.argv[1] if len(sys.argv) > 1 else '{}')
    urls = params.get('urls', [])

    runner = RecipeRunner()
    results = []

    for i, url in enumerate(urls, 1):
        print(f"Processing {i}/{len(urls)}...", file=sys.stderr)
        try:
            result = runner.run('youtube_extract_video_transcript', {'url': url})
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
        'total': len(urls),
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
# ~/.frago/recipes/workflows/youtube_batch_extract/recipe.md
name: youtube_batch_extract
type: workflow
runtime: python
version: "1.0.0"
description: "Batch extract subtitles from multiple YouTube videos"
use_cases:
  - "Batch transcript extraction"
  - "Build a subtitle archive"
tags: ["youtube", "batch", "workflow"]
output_targets: [stdout, file]
inputs:
  urls:
    type: array
    description: "List of YouTube video URLs"
    required: true
outputs:
  results:
    type: array
    description: "Array of transcripts"
dependencies:
  - youtube_extract_video_transcript
---
```

### Execute Workflow

```bash
# Create the task directory and the URL list
mkdir -p ~/.frago/data/youtube/20260813-batch-subtitles
cat > ~/.frago/data/youtube/20260813-batch-subtitles/video_urls.json <<'EOF'
{
  "urls": [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://www.youtube.com/watch?v=oHg5SJYRHA0",
    "https://www.youtube.com/watch?v=..."
  ]
}
EOF

# Run the workflow directly, pointing the output explicitly at the task directory
frago recipe run youtube_batch_extract \
  --params-file ~/.frago/data/youtube/20260813-batch-subtitles/video_urls.json \
  --output-file ~/.frago/data/youtube/20260813-batch-subtitles/subtitles.json
```

**Output** (`subtitles.json`):
```json
{
  "total": 3,
  "success": 3,
  "failed": 0,
  "results": [
    {
      "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
      "data": {
        "title": "Rick Astley - Never Gonna Give You Up",
        "transcript": "...",
        "language": "en"
      },
      "status": "success"
    }
  ]
}
```

---

## Example 5: Complex Multi-Platform Task (Vision)

> This example illustrates the intended workflow when the orchestration layer is complete. Currently, users need to manually choose between `/frago.run` (exploration) and `frago recipe run` (replay).

**Goal**: Monitor iPhone 15 prices on Amazon and eBay, generate comparison report.

### Using Claude Code

```
/frago.run Monitor iPhone 15 prices on Amazon and eBay, generate comparison report and save as Markdown
```

AI will:
1. Create the task directory: `~/.frago/data/iphone/20260813-price-monitor/`
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
4. Generate Markdown report

**Generated Report** (`~/.frago/data/iphone/20260813-price-monitor/price_comparison.md`):
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
Generated with frago | ~/.frago/data/iphone/20260813-price-monitor/
```

---

## Example 6: CDP Command Usage Patterns

### Basic Navigation and Interaction

```bash
# Start a dedicated headless CDP instance (port 9222)
frago browser -b cdp start --headless

# Navigate to page
frago browser navigate https://news.ycombinator.com/ --group hn

# Wait for page load
frago browser wait --group hn 2

# Click element
frago browser click 'a.titlelink:first-child' --group hn

# Get page title
frago browser exec-js 'document.title' --return-value --group hn

# Tear the instance down when done
frago browser -b cdp stop
```

### Screenshots and Visual Effects

```bash
# Take full page screenshot
frago browser screenshot hackernews_page.png --group hn --full-page

# Highlight specific element
frago browser highlight '.storylink' --color "#FF6B6B" --life-time 3 --group hn

# Spotlight effect (dim surroundings)
frago browser spotlight '.athing:first-child' --life-time 5 --group hn

# Add annotation
frago browser annotate '.score' "Top story" --position top --group hn
```

### JavaScript Execution

```bash
# Extract all links
frago browser exec-js 'Array.from(document.querySelectorAll("a")).map(a => a.href)' \
  --return-value --group hn

# Scroll to bottom
frago browser exec-js 'window.scrollTo(0, document.body.scrollHeight)' --group hn

# Check element existence
frago browser exec-js 'document.querySelector(".pagetop") !== null' \
  --return-value --group hn
```

---

## Example 7: Finding Work You Did Earlier

Three separate paths: find the **artifacts**, replay the **raw conversation**, look up the **captured lessons**.

### Where Did That Thing End Up?

```bash
# Locate it by keyword — don't list directories and guess
frago context data:youtube

# The data: prefix searches only ~/.frago/data; without a prefix it sweeps all of
# ~/.frago, which is slow and noisy, so it asks for confirmation
frago context youtube --yes

# Machine-readable
frago context data:iphone --json
```

Hits print in three tiers: directory-name hits, filename hits, and content hits in readable documents.
The command reports paths only and prints no file contents — you decide what is worth reading.

### Replay What You Did Before

```bash
# Describe it in one sentence; a model expands it into terms, then both the claude
# and opencode session stores are swept
frago session search "that time we researched YouTube subtitle extraction"

# When you already know the literal terms, pass them and skip the model turn
frago session search "subtitle extraction" --terms "transcript,ytd-transcript-segment-renderer" --days 30

# Just the most relevant sessions
frago session search "CDP won't connect" --top 5
```

Sessions rank by how many **distinct** terms they matched. Each hit reports the session id,
matching excerpts, and a ready-to-run command to resume that session.

### Look Up Captured Lessons

```bash
# Which knowledge domains exist
frago def list

# What is stored in one domain
frago browser-automation find

# Read a single document in full
frago browser-automation find -- --name=youtube-transcript-extraction

# Filter by tag
frago browser-automation find -- --tags=youtube
```

---

## Common Patterns and Best Practices

### Pattern 1: Exploration → Recipe → Automation

```
1. frago context data:<keyword> to find an existing landing spot; create a task directory if none
2. Explore page interactively (browser commands)
3. Save scripts under the task directory's scripts/, lessons via frago <domain> save
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
# CDP ports are whitelisted: 9222 (default) and 9223 (agent_os recorder)
lsof -i :9222

# If the virtual desktop stage is up, its actor owns 9222 — leave it alone
frago desktop status

# Start / check / stop the frago-managed CDP instance
frago browser -b cdp start --headless
frago browser status
frago browser -b cdp stop
```

### Example: Recipe Not Found

```bash
# List all available Recipes
frago recipe list

# Check Recipe name (case-sensitive)
frago recipe info youtube_extract_video_transcript
```

### Example: Where Screenshots Land

```bash
# ❌ Wrong: relative path — lands in whatever the shell's working directory was, unfindable later
frago browser screenshot screenshot.png --group my-task

# ❌ Wrong: task directory sitting directly under the data root, missing the subject level
frago browser screenshot ~/.frago/data/20260813-subtitle-extraction/screenshot.png --group my-task

# ✅ Correct: absolute path with both levels, <subject>/<YYYYMMDD>-<slug>
frago browser screenshot ~/.frago/data/youtube/20260813-subtitle-extraction/screenshot.png --group my-task
```

---

## Next Steps

- **Learn core concepts**: Read [Concepts](concepts.md)
- **Create your own Recipes**: See [Recipe System Guide](recipes.md)

---

Created with Claude Code | 2025-11
