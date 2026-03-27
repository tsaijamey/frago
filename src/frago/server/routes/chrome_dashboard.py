"""Chrome landing page dashboard.

Serves a lightweight HTML dashboard at /chrome/dashboard that shows
the current tab group state. The page auto-refreshes via polling
the tab group state file.
"""

import json
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter()

STATE_FILE = Path.home() / ".frago" / "chrome" / "tab_groups.json"

DASHBOARD_HTML = """\
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>frago</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0a0a;color:#e0e0e0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;padding:48px}
h1{font-size:36px;font-weight:700;margin-bottom:8px}
.subtitle{color:#888;font-size:16px;margin-bottom:40px}
#groups{display:flex;flex-direction:column;gap:16px}
.group{background:#161616;border:1px solid #2a2a2a;border-radius:8px;padding:16px}
.group-title{font-size:18px;font-weight:600;margin-bottom:8px;color:#50c878}
.tab{padding:4px 0;font-size:13px;color:#aaa;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tab .origin{color:#666;margin-left:8px}
.empty{color:#555;font-style:italic}
</style></head>
<body>
<h1>frago</h1>
<p class="subtitle">is controlling your Chrome</p>
<div id="groups"><p class="empty">No active tab groups</p></div>
<script>
function render(data) {
  var c = document.getElementById('groups');
  if (!data || !data.groups || Object.keys(data.groups).length === 0) {
    c.innerHTML = '<p class="empty">No active tab groups</p>';
    return;
  }
  var html = '';
  for (var name in data.groups) {
    var g = data.groups[name];
    html += '<div class="group"><div class="group-title">' + name + ' (' + Object.keys(g.tabs).length + ' tabs)</div>';
    for (var tid in g.tabs) {
      var t = g.tabs[tid];
      html += '<div class="tab">' + (t.title || t.url) + '<span class="origin">' + t.origin + '</span></div>';
    }
    html += '</div>';
  }
  c.innerHTML = html;
}

// Also support push from CDP
window.__frago_update_dashboard__ = render;

// Poll for updates every 3s
async function poll() {
  try {
    var resp = await fetch('/chrome/dashboard/state');
    if (resp.ok) render(await resp.json());
  } catch(e) {}
  setTimeout(poll, 3000);
}
poll();
</script></body></html>
"""


@router.get("/dashboard", response_class=HTMLResponse)
async def chrome_dashboard():
    """Serve the Chrome tab group dashboard page."""
    return DASHBOARD_HTML


@router.get("/dashboard/state")
async def chrome_dashboard_state():
    """Return current tab group state as JSON."""
    if not STATE_FILE.exists():
        return JSONResponse({"groups": {}})
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return JSONResponse(data)
    except Exception:
        return JSONResponse({"groups": {}})
