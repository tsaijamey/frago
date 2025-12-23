# Workspace and Directory Management

Applies to: `/frago.run`, `/frago.do`

## I. projects Directory

All run instances are stored in `~/.frago/projects/`, this is a fixed location.

```bash
frago run init "my-task"  # Creates ~/.frago/projects/<id>/
```

---

## II. Workspace Isolation Principle

### All Outputs Must Be Placed Inside Project Workspace

```
~/.frago/projects/<id>/      # Run instance workspace root directory
├── project.json             # Metadata
├── logs/
│   └── execution.jsonl      # Execution logs
├── scripts/                 # Execution scripts
├── screenshots/             # Screenshots
├── outputs/                 # Task outputs (data, reports, videos, etc.)
│   ├── video_script.json    # Generated script instance
│   ├── final_video.mp4      # Video output
│   └── analysis.json        # Analysis results
└── temp/                    # Temporary files (clean up after task completion)
```

### Prohibited Behaviors

- ❌ Create files in external locations like Desktop, /tmp, Downloads
- ❌ Use recipe default location without specifying output_dir when executing recipes
- ❌ Outputs scattered in directories outside workspace

### Correct Approach

- ✅ All files use paths under `~/.frago/projects/<id>/`
- ✅ Explicitly specify `output_dir` inside workspace when calling recipes
- ✅ Place temporary files in `temp/`, clean up after task completion

```bash
# ✅ Correct: All outputs inside workspace
frago recipe run video_produce_from_script \
  --params '{
    "script_file": "~/.frago/projects/<id>/outputs/video_script.json",
    "output_dir": "~/.frago/projects/<id>/outputs/video"
  }'

# ❌ Wrong: Using external directory
frago recipe run video_produce_from_script \
  --params '{"script_file": "~/Desktop/script.json"}'
```

---

## III. Single Run Exclusivity

**The system only allows one active Project context.** This is a design constraint to ensure focused work.

### Exclusivity Rules

- When `set-context` is called, if another project is already active, the command will fail and prompt to release first
- The same project can be `set-context` multiple times (resume work)
- **Must** release context after task completion

### Typical Workflow

```bash
# 1. Start task
frago run init "upwork python job apply"
frago run set-context upwork-python-job-apply

# 2. Execute task...

# 3. Task completed, release context (mandatory!)
frago run release

# 4. Start new task
frago run init "another task"
frago run set-context another-task
```

### If You Forget to Release

```bash
# You'll see an error when trying to set new context
Error: Another run 'upwork-python-job-apply' is currently active.
Run 'frago run release' to release it first,
or 'frago run set-context upwork-python-job-apply' to continue it.
```

---

## IV. Working Directory Management

**Do NOT use `cd` command to switch directories!** This will cause `frago` commands to fail.

### Correct Approach

**Always execute all commands from the project root directory**, access files using absolute or relative paths:

```bash
# ✅ Correct: Use absolute path to execute script
uv run python ~/.frago/projects/<id>/scripts/filter_jobs.py

# ✅ Correct: Use absolute path to read file
cat ~/.frago/projects/<id>/outputs/result.json

# ✅ Correct: Use find to view file structure
find ~/.frago/projects/<id> -type f -name "*.md" | sort
```

### Wrong Approach

```bash
# ❌ Wrong: Don't use cd
cd ~/.frago/projects/<id> && uv run python scripts/filter_jobs.py

# ❌ Wrong: frago will fail after switching directory
cd ~/.frago/projects/<id>
frago run log ...  # This will error!
```

### File Path Convention

When referencing files inside a project instance, use **paths relative to the project root**:

```bash
# When logging, data.file uses relative path
frago run log \
  --data '{"file": "scripts/filter_jobs.py", "result_file": "outputs/filtered_jobs.json"}'

# But when executing scripts, use full relative path or absolute path
uv run python ~/.frago/projects/<id>/scripts/filter_jobs.py
```

---

## V. Notes

- **Context storage**: `~/.frago/current_run`
- **Context priority**: Environment variable `FRAGO_CURRENT_RUN` > config file
- **Concurrency safety**: Work in only one run instance at a time
