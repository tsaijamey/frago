---
name: frago-x-extract-tweet-with-comments
description: Twitter/X tweet and comment extraction and content production guide. Use this skill when users mention "Twitter videos", "tweet opinions", "X comment videos", "netizen opinion videos", or explicitly specify this skill. Covers material collection, opinion organization, and narration script generation workflow.
---

# X Extract Tweet with Comments - Content Production Guide

Collect posts and comments from Twitter/X around specific topics, organize netizen opinions and add host commentary, and generate narration scripts.

## Warning: Core Principle - Document Output Oriented

**The output of this skill serves subsequent stages, and all processes must be documented in files.**

1. **Do not just display in response** - Results of each stage must be written to corresponding `outputs/` files
2. **Incremental saving** - Write to files immediately after collecting/organizing each batch of content, don't wait until the end
3. **Traceable** - All content must be annotated with real sources (URLs) to ensure subsequent verification
4. **Templates are for format reference only** - Placeholders must be replaced with real content, copying example text is prohibited

---

## Production Workflow

| Stage | Task | Output | Manual Intervention |
|-------|------|--------|-------------------|
| 1. Material Collection | Search/browse on X, incrementally record materials | `01_draft.jsonl` | - |
| 2. Extraction & Organization | Categorize opinions, discuss "my" viewpoint with user | `02_content_draft.md` | - |
| 3. Narration Generation | Generate formal narration script | `03_narration.md` | Adjust narration content |

---

## Stage 1: Material Collection

**Output**: `outputs/01_draft.jsonl`, incrementally record all materials.

**Principle**: Better more than less, missing materials cannot be traced later.

**01_draft.jsonl Fields**: `type`(tweet/comment), `url`, `author`, `content`, `scroll_to_text`, `parent_url`(required for comments)

Format example see [templates/01_draft.jsonl](templates/01_draft.jsonl)

### Warning: Critical Constraints (Must Follow)

1. **Do not copy template example content** - Templates are for format reference only, each record must be actually collected material
2. **URLs must be real** - Obtain from browser address bar or DOM, **fabricating or using placeholders is strictly prohibited**
3. **Clear output file before starting collection** - Ensure `outputs/01_draft.jsonl` doesn't contain old data or template content

### Screenshot Usage Guidelines

**Principle**: Use screenshots sparingly, use recipes to extract content more.

| Purpose | Correct | Incorrect |
|---------|---------|-----------|
| Get content | `x_extract_*` recipes | Screenshot and let AI "read" |
| Verify status | Screenshot check | - |
| Backup position | Screenshot (comments may reorder) | - |

---

## Stage 2: Extraction & Organization

Extract materials from `01_draft.jsonl`, categorize and organize, discuss "my" opinions with user.

**Output**: `outputs/02_content_draft.md`, contains categorized opinions and "my comments".

Template see [templates/02_content_draft.md](templates/02_content_draft.md)

Query command: `cat outputs/01_draft.jsonl | jq 'select(.type=="tweet")'`

---

## Stage 3: Narration Generation

Generate formal narration script based on `02_content_draft.md`.

**Output**: `outputs/03_narration.md`

Template see [templates/03_narration.md](templates/03_narration.md)

**Style Requirements**:
- Conversational, brisk language rhythm
- Get straight to the topic, no self-introduction
- Start with an impactful hook to grab attention

**Manual Operation**: Adjust narration content to ensure natural and smooth expression.

---

## Common Issues

| Issue | Solution |
|-------|----------|
| Cannot find target element | Use longer text snippets |
| Comment position changes | Screenshot backup during collection |

---

## Reference Documentation

- Twitter element features and selectors: [REFERENCE.md](REFERENCE.md)
- frago CDP commands: `uv run frago --help`
