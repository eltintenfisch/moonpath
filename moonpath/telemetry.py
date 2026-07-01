import json
import logging
import os
import re
import secrets
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SERVICE_NAME = "moonpath"
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_MAX_LOG_BYTES = 8 * 1024 * 1024
_MAX_ENTRIES = 500
_SENSITIVE_KEY = re.compile(r"(password|token|secret|cookie|authorization|api[_-]?key|private[_-]?key)", re.IGNORECASE)

logger = logging.getLogger("moonpath")

_entries: list[dict] = []


@dataclass(frozen=True)
class TelemetryContext:
    request_id: str
    trace_id: str
    span_id: str


_context: ContextVar["TelemetryContext | None"] = ContextVar("telemetry_context", default=None)


def new_trace_id() -> str:
    return secrets.token_hex(16)


def new_span_id() -> str:
    return secrets.token_hex(8)


def new_request_id() -> str:
    return secrets.token_hex(16)


def get_telemetry_context() -> "TelemetryContext | None":
    return _context.get()


def set_telemetry_context(ctx: "TelemetryContext"):
    """Returns a token; caller must pass it to `reset_telemetry_context` when the request/operation ends."""
    return _context.set(ctx)


def reset_telemetry_context(token) -> None:
    _context.reset(token)


def correlation_from_headers(headers) -> TelemetryContext:
    """Inherit request/trace IDs from inbound headers when present, generate otherwise."""
    request_id = (headers.get("x-request-id") or "").strip() or new_request_id()
    trace_id = (headers.get("x-trace-id") or "").strip() or new_trace_id()
    return TelemetryContext(request_id=request_id, trace_id=trace_id, span_id=new_span_id())


def _telemetry_path() -> Path:
    override = os.environ.get("TELEMETRY_LOG_PATH", "").strip()
    if override:
        return Path(override)
    return _REPO_ROOT / "data" / f"{_SERVICE_NAME}.telemetry.jsonl"


def get_telemetry_file_path() -> Path:
    return _telemetry_path()


def _deployment_environment() -> str:
    return (
        os.environ.get("DEPLOYMENT_ENVIRONMENT", "").strip()
        or os.environ.get("ENVIRONMENT", "").strip()
        or "development"
    )


def _max_log_bytes() -> int:
    raw = os.environ.get("TELEMETRY_LOG_MAX_BYTES", "").strip()
    if raw:
        try:
            n = int(raw)
            if n > 0:
                return n
        except ValueError:
            pass
    return _DEFAULT_MAX_LOG_BYTES


def _rotate_if_needed(path: Path) -> None:
    try:
        if not path.exists():
            return
        if path.stat().st_size <= _max_log_bytes():
            return
        rotated = path.with_name(path.name + ".1")
        if rotated.exists():
            rotated.unlink()
        path.rename(rotated)
    except Exception as exc:
        logger.error("[telemetry] failed to rotate log: %s", exc)


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        if len(value) > 2048:
            return value[:2048] + "…[truncated]"
        return value
    if isinstance(value, list):
        return [_redact_value(v) for v in value]
    if isinstance(value, dict):
        return sanitize_attributes(value)
    return value


def sanitize_attributes(attributes: "dict | None") -> "dict | None":
    if not attributes:
        return None
    out: dict = {}
    for key, value in attributes.items():
        out[key] = "[redacted]" if _SENSITIVE_KEY.search(key) else _redact_value(value)
    return out


def _append(record: dict) -> None:
    _entries.append(record)
    if len(_entries) > _MAX_ENTRIES:
        del _entries[: len(_entries) - _MAX_ENTRIES]

    try:
        path = _telemetry_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate_if_needed(path)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception as exc:
        logger.error("[telemetry] failed to write log: %s", exc)

    summary = f"[telemetry] {record['timestamp']} {record['severity_text']} {record['event.name']} {record['body']}"
    if record["severity_text"] == "ERROR":
        logger.error(summary)
    elif record["severity_text"] == "WARN":
        logger.warning(summary)


def emit(
    event_name: str,
    body: str,
    severity: str = "INFO",
    entity: "str | None" = None,
    entity_id: "str | None" = None,
    duration_ms: "float | None" = None,
    attributes: "dict | None" = None,
    request_id: "str | None" = None,
    trace_id: "str | None" = None,
    span_id: "str | None" = None,
) -> dict:
    ctx = get_telemetry_context()
    record: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "severity_text": severity,
        "event.name": event_name,
        "body": body,
        "service.name": _SERVICE_NAME,
        "deployment.environment": _deployment_environment(),
    }
    rid = request_id or (ctx.request_id if ctx else None)
    tid = trace_id or (ctx.trace_id if ctx else None)
    sid = span_id or (ctx.span_id if ctx else None)
    if rid:
        record["request_id"] = rid
    if tid:
        record["trace_id"] = tid
    if sid:
        record["span_id"] = sid
    if entity:
        record["entity"] = entity
    if entity_id:
        record["entity_id"] = entity_id
    if duration_ms is not None:
        record["duration_ms"] = round(duration_ms, 2)
    sanitized = sanitize_attributes(attributes)
    if sanitized:
        record["attributes"] = sanitized
    _append(record)
    return record


def emit_error(
    event_name: str,
    body: str,
    exc: Exception,
    entity: "str | None" = None,
    entity_id: "str | None" = None,
    duration_ms: "float | None" = None,
    attributes: "dict | None" = None,
    request_id: "str | None" = None,
    trace_id: "str | None" = None,
) -> dict:
    ctx = get_telemetry_context()
    record: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "severity_text": "ERROR",
        "event.name": event_name,
        "body": body,
        "service.name": _SERVICE_NAME,
        "deployment.environment": _deployment_environment(),
    }
    rid = request_id or (ctx.request_id if ctx else None)
    tid = trace_id or (ctx.trace_id if ctx else None)
    if rid:
        record["request_id"] = rid
    if tid:
        record["trace_id"] = tid
    if ctx and ctx.span_id:
        record["span_id"] = ctx.span_id
    if entity:
        record["entity"] = entity
    if entity_id:
        record["entity_id"] = entity_id
    if duration_ms is not None:
        record["duration_ms"] = round(duration_ms, 2)
    sanitized = sanitize_attributes(attributes)
    if sanitized:
        record["attributes"] = sanitized
    record["exception.type"] = type(exc).__name__
    record["exception.message"] = str(exc)
    _append(record)
    return record


def emit_external_api(
    direction: str,
    entity: str,
    operation: str,
    body: str,
    attributes: "dict | None" = None,
    duration_ms: "float | None" = None,
    severity: str = "INFO",
) -> dict:
    event_name = "external_api.request" if direction == "request" else "external_api.response"
    return emit(
        event_name=event_name,
        body=body,
        severity=severity,
        entity=entity,
        duration_ms=duration_ms,
        attributes={"operation": operation, **(attributes or {})},
    )


def get_telemetry_entries(limit: int = 100) -> list[dict]:
    n = max(1, min(limit, _MAX_ENTRIES))
    return _entries[-n:]


def read_telemetry_file_tail(limit: int = 100) -> list[dict]:
    path = _telemetry_path()
    if not path.exists():
        return []
    lines = [line for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]
    out: list[dict] = []
    for line in lines[-max(1, limit):]:
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out
