"""Moonpath HTTP service — Cast control over a clean REST API."""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pychromecast.error import RequestFailed
from pydantic import BaseModel, Field

from moonpath import telemetry
from moonpath.connection_pool import ConnectionPool
from moonpath.controller import (
    CastController,
    DEFAULT_PLAYBACK_WAIT_TIMEOUT,
    HLS_PLAYBACK_WAIT_TIMEOUT,
    guess_content_type,
    is_hls_url,
)
from moonpath.discovery import DEFAULT_DISCOVERY_TIMEOUT, discover_devices
from moonpath.errors import AmbiguousDeviceError, CastConnectionError, DeviceNotFoundError
from moonpath.json_api import device_to_json, error_type_for, status_to_json
from moonpath.models import CastDevice

logger = logging.getLogger("moonpath")

PORT = int(os.environ.get("MOONPATH_PORT", "8001"))

pool = ConnectionPool()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Moonpath service starting on port %d", PORT)
    yield
    await pool.disconnect_all()
    logger.info("Moonpath service stopped")


app = FastAPI(title="Moonpath", description="Google Cast control service", lifespan=lifespan)


@app.middleware("http")
async def telemetry_middleware(request: Request, call_next):
    ctx = telemetry.correlation_from_headers(request.headers)
    token = telemetry.set_telemetry_context(ctx)
    try:
        response = await call_next(request)
    finally:
        telemetry.reset_telemetry_context(token)
    response.headers["X-Request-ID"] = ctx.request_id
    response.headers["X-Trace-ID"] = ctx.trace_id
    return response


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class DeviceRef(BaseModel):
    """Device connection details. host is required when no cached connection exists."""
    host: str | None = None
    port: int = 8009
    name: str | None = None
    model: str | None = None


class PlayUrlRequest(DeviceRef):
    url: str
    content_type: str | None = None
    stream_type: str | None = Field(None, pattern="^(BUFFERED|LIVE)$")
    position: float | None = None
    subtitles_url: str | None = None
    subtitles_lang: str = "en-US"
    replace: bool = False


class PlayRadioRequest(DeviceRef):
    url: str
    content_type: str = "audio/mpeg"


class SeekRequest(DeviceRef):
    position: float


class VolumeRequest(DeviceRef):
    level: float = Field(..., ge=0.0, le=1.0)


class MuteRequest(DeviceRef):
    muted: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_device(device_id: str, ref: DeviceRef) -> CastDevice:
    host = (ref.host or "").strip()
    if not host:
        raise HTTPException(
            status_code=400,
            detail="host is required when no cached connection exists for this device",
        )
    return CastDevice(
        name=(ref.name or "cast-device").strip() or "cast-device",
        ip=host,
        port=ref.port,
        uuid=device_id,
        model=ref.model,
    )


def _device_from_pool_or_ref(device_id: str, ref: DeviceRef) -> CastDevice:
    """Use cached device info if available, otherwise require host in ref."""
    cached = pool._device_info.get(device_id)
    if cached is not None:
        return cached
    return _resolve_device(device_id, ref)


def _handle_cast_error(exc: Exception, device_id: str) -> HTTPException:
    if isinstance(exc, DeviceNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, AmbiguousDeviceError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, CastConnectionError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, RequestFailed):
        return HTTPException(status_code=502, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


async def _run(
    request: Request,
    device_id: str,
    operation: str,
    device: CastDevice,
    fn,
    attributes: dict | None = None,
) -> Any:
    start_ms = time.monotonic() * 1000

    telemetry.emit(
        event_name="cast.request",
        body=f"{operation} requested",
        entity="cast_device",
        entity_id=device_id,
        attributes={"operation": operation, "device_name": device.name, **(attributes or {})},
    )

    try:
        result = await pool.execute(device, fn)
    except Exception as exc:
        duration_ms = time.monotonic() * 1000 - start_ms
        telemetry.emit_error(
            event_name="cast.error",
            body=f"{operation} failed",
            exc=exc,
            entity="cast_device",
            entity_id=device_id,
            duration_ms=duration_ms,
            attributes={"operation": operation, "device_name": device.name},
        )
        raise _handle_cast_error(exc, device_id) from exc

    duration_ms = time.monotonic() * 1000 - start_ms
    telemetry.emit(
        event_name="cast.success",
        body=f"{operation} completed",
        entity="cast_device",
        entity_id=device_id,
        duration_ms=duration_ms,
        attributes={"operation": operation, "device_name": device.name},
    )
    return result


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {
        "status": "ok",
        "active_connections": pool.active_device_ids(),
    }


@app.get("/devices")
async def devices_discover(
    request: Request,
    timeout: float = DEFAULT_DISCOVERY_TIMEOUT,
):
    start_ms = time.monotonic() * 1000

    telemetry.emit(
        event_name="cast.request",
        body="discover requested",
        entity="cast_service",
        attributes={"operation": "discover", "timeout": timeout},
    )

    try:
        import asyncio
        loop = asyncio.get_running_loop()
        found = await loop.run_in_executor(None, lambda: discover_devices(timeout=timeout))
    except Exception as exc:
        duration_ms = time.monotonic() * 1000 - start_ms
        telemetry.emit_error(
            event_name="cast.error",
            body="discover failed",
            exc=exc,
            duration_ms=duration_ms,
            attributes={"operation": "discover"},
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    duration_ms = time.monotonic() * 1000 - start_ms
    telemetry.emit(
        event_name="cast.success",
        body=f"discover completed, {len(found)} device(s) found",
        duration_ms=duration_ms,
        attributes={"operation": "discover", "count": len(found)},
    )
    return {"devices": [device_to_json(d) for d in found if d.uuid is not None]}


@app.get("/devices/{device_id}/status")
async def device_status(
    device_id: str,
    request: Request,
    host: str | None = None,
    port: int = 8009,
    name: str | None = None,
):
    ref = DeviceRef(host=host, port=port, name=name)
    device = _device_from_pool_or_ref(device_id, ref)

    def fn(controller: CastController):
        return status_to_json(controller.get_status(), device_id)

    result = await _run(request, device_id, "status", device, fn)
    return result


@app.post("/devices/{device_id}/play-url")
async def play_url(device_id: str, body: PlayUrlRequest, request: Request):
    device = _device_from_pool_or_ref(device_id, body)
    content_type = body.content_type or guess_content_type(body.url)
    stream_type = body.stream_type or ("LIVE" if is_hls_url(body.url, content_type) else "BUFFERED")
    playback_timeout = HLS_PLAYBACK_WAIT_TIMEOUT if stream_type == "LIVE" else DEFAULT_PLAYBACK_WAIT_TIMEOUT
    position = body.position if body.position and body.position > 0 else None
    subtitles_url = body.subtitles_url.strip() if body.subtitles_url else None

    def fn(controller: CastController):
        controller.play_url(
            body.url,
            content_type=content_type,
            stream_type=stream_type,
            start_position=position,
            subtitles_url=subtitles_url,
            subtitles_lang=body.subtitles_lang,
            replace_in_place=body.replace,
        )
        status = controller.wait_for_playback(timeout=playback_timeout)
        return status_to_json(status, device_id)

    result = await _run(
        request, device_id, "play-url", device, fn,
        attributes={"url": body.url, "content_type": content_type, "stream_type": stream_type},
    )
    return result


@app.post("/devices/{device_id}/play-radio")
async def play_radio(device_id: str, body: PlayRadioRequest, request: Request):
    device = _device_from_pool_or_ref(device_id, body)
    content_type = body.content_type or guess_content_type(body.url, default="audio/mpeg")

    def fn(controller: CastController):
        controller.play_radio(body.url, content_type=content_type)
        status = controller.wait_for_playback()
        return status_to_json(status, device_id)

    result = await _run(
        request, device_id, "play-radio", device, fn,
        attributes={"url": body.url, "content_type": content_type},
    )
    return result


@app.post("/devices/{device_id}/pause")
async def pause(device_id: str, request: Request, body: DeviceRef = None):
    body = body or DeviceRef()
    device = _device_from_pool_or_ref(device_id, body)

    def fn(controller: CastController):
        controller.pause()
        return status_to_json(controller.get_status(), device_id)

    return await _run(request, device_id, "pause", device, fn)


@app.post("/devices/{device_id}/resume")
async def resume(device_id: str, request: Request, body: DeviceRef = None):
    body = body or DeviceRef()
    device = _device_from_pool_or_ref(device_id, body)

    def fn(controller: CastController):
        controller.resume()
        return status_to_json(controller.get_status(), device_id)

    return await _run(request, device_id, "resume", device, fn)


@app.post("/devices/{device_id}/stop")
async def stop(device_id: str, request: Request, body: DeviceRef = None):
    body = body or DeviceRef()
    device = _device_from_pool_or_ref(device_id, body)

    def fn(controller: CastController):
        controller.stop()
        return status_to_json(controller.get_status(), device_id)

    return await _run(request, device_id, "stop", device, fn)


@app.post("/devices/{device_id}/seek")
async def seek(device_id: str, body: SeekRequest, request: Request):
    device = _device_from_pool_or_ref(device_id, body)

    def fn(controller: CastController):
        controller.seek(body.position)
        return status_to_json(controller.get_status(), device_id)

    return await _run(
        request, device_id, "seek", device, fn,
        attributes={"position": body.position},
    )


@app.post("/devices/{device_id}/volume")
async def volume(device_id: str, body: VolumeRequest, request: Request):
    device = _device_from_pool_or_ref(device_id, body)

    def fn(controller: CastController):
        controller.set_volume(body.level)
        status = controller.get_status()
        return {
            "volume": {"level": status.volume_level, "muted": status.volume_muted},
            "status": status_to_json(status, device_id),
        }

    return await _run(
        request, device_id, "volume", device, fn,
        attributes={"level": body.level},
    )


@app.post("/devices/{device_id}/mute")
async def mute(device_id: str, body: MuteRequest, request: Request):
    device = _device_from_pool_or_ref(device_id, body)

    def fn(controller: CastController):
        controller.set_volume_muted(body.muted)
        status = controller.get_status()
        return {
            "volume": {"level": status.volume_level, "muted": status.volume_muted},
            "status": status_to_json(status, device_id),
        }

    return await _run(
        request, device_id, "mute", device, fn,
        attributes={"muted": body.muted},
    )


if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
