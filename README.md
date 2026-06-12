# moonpath

Standalone Python library and CLI for Google Cast control on native Ubuntu Linux.

Moonpath wraps [PyChromecast](https://github.com/home-assistant-libs/pychromecast) behind a small API so other apps (like Nereid) do not need to depend on it directly.

```text
Nereid → moonpath CLI → PyChromecast → Cast device
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

This installs the `moonpath` command on your PATH.

## CLI (Nereid integration boundary)

Nereid calls Moonpath via `child_process.execFile`. Use `--json` so **stdout is JSON only**; logs go to **stderr**.

### Discover devices

```bash
moonpath discover --json
```

```json
{
  "ok": true,
  "operation": "discover",
  "devices": [
    {
      "id": "16cd470e-91cf-46f5-876f-8e8db75d6380",
      "name": "Living Room speaker",
      "host": "192.168.1.50",
      "model": "Chromecast Audio",
      "port": 8009
    }
  ]
}
```

Device `id` is the Cast UUID. Use it for all other commands via `--device-id`.

### Status

```bash
moonpath status --device-id <uuid> --json
```

### Faster commands with a cached device address

After `discover`, callers may pass `--device-host` and optionally `--device-port` on any
`--device-id` command to connect directly and **skip the 8s mDNS scan**:

```bash
moonpath status --device-id <uuid> --device-host 192.168.1.50 --device-port 8009 --json
moonpath play-url --device-id <uuid> --device-host 192.168.1.50 --url "https://example.com/track.mp3" --json
```

If `--device-host` is omitted, moonpath discovers devices as before.

`status.player_state` values:

| Value | Meaning |
|-------|---------|
| `PLAYING` | Actively playing |
| `PAUSED` | Paused |
| `BUFFERING` | Starting or buffering |
| `ACTIVE` | Cast app running; media details not yet available |
| `IDLE` | Stopped / no active media |
| `UNKNOWN` | No media session (common when `device_idle` is true) |

Other useful `status` fields: `device_idle`, `content_id`, `stream_type` (`BUFFERED` / `LIVE`), `volume_level`, `volume_muted`.

### Play URL (file, podcast)

```bash
moonpath play-url --device-id <uuid> --url "https://example.com/track.mp3" --json
moonpath play-url --device-id <uuid> --url "https://example.com/book.m4b" --position 3600 --json
```

`--content-type` is optional (inferred from URL extension). `--position` starts buffered media at that offset (seconds).

### Play radio

```bash
moonpath play-radio --device-id <uuid> --url "https://stream.example.com/radio.mp3" --json
```

### Transport and volume

```bash
moonpath pause  --device-id <uuid> --json
moonpath resume --device-id <uuid> --json
moonpath stop   --device-id <uuid> --json
moonpath seek   --device-id <uuid> --position 120.5 --json
moonpath volume --device-id <uuid> --level 0.5 --json
moonpath mute   --device-id <uuid> --muted true --json
```

`seek` applies to buffered media (tracks, podcasts). It fails for live radio streams (`stream_type: LIVE`).

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success — `ok: true` JSON on stdout |
| non-zero | Failure — `ok: false` JSON on stdout (when `--json`), logs on stderr |

On failure, Moonpath **always exits non-zero**, even when stdout contains valid error JSON. Node `execFile` will reject; read JSON from `err.stdout`.

### Error JSON

```json
{
  "ok": false,
  "operation": "play-url",
  "error": {
    "type": "DeviceNotFound",
    "message": "No device found for id '...'"
  }
}
```

Error types: `DeviceNotFound`, `AmbiguousDevice`, `ConnectionFailed`, `PlaybackFailed`, `InvalidArgument`, `InternalError`.

### Nereid (Node.js) caller

Binary resolution:

```javascript
const MOONPATH = config.moonpathBin ?? process.env.MOONPATH_BIN ?? "moonpath";
```

Wrapper (`execFile` rejects on non-zero exit):

```javascript
const { execFile } = require("child_process");
const { promisify } = require("util");
const execFileAsync = promisify(execFile);

async function moonpath(...args) {
  let stdout;
  try {
    ({ stdout } = await execFileAsync(MOONPATH, [...args, "--json"]));
  } catch (e) {
    stdout = e.stdout ?? "";
    if (!stdout) throw e;
  }
  const result = JSON.parse(stdout);
  if (!result.ok) {
    const err = new Error(result.error.message);
    err.code = result.error.type;
    err.operation = result.operation;
    throw err;
  }
  return result;
}
```

Is something playing?

```javascript
const s = result.status;
const playing =
  !s.device_idle &&
  ["PLAYING", "PAUSED", "BUFFERING", "ACTIVE"].includes(s.player_state);
```

## Python library (optional)

Moonpath can also be used as a Python library. The CLI is the stable integration boundary for Nereid.

```python
from moonpath import CastController, discover_devices, select_device
```

## Target devices

- Google Chromecast Audio
- Atonemo Streamplayer
