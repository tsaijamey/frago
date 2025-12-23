#!/bin/bash
# Run Command Workflow Example
# Applies to: /frago.run (exploration & research, preparation for Recipe creation)

# === 1. Check Existing Projects ===
frago run list --format json

# === 2. Create New Project ===
frago run init "nano-banana-pro image api research"
# Returns project_id, assume it's nano-banana-pro-image-api-research

# === 3. Set Context ===
frago run set-context nano-banana-pro-image-api-research

# === 4. Execute Research Operations ===
# Navigate (auto-logged)
frago chrome navigate "https://example.com"

# Extract page links
frago chrome exec-js "Array.from(document.querySelectorAll('a')).map(a => ({text: a.textContent.trim(), href: a.href})).filter(a => a.text)" --return-value

# Screenshot verification (auto-logged)
frago chrome screenshot /tmp/step1.png

# === 5. Manually Record Analysis Results (with _insights) ===
frago run log \
  --step "Analyze API documentation structure" \
  --status "success" \
  --action-type "analysis" \
  --execution-method "analysis" \
  --data '{
    "conclusion": "API uses REST style",
    "endpoints": ["/generate", "/status"],
    "_insights": [
      {"type": "key_factor", "summary": "Requires API Key authentication"}
    ]
  }'

# === 6. Record Failures and Retries (must record _insights) ===
# Assume click failed
frago chrome click '.api-key-btn'  # Failed

# Record failure reason
frago run log \
  --step "Analyze click failure reason" \
  --status "warning" \
  --action-type "analysis" \
  --execution-method "analysis" \
  --data '{
    "command": "frago chrome click .api-key-btn",
    "error": "Element not found",
    "_insights": [
      {"type": "pitfall", "summary": "Dynamic class unreliable, need data-testid"}
    ]
  }'

# === 7. Research Complete: Generate Recipe Draft ===
frago run log \
  --step "Summarize research conclusions and generate Recipe draft" \
  --status "success" \
  --action-type "analysis" \
  --execution-method "analysis" \
  --data '{
    "ready_for_recipe": true,
    "recipe_spec": {
      "name": "nano_banana_generate_image",
      "type": "atomic",
      "runtime": "chrome-js",
      "description": "Generate image using Nano Banana Pro",
      "inputs": {
        "prompt": {"type": "string", "required": true}
      },
      "outputs": {
        "image_url": "string"
      },
      "key_steps": [
        "1. Input prompt",
        "2. Click generate button",
        "3. Wait for result",
        "4. Extract image URL"
      ],
      "pitfalls_to_avoid": ["Dynamic class unreliable"],
      "key_factors": ["Requires API Key authentication"]
    }
  }'

# === 8. Release Context (Mandatory!) ===
frago run release
