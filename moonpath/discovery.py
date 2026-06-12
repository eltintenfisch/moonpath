"""Cast device discovery and selection."""

from __future__ import annotations

import logging
import time

import zeroconf
from pychromecast.discovery import CastBrowser, SimpleCastListener

from moonpath.errors import AmbiguousDeviceError, DeviceNotFoundError
from moonpath.models import CastDevice

logger = logging.getLogger("moonpath")

DEFAULT_DISCOVERY_TIMEOUT = 8.0


def discover_devices(timeout: float = DEFAULT_DISCOVERY_TIMEOUT) -> list[CastDevice]:
    """Discover Cast devices on the local network."""
    logger.info("Discovering Cast devices (timeout=%ss)...", timeout)
    zconf = zeroconf.Zeroconf()
    browser = CastBrowser(SimpleCastListener(), zconf)
    browser.start_discovery()
    try:
        time.sleep(timeout)
        devices = [_cast_info_to_device(cast_info) for cast_info in browser.devices.values()]
        devices.sort(key=lambda device: device.name.casefold())
        logger.info("Found %d device(s)", len(devices))
        return devices
    finally:
        browser.stop_discovery()


def select_device(devices: list[CastDevice], name_query: str) -> CastDevice:
    """Select a device by case-insensitive substring match on friendly name."""
    query = name_query.casefold().strip()
    matches = [device for device in devices if query in device.name.casefold()]

    if not matches:
        names = ", ".join(device.name for device in devices) or "(none)"
        raise DeviceNotFoundError(
            f"No device matching {name_query!r}. Available: {names}",
            operation="select_device",
            device_name=name_query,
        )

    if len(matches) > 1:
        matched_names = ", ".join(device.name for device in matches)
        raise AmbiguousDeviceError(
            f"Multiple devices match {name_query!r}: {matched_names}",
            operation="select_device",
            device_name=name_query,
        )

    return matches[0]


def resolve_device_by_id(
    device_id: str,
    timeout: float = DEFAULT_DISCOVERY_TIMEOUT,
) -> CastDevice:
    """Find a device by Cast UUID via mDNS discovery."""
    query = device_id.strip()
    for device in discover_devices(timeout=timeout):
        if device.uuid == query:
            return device

    raise DeviceNotFoundError(
        f"No device found for id {query!r}",
        operation="resolve_device",
    )


def resolve_device(
    device_id: str,
    *,
    host: str | None = None,
    port: int | None = None,
    name: str | None = None,
    model: str | None = None,
    discovery_timeout: float = DEFAULT_DISCOVERY_TIMEOUT,
) -> CastDevice:
    """Resolve a device by UUID, using a cached host when provided."""
    query = device_id.strip()
    if not query:
        raise DeviceNotFoundError("device id is required", operation="resolve_device")

    host_value = (host or "").strip()
    if host_value:
        return CastDevice(
            name=(name or "cast-device").strip() or "cast-device",
            ip=host_value,
            port=port if port is not None else 8009,
            uuid=query,
            model=model,
        )

    return resolve_device_by_id(query, timeout=discovery_timeout)


def _cast_info_to_device(cast_info) -> CastDevice:
    return CastDevice(
        name=cast_info.friendly_name or "unknown",
        ip=cast_info.host,
        model=cast_info.model_name,
        uuid=str(cast_info.uuid) if cast_info.uuid else None,
        port=cast_info.port,
    )
