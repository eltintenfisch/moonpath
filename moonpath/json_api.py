"""JSON response helpers for the Moonpath CLI."""

from __future__ import annotations

import json
import sys
from typing import Any

from pychromecast.error import RequestFailed

from moonpath.errors import (
    AmbiguousDeviceError,
    CastConnectionError,
    DeviceNotFoundError,
    MoonpathError,
)
from moonpath.models import CastDevice, PlaybackStatus

ERROR_DEVICE_NOT_FOUND = "DeviceNotFound"
ERROR_AMBIGUOUS_DEVICE = "AmbiguousDevice"
ERROR_CONNECTION_FAILED = "ConnectionFailed"
ERROR_PLAYBACK_FAILED = "PlaybackFailed"
ERROR_INVALID_ARGUMENT = "InvalidArgument"
ERROR_INTERNAL = "InternalError"


def error_type_for(exc: BaseException) -> str:
    if isinstance(exc, DeviceNotFoundError):
        return ERROR_DEVICE_NOT_FOUND
    if isinstance(exc, AmbiguousDeviceError):
        return ERROR_AMBIGUOUS_DEVICE
    if isinstance(exc, CastConnectionError):
        return ERROR_CONNECTION_FAILED
    if isinstance(exc, ValueError):
        return ERROR_INVALID_ARGUMENT
    if isinstance(exc, RequestFailed):
        return ERROR_PLAYBACK_FAILED
    if isinstance(exc, MoonpathError):
        return ERROR_INTERNAL
    return ERROR_INTERNAL


def device_to_json(device: CastDevice) -> dict[str, Any]:
    return {
        "id": device.uuid,
        "name": device.name,
        "host": device.ip,
        "model": device.model,
        "port": device.port,
    }


def status_to_json(status: PlaybackStatus, device_id: str) -> dict[str, Any]:
    return {
        "device_id": device_id,
        "device_name": status.device_name,
        "device_idle": status.device_idle,
        "app_name": status.app_name,
        "app_id": status.app_id,
        "player_state": status.player_state,
        "content_id": status.content_id,
        "content_type": status.content_type,
        "current_time": status.current_time,
        "duration": status.duration,
        "stream_type": status.stream_type,
        "volume_level": status.volume_level,
        "volume_muted": status.volume_muted,
    }


def write_json(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, indent=2))
    sys.stdout.write("\n")
    sys.stdout.flush()


def success_payload(operation: str, **fields: Any) -> dict[str, Any]:
    return {"ok": True, "operation": operation, **fields}


def error_payload(operation: str, exc: BaseException) -> dict[str, Any]:
    return {
        "ok": False,
        "operation": operation,
        "error": {
            "type": error_type_for(exc),
            "message": str(exc),
        },
    }
