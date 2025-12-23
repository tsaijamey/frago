# Logging System Guide

Applies to: `/frago.run`, `/frago.do`

## I. Automatic Logging vs Manual Logging

### Automatic Logging (Auto-recorded After CDP Command Execution)

The following CDP commands **automatically write logs** when there's an active run context:

| Command | action_type | Auto-recorded Content |
|------|-------------|-------------|
| `navigate` | navigation | URL, load status, DOM characteristics |
| `click` | interaction | Selector, DOM characteristic changes |
| `scroll` | interaction | Scroll distance |
| `exec-js` | interaction | Execution results |
| `zoom` | interaction | Zoom ratio |
| `screenshot` | screenshot | File path |
| `get-title` | extraction | Page title |
| `get-content` | extraction | Selector, content |
| `highlight/pointer/spotlight/annotate` | interaction | Visual effect parameters |

**Important**: Automatic logs only record **objective execution results**, not including `_insights`.

### Manual Logging (Used When Agent Needs to Judge)

The following situations **must** manually call `frago run log`:

1. **Add `_insights`** (failure reflection, key discoveries)
2. **Record AI analysis** (`action_type: analysis`)
3. **Record user interaction** (`action_type: user_interaction`)
4. **Record Recipe execution** (`action_type: recipe_execution`)
5. **Record data processing** (`action_type: data_processing`)
6. **Record file script execution** (`execution_method: file`)

---

## II. Log Command Format

```bash
frago run log \
  --step "step description" \
  --status "success|error|warning" \
  --action-type "<see values below>" \
  --execution-method "<see values below>" \
  --data '{"key": "value"}'
```

### action-type Valid Values

**CDP command auto-recorded**:
- `navigation` - Page navigation
- `extraction` - Data extraction
- `interaction` - Page interaction
- `screenshot` - Screenshot

**Manual logging exclusive**:
1. `recipe_execution` - Execute Recipe
2. `data_processing` - Data processing (filter, transform, save file)
3. `analysis` - AI analysis and reasoning
4. `user_interaction` - User interaction (ask, confirm)
5. `other` - Other operations

### execution-method Valid Values (6 types)

1. `command` - CLI command execution (e.g., `frago chrome navigate`)
2. `recipe` - Recipe call
3. `file` - Execute script file (.py/.js/.sh)
4. `manual` - Manual human operation
5. `analysis` - AI reasoning and thinking
6. `tool` - AI tool call (e.g., AskUserQuestion)

---

## III. Complete Examples of 6 execution_methods

### 1. command - CLI Command Execution

```bash
# Execute command
frago chrome navigate https://upwork.com/search

# Log
frago run log \
  --step "Navigate to Upwork search page" \
  --status "success" \
  --action-type "navigation" \
  --execution-method "command" \
  --data '{"command": "frago chrome navigate https://upwork.com/search", "exit_code": 0}'
```

### 2. recipe - Recipe Call

```bash
# Execute Recipe
frago recipe run upwork_extract_job_list --params '{"keyword": "Python"}'

# Log
frago run log \
  --step "Extract Python job list" \
  --status "success" \
  --action-type "recipe_execution" \
  --execution-method "recipe" \
  --data '{"recipe_name": "upwork_extract_job_list", "params": {"keyword": "Python"}, "output": {"jobs": [], "total": 15}}'
```

### 3. file - Execute Script File

```bash
# Save script
cat > ~/.frago/projects/<id>/scripts/filter_jobs.py <<EOF
import json
jobs = json.load(open('outputs/raw_jobs.json'))
filtered = [j for j in jobs if j['rate'] > 50]
json.dump(filtered, open('outputs/filtered_jobs.json', 'w'))
print(f"Filtered {len(filtered)} high-paying jobs")
EOF

# Execute script
uv run python ~/.frago/projects/<id>/scripts/filter_jobs.py

# Log
frago run log \
  --step "Filter jobs with rate > $50" \
  --status "success" \
  --action-type "data_processing" \
  --execution-method "file" \
  --data '{
    "file": "scripts/filter_jobs.py",
    "language": "python",
    "command": "uv run python ~/.frago/projects/<id>/scripts/filter_jobs.py",
    "exit_code": 0,
    "output": "Filtered 8 high-paying jobs",
    "result_file": "outputs/filtered_jobs.json"
  }'
```

**Important Constraint**:
- When `execution_method=file`, `data` **must include `file` field**
- Code exceeding 30 lines must be saved as a file, not stored directly in logs

### 4. manual - Manual Operation

```bash
# Prompt user for manual operation and wait for confirmation
# Log
frago run log \
  --step "Wait for user to log in to Upwork" \
  --status "success" \
  --action-type "user_interaction" \
  --execution-method "manual" \
  --data '{"instruction": "Please manually log in to Upwork account", "completed": true}'
```

### 5. analysis - AI Reasoning/Thinking

```bash
# AI analyzes DOM structure, infers selector
# Log
frago run log \
  --step "Analyze page DOM structure" \
  --status "success" \
  --action-type "analysis" \
  --execution-method "analysis" \
  --data '{
    "conclusion": "Job list uses CSS selector .job-card",
    "confidence": "high",
    "reasoning": "Observed that all job elements contain job-card class name"
  }'
```

### 6. tool - AI Tool Call

```bash
# Use AskUserQuestion tool
# Log
frago run log \
  --step "Ask user to select target job" \
  --status "success" \
  --action-type "user_interaction" \
  --execution-method "tool" \
  --data '{
    "tool": "AskUserQuestion",
    "question": "Found 8 high-paying jobs, which one to choose?",
    "options": ["Job A", "Job B"],
    "answer": "Job A"
  }'
```

---

## IV. _insights Mandatory Recording (/frago.run Exclusive)

**At least 1 out of every 5 logs must include `_insights`.** This is the core information source for Recipe generation.

**Important**: Automatic logs from CDP commands only record objective execution results, **`_insights` must be manually added by Agent**.

| Trigger Condition | insight_type | Requirement |
|---------|--------------|------|
| Operation failure/error | `pitfall` | **Must** |
| Success after retry | `lesson` | **Must** |
| Discover unexpected behavior | `pitfall`/`workaround` | **Must** |
| Find key technique | `key_factor` | **Must** |
| Success on first try | - | Optional |

### Typical Flow

```bash
# 1. Execute CDP command → Auto-record basic log
frago chrome click '.job-card'  # Failed, auto-record error log

# 2. Agent reflects and manually adds insight
frago run log \
  --step "Analyze click failure reason" \
  --status "warning" \
  --action-type "analysis" \
  --execution-method "analysis" \
  --data '{
    "command": "frago chrome click .job-card",
    "error": "Element not found",
    "_insights": [
      {"type": "pitfall", "summary": "Dynamic class unreliable, need data-testid"}
    ]
  }'
```

---

## V. Research Success Criteria (/frago.run Exclusive)

Research completion must meet the following conditions:

1. **Key questions have answers**: Each predefined key question has a clear answer
2. **Verification tests passed**: If involving API/tools, have test scripts to verify feasibility
3. **Last log contains Recipe draft**:

```json
{
  "action_type": "analysis",
  "execution_method": "analysis",
  "step": "Summarize research conclusions and generate Recipe draft",
  "data": {
    "ready_for_recipe": true,
    "recipe_spec": {
      "name": "recipe_name_snake_case",
      "type": "atomic",
      "runtime": "chrome-js",
      "description": "Brief description",
      "inputs": {},
      "outputs": {},
      "key_steps": [],
      "critical_selectors": {},
      "pitfalls_to_avoid": ["Summarized from _insights"],
      "key_factors": ["Summarized from _insights"]
    }
  }
}
```

---

## VI. Code File Processing Constraints

**When code execution is needed**:

1. **Simple commands**: Use `frago <command>` directly, record as `execution_method: command`
2. **Complex scripts** (>30 lines): Save as `scripts/<name>.{py,js,sh}`, record as `execution_method: file`

```python
# ❌ Wrong approach (prohibited)
data = {
    "code": "import json\nwith open(...) as f:\n..."  # Don't store long code
}

# ✅ Correct approach
# 1. Save script
with open('~/.frago/projects/<id>/scripts/filter_jobs.py', 'w') as f:
    f.write(script_content)

# 2. Execute script
uv run python ~/.frago/projects/<id>/scripts/filter_jobs.py

# 3. Log
data = {
    "file": "scripts/filter_jobs.py",  # ✓ Record file path
    "language": "python",
    "command": "uv run python scripts/filter_jobs.py",
    "exit_code": 0,
    "output": "Processed 15 data entries",
    "result_file": "outputs/filtered_jobs.json"
}
```

---

## VII. Progress Display

**Output progress summary every 5 steps**:

```markdown
✅ Completed 5 steps:
1. Navigate to Upwork search page (navigation/command)
2. Extract 15 Python jobs (extraction/command) 💡 key_factor: Need to wait for loading
3. Filter jobs with rate > $50 (data_processing/file)
4. Analyze skill requirements (analysis/analysis)
5. Generate report (data_processing/file)

📊 Current stats: 15 logs, 3 screenshots, 2 script files | Insights: 2 key_factors, 1 pitfall
```
