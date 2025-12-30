#!/bin/bash
# frago Common Command Quick Reference
# Applies to: /frago.run, /frago.do, /frago.recipe, /frago.test

# === Chrome Management (Execute First) ===
# Check CDP connection status
frago chrome status

# Start Chrome (two modes)
frago chrome start              # Normal window mode
frago chrome start --headless   # Headless mode (no UI)

# Common startup options
frago chrome start --port 9333        # Use different port
frago chrome start --keep-alive       # Keep running after start, until Ctrl+C
frago chrome start --no-kill          # Don't kill existing CDP Chrome process

# Stop Chrome
frago chrome stop

# === Discover Resources ===
# List all recipes
frago recipe list
frago recipe list --format json  # AI format

# View recipe details
frago recipe info <recipe_name>

# Search related run records
rg -l "keyword" ~/.frago/projects/

# === Browser Operations ===
# Navigate
frago chrome navigate <url>
frago chrome navigate <url> --wait-for <selector>

# Click
frago chrome click <selector>
frago chrome click <selector> --wait-timeout 10

# Scroll
frago chrome scroll <pixels>  # Positive for down, negative for up
frago chrome scroll-to --text "target text"

# Wait
frago chrome wait <seconds>

# === Information Extraction ===
# Get title
frago chrome get-title

# Get content
frago chrome get-content
frago chrome get-content <selector>

# Execute JavaScript
frago chrome exec-js <expression>
frago chrome exec-js <expression> --return-value
frago chrome exec-js "window.location.href" --return-value  # Get URL

# Screenshot
frago chrome screenshot output.png
frago chrome screenshot output.png --full-page

# === Visual Effects ===
frago chrome highlight <selector>
frago chrome pointer <selector>
frago chrome spotlight <selector>
frago chrome annotate <selector> --text "description"

# === Run/Project Management ===
# List projects
frago run list
frago run list --format json

# Initialize project
frago run init "task description"

# Set context
frago run set-context <project_id>

# Release context
frago run release

# Log
frago run log \
  --step "step description" \
  --status "success" \
  --action-type "analysis" \
  --execution-method "analysis" \
  --data '{"key": "value"}'

# Screenshot (in context)
frago run screenshot "step description"

# === Recipe Execution ===
frago recipe run <name>
frago recipe run <name> --params '{"key": "value"}'
frago recipe run <name> --output-file result.json
