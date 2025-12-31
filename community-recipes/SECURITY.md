# Community Recipe Security Policy

This document defines the security requirements for community recipes. All submitted recipes MUST comply with these rules.

## 1. Network Access

| Rule | Description |
|------|-------------|
| **Allowed** | Access to legitimate websites and APIs |
| **Prohibited** | Illegal content, adult/18+ content, gambling sites |
| **Prohibited** | Brute-force attacks, DDoS, rate-limit abuse |
| **Prohibited** | Accessing URLs without clear purpose in recipe logic |

## 2. Filesystem Access

| Path | Permission |
|------|------------|
| `$OUTPUT_DIR` (user specified) | Read/Write |
| `/tmp/frago-*` | Read/Write (temporary) |
| `~/.frago/` | **Prohibited** (frago internal only) |
| `~/.claude/` | **Prohibited** (Claude Code internal) |
| `~/.ssh/`, `~/.aws/`, `~/.gnupg/` | **Prohibited** (sensitive credentials) |
| `/etc/`, `/usr/`, `/var/` | **Prohibited** (system directories) |
| User home directory | Read only with explicit user consent |

**Principle**: Recipes should only access paths explicitly provided by user input or documented in recipe metadata.

## 3. Data Security

**Prohibited data exfiltration**:
- API keys, tokens, passwords (`*_KEY`, `*_TOKEN`, `*_SECRET`)
- Session data from `~/.frago/sessions/`
- Configuration files from `~/.frago/config.json`
- Any file outside the recipe's declared scope

**Prohibited behaviors**:
- Sending user data to undeclared third-party servers
- Collecting system information (hostname, username, IP) without purpose
- Base64/hex encoding data before transmission (obfuscation)

## 4. Command Execution

### Prohibited (Immediate rejection)

| Command | Reason |
|---------|--------|
| `rm -rf /`, `rm -rf ~` | Destructive deletion |
| `sudo`, `su` | Privilege escalation |
| `chmod 777` | Insecure permissions |
| `curl\|sh`, `wget\|sh` | Download and execute |
| `eval()`, `exec()` | Dynamic code execution |
| `nc -l`, `ncat -l`, reverse shells | Backdoor/remote access |
| `os.system(shell=True)` | Shell injection risk |

### Warning (User will be warned, UI shows red highlight)

| Command | Reason |
|---------|--------|
| `brew install`, `apt install`, `yum install` | Installing unknown software |
| `npm install -g`, `pip install`, `gem install` | Global package installation |
| `chmod` (non-777) | Permission modification |
| `rm`, `rmdir` (non-destructive) | File/directory deletion |
| `curl`, `wget` (standalone) | Network download |
| `kill`, `pkill`, `killall` | Process termination |
| `crontab`, `launchctl`, `systemctl` | Scheduled task modification |
| `open`, `xdg-open`, `start` | Opening external applications |
| `git clone`, `git pull` | Fetching external code |

### Safe (Allowed)

| Command | Notes |
|---------|-------|
| `yt-dlp`, `ffmpeg`, `imagemagick` | Media processing tools |
| `jq`, `yq`, `sed`, `awk` | Text processing |
| `cat`, `head`, `tail`, `grep` | File reading |
| `echo`, `printf` | Output |
| `mkdir`, `cp`, `mv` (to $OUTPUT_DIR) | File operations in allowed paths |

**Principle**: Commands must be static and predictable. No dynamic command construction from user input without sanitization. No installing software from unknown sources.

> **Note**: The commands listed above are examples, not an exhaustive list. Any command with similar risk characteristics will be treated accordingly.

### Declaring Warnings in recipe.md

Recipes using **Warning-level** operations MUST declare them in the `warnings` field. This enables the web UI to display appropriate warnings to users before execution.

```yaml
---
name: my-recipe
# ... other fields
warnings:
  - type: network_download
    command: curl
    reason: "Downloads video metadata from YouTube"
  - type: file_deletion
    command: rm
    reason: "Removes temporary files after processing"
---
```

**Warning types**:
- `software_install` - Installing packages (brew, apt, npm, pip)
- `network_download` - Downloading files (curl, wget)
- `file_deletion` - Deleting files (rm, rmdir)
- `permission_change` - Modifying permissions (chmod)
- `process_control` - Managing processes (kill, pkill)
- `scheduled_task` - Modifying cron/launchctl
- `external_app` - Opening external applications
- `code_fetch` - Fetching code from repositories

## 5. Dependencies

**Python recipes** MUST use [PEP 723](https://peps.python.org/pep-0723/) inline script metadata:

```python
# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "requests>=2.28.0",
#   "pyyaml>=6.0",
# ]
# ///
```

**Prohibited**:
- `pip install` or `uv add` during runtime
- Downloading and executing remote scripts
- Dependencies from non-PyPI sources without justification

## 6. Environment Variables

| Access | Policy |
|--------|--------|
| Recipe-defined variables (declared in `recipe.md`) | Allowed |
| `PATH`, `HOME`, `USER` | Allowed (read-only) |
| `*_API_KEY`, `*_TOKEN`, `*_SECRET` | **Prohibited** unless declared |
| `ANTHROPIC_*`, `OPENAI_*`, `AWS_*` | **Prohibited** |

**Principle**: Recipes must declare all required environment variables in `recipe.md`. Undeclared access is a violation.

## 7. Output Handling

- Output must go to declared `output_targets` only
- No silent file creation outside `$OUTPUT_DIR`
- No clipboard access without `clipboard` in `output_targets`
- No network transmission without `network` declaration

## 8. Code Quality

- No obfuscated or minified code
- No encoded payloads (base64, hex) without clear purpose
- Comments required for non-obvious operations
- Error handling must not expose sensitive information

---

## Violation Severity

| Level | Action |
|-------|--------|
| **Critical** | Immediate rejection, author may be blocked |
| **High** | Rejection, requires fix before re-submission |
| **Medium** | Requires justification in PR description |
| **Low** | Warning, should be addressed |

## Reporting Security Issues

If you discover a security vulnerability in a community recipe:
1. Do NOT open a public issue
2. Email: [security contact] or open a private security advisory
3. Include: recipe name, vulnerability description, reproduction steps

---

*Last updated: 2025-12*
