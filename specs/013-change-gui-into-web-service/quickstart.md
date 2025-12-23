# Quickstart: Web Service Based GUI

**Date**: 2025-12-23
**Feature**: 013-change-gui-into-web-service

## Prerequisites

- Python 3.9+
- Modern browser (Chrome, Firefox, Edge, Safari)
- Existing Frago installation

## Quick Start

### 1. Start the Web Server

```bash
frago serve
```

This will:
1. Start the HTTP server on `127.0.0.1:8080`
2. Open your default browser automatically
3. Display the Frago GUI

### 2. Custom Port

```bash
frago serve --port 3000
```

### 3. Without Auto-Open

```bash
frago serve --no-open
```

Then manually open `http://127.0.0.1:8080` in your browser.

### 4. Backward Compatibility

The existing `--gui` flag continues to work:

```bash
frago --gui
# Equivalent to: frago serve --open
```

## Development Setup

### Backend Changes

New module: `src/frago/server/`

```
src/frago/server/
├── __init__.py
├── app.py           # FastAPI application
├── routes/
│   ├── recipes.py   # Recipe endpoints
│   ├── tasks.py     # Task endpoints
│   ├── config.py    # Configuration endpoints
│   └── system.py    # System status endpoints
├── websocket.py     # WebSocket manager
└── dependencies.py  # FastAPI dependencies
```

### Frontend Changes

Update API client: `src/frago/gui/frontend/src/api/`

```typescript
// Before (pywebview)
const result = await window.pywebview.api.get_recipes();

// After (HTTP)
const result = await fetch('/api/recipes').then(r => r.json());
```

### Dependencies

Add to `pyproject.toml`:

```toml
dependencies = [
    # ... existing deps ...
    "fastapi>=0.100.0",
    "uvicorn[standard]>=0.23.0",
]
```

## API Usage Examples

### List Recipes

```bash
curl http://127.0.0.1:8080/api/recipes
```

### Run a Recipe

```bash
curl -X POST http://127.0.0.1:8080/api/recipes/my-recipe/run \
  -H "Content-Type: application/json" \
  -d '{"params": {"key": "value"}}'
```

### Get Task Status

```bash
curl http://127.0.0.1:8080/api/tasks/{task_id}
```

### WebSocket Connection

```javascript
const ws = new WebSocket('ws://127.0.0.1:8080/ws');

ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  console.log('Received:', message.type, message.payload);
};
```

## Migration Notes

### For Users

- `frago --gui` continues to work exactly as before
- New option: `frago serve` for explicit web server mode
- No system dependencies needed (no GTK/WebView2)

### For Developers

- All `FragoGuiApi` methods are now HTTP endpoints
- WebSocket replaces the polling-based session sync
- Frontend uses `fetch()` instead of `window.pywebview.api`

## Troubleshooting

### Port Already in Use

```bash
# Find and use next available port
frago serve --port 8081
```

### Browser Doesn't Open

If the browser doesn't open automatically, check the console for the URL and open it manually.

### Connection Issues

- Ensure the server is running (`frago serve`)
- Check if the port is accessible: `curl http://127.0.0.1:8080/api/status`
- Frontend should show reconnection UI if connection is lost
