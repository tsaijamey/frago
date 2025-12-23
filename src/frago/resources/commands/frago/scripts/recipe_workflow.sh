#!/bin/bash
# Recipe Command Workflow Example
# Applies to: /frago.recipe (recipe creation/update)

# === 1. View Existing Recipes ===
frago recipe list
frago recipe info <recipe_name> --format json

# === 2. Exploration Steps (with Validation) ===

# Step 2.1: Execute operation
frago chrome click '[aria-label="Submit"]'

# Step 2.2: Wait
frago chrome wait 0.5

# Step 2.3: Verify result
frago chrome screenshot /tmp/step1_result.png
# Or verify element appears
frago chrome exec-js "document.querySelector('.success-message') !== null" --return-value

# === 3. Validate Selectors ===
# Check if selector exists
frago chrome exec-js "document.querySelector('[aria-label=\"Submit\"]') !== null" --return-value

# Highlight element to confirm position
frago chrome highlight '[aria-label="Submit"]'

# Get element text to confirm content
frago chrome exec-js "document.querySelector('[aria-label=\"Submit\"]')?.textContent" --return-value

# === 4. Atomic Recipe Directory Structure ===
# ~/.frago/recipes/atomic/chrome/<recipe_name>/   (chrome-js)
# ~/.frago/recipes/atomic/system/<recipe_name>/   (python/shell)
# ├── recipe.md      # Metadata + documentation
# └── recipe.js/py   # Execution script

# === 5. Workflow Recipe Directory Structure ===
# ~/.frago/recipes/workflows/<workflow_name>/
# ├── recipe.md      # Metadata + documentation
# ├── recipe.py      # Execution script
# └── examples/      # Example data (optional)

# === 6. Execute Recipe ===
# ✅ Only correct way
frago recipe run <recipe_name>
frago recipe run <recipe_name> --output-file result.json
frago recipe run <recipe_name> --params '{"key": "value"}'

# === 7. Update Recipe ===
# 1. View recipe location
frago recipe info <recipe_name> --format json

# 2. Re-explore and update files
# 3. Update version number and update history
