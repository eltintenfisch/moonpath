# moonpath

Standalone Python library and HTTP service for Google Cast control on native Ubuntu Linux.

Moonpath wraps [PyChromecast](https://github.com/home-assistant-libs/pychromecast) behind a REST API so other apps (like Nereid) do not need to depend on it directly.

```text
Nereid → HTTP → Moonpath service → PyChromecast → Cast device
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Running the service

```bash
uvicorn moonpath.service:app --host 127.0.0.1 --port 8001
```

Or via systemd (recommended):

```bash
sudo ln -sf /home/rod/code/moonpath/services/moonpath.service /etc/systemd/system/moonpath.service
sudo systemctl daemon-reload
sudo systemctl enable --now moonpath
```

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MOONPATH_PORT` | `8001` | Port to listen on |

## HTTP API

All endpoints accept and return JSON. Pass `X-Request-ID` / `X-Trace-ID` headers for telemetry correlation.

### `GET /health`

```json
{ "status": "ok", "active_connections": ["<uuid>"] }
```

### `GET /devices`

Discovers Cast devices on the network (~5s scan).

```json
{
  "devices": [
    {
      "id": "16cd470e-91cf-46f5-876f-8e8db75d6380",
      "name": "Living Room speaker",
      "host": "192.168.1.50",
      "port": 8009,
      "model": "Chromecast Audio"
    }
  ]
}
```

### `GET /devices/{device_id}/status`

Query params: `host` (optional if cached), `port` (default 8009)

```json
{
  "device_id": "16cd470e-...",
  "device_idle": false,
  "player_state": "PLAYING",
  "content_id": "https://example.com/track.mp3",
  "content_type": "audio/mpeg",
  "current_time": 142.3,
  "duration": 3600.0,
  "stream_type": "BUFFERED",
  "volume_level": 0.5,
  "volume_muted": false
}
```

`player_state` values:

| Value | Meaning |
|-------|---------|
| `PLAYING` | Actively playing |
| `PAUSED` | Paused |
| `BUFFERING` | Starting or buffering |
| `ACTIVE` | Cast app running; media details not yet available |
| `IDLE` | Stopped / no active media |
| `UNKNOWN` | No media session (common when `device_idle` is true) |

### `POST /devices/{device_id}/play-url`

```json
{
  "host": "192.168.1.50",
  "url": "https://example.com/track.mp3",
  "content_type": "audio/mpeg",
  "stream_type": "BUFFERED",
  "position": 3600.0,
  "subtitles_url": "https://example.com/subs.vtt",
  "subtitles_lang": "en-US",
  "replace": false
}
```

`host` is required on first connect; omit once the service has a cached connection. Returns a status object.

### `POST /devices/{device_id}/play-radio`

```json
{ "host": "192.168.1.50", "url": "https://stream.example.com/radio.mp3", "content_type": "audio/mpeg" }
```

### `POST /devices/{device_id}/pause`
### `POST /devices/{device_id}/resume`
### `POST /devices/{device_id}/stop`

Body: `{ "host": "192.168.1.50" }` (optional if cached). Returns a status object.

### `POST /devices/{device_id}/seek`

```json
{ "host": "192.168.1.50", "position": 120.5 }
```

Applies to buffered media only. Returns a status object.

### `POST /devices/{device_id}/volume`

```json
{ "host": "192.168.1.50", "level": 0.5 }
```

`level` must be between 0.0 and 1.0. Returns `{ "volume": { "level": 0.5, "muted": false }, "status": {...} }`.

### `POST /devices/{device_id}/mute`

```json
{ "host": "192.168.1.50", "muted": true }
```

Returns `{ "volume": { "level": 0.5, "muted": true }, "status": {...} }`.

## Error responses

All errors return an appropriate HTTP status code with:

```json
{ "detail": "No device found for id '...'" }
```

| HTTP status | Meaning |
|-------------|---------|
| `400` | Invalid argument |
| `404` | Device not found |
| `409` | Ambiguous device match |
| `503` | Connection failed |
| `502` | Playback failed |
| `500` | Internal error |

## Connection pool

The service maintains one persistent PyChromecast connection per device. Connections are reused across requests, eliminating the mDNS discovery overhead on every command. On a stale connection the service reconnects once automatically before returning an error.

## Nereid integration

Nereid resolves the service URL from the `moonpath_url` DB key, `MOONPATH_URL` env var, or defaults to `http://localhost:8001`.

```typescript
const res = await fetch(`${serviceUrl}/devices/${deviceId}/play-url`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ host, url, content_type: contentType }),
});
```

## CLI

A `moonpath` CLI is still available for manual use and debugging:

```bash
moonpath discover
moonpath status --device-id <uuid> --device-host 192.168.1.50
moonpath play-url --device-id <uuid> --device-host 192.168.1.50 --url "https://example.com/track.mp3"
moonpath pause --device-id <uuid> --device-host 192.168.1.50
```

The CLI is not used by Nereid; it connects and disconnects per command with no connection pooling.

## Target devices

- Google Chromecast Audio
- Atonemo Streamplayer
