[简体中文](use-cases.zh-CN.md)

# Frago Use Cases

This document demonstrates Frago's application in real-world scenarios, showcasing how the three core systems (Run System + Recipe System + Native CDP) work together to solve AI agents' automation challenges.

---

## Why Frago for AI-Driven Automation

AI agents executing browser automation face a fundamental problem: each conversation starts fresh with no memory of past work. Frago addresses this through three mechanisms:

**Standardized Context Accumulation**

Every AI operation follows a unified specification and gets recorded to structured JSONL logs. This means context persists across sessions - the AI can pick up where it left off, understand what was tried before, and build on previous discoveries rather than starting from zero each time.

**Rapid Log Retrieval**

The Run system provides AI with efficient methods to search and query execution history. Instead of re-exploring a page the AI has visited before, it can retrieve the validated selectors, working scripts, and observed behaviors from previous runs.

**Deterministic Execution via Recipes**

When an exploration succeeds, the working approach gets solidified into a Recipe - a versioned, tested automation script. On subsequent encounters with similar tasks, the AI executes the Recipe directly instead of reasoning through the problem again. This eliminates token waste on repeated exploration and removes the randomness that causes intermittent failures when AI "figures it out" differently each time.

---

## Three Usage Modes

| Mode | Command | Goal | Output |
|------|---------|------|--------|
| **🧠 Exploration** | `uv run frago run init` + CDP commands | Explore unknown workflows, accumulate context | JSONL logs + validated scripts + screenshots |
| **📚 Solidification** | `/frago.recipe create` | Transform exploration into reusable Recipe | Recipe files (.js/.py + .md metadata) |
| **⚡ Execution** | `uv run frago recipe run` or `/frago.run` | Complete specific tasks efficiently | Task results + execution logs |

### Selection Recommendations

**When to use Run System**:
- ✅ Exploring unknown pages/workflows
- ✅ Debugging complex issues
- ✅ Need to maintain context across multiple sessions
- ✅ Want to accumulate auditable execution history

**When to create Recipe**:
- ✅ Task will be repeated frequently
- ✅ High-frequency operations consume too many AI tokens
- ✅ Need standardized, reproducible automation
- ✅ Want to share automation scripts with team

**When to use Workflow Recipe**:
- ✅ Task involves multiple platforms or data sources
- ✅ Need to orchestrate multiple atomic operations
- ✅ Require error handling and retry logic
- ✅ Complex business processes with clear steps

---

## Three Core Systems Overview

| System | Core Value | Typical Scenarios |
|--------|-----------|------------------|
| **🧠 Run System** | AI's Working Memory | Explore unknown workflows, debug, context accumulation |
| **📚 Recipe System** | AI's "Muscle Memory" | Solidify high-frequency operations, avoid repeated reasoning |
| **⚡ Native CDP** | Lightweight Execution Engine | Direct Chrome connection, no relay latency |

---

## Scenario 1: Interactive Exploration and Debugging

**Goal**: Step-by-step exploration of unknown pages while maintaining persistent context for future reference.

### Problem Without Run System

```bash
# Traditional approach: No memory between operations
frago chrome navigate https://youtube.com/watch?v=...
frago chrome screenshot step1.png  # Where did this file go?
frago chrome click 'button[aria-label="Show transcript"]'
frago chrome screenshot step2.png  # Lost context from step1

# Problems:
❌ No connection between operations
❌ Screenshots scattered across filesystem
❌ Validated scripts disappear after session ends
❌ Cannot resume or review exploration process
```

### Solution With Run System

**CLI Method**:

```bash
# 1. Create Run instance - establish persistent context
uv run frago run init "Research YouTube subtitle extraction methods"
# Output: Created Run instance: youtube-subtitle-extraction-abc123

# 2. All subsequent operations automatically link to this Run
frago chrome navigate https://youtube.com/watch?v=dQw4w9WgXcQ
frago chrome screenshot step1_initial_page.png
# ✅ Screenshot saved to: projects/youtube-subtitle-extraction-abc123/screenshots/

# 3. Record exploration steps with structured logs
uv run frago run log \
  --step "Located transcript button" \
  --status "success" \
  --action-type "dom_inspection" \
  --execution-method "command" \
  --data '{"selector": "button[aria-label=\"Show transcript\"]"}'

frago chrome click 'button[aria-label="Show transcript"]'
frago chrome screenshot step2_transcript_opened.png

# 4. Save validated script for future use
cat > projects/youtube-subtitle-extraction-abc123/scripts/extract_transcript.js <<'EOF'
(async () => {
  const button = document.querySelector('button[aria-label*="transcript"]');
  if (button) button.click();
  await new Promise(r => setTimeout(r, 1000));

  const segments = document.querySelectorAll('.ytd-transcript-segment-renderer');
  return Array.from(segments).map(s => s.textContent.trim()).join('\n');
})();
EOF

# 5. View complete Run history
uv run frago run info youtube-subtitle-extraction-abc123
```

**Claude Code Method**:

```
/frago.run Research YouTube subtitle extraction methods: locate transcript button, test extraction, save working script
```

AI will automatically:
1. Create or discover Run instance
2. Execute exploration steps (navigate, inspect, click, screenshot)
3. Record all operations to JSONL logs
4. Save validated scripts to Run directory
5. Generate exploration report

### Value of Run System

**Persistent Context**:
```
projects/youtube-subtitle-extraction-abc123/
├── logs/
│   └── execution.jsonl           # Complete operation history
├── screenshots/
│   ├── step1_initial_page.png    # Timestamped screenshots
│   └── step2_transcript_opened.png
├── scripts/
│   └── extract_transcript.js     # Validated working scripts
└── outputs/
    └── exploration_report.md     # AI-generated summary
```

**Key Benefits**:
- ✅ **100% Auditable**: JSONL logs can be programmatically analyzed
- ✅ **Knowledge Accumulation**: Validated scripts persist across sessions
- ✅ **Resumable**: Can continue exploration days later with full context
- ✅ **AI Discovery**: AI can find and resume relevant Run instances using fuzzy matching

---

## Scenario 2: From Exploration to Recipe Solidification

**Goal**: Transform exploration results into reusable Recipe scripts that AI can automatically discover and use.

### Complete Workflow: Explore → Solidify → Reuse

**Step 1: Exploration (Use Run System)**

```bash
# Create exploration Run
uv run frago run init "Find best way to extract Upwork job details"

# Interactive exploration
frago chrome navigate https://www.upwork.com/freelance-jobs/...
frago chrome screenshot job_page_layout.png
frago chrome exec-js 'document.querySelector(".job-title").textContent' --return-value

# Record working approach
uv run frago run log \
  --step "Identified job title selector" \
  --data '{"selector": ".job-title", "works": true}'
```

**Step 2: Solidification (Create Recipe)**

Using Claude Code:
```
/frago.recipe create "Extract Upwork job details as Markdown" from run upwork-job-extraction-abc123
```

AI will:
1. Review Run instance logs and scripts
2. Extract validated selectors and logic
3. Generate Recipe script (.js) + metadata (.md)
4. Save to `~/.frago/recipes/atomic/chrome/upwork_extract_job_details_as_markdown.js`

**Generated Recipe Structure**:

```javascript
// upwork_extract_job_details_as_markdown.js
(async () => {
  const title = document.querySelector('.job-title')?.textContent?.trim();
  const budget = document.querySelector('.budget')?.textContent?.trim();
  const description = document.querySelector('.description')?.textContent?.trim();

  const markdown = `# ${title}\n\n**Budget**: ${budget}\n\n${description}`;
  return { markdown, title, budget };
})();
```

```yaml
---
# upwork_extract_job_details_as_markdown.md
name: upwork_extract_job_details_as_markdown
type: atomic
runtime: chrome-js
description: "Extract complete job information from Upwork job page and format as Markdown"
use_cases:
  - "Analyze job market demands"
  - "Batch collect job information"
tags: ["upwork", "web-scraping", "markdown"]
output_targets: [stdout, file]
version: "1.0.0"
---
```

**Step 3: Reuse (Execute Recipe)**

CLI method:
```bash
uv run frago recipe run upwork_extract_job_details_as_markdown \
  --params '{"url": "https://www.upwork.com/freelance-jobs/..."}' \
  --output-file job_details.md
```

Claude Code method (AI discovers Recipe automatically):
```
/frago.run Extract job details from https://www.upwork.com/freelance-jobs/... and save as Markdown
```

AI will:
1. Query available Recipes: `uv run frago recipe list --format json`
2. Match user intent with Recipe metadata (description, use_cases, tags)
3. Execute Recipe with appropriate parameters
4. Handle output (stdout/file/clipboard based on user request)

### Token Efficiency Comparison

| Approach | First Time | Second Time | Token Savings |
|----------|-----------|-------------|---------------|
| **Without Recipe** | AI explores DOM (150k tokens) | AI explores again (150k tokens) | 0% |
| **With Recipe** | AI explores + creates Recipe (160k tokens) | Execute Recipe (2k tokens) | **98.7%** |

---

## Scenario 3: Atomic Task Automation

**Goal**: Quickly execute single, well-defined tasks using existing Recipes.

### Example: Extract YouTube Video Transcript

**CLI Method**:

```bash
# Discover available Recipes
uv run frago recipe list --format table

# View Recipe details
uv run frago recipe info youtube_extract_video_transcript

# Execute Recipe
uv run frago recipe run youtube_extract_video_transcript \
  --params '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}' \
  --output-file transcript.txt
```

**Claude Code Method**:

```
/frago.run Extract subtitles from https://www.youtube.com/watch?v=dQw4w9WgXcQ
```

AI execution flow:
1. **Intent Recognition**: User wants to extract YouTube subtitles
2. **Recipe Discovery**: `uv run frago recipe list --format json`
3. **Recipe Selection**: Matches `youtube_extract_video_transcript` based on:
   - `description`: "Extract complete subtitle content..."
   - `use_cases`: ["Get subtitles for translation", "Create subtitle files"]
   - `tags`: ["youtube", "transcript"]
4. **Execution**: `uv run frago recipe run youtube_extract_video_transcript ...`
5. **Output Handling**: Checks `output_targets: [stdout, file]`, saves to file

### Applicable Scenarios

- **Data Collection**: Scrape structured data from specific websites
- **Content Extraction**: Video subtitles, article body, comment lists
- **Status Checking**: Page load status, element visibility
- **API Testing**: Execute JavaScript to test web APIs

---

## Scenario 4: Complex Workflow Orchestration

**Goal**: Execute complex business processes spanning multiple platforms and steps.

### Example: Competitor Price Monitoring

**Scenario**: Monitor iPhone 15 prices on Amazon and eBay, generate comparison report.

**Workflow Recipe Structure** (Python + multiple atomic Recipes):

```python
# ~/.frago/recipes/workflows/competitor_price_monitor.py
import sys, json
from frago.recipes import RecipeRunner

def main():
    params = json.loads(sys.argv[1] if len(sys.argv) > 1 else '{}')
    product = params.get('product', '')

    runner = RecipeRunner()

    # Step 1: Extract Amazon data
    amazon_data = runner.run('amazon_search_product', {
        'keyword': product
    })

    # Step 2: Extract eBay data
    ebay_data = runner.run('ebay_search_product', {
        'keyword': product
    })

    # Step 3: Data aggregation and analysis
    result = {
        'product': product,
        'amazon': amazon_data['data'],
        'ebay': ebay_data['data'],
        'comparison': {
            'price_diff': amazon_data['data']['price'] - ebay_data['data']['price'],
            'recommendation': 'Amazon' if amazon_data['data']['price'] < ebay_data['data']['price'] else 'eBay'
        }
    }

    print(json.dumps(result))

if __name__ == '__main__':
    main()
```

**Execution with Run System Context**:

```bash
# Create Run instance for this workflow
uv run frago run init "Monitor iPhone 15 competitor prices"

# Execute Workflow Recipe (operations auto-logged to Run)
uv run frago recipe run competitor_price_monitor \
  --params '{"product": "iPhone 15"}' \
  --output-file price_report.json

# Review complete workflow execution
uv run frago run info <run_id>
```

**Claude Code Method**:

```
/frago.run Monitor iPhone 15 prices on Amazon and eBay, generate comparison report and save as Markdown
```

AI will:
1. Create or discover Run instance
2. Identify as multi-platform price comparison task
3. Execute Workflow Recipe or orchestrate multiple atomic Recipes
4. Record all operations to JSONL logs
5. Generate Markdown report from JSON data

### Run System + Workflow Recipe Integration

**Benefits**:
- ✅ **Complete Audit Trail**: JSONL logs record each atomic Recipe execution
- ✅ **Error Recovery**: If Workflow fails at Step 2, Run logs show exactly where and why
- ✅ **Incremental Execution**: Can manually resume from failed step
- ✅ **Knowledge Base**: Successful Workflow executions become templates for similar tasks

---

## Scenario 5: Batch Processing and Data Collection

**Goal**: Execute repetitive tasks in batches, extract large amounts of data efficiently.

### Example: Batch Extract Upwork Jobs

**Workflow Recipe** (orchestrates atomic Recipe in loop):

```python
# ~/.frago/recipes/workflows/upwork_batch_extract.py
import sys, json
from frago.recipes import RecipeRunner

def main():
    params = json.loads(sys.argv[1] if len(sys.argv) > 1 else '{}')
    keyword = params.get('keyword', '')
    count = params.get('count', 10)

    runner = RecipeRunner()

    # Step 1: Search jobs
    search_result = runner.run('upwork_search_jobs', {'keyword': keyword})
    job_urls = search_result['data']['urls'][:count]

    # Step 2: Extract each job (with progress tracking)
    results = []
    for i, url in enumerate(job_urls, 1):
        print(f"Processing {i}/{len(job_urls)}...", file=sys.stderr)
        try:
            job_data = runner.run('upwork_extract_job_details_as_markdown', {'url': url})
            results.append(job_data['data'])
        except Exception as e:
            results.append({'url': url, 'error': str(e)})

    # Step 3: Output aggregated result
    output = {
        'keyword': keyword,
        'total': len(job_urls),
        'success': sum(1 for r in results if 'error' not in r),
        'jobs': results
    }
    print(json.dumps(output))

if __name__ == '__main__':
    main()
```

**Execution**:

```bash
# CLI method
uv run frago recipe run upwork_batch_extract \
  --params '{"keyword": "Python", "count": 20}' \
  --output-file jobs.json

# Claude Code method
/frago.run Extract 20 Python jobs from Upwork and save as JSON
```

**With Run System Context**:

```
projects/upwork-python-jobs-abc123/
├── logs/
│   └── execution.jsonl           # Records all 20 extraction operations
├── screenshots/
│   ├── job_001.png               # Optional: screenshots of each job
│   └── job_002.png
└── outputs/
    └── jobs.json                 # Final aggregated result
```

---

## Three Systems Working Together

```
User Request: "Find and analyze Python jobs on Upwork"
          │
          ▼
    ┌───────────────────────────────────────┐
    │  1. Run System (Working Memory)       │
    │     Creates: upwork-python-jobs-123   │
    │     Logs: All operations to JSONL     │
    └───────────────┬───────────────────────┘
                    │
                    ▼
    ┌───────────────────────────────────────┐
    │  2. Recipe System (Muscle Memory)     │
    │     Executes: upwork_search_jobs      │
    │     Executes: upwork_extract_job...   │
    └───────────────┬───────────────────────┘
                    │
                    ▼
    ┌───────────────────────────────────────┐
    │  3. Native CDP (Execution Engine)     │
    │     Commands: navigate, click, exec-js│
    │     Direct WebSocket → Chrome         │
    └───────────────┬───────────────────────┘
                    │
                    ▼
            Final Output:
            - jobs.json (structured data)
            - execution.jsonl (complete audit trail)
            - screenshots/ (visual evidence)
```

---

## Next Steps

- **New to Frago?** Start with [Installation Guide](installation.md)
- **Want to create Recipes?** Read [Recipe System Guide](recipes.md)
- **Need technical details?** Check [Architecture](architecture.md)
- **Looking for examples?** See [Example Reference](examples.md)

---

Created with Claude Code | 2025-11
