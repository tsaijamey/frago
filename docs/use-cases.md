[简体中文](use-cases.zh-CN.md)

# Frago Use Cases

This document demonstrates Frago's application in real-world scenarios, covering the complete workflow from Recipe creation to complex Workflow orchestration.

---

## Scenario 1: Recipe Generation and Consolidation

**Goal**: Transform naturally described tasks into reusable standardized Recipe scripts.

### Claude Code Method

```
/frago.recipe Generate an extraction script for this page: https://news.ycombinator.com/, extract titles and links of top 10 news items
```

### AI Execution Flow

1. **Analyze page**: Automatically obtain page structure via CDP
2. **Generate code**: Write `hn_extract.js` (Chrome Runtime) and `hn_extract.md` (metadata)
3. **Verify and save**: Test run in temporary environment, save to `.frago/recipes/project/` upon success
4. **Immediately available**: Can be directly called via `/frago.run` subsequently

### CLI Equivalent Operation

```bash
# Manually create Recipe (requires manual code writing)
cat > .frago/recipes/project/hn_extract.js <<'EOF'
(async () => {
  const items = Array.from(document.querySelectorAll('.athing')).slice(0, 10);
  return items.map(item => ({
    title: item.querySelector('.titleline a').textContent,
    url: item.querySelector('.titleline a').href
  }));
})();
EOF

# Create metadata file
cat > .frago/recipes/project/hn_extract.md <<'EOF'
---
name: hn_extract
type: atomic
runtime: chrome-js
description: "Extract top 10 news items from Hacker News homepage"
...
EOF

# Execute Recipe
uv run frago recipe run hn_extract --output-file news.json
```

---

## Scenario 2: Atomic Task Automation

**Goal**: Quickly execute single, clearly defined tasks, such as extracting data from specific pages.

### CLI Method

```bash
# Directly execute Recipe to extract YouTube video subtitles
uv run frago recipe run youtube_extract_video_transcript \
  --params '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}' \
  --output-file transcript.md
```

### Claude Code Method

```
/frago.run Extract subtitles from this video: https://www.youtube.com/watch?v=dQw4w9WgXcQ
```

AI automatically identifies intent → Matches `youtube_extract_video_transcript` Recipe → Executes and returns result

### Applicable Scenarios

- Data collection (scrape structured data from specific websites)
- Content extraction (video subtitles, article body, comment lists)
- Status checking (page load status, element visibility)

---

## Scenario 3: Interactive Debugging and Exploration

**Goal**: Step-by-step troubleshooting or exploration of unknown pages while maintaining context.

### CLI Sequential Operations

```bash
# 1. Initialize debug session
uv run frago run init "Investigate login page layout shift issue"

# 2. Execute series of operations (context automatically associated with current Run)
uv run frago navigate https://staging.example.com/login
uv run frago exec-js "window.innerWidth"
uv run frago screenshot before_click.png
uv run frago click "#login-btn"
uv run frago screenshot after_click.png

# 3. Record manual observations
uv run frago run log \
  --step "Observed 20px rightward shift after click" \
  --status "failure" \
  --action-type "analysis" \
  --execution-method "manual" \
  --data '{"observation": "After login button click, entire form shifts 20px right"}'

# 4. Archive session
uv run frago run archive "Investigate login page layout shift issue"
```

### Claude Code Method

```
/frago.run Investigate layout shift issue on staging.example.com/login, first take screenshot, then click login button and screenshot again, compare differences
```

AI will automatically:
1. Create Run instance
2. Execute navigation, screenshot, click operations
3. Analyze differences between two screenshots
4. Generate report with diagnostic information

### Value of Run System

- **Context persistence**: All operations recorded in `execution.jsonl`, can be traced anytime
- **Screenshot archiving**: Key step screenshots automatically saved to `screenshots/`
- **Script accumulation**: Validation scripts generated during exploration saved to `scripts/`
- **Reusable**: Can continue this Run instance for similar issues later

---

## Scenario 4: Complex Workflow Orchestration

**Goal**: Execute complex business processes spanning platforms and multiple steps.

### CLI Method (Python Recipe Orchestration)

```bash
# Execute complex Recipe with multiple steps
uv run frago recipe run competitor_price_monitor \
  --params '{"product": "iPhone 15", "sites": ["amazon", "ebay"]}' \
  --output-file price_report.json
```

### Claude Code Method

```
/frago.run Monitor iPhone 15 prices on Amazon and eBay, generate comparison report and save as markdown
```

### AI Execution Flow

1. **Intent recognition**: Identify as multi-platform price comparison task
2. **Task breakdown**:
   - Subtask A: Amazon search and extraction (call `amazon_search` Recipe)
   - Subtask B: eBay search and extraction (call `ebay_search` Recipe)
   - Subtask C: Data aggregation and report generation (call Python data processing logic)
3. **Execute and feedback**: Execute subtasks sequentially, finally generate `price_comparison.md`

### Workflow Recipe Example Structure

```python
# examples/workflows/competitor_price_monitor.py
from frago.recipes import RecipeRunner

runner = RecipeRunner()

# Step 1: Extract Amazon data
amazon_data = runner.run('amazon_search', params={
    'keyword': params['product']
})

# Step 2: Extract eBay data
ebay_data = runner.run('ebay_search', params={
    'keyword': params['product']
})

# Step 3: Data aggregation
result = {
    'product': params['product'],
    'amazon': amazon_data['data'],
    'ebay': ebay_data['data'],
    'comparison': analyze_prices(amazon_data, ebay_data)
}

print(json.dumps(result))
```

---

## Scenario 5: Batch Processing and Data Collection

**Goal**: Execute repetitive tasks in batches, extract large amounts of data.

### Example: Batch Extract Upwork Jobs

```bash
# Use Workflow Recipe for batch processing
uv run frago recipe run upwork_batch_extract \
  --params '{"keyword": "Python", "count": 20}' \
  --output-file jobs.json
```

### Internal Workflow Logic

```python
# examples/workflows/upwork_batch_extract.py
runner = RecipeRunner()

# Call atomic Recipe to extract job list
job_list = runner.run('upwork_search_jobs', params={
    'keyword': params['keyword']
})

# Loop call atomic Recipe to extract details
results = []
for job_url in job_list['data']['urls'][:params['count']]:
    job_detail = runner.run('upwork_extract_job_details', params={
        'url': job_url
    })
    results.append(job_detail['data'])

print(json.dumps({'jobs': results, 'total': len(results)}))
```

---

## Summary: Three Usage Modes

| Mode | Command | Goal | Output |
|------|---------|------|--------|
| **Exploration Research** | `/frago.run` | Collect information to create Recipe | JSONL logs + validation scripts + Recipe draft |
| **Consolidate Recipe** | `/frago.recipe` | Transform exploration results into reusable scripts | Recipe files (.js/.py + .md) |
| **Task Execution** | `/frago.exec` | Complete specific business goals | Task results + execution logs |

Selection Recommendations:
- **Unknown pages/processes**: Use `/frago.run` for exploration, accumulate context
- **Repetitive tasks**: Create Recipe then use `/frago.exec` or directly execute Recipe
- **Complex business processes**: Create Workflow Recipe, orchestrate multiple atomic Recipes
