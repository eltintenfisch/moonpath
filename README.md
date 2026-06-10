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

### Play URL (file, podcast)

```bash
moonpath play-url --device-id <uuid> --url "https://example.com/track.mp3" --json
```

`--content-type` is optional (inferred from URL extension).

### Play radio

```bash
moonpath play-radio --device-id <uuid> --url "https://stream.example.com/radio.mp3" --json
```

### Transport and volume

```bash
moonpath pause  --device-id <uuid> --json
moonpath resume --device-id <uuid> --json
moonpath stop   --device-id <uuid> --json
moonpath volume --device-id <uuid> --level 0.5 --json
```

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success — parse JSON from stdout |
| non-zero | Failure — parse JSON from stdout if `--json`, details also on stderr |

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

## Python library (optional)

Moonpath can also be used as a Python library. The CLI is the stable integration boundary for Nereid.

```python
from moonpath import CastController, discover_devices, select_device
```

## Target devices

- Google Chromecast Audio
- Atonemo Streamplayer
