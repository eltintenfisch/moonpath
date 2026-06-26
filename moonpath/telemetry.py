import json
import logging
import os
import secrets
import time
from pathlib import Path

_SERVICE_NAME = "moonpath"
_MAX_LOG_BYTES = int(os.environ.get("TELEMETRY_LOG_MAX_BYTES", str(8 * 1024 * 1024)))

logger = logging.getLogger("moonpath")


def _telemetry_path() -> Path:
    override = os.environ.get("TELEMETRY_LOG_PATH", "").strip()
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "moonpath" / "moonpath.telemetry.jsonl"


def _deployment_environment() -> str:
    return (
        os.environ.get("DEPLOYMENT_ENVIRONMENT", "").strip()
        or os.environ.get("ENVIRONMENT", "").strip()
        or "development"
    )


def new_trace_id() -> str:
    return secrets.token_hex(16)


def _rotate_if_needed(path: Path) -> None:
    try:
        if not path.exists():
            return
        if path.stat().st_size <= _MAX_LOG_BYTES:
            return
        rotated = path.with_suffix(".jsonl.1")
        if rotated.exists():
            rotated.unlink()
        path.rename(rotated)
    except Exception as exc:
        logger.error("[telemetry] failed to rotate log: %s", exc)


def _append(record: dict) -> None:
    try:
        path = _telemetry_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate_if_needed(path)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as exc:
        logger.error("[telemetry] failed to write log: %s", exc)


def _build(
    event_name: str,
    body: str,
    severity: str = "INFO",
    trace_id: str | None = None,
    entity: str | None = None,
    entity_id: str | None = None,
    duration_ms: float | None = None,
    attributes: dict | None = None,
    exception: Exception | None = None,
) -> dict:
    record: dict = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int(time.time() * 1000) % 1000:03d}Z",
        "severity_text": severity,
        "event.name": event_name,
        "body": body,
        "service.name": _SERVICE_NAME,
        "deployment.environment": _deployment_environment(),
    }
    if trace_id:
        record["trace_id"] = trace_id
    if entity:
        record["entity"] = entity
    if entity_id:
        record["entity_id"] = entity_id
    if duration_ms is not None:
        record["duration_ms"] = round(duration_ms, 2)
    if attributes:
        record["attributes"] = attributes
    if exception is not None:
        record["exception.type"] = type(exception).__name__
        record["exception.message"] = str(exception)
    return record


def emit(
    event_name: str,
    body: str,
    severity: str = "INFO",
    trace_id: str | None = None,
    entity: str | None = None,
    entity_id: str | None = None,
    duration_ms: float | None = None,
    attributes: dict | None = None,
) -> None:
    _append(_build(
        event_name=event_name,
        body=body,
        severity=severity,
        trace_id=trace_id,
        entity=entity,
        entity_id=entity_id,
        duration_ms=duration_ms,
        attributes=attributes,
    ))


def emit_error(
    event_name: str,
    body: str,
    exc: Exception,
    trace_id: str | None = None,
    entity: str | None = None,
    entity_id: str | None = None,
    duration_ms: float | None = None,
    attributes: dict | None = None,
) -> None:
    _append(_build(
        event_name=event_name,
        body=body,
        severity="ERROR",
        trace_id=trace_id,
        entity=entity,
        entity_id=entity_id,
        duration_ms=duration_ms,
        attributes=attributes,
        exception=exc,
    ))
