---
id: troubleshooting
title: Troubleshooting
category: troubleshooting
order: 5
version: 0.38.1
last_updated: 2026-01-17
tags:
  - troubleshooting
  - errors
  - debugging
  - chrome
---

# Troubleshooting

## Q: Why is there no output after sending messages in Console?

**A**: Four most common reasons: API Key not configured, task still executing, Chrome not started, or task description unclear. Check in order.

**Troubleshooting Steps**:

### 1. Check API Key Configuration (Most Common)

**Symptom**: After sending message, nothing appears, or shows Authentication error

**Solution**:
1. Settings → General
2. Confirm API Key is filled in
3. Key format: `sk-ant-...` (Anthropic) or third-party format
4. Test: Send simple message "hello"

**Related Questions**: Where do I enter API Key? (See Configuration chapter)

---

### 2. Task is Executing (Be Patient)

**Symptom**: After sending message, shows "Connecting..." or spinning, but no output

**Reason**: AI might be:
- 🌐 Visiting webpage (slow page load)
- 🔍 Exploring solution (first-time tasks need thinking)
- 📸 Waiting for page to render

**Solution**:
- ⏰ Wait 30 seconds to 1 minute
- 👀 Watch status in upper right: Running/Thinking
- 💡 Complex webpages may take longer

**Tip**: First-time execution of new task types is slower than repeats—this is normal.

---

### 3. Chrome Not Connected (CDP Not Started)

**Symptom**: Task errors with "Chrome not connected" or "CDP connection failed"

**Reason**: frago needs Chrome DevTools Protocol (CDP) to operate browser

**Solution**:
1. **Start Chrome** (recommended method):
   ```bash
   # Command line start (auto-enables CDP)
   uv run frago chrome start
   ```

2. **Check if Chrome is started**:
   - Look for Chrome icon in taskbar/Dock
   - Opened Chrome should show "frago is controlling..." banner

3. **Manual start** (advanced):
   ```bash
   # Mac/Linux
   /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
     --remote-debugging-port=9222 --user-data-dir=~/.frago/chrome_profile

   # Windows
   "C:\Program Files\Google\Chrome\Application\chrome.exe" \
     --remote-debugging-port=9222 --user-data-dir=%USERPROFILE%\.frago\chrome_profile
   ```

**Related Questions**: Chrome not connected detailed troubleshooting (see next FAQ)

---

### 4. Task Description Unclear

**Symptom**: AI responds but says "don't understand" or "need more information"

**Reason**: Task description too vague

**Examples**:
```
❌ Bad: "Help me process this"
✅ Good: "Help me extract product titles and prices from https://example.com"

❌ Bad: "Automate this website"
✅ Good: "Every day at 9am visit https://news.com, extract headlines, email me"
```

**Related Questions**: How to extract webpage data? (See Usage Tips chapter)

---

## Q: Console shows "Chrome not connected", what to do?

**A**: Follow these steps in order: Start Chrome → Check port → Check config → Restart service.

### Quick Fix (90% of cases)

**1. Start Chrome using frago command**
```bash
uv run frago chrome start
```

This will automatically:
- ✅ Start Chrome with CDP
- ✅ Use correct port (9222)
- ✅ Use frago-specific profile

**2. Verify connection**
- Browser top bar shows: "frago is controlling this browser"
- Console should work normally

---

### Detailed Troubleshooting Steps

**Step 1: Confirm Chrome process exists**

```bash
# Mac/Linux
ps aux | grep chrome | grep remote-debugging-port

# Windows (PowerShell)
Get-Process chrome | Where-Object {$_.CommandLine -like "*remote-debugging-port*"}
```

If no output → Chrome not started in CDP mode, run `uv run frago chrome start`

---

**Step 2: Check if port 9222 is occupied**

```bash
# Mac/Linux
lsof -i :9222

# Windows (PowerShell)
netstat -ano | findstr :9222
```

**If port is occupied**:
1. Kill the occupying process
2. Or modify frago config to use different port (advanced)

---

**Step 3: Check firewall**

**Mac**: System Settings → Security → Firewall, ensure Chrome is allowed

**Windows**: Control Panel → Windows Defender Firewall → Allow apps, check Chrome

---

**Step 4: Clean Chrome profile (last resort)**

```bash
# Backup old profile
mv ~/.frago/chrome_profile ~/.frago/chrome_profile.bak

# Restart Chrome
uv run frago chrome start
```

---

### Advanced Configuration (Optional)

**Custom CDP port** (if 9222 is occupied):

Edit `~/.frago/config.json`:
```json
{
  "chrome": {
    "cdp_port": 9333  // Change to another port
  }
}
```

Then restart frago service.

---

**Common Error Messages**:

| Error Message | Cause | Solution |
|---------------|-------|----------|
| `Connection refused` | Chrome not started | `frago chrome start` |
| `Port 9222 in use` | Port occupied | Kill process or change port |
| `Timeout connecting` | Firewall blocking | Check firewall settings |
| `Protocol error` | Chrome version too old | Update Chrome to latest |

---

## Q: I see a task showing "Error" in Tasks, how to debug?

**A**: Click the task to view detailed logs, take corresponding solutions based on error type. Most errors can be located by viewing execution steps.

### View Error Details

**Step 1: Open task details**
1. Tasks page
2. Click task showing "Error"
3. View "Execution Steps" section

**Step 2: Locate error location**
- 🔴 Red-marked steps = where error occurred
- 📝 Expand to view detailed error message
- ⚠️ Note Tool Call type (Read/Bash/CDP, etc.)

---

### Common Error Types & Solutions

### 1. File/Path Errors

**Error message**:
```
FileNotFoundError: [Errno 2] No such file or directory: '/path/to/file.txt'
```

**Cause**: File doesn't exist or path is wrong

**Solution**:
- ✅ Check if file exists
- ✅ Confirm path is correct (absolute vs relative)
- ✅ Check Working Directory setting

---

### 2. Permission Errors

**Error message**:
```
PermissionError: [Errno 13] Permission denied: '/System/...'
```

**Cause**: No read/write permission

**Solution**:
- ✅ Avoid system-protected directories
- ✅ Change Working Directory to permitted location
- ✅ Check file permissions: `ls -l filename`

---

### 3. Webpage Element Not Found

**Error message**:
```
selector not found: .product-title
TimeoutError: Waiting for selector .product-title failed
```

**Cause**:
- Webpage structure changed
- Element loads slowly
- Selector is wrong

**Solution**:
```
Ask AI to re-explore:
"Please revisit https://example.com, check page structure, update extraction logic"
```

---

### 4. API/Network Errors

**Error message**:
```
requests.exceptions.ConnectionError
HTTPError: 403 Forbidden
```

**Cause**: Network issues or blocked by website

**Solution**:
- ✅ Check network connection
- ✅ Website may have anti-scraping mechanisms
- ✅ Try adding delays or simulating real user behavior

---

### 5. Chrome/CDP Errors

**Error message**:
```
chrome not connected
CDP connection error
```

**Solution**: See previous FAQ "Chrome not connected what to do?"

---

### Debugging Techniques

**1. Copy error message and ask AI**

In Console:
```
I encountered this error while executing task:
[paste complete error message]

Please help me analyze the cause and provide solution
```

**2. View complete logs**

```bash
# View session logs from command line
uv run frago session view [session_id]
```

**3. Simplify and retry task**

Break complex task into parts:
```
Original task: "Visit site → Login → Extract data → Save"
Split:
  Step 1: "Visit site and login" (verify this step OK first)
  Step 2: "Extract data"
  Step 3: "Save data"
```

**4. Screenshot for debugging**

```
"Please screenshot current page state, let me see what's wrong"
```

---

### Error Type Quick Reference

| Error Keyword | Common Cause | Quick Fix |
|---------------|--------------|-----------|
| `FileNotFoundError` | File doesn't exist | Check path |
| `PermissionError` | No permission | Change Working Directory |
| `selector not found` | Element not found | Re-explore page |
| `ConnectionError` | Network issue | Check network |
| `chrome not connected` | CDP not connected | `frago chrome start` |
| `Authentication failed` | API Key error | Reconfigure Key |
| `TimeoutError` | Wait timeout | Increase wait time or check webpage |

---

### Submit Bug Report (Last Resort)

If none of the above works:

1. **Collect information**:
   - Complete error message
   - Task description
   - frago version: `uv run frago --version`
   - Operating system

2. **Submit Issue**:
   - GitHub: https://github.com/your-org/frago/issues
   - Include above information
   - If possible, provide reproduction steps

**Related Questions**: What if Authentication failed? (See Configuration chapter)
