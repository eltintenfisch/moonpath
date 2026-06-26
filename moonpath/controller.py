"""Cast device connection and playback control."""

from __future__ import annotations

import logging
import time
from pathlib import PurePosixPath
from urllib.parse import urlparse
from uuid import UUID

import pychromecast
from pychromecast import Chromecast
from pychromecast.error import RequestFailed

from moonpath.discovery import DEFAULT_DISCOVERY_TIMEOUT
from moonpath.errors import CastConnectionError
from moonpath.models import CastDevice, PlaybackStatus

logger = logging.getLogger("moonpath")

DEFAULT_PLAYBACK_WAIT_TIMEOUT = 15.0
DEFAULT_SYNC_TIMEOUT = 5.0
_ACTIVE_PLAYER_STATES = frozenset({"PLAYING", "PAUSED", "BUFFERING", "ACTIVE"})
_HLS_CONTENT_TYPES = frozenset(
    {
        "application/vnd.apple.mpegurl",
        "application/x-mpegurl",
        "audio/mpegurl",
        "audio/x-mpegurl",
    },
)
HLS_PLAYBACK_WAIT_TIMEOUT = 30.0

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


def is_video_content_type(content_type: str) -> bool:
    return content_type.casefold().startswith("video/")


def guess_content_type(url: str, default: str = "audio/mpeg") -> str:
    """Guess MIME type from a URL path extension."""
    path = urlparse(url).path
    suffix = PurePosixPath(path).suffix.casefold()
    return _CONTENT_TYPES.get(suffix, default)


def is_hls_url(url: str, content_type: str | None = None) -> bool:
    resolved = (content_type or guess_content_type(url)).casefold()
    if resolved in _HLS_CONTENT_TYPES:
        return True
    return PurePosixPath(urlparse(url).path).suffix.casefold() == ".m3u8"


def normalize_player_state(
    *,
    device_idle: bool,
    player_state: str | None,
    media_session_id: int | None,
) -> str | None:
    """Map Default Media Receiver quirks to states Nereid can treat as active."""
    if device_idle:
        return player_state
    if media_session_id is not None and player_state in (None, "UNKNOWN", "IDLE"):
        return "BUFFERING"
    if player_state in (None, "UNKNOWN"):
        return "ACTIVE"
    return player_state


class CastController:
    """Control a single Google Cast device."""

    def __init__(
        self,
        device: CastDevice,
        *,
        discovery_timeout: float = DEFAULT_DISCOVERY_TIMEOUT,
        connect_timeout: float = 10.0,
        sync_timeout: float = DEFAULT_SYNC_TIMEOUT,
    ) -> None:
        self._device = device
        self._discovery_timeout = discovery_timeout
        self._connect_timeout = connect_timeout
        self._sync_timeout = sync_timeout
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
            if self._device.uuid:
                self._cast = pychromecast.get_chromecast_from_host(
                    (
                        self._device.ip,
                        self._device.port,
                        UUID(self._device.uuid),
                        self._device.model,
                        self._device.name,
                    ),
                    timeout=self._connect_timeout,
                )
            else:
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
            self._sync_cast_state()
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

    def _sync_cast_state(self) -> None:
        """Refresh receiver and media state, including orphaned playback sessions."""
        assert self._cast is not None
        cast = self._cast
        receiver = cast.socket_client.receiver_controller

        cast.wait(timeout=self._connect_timeout)
        receiver.update_status()
        cast.status_event.wait(timeout=self._sync_timeout)

        if cast.is_idle:
            return

        media = cast.media_controller
        deadline = time.monotonic() + self._sync_timeout
        while time.monotonic() < deadline:
            media.update_status()
            media.block_until_active(timeout=0.5)
            status = media.status
            if status is None:
                time.sleep(0.2)
                continue
            if status.media_session_id is not None:
                return
            if status.player_state not in (None, "UNKNOWN"):
                return
            time.sleep(0.2)

    def play_url(
        self,
        url: str,
        *,
        content_type: str | None = None,
        stream_type: str = "BUFFERED",
        start_position: float | None = None,
        subtitles_url: str | None = None,
        subtitles_lang: str = "en-US",
        replace_in_place: bool = False,
    ) -> None:
        self.connect()
        assert self._cast is not None

        resolved_type = content_type or guess_content_type(url)
        current_time = None
        if start_position is not None and start_position > 0:
            current_time = float(start_position)

        if not replace_in_place:
            self._prepare_for_new_media()
            if not subtitles_url and is_video_content_type(resolved_type):
                self._reset_receiver_before_subtitle_free_video()

        subtitle_detail = (
            f", subtitles={subtitles_url}"
            if subtitles_url
            else ", no subtitles"
            if is_video_content_type(resolved_type)
            else ""
        )
        logger.info(
            "Playing URL on %s (%s, %s%s%s)",
            self._device.name,
            resolved_type,
            stream_type,
            f", start={current_time:.1f}s" if current_time is not None else "",
            subtitle_detail,
        )
        media = self._cast.media_controller
        if subtitles_url:
            media.play_media(
                url,
                resolved_type,
                stream_type=stream_type,
                current_time=current_time,
                subtitles=subtitles_url,
                subtitles_lang=subtitles_lang,
                subtitles_mime="text/vtt",
            )
        else:
            media.play_media(
                url,
                resolved_type,
                stream_type=stream_type,
                current_time=current_time,
            )
        media.block_until_active(timeout=self._connect_timeout)

    def _prepare_for_new_media(self) -> None:
        """Stop the current Cast session so a new play replaces what's on the TV."""
        assert self._cast is not None
        self._sync_cast_state()
        cast = self._cast
        if cast.is_idle:
            return

        media = cast.media_controller
        logger.info("Replacing current media on %s", self._device.name)
        try:
            if media.status and media.status.media_session_id is not None:
                media.stop()
                time.sleep(0.3)
                self._sync_cast_state()
                if cast.is_idle:
                    return
        except RequestFailed as exc:
            logger.warning(
                "Media stop failed on %s before new playback: %s",
                self._device.name,
                exc,
            )

        logger.info("Quitting receiver on %s for new playback", self._device.name)
        try:
            cast.quit_app()
            time.sleep(0.3)
        except Exception as exc:
            logger.warning(
                "quit_app failed on %s before new playback: %s",
                self._device.name,
                exc,
            )
        self._sync_cast_state()

    def _reset_receiver_before_subtitle_free_video(self) -> None:
        """Tear down the Cast receiver so a direct film switch drops prior subtitle tracks."""
        assert self._cast is not None
        self._sync_cast_state()
        cast = self._cast
        if cast.is_idle:
            return

        media = cast.media_controller
        logger.info("Resetting %s receiver before subtitle-free video load", self._device.name)
        try:
            if media.status and media.status.media_session_id is not None:
                media.stop()
        except RequestFailed as exc:
            logger.warning(
                "Media stop failed on %s before subtitle-free load: %s",
                self._device.name,
                exc,
            )

        time.sleep(0.3)
        self._sync_cast_state()
        if cast.is_idle:
            return

        logger.info("Quitting media receiver on %s", self._device.name)
        cast.quit_app()
        time.sleep(0.5)
        self._sync_cast_state()

    def play_radio(self, url: str, *, content_type: str | None = None) -> None:
        self.play_url(
            url,
            content_type=content_type or guess_content_type(url, default="audio/mpeg"),
            stream_type="LIVE",
        )

    def pause(self) -> None:
        self.connect()
        assert self._cast is not None
        self._sync_cast_state()
        logger.info("Pausing %s", self._device.name)
        self._cast.media_controller.pause()

    def resume(self) -> None:
        self.connect()
        assert self._cast is not None
        self._sync_cast_state()
        logger.info("Resuming %s", self._device.name)
        self._cast.media_controller.play()

    def seek(self, position: float) -> None:
        if position < 0:
            raise ValueError(f"Position must be >= 0, got {position}")

        self.connect()
        assert self._cast is not None
        self._sync_cast_state()
        media = self._cast.media_controller
        status = media.status

        if status and getattr(status, "stream_type", None) == "LIVE":
            raise ValueError("Cannot seek live streams")

        duration = getattr(status, "duration", None)
        if isinstance(duration, (int, float)) and duration > 0:
            position = min(position, float(duration))

        logger.info("Seeking %s to %.1fs", self._device.name, position)
        media.seek(position)

    def stop(self) -> None:
        self.connect()
        assert self._cast is not None
        self._sync_cast_state()
        cast = self._cast
        media = cast.media_controller
        logger.info("Stopping %s", self._device.name)

        if media.status and media.status.media_session_id is not None:
            try:
                media.stop()
                return
            except RequestFailed as exc:
                logger.warning(
                    "Media stop failed on %s, trying quit_app: %s",
                    self._device.name,
                    exc,
                )

        if not cast.is_idle:
            cast.quit_app()
            return

        logger.info("%s already idle", self._device.name)

    def set_volume(self, level: float) -> None:
        if not 0.0 <= level <= 1.0:
            raise ValueError(f"Volume must be between 0.0 and 1.0, got {level}")

        self.connect()
        assert self._cast is not None
        logger.info("Setting volume on %s to %.2f", self._device.name, level)
        self._cast.set_volume(level)

    def set_volume_muted(self, muted: bool) -> None:
        self.connect()
        assert self._cast is not None
        logger.info("Setting mute on %s to %s", self._device.name, muted)
        self._cast.set_volume_muted(muted)

    def get_status(self) -> PlaybackStatus:
        self.connect()
        assert self._cast is not None
        self._sync_cast_state()

        cast = self._cast
        cast_status = cast.status
        media_status = cast.media_controller.status
        volume_level = cast_status.volume_level if cast_status else None
        volume_muted = cast_status.volume_muted if cast_status else None

        player_state = normalize_player_state(
            device_idle=cast.is_idle,
            player_state=getattr(media_status, "player_state", None),
            media_session_id=getattr(media_status, "media_session_id", None),
        )

        return PlaybackStatus(
            device_name=self._device.name,
            player_state=player_state,
            content_id=getattr(media_status, "content_id", None),
            content_type=getattr(media_status, "content_type", None),
            current_time=getattr(media_status, "current_time", None),
            duration=getattr(media_status, "duration", None),
            stream_type=getattr(media_status, "stream_type", None),
            volume_level=volume_level,
            volume_muted=volume_muted,
            app_name=cast.app_display_name,
            app_id=cast.app_id,
            device_idle=cast.is_idle,
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
            if status.player_state in _ACTIVE_PLAYER_STATES and not status.device_idle:
                return status
            time.sleep(poll_interval)
            status = self.get_status()

        logger.warning(
            "Playback did not reach an active state within %.0fs (state=%s, idle=%s)",
            timeout,
            status.player_state,
            status.device_idle,
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
