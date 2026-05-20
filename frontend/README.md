# Frontend — Web Chat UI

Single-page web UI that connects to the backend via WebSocket and renders
streaming chat with tool-call visualizations.

## How it works

The frontend is a standalone `index.html` (HTML + CSS + JS, no build step).
It connects to `ws://localhost:8765` and exchanges JSON messages with the
backend's WebSocket server.

### Protocol

**Client sends:**
```json
{"content": "What's the weather in Tokyo?"}
```

**Server streams events:**

| Event type    | Description                                      |
|---------------|--------------------------------------------------|
| `text`        | Streamed LLM text token                          |
| `tool_start`  | Tool call initiated (name + args)                |
| `status`      | Status message (e.g. "Looking up weather...")     |
| `tool_result` | Parsed tool result (weather card or research card)|
| `error`       | Error from API or LLM                            |
| `done`        | Turn complete                                    |

> Note: cancellation is CLI-only (SIGINT). The WebSocket server does not emit
> a `cancelled` event and the web UI has no cancel button.

### Features

- Streaming text display with typing indicator
- Weather cards with temperature, condition, humidity
- Research cards with topic, summary, sources, cache/freshness status
- Rate-limit status indicator in the status bar
- Connection state with auto-reconnect on disconnect
- Dark mode by default with light mode toggle
- Responsive layout

## Running

```bash
# 1. Start the backend WebSocket server
python -m backend.chat --serve

# 2. Serve the frontend (separate terminal)
python -m http.server 8000 --directory frontend
# then visit http://localhost:8000
```
