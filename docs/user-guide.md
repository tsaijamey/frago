[简体中文](user-guide.zh-CN.md)

# Frago User Guide

## Core Use Cases

Frago is suitable for various browser automation and data collection tasks:

1. **Web Data Collection** - Batch extract structured information
   - Example: `"Extract job details from Upwork and export as Markdown"`

2. **Social Media Analysis** - Collect and analyze social content
   - Example: `"Extract Twitter/X posts and comments"`

3. **Content Transcription** - Extract text content from videos/audio
   - Example: `"Download YouTube video subtitles as text"`

4. **Custom Workflows** - Combine multiple Recipes to complete complex tasks
   - Example: `"Batch process form submissions, archive screenshots"`

**Typical Workflow**:
1. AI analyzes task requirements and selects appropriate Recipe
2. Invoke CDP commands to control Chrome execution
3. Record execution logs to JSONL files (100% parsable)
4. Output structured data (JSON/Markdown/text)
5. Persist task context to Run instances

## Environment Requirements

- macOS (for AVFoundation recording)
- Chrome browser
- Python 3.12+
- ffmpeg 8.0+
- uv package manager
- Screen recording permission (System Settings > Privacy & Security > Screen Recording)

## Dependency Installation

```bash
# System dependencies (if not installed)
brew install ffmpeg
brew install uv

# Python dependencies (uv automatically manages virtual environment)
uv sync
```

## Complete Pipeline Execution Flow

### One-Click Pipeline Launch

```bash
# Launch complete pipeline
uv run python src/pipeline_master.py "<topic>" <project_name>
```

### Example Commands

```bash
# Type 1: In-depth News Analysis
uv run python src/pipeline_master.py "AI Education Revolution - Opinion: Personalized Learning Will Replace Traditional Classrooms" ai_education

# Type 2: GitHub Project Analysis
uv run python src/pipeline_master.py "https://github.com/openai/whisper" whisper_intro

# Type 3: Product Introduction
uv run python src/pipeline_master.py "Notion Product Features Introduction" notion_demo

# Type 4: MVP Development Demo
uv run python src/pipeline_master.py "React Todo App MVP Development" todo_mvp
```

### Pipeline Execution Flow

1. **Auto-start Chrome CDP** (port 9222)
2. **Information Collection** (/frago.start) → start.done
3. **Storyboard Planning** (/frago.storyboard) → storyboard.done
4. **Video Generation Loop** (/frago.generate × N) → generate.done
5. **Material Evaluation** (/frago.evaluate) → evaluate.done
6. **Video Merging** (/frago.merge) → merge.done
7. **Environment Cleanup**, output final video

The entire process is fully automated, synchronized through .done files.

## CDP Command Usage Guide

### Basic CDP Commands

All CDP functionality is accessed through a unified CLI interface (`uv run frago <command>`).

```bash
# Navigate to webpage
uv run frago navigate <url>

# Click element
uv run frago click <selector>

# Execute JavaScript
uv run frago exec-js <expression>

# Take screenshot
uv run frago screenshot <output_file>

# Other commands
uv run frago --help
```

### Proxy Configuration

Frago's CDP integration supports proxy configuration for environments requiring network access through a proxy.

#### Environment Variable Configuration

Set global proxy through environment variables:

```bash
export HTTP_PROXY=http://proxy.example.com:8080
export HTTPS_PROXY=http://proxy.example.com:8080
export NO_PROXY=localhost,127.0.0.1
```

#### CLI Parameter Configuration

All CDP commands support proxy parameters:

```bash
# Use proxy
uv run frago navigate https://example.com \
    --proxy-host proxy.example.com \
    --proxy-port 8080

# Bypass proxy
uv run frago navigate https://example.com --no-proxy
```

### Retry Mechanism

CDP connections support intelligent retry mechanisms, specifically optimized for proxy environments:

- **Default retry strategy**: Up to 3 attempts, exponential backoff delay
- **Proxy connection retry strategy**: Up to 5 attempts, shorter delays, suitable for proxy environments
- **Connection timeout**: Default 30 seconds
- **Command timeout**: Default 60 seconds

The retry mechanism automatically identifies proxy connection failures and provides diagnostic information.

## Recipe Management and Usage

The Recipe system provides metadata-driven automation script management.

### Recipe Management Commands

```bash
# List all available Recipes
uv run frago recipe list

# List in JSON format (for AI parsing)
uv run frago recipe list --format json

# View Recipe detailed information
uv run frago recipe info youtube_extract_video_transcript

# Execute Recipe (recommended method)
uv run frago recipe run youtube_extract_video_transcript \
    --params '{"url": "https://youtube.com/watch?v=..."}' \
    --output-file transcript.txt

# Output to clipboard
uv run frago recipe run upwork_extract_job_details_as_markdown \
    --params '{"url": "..."}' \
    --output-clipboard
```

**Supported Options**:
- `--format [table/json/names]` - Output format (list command)
- `--source [project/user/example/all]` - Filter Recipe source (list command)
- `--type [atomic/workflow/all]` - Filter Recipe type (list command)
- `--params '{...}'` - JSON parameters (run command)
- `--params-file <path>` - Read parameters from file (run command)
- `--output-file <path>` - Save output to file
- `--output-clipboard` - Copy output to clipboard
- `--timeout <seconds>` - Execution timeout

### Three Ways to Use Recipes

```bash
# Method 1: Recommended - Metadata-driven (parameter validation, output handling)
uv run frago recipe run youtube_extract_video_transcript \
    --params '{"url": "https://youtube.com/..."}' \
    --output-file transcript.txt

# Method 2: Discover available Recipes
uv run frago recipe list --format json

# Method 3: Traditional method - Direct JS execution (bypass metadata system)
uv run frago exec-js examples/atomic/chrome/youtube_extract_video_transcript.js
```

### Available Example Recipes

Currently provides 4 example Recipes:

| Name | Function | Supported Output |
|------|----------|------------------|
| `test_inspect_tab` | Get current tab diagnostic information (title, URL, DOM stats) | stdout |
| `youtube_extract_video_transcript` | Extract complete YouTube video subtitles | stdout, file |
| `upwork_extract_job_details_as_markdown` | Extract Upwork job details as Markdown | stdout, file |
| `x_extract_tweet_with_comments` | Extract X(Twitter) tweets and comments | stdout, file, clipboard |

### Creating and Updating Recipes

Manage Recipes through `/frago.recipe` command (Claude Code Slash Command):

```
# Create new Recipe (AI interactive guidance)
/frago.recipe create "Extract complete subtitle content from YouTube video page"

# Update existing Recipe
/frago.recipe update youtube_extract_subtitles "YouTube redesign broke subtitle button"

# List all Recipes
/frago.recipe list
```

### Recipe Storage Structure

- **Location**: `src/frago/recipes/` (engine code), `examples/atomic/chrome/` (example Recipes)
- **Naming convention**: `<platform>_<function_description>.js` (e.g., `youtube_extract_subtitles.js`)
- **Supporting documentation**: Each Recipe script (.js) has a corresponding Markdown document (.md)
- **Execution method**: `uv run frago recipe run <recipe_name>`

## Project Directory Structure

Each video project creates the following structure in `projects/<project_name>/`:

```
projects/<project_name>/
├── research/                # AI information collection output
│   ├── report.json
│   └── screenshots/
├── shots/                   # AI storyboard planning output
│   └── shot_xxx.json
├── clips/                   # AI-generated video clips
│   ├── shot_xxx_record.sh   # AI-created recording script
│   ├── shot_xxx.mp4
│   └── shot_xxx_audio.mp3
├── outputs/                 # Final video output
└── logs/                    # Execution logs
```

## Important Notes

1. Chrome must run through CDP launcher with port 9222 available
2. Screen recording permission must be authorized before recording
3. All screenshots must use absolute paths
4. Video length must be greater than or equal to total audio length
5. A `.completed` marker file must be created after each shot is completed
