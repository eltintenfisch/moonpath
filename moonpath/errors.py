"""Moonpath exceptions and failure logging."""

from __future__ import annotations

import logging
import sys
from typing import NoReturn

logger = logging.getLogger("moonpath")


class MoonpathError(Exception):
    """Base error for Moonpath operations."""

    def __init__(
        self,
        message: str,
        *,
        operation: str | None = None,
        device_name: str | None = None,
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.device_name = device_name


class DeviceNotFoundError(MoonpathError):
    """No device matched the given name."""


class AmbiguousDeviceError(MoonpathError):
    """Multiple devices matched the given name."""


class CastConnectionError(MoonpathError):
    """Failed to connect to a Cast device."""


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def log_failure(
    exc: BaseException,
    *,
    operation: str,
    device_name: str | None = None,
) -> None:
    logger.error("Operation: %s", operation)
    if device_name:
        logger.error("Device: %s", device_name)
    logger.error("Exception: %s", type(exc).__name__)
    logger.error("Message: %s", exc)


def fail(
    exc: BaseException,
    *,
    operation: str,
    device_name: str | None = None,
) -> NoReturn:
    log_failure(exc, operation=operation, device_name=device_name)
    if isinstance(exc, MoonpathError):
        raise exc
    raise MoonpathError(str(exc), operation=operation, device_name=device_name) from exc


def main_fail(
    exc: BaseException,
    *,
    operation: str,
    device_name: str | None = None,
) -> NoReturn:
    log_failure(exc, operation=operation, device_name=device_name)
    sys.exit(1)
