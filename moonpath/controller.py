"""Cast device connection and playback control."""

from __future__ import annotations

import logging
import time
from pathlib import PurePosixPath
from urllib.parse import urlparse

import pychromecast
from pychromecast import Chromecast

from moonpath.discovery import DEFAULT_DISCOVERY_TIMEOUT
from moonpath.errors import CastConnectionError
from moonpath.models import CastDevice, PlaybackStatus

logger = logging.getLogger("moonpath")

DEFAULT_PLAYBACK_WAIT_TIMEOUT = 15.0
_ACTIVE_PLAYER_STATES = frozenset({"PLAYING", "PAUSED"})

_CONTENT_TYPES = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/opus",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
}


def guess_content_type(url: str, default: str = "audio/mpeg") -> str:
    """Guess MIME type from a URL path extension."""
    path = urlparse(url).path
    suffix = PurePosixPath(path).suffix.casefold()
    return _CONTENT_TYPES.get(suffix, default)


class CastController:
    """Control a single Google Cast device."""

    def __init__(
        self,
        device: CastDevice,
        *,
        discovery_timeout: float = DEFAULT_DISCOVERY_TIMEOUT,
        connect_timeout: float = 10.0,
    ) -> None:
        self._device = device
        self._discovery_timeout = discovery_timeout
        self._connect_timeout = connect_timeout
        self._cast: Chromecast | None = None
        self._browser = None

    @property
    def device(self) -> CastDevice:
        return self._device

    def connect(self) -> None:
        if self._cast is not None:
            return

        logger.info("Connecting to %s (%s)...", self._device.name, self._device.ip)
        try:
            chromecasts, browser = pychromecast.get_listed_chromecasts(
                friendly_names=[self._device.name],
                discovery_timeout=self._discovery_timeout,
            )
            self._browser = browser
            if not chromecasts:
                raise CastConnectionError(
                    f"Could not find {self._device.name!r} on the network",
                    operation="connect",
                    device_name=self._device.name,
                )
            self._cast = chromecasts[0]
            self._cast.wait(timeout=self._connect_timeout)
        except CastConnectionError:
            self.disconnect()
            raise
        except Exception as exc:
            self.disconnect()
            raise CastConnectionError(
                str(exc),
                operation="connect",
                device_name=self._device.name,
            ) from exc

        logger.info("Connected to %s", self._device.name)

    def play_url(
        self,
        url: str,
        *,
        content_type: str | None = None,
        stream_type: str = "BUFFERED",
    ) -> None:
        self.connect()
        assert self._cast is not None

        resolved_type = content_type or guess_content_type(url)
        logger.info(
            "Playing URL on %s (%s, %s)",
            self._device.name,
            resolved_type,
            stream_type,
        )
        media = self._cast.media_controller
        media.play_media(url, resolved_type, stream_type=stream_type)
        media.block_until_active()

    def play_radio(self, url: str, *, content_type: str | None = None) -> None:
        self.play_url(
            url,
            content_type=content_type or guess_content_type(url, default="audio/mpeg"),
            stream_type="LIVE",
        )

    def pause(self) -> None:
        self.connect()
        assert self._cast is not None
        logger.info("Pausing %s", self._device.name)
        self._cast.media_controller.pause()

    def resume(self) -> None:
        self.connect()
        assert self._cast is not None
        logger.info("Resuming %s", self._device.name)
        self._cast.media_controller.play()

    def stop(self) -> None:
        self.connect()
        assert self._cast is not None
        logger.info("Stopping %s", self._device.name)
        self._cast.media_controller.stop()

    def set_volume(self, level: float) -> None:
        if not 0.0 <= level <= 1.0:
            raise ValueError(f"Volume must be between 0.0 and 1.0, got {level}")

        self.connect()
        assert self._cast is not None
        logger.info("Setting volume on %s to %.2f", self._device.name, level)
        self._cast.set_volume(level)

    def get_status(self) -> PlaybackStatus:
        self.connect()
        assert self._cast is not None

        cast_status = self._cast.status
        media_status = self._cast.media_controller.status
        volume_level = cast_status.volume_level if cast_status else None
        volume_muted = cast_status.volume_muted if cast_status else None

        return PlaybackStatus(
            device_name=self._device.name,
            player_state=getattr(media_status, "player_state", None),
            content_id=getattr(media_status, "content_id", None),
            content_type=getattr(media_status, "content_type", None),
            current_time=getattr(media_status, "current_time", None),
            duration=getattr(media_status, "duration", None),
            stream_type=getattr(media_status, "stream_type", None),
            volume_level=volume_level,
            volume_muted=volume_muted,
        )

    def wait_for_playback(
        self,
        timeout: float = DEFAULT_PLAYBACK_WAIT_TIMEOUT,
        poll_interval: float = 0.5,
    ) -> PlaybackStatus:
        """Wait until playback reaches an active state, then return status."""
        deadline = time.monotonic() + timeout
        status = self.get_status()

        while time.monotonic() < deadline:
            if status.player_state in _ACTIVE_PLAYER_STATES:
                return status
            time.sleep(poll_interval)
            status = self.get_status()

        logger.warning(
            "Playback did not reach an active state within %.0fs (state=%s)",
            timeout,
            status.player_state,
        )
        return status

    def disconnect(self) -> None:
        if self._cast is not None:
            logger.info("Disconnecting from %s", self._device.name)
            self._cast.disconnect()
            self._cast = None

        if self._browser is not None:
            self._browser.stop_discovery()
            self._browser = None


def run_interactive_controls(controller: CastController) -> None:
    """Read simple playback commands from stdin until quit."""
    print(controller.get_status().format())
    print()
    print("Commands: pause | resume | stop | volume <0.0-1.0> | status | quit")

    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue

        parts = line.split()
        command = parts[0].casefold()

        try:
            if command in {"quit", "q", "exit"}:
                break
            if command == "pause":
                controller.pause()
            elif command in {"resume", "play"}:
                controller.resume()
            elif command == "stop":
                controller.stop()
            elif command == "status":
                print(controller.get_status().format())
                continue
            elif command == "volume":
                if len(parts) != 2:
                    print("Usage: volume <0.0-1.0>")
                    continue
                controller.set_volume(float(parts[1]))
            else:
                print("Unknown command. Use: pause | resume | stop | volume <0.0-1.0> | status | quit")
                continue
        except Exception as exc:
            from moonpath.errors import log_failure

            log_failure(
                exc,
                operation=f"interactive:{command}",
                device_name=controller.device.name,
            )
            continue

        print(controller.get_status().format())
