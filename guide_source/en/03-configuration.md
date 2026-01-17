---
id: configuration
title: Configuration
category: config
order: 3
version: 0.38.1
last_updated: 2026-01-17
tags:
  - configuration
  - settings
  - api-key
  - model
  - sync
---

# Configuration

## Q: Where do I enter my Anthropic API Key?

**A**: Go to **Settings → General → API Key** to enter it. You must configure an API Key for AI to work when first using frago.

**Detailed Steps**:

1. **Obtain API Key**
   - Visit [https://console.anthropic.com/](https://console.anthropic.com/)
   - Log in to your Anthropic account (register if you don't have one)
   - Go to API Keys page
   - Click "Create Key" to create a new key
   - Copy the generated key (format: `sk-ant-...`)

2. **Configure in frago**
   - Open frago Web UI
   - Click **Settings** in the left sidebar
   - Select **General** tab
   - In "API Endpoint" section, ensure **"Official Claude API"** is selected
   - Paste your key in the "API Key" input field
   - Click **"Save Configuration"**

3. **Verify Configuration**
   - Go to Console or Tasks
   - Send a simple message like "hello"
   - If AI responds, configuration is successful

**Common Issues**:

❌ **Shows "Authentication failed"**
   - Check if key is fully copied (starts with sk-ant-)
   - Check if account has credits
   - Check if network can access Anthropic API

❌ **No response after saving**
   - Refresh the page and retry
   - Check browser Console for errors

**Security Warning**:
⚠️ API Key is sensitive information. Don't share with others. If leaked, immediately delete it in Anthropic console and create a new one.

**Billing Info**:
💰 Using Anthropic API incurs charges, billed per token. Recommend setting usage limits in Anthropic console to avoid unexpected costs.

**Related Questions**: What if Authentication failed? (See Troubleshooting chapter)

---

## Q: What is "Model Override" in Settings? Which should I choose?

**A**: Model Override allows you to override the default AI model selection. Beginners should keep default (leave empty), frago will automatically choose the most suitable model.

**Model Comparison**:

| Model | Speed | Capability | Cost | Use Cases |
|-------|-------|------------|------|-----------|
| **Sonnet** (default) | ⚡⚡ Fast | 💪💪 Strong | 💵 Medium | Daily tasks, balanced performance |
| **Opus** | ⚡ Slower | 💪💪💪 Strongest | 💵💵💵 Expensive | Complex reasoning, code generation |
| **Haiku** | ⚡⚡⚡ Fastest | 💪 Basic | 💵 Cheap | Simple tasks, quick responses |

**Field Descriptions**:

1. **Sonnet Model (optional override)**
   - Default empty → frago uses preset Sonnet version
   - Fill in → Override to specified version (e.g., `claude-sonnet-4-5-20251101`)

2. **Haiku Model (optional override)**
   - Used for quick tasks (like generating task titles)
   - Default empty → frago uses preset Haiku version

**Usage Recommendations**:

✅ **Keep Default (Recommended)**:
   - Let frago automatically choose appropriate model versions
   - frago follows official recommendations for updates

⚠️ **Manually Specify Model**:
   - Only when you need to test specific model versions
   - Requires understanding model version naming conventions
   - Example: `claude-sonnet-4-5-20251101`

**Example Scenarios**:

```
Scenario 1: Daily Use
  Sonnet Model: [leave empty]
  Haiku Model: [leave empty]
  → frago uses default configuration, worry-free

Scenario 2: Testing New Model
  Sonnet Model: claude-sonnet-4-5-20251101
  Haiku Model: [leave empty]
  → Main tasks use specified Sonnet version, auxiliary tasks use default Haiku

Scenario 3: Reduce Costs
  Sonnet Model: [leave empty]
  Haiku Model: [leave empty]
  → Consider using Custom Endpoint with third-party API (see next question)
```

**Pricing Reference** (January 2026):
- Haiku: ~$0.25/M tokens (input)
- Sonnet: ~$3/M tokens (input)
- Opus: ~$15/M tokens (input)

💡 **Tip**: Not sure what to choose? Keep the defaults! frago automatically selects based on task type.

---

## Q: What's the difference between "Endpoint Type" options?

**A**: Official Claude API uses Anthropic's official API (recommended), while Custom Endpoint connects to third-party compatible APIs (for advanced users).

**Comparison of Two Modes**:

### 1. Official Claude API

**Features**:
- ✅ Uses Anthropic's official service
- ✅ Stable and reliable, full functionality
- ✅ Beginner-friendly, simple configuration
- ⚠️ Requires international payment method (credit card)
- ⚠️ May require VPN

**Configuration**:
1. Select "Official Claude API"
2. Enter API Key (obtained from Anthropic)
3. Save

### 2. Custom API Endpoint

**Features**:
- ✅ Can connect to third-party compatible services (DeepSeek, Kimi, domestic proxies, etc.)
- ✅ Supports locally deployed models
- ⚠️ Requires manual URL and Key configuration
- ⚠️ Functionality may be incomplete (depends on third-party implementation)

**Configuration**:
1. Select "Custom API Endpoint"
2. Fill in the following:
   - **API URL**: Third-party API address (e.g., `https://api.example.com/v1`)
   - **API Key**: Key provided by third party
   - **Default Model**: Main model name (e.g., `deepseek-chat`)
   - **Sonnet Model**: Sonnet model name (optional)
   - **Haiku Model**: Haiku model name (optional)
3. Save

**Switching Risk Warning**:

⚠️ **Switching from Official to Custom will clear your API Key configuration. This action cannot be undone!**

Before switching, please confirm:
- You have complete information for the third-party API
- You understand the limitations and costs of the third-party API
- You have backed up current configuration

**Usage Scenarios**:

| Scenario | Recommendation |
|----------|----------------|
| First time using frago | Use Official Claude API |
| Cannot access Anthropic | Use Custom Endpoint + domestic proxy |
| Reduce costs | Use Custom Endpoint + compatible cheaper models |
| Local deployment | Use Custom Endpoint + local model |
| Enterprise intranet | Use Custom Endpoint + intranet proxy |

**Example Configuration (Custom Endpoint)**:

```
Using DeepSeek API:
  API URL: https://api.deepseek.com/v1
  API Key: sk-xxxxxxxxxxxxxxxx
  Default Model: deepseek-chat

Using proxy:
  API URL: https://your-proxy.com/v1
  API Key: [Key provided by proxy]
  Default Model: claude-sonnet-4-5
```

💡 **Beginner Advice**: Prioritize using Official Claude API to avoid configuration issues.

**Related Questions**: API Key configured but still getting errors? (See Troubleshooting chapter)

---

## Q: What is Sync for? When do I need it?

**A**: Sync synchronizes your Recipes and Skills across devices via Git repository. Single-machine frago usage doesn't require Sync configuration.

**What Sync Does**:

Automatically syncs the following to Git repository:
- ✅ Your Recipes (`~/.frago/recipes/`)
- ✅ Your Skills (`~/.frago/skills/`)
- ✅ Claude Code Commands configuration
- ❌ Doesn't sync Secrets (credentials)
- ❌ Doesn't sync Session history
- ❌ Doesn't sync project files

**Usage Scenarios**:

| Scenario | Need Sync? |
|----------|------------|
| Using only one computer | ❌ No |
| Using frago on multiple computers | ✅ Yes |
| Team collaboration on Recipes | ✅ Yes |
| Backup Recipes to prevent loss | ✅ Yes (optional) |
| Share Recipes with others | ❌ Use Community Recipes |

**Configuration Steps**:

1. **Create Private Git Repository**
   - Create a private repository on GitHub (e.g., `frago-sync`)
   - Ensure repository is private (may contain sensitive configuration)

2. **Configure in frago**
   - Settings → Sync
   - Enter repository URL
   - Configure GitHub authentication (requires gh CLI)
   - Click "Sync Now" to test

3. **Automatic Sync**
   - After configuration, frago auto-syncs on startup
   - Can also manually click "Sync Now"

**How It Works**:

```
Device A changes → Push to Git repo → Pull to Device B
     ↓                                      ↓
~/.frago/recipes/                  ~/.frago/recipes/
└── my-recipe.py                  └── my-recipe.py
```

**Security Considerations**:

⚠️ **Must use private repository!**
- Recipes may contain sensitive information (URLs, logic)
- Configuration files may expose usage patterns

⚠️ **Secrets are not synced**
- API keys and other sensitive information are excluded by default
- Need to configure separately on each device

**Beginner Advice**:

💡 If you:
- Use only one computer
- Just started using frago
- Haven't created your own Recipes yet

**Then you don't need to configure Sync**. Consider backup and sync after you've created valuable Recipes.

**Related Questions**: Sync configured but not working? (Check gh CLI configuration and repository permissions)

---

## Q: What is the Secrets page for?

**A**: Secrets securely stores API keys, database passwords, and other sensitive information for Recipes to use. Beginners can skip this until specific Recipes require it.

**Why Need Secrets?**

Many Recipes need to access external services, such as:
- 📧 Send email → Need SMTP password
- 🗄️ Query database → Need database password
- 🤖 Call OpenAI → Need OPENAI_API_KEY
- ☁️ Upload to S3 → Need AWS credentials

**Secrets are never synced or shared**, ensuring security.

**How to Use Secrets?**

**1. Add in Secrets page**:
```
Name: OPENAI_API_KEY
Value: sk-xxxxxxxxxxxxxxxx
```

**2. Reference in Recipe**:
```python
import os

# frago automatically injects Secrets as environment variables
api_key = os.getenv("OPENAI_API_KEY")
```

**3. Run Recipe**:
   - frago automatically injects environment variables
   - Recipe can use them directly
   - Keys won't show in logs

**Common Environment Variables**:

| Variable Name | Purpose | Example Value |
|---------------|---------|---------------|
| `OPENAI_API_KEY` | OpenAI API | sk-... |
| `GITHUB_TOKEN` | GitHub API | ghp_... |
| `SMTP_PASSWORD` | Email sending | your_password |
| `DATABASE_URL` | Database connection | postgresql://... |

**When to Configure?**

✅ **Need to Configure**:
- Recipe fails with "Missing required environment variable"
- Recipe documentation explicitly requires certain API Key
- Secrets page shows "not configured" warning

❌ **Don't Need to Configure**:
- Only using frago's Console and Tasks
- Running Recipes that don't need external services
- Just learning frago

**Security Tips**:

✅ **Secure**:
- Secrets stored locally (`~/.frago/secrets.json`)
- Not synced to Git repository
- Not shown in plaintext in Web UI

⚠️ **Caution**:
- Don't hardcode keys in Recipe code
- Don't print keys in logs
- Regularly rotate important keys

**Example Scenario**:

```
Scenario: Running community Recipe "send-email-report"

1. Check Recipe documentation, find it requires:
   - SMTP_HOST
   - SMTP_PORT
   - SMTP_USERNAME
   - SMTP_PASSWORD

2. Go to Settings → Secrets, add these 4 variables

3. Run Recipe, fill other parameters (recipient, subject, etc.)

4. Recipe automatically uses SMTP configuration from Secrets to send email
```

**Related Questions**: Recipe shows missing environment variable? (Add to Secrets page as prompted)

---

## Q: What is "Working Directory"? Can I change it?

**A**: Working Directory is the default working directory where AI executes tasks. Usually no need to modify unless you want AI to work in a specific directory.

**What Working Directory Does**:

When AI performs file operations, relative paths are based on this directory:

```python
# Working Directory: /Users/you/projects

# AI executes: read "data.json"
# Actually reads: /Users/you/projects/data.json

# AI executes: create "output/result.csv"
# Actually creates: /Users/you/projects/output/result.csv
```

**Default Values**:

- **Desktop mode** (pywebview): `~/Desktop`
- **Server mode** (Web UI): `~/.frago/projects/current_run/workspace`

**When to Modify?**

✅ **Good to Modify**:
- You have a fixed project directory (like `~/my-project`)
- Need AI to work in a specific directory
- Easier to manage AI-generated files

❌ **Not Recommended**:
- Just started using frago
- Unsure what directory to set
- Frequently switching between different projects

**How to Modify?**

1. Settings → General
2. Find "Working Directory"
3. Click "Edit" button
4. Select or enter directory path
5. Save

**Considerations**:

⚠️ **Directory must exist**:
- frago won't automatically create non-existent directories
- Ensure directory is created before setting

⚠️ **Permission issues**:
- Ensure frago has read/write permissions
- Avoid setting system-protected directories (like `/System`)

⚠️ **Path format**:
- **Mac/Linux**: `/Users/you/project` or `~/project`
- **Windows**: `C:/Users/you/project` or use forward slashes

**Usage Recommendations**:

💡 **Recommended Practice**:
1. Create dedicated working directory for frago: `~/frago-workspace`
2. Set it as Working Directory in Settings
3. All AI-generated files will be here, easy to manage

💡 **Advanced Usage**:
- Run projects are created in `~/.frago/projects/[run_id]/`
- Working Directory doesn't affect Run project location
- Can temporarily switch directory in Console: `cd /path/to/dir`

**Example**:

```
Scenario: You're developing a website project

1. Create project directory: ~/my-website
2. Set Working Directory to: ~/my-website
3. In Console say: "help me generate an index.html"
4. AI creates file at ~/my-website/index.html
```

**Related Questions**: Can't find AI-generated files? (Check Working Directory setting and Workspace)
