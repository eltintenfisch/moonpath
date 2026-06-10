"""Data models for Moonpath."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CastDevice:
    name: str
    ip: str
    model: str | None = None
    uuid: str | None = None
    port: int = 8009


@dataclass(frozen=True)
class PlaybackStatus:
    device_name: str | None
    player_state: str | None
    content_id: str | None
    content_type: str | None
    current_time: float | None
    duration: float | None
    stream_type: str | None
    volume_level: float | None
    volume_muted: bool | None
    app_name: str | None = None
    app_id: str | None = None
    device_idle: bool | None = None

    def format(self) -> str:
        lines = [
            f"device: {self.device_name or 'unknown'}",
            f"device_idle: {self._format_bool(self.device_idle)}",
            f"app: {self.app_name or '-'}",
            f"player_state: {self.player_state or 'unknown'}",
            f"content_id: {self.content_id or '-'}",
            f"content_type: {self.content_type or '-'}",
            f"current_time: {self._format_time(self.current_time)}",
            f"duration: {self._format_time(self.duration)}",
            f"stream_type: {self.stream_type or '-'}",
            f"volume: {self._format_volume()}",
        ]
        return "\n".join(lines)

    @staticmethod
    def _format_time(value: float | None) -> str:
        if value is None:
            return "-"
        return f"{value:.1f}s"

    @staticmethod
    def _format_bool(value: bool | None) -> str:
        if value is None:
            return "unknown"
        return "yes" if value else "no"

    def _format_volume(self) -> str:
        if self.volume_level is None:
            return "-"
        muted = " (muted)" if self.volume_muted else ""
        return f"{self.volume_level:.2f}{muted}"
