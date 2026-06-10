"""Cast device discovery and selection."""

from __future__ import annotations

import logging

import pychromecast

from moonpath.errors import AmbiguousDeviceError, DeviceNotFoundError
from moonpath.models import CastDevice

logger = logging.getLogger("moonpath")

DEFAULT_DISCOVERY_TIMEOUT = 8.0


def discover_devices(timeout: float = DEFAULT_DISCOVERY_TIMEOUT) -> list[CastDevice]:
    """Discover Cast devices on the local network."""
    logger.info("Discovering Cast devices (timeout=%ss)...", timeout)
    chromecasts, browser = pychromecast.get_chromecasts(timeout=timeout)
    try:
        devices = [_chromecast_to_device(cc) for cc in chromecasts]
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


def _chromecast_to_device(chromecast: pychromecast.Chromecast) -> CastDevice:
    info = chromecast.cast_info
    return CastDevice(
        name=chromecast.name,
        ip=info.host,
        model=info.model_name,
        uuid=str(info.uuid) if info.uuid else None,
        port=info.port,
    )
