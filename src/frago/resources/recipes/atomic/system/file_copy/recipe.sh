#!/bin/bash
# Recipe: Copy file
# Runtime: shell
# Input parameters: source_path, dest_path
# Output: Operation result in JSON format

set -euo pipefail

# Parse input parameters (JSON format)
if [ $# -eq 0 ]; then
    echo '{"source_path": "missing", "dest_path": "missing"}'
    exit 0
fi

PARAMS_JSON="$1"

# Extract parameters
SOURCE=$(echo "$PARAMS_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin).get('source_path', ''))")
DEST=$(echo "$PARAMS_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin).get('dest_path', ''))")

# Validate parameters (parameter validation should be done by RecipeRunner, this is just an extra check)
if [ -z "$SOURCE" ] || [ -z "$DEST" ]; then
    >&2 echo "Error: Missing required parameters: source_path and dest_path"
    exit 1
fi

# Check if source file exists
if [ ! -f "$SOURCE" ]; then
    >&2 echo "Error: Source file not found: $SOURCE"
    exit 1
fi

# Execute copy operation
if cp "$SOURCE" "$DEST" 2>/dev/null; then
    SOURCE_SIZE=$(stat -c%s "$SOURCE" 2>/dev/null || stat -f%z "$SOURCE" 2>/dev/null)
    echo "{\"source\": \"$SOURCE\", \"destination\": \"$DEST\", \"size_bytes\": $SOURCE_SIZE, \"operation\": \"copy\"}"
    exit 0
else
    >&2 echo "Error: Failed to copy file from $SOURCE to $DEST"
    exit 1
fi
