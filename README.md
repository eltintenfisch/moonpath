# moonpath

Standalone Python library and CLI for Google Cast control on native Ubuntu Linux.

Moonpath wraps [PyChromecast](https://github.com/home-assistant-libs/pychromecast) behind a small API so other projects (like Nereid) do not need to depend on it directly.

```text
Nereid → moonpath → PyChromecast → Cast device
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Library usage

```python
from moonpath import CastController, discover_devices

devices = discover_devices()
controller = CastController(devices[0])

controller.play_url("https://example.com/test.mp3", content_type="audio/mpeg")
controller.pause()
controller.resume()
controller.stop()
controller.set_volume(0.5)
status = controller.get_status()
controller.disconnect()
```

## CLI usage

Run from the repository root:

```bash
python cli/discover.py

python cli/play_url.py --device "Living Room speaker" --url "https://example.com/test.mp3"

python cli/play_radio.py --device "Living Room speaker" --url "RADIO_STREAM_URL"

python cli/status.py --device "Living Room speaker"
```

`play_url.py` and `play_radio.py` start playback, print status, then accept simple interactive commands:

`pause` | `resume` | `stop` | `volume <0.0-1.0>` | `status` | `quit`

Device names are matched case-insensitively by substring. If multiple devices match, the CLI reports an error.

## Target devices

- Google Chromecast Audio
- Atonemo Streamplayer
