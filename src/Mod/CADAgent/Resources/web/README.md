# CAD Agent web UI

The panel is a `QWebEngineView` loading an HTML/JS app that talks to Python over
`QWebChannel`. Two variants ship here:

## 1. `index.html` — vanilla (default, works without any build step)

A single self-contained HTML file with inline JS. This is what
`WebChatPanel.py` loads today, so enabling the web UI (via Preferences →
CAD Agent → Use web UI) works immediately after a CMake rebuild.

## 2. `src/` — React + TypeScript (Vite) upgrade path

Files: `package.json`, `tsconfig.json`, `vite.config.ts`, `src/{main.tsx,App.tsx,bridge.ts,styles.css}`.

To switch to the React build:

```bash
cd src/Mod/CADAgent/Resources/web
npm install
# Create a Vite-style entry that loads src/main.tsx:
cat > index.html <<'EOF'
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>CAD Agent</title>
  <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
</head>
<body>
  <div id="root"></div>
  <script type="module" src="/src/main.tsx"></script>
</body>
</html>
EOF
npm run build
```

Then update `WebChatPanel.py` to load `Resources/web/dist/index.html` instead
of `Resources/web/index.html`. (Or keep both: code checks `dist/` first, falls
back to the vanilla `index.html` if no build exists.)

## Bridge API

Python side: `Bridge.py` exposes one `ChatBridge(QObject)` on the channel as
`bridge`. JS calls slots; Python emits signals.

| Direction    | Name                   | Payload                                  |
|--------------|------------------------|------------------------------------------|
| JS → Python  | `submit(text)`         | user turn                                |
| JS → Python  | `stop()`               | interrupt current turn                   |
| JS → Python  | `decidePermission(id, allowed, reason)` | reply to a pending tool |
| Python → JS  | `assistantText(text)`  | streaming assistant chunk                |
| Python → JS  | `thinkingText(text)`   | extended-thinking preview                |
| Python → JS  | `toolUse(id, name, input_json)` | tool invocation                  |
| Python → JS  | `toolResult(id, content_json, isError)` | tool return              |
| Python → JS  | `permissionRequest(req_id, name, input_json)` | Apply/Reject prompt |
| Python → JS  | `turnComplete(cost_usd)` | end of turn (-1 if unknown)            |
| Python → JS  | `errorText(text)`      | runtime error                            |
| Python → JS  | `systemText(text)`     | system note                              |
| Python → JS  | `bypassChanged(on)`    | permission mode switched                 |

## Dependencies

`QWebEngineView` / `QWebChannel` come from Qt's WebEngine module. On
conda-forge they are packaged with `pyside6`; if the import fails, add
`qt6-webengine` (or `qt-webengine`) to `pixi.toml` under `[dependencies]`.
