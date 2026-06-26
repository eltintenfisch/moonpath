"""Persistent Cast connection pool with auto-reconnect."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TypeVar

from pychromecast.error import RequestFailed

from moonpath.controller import CastController
from moonpath.errors import CastConnectionError
from moonpath.models import CastDevice

logger = logging.getLogger("moonpath")

T = TypeVar("T")


class ConnectionPool:
    """Maintain one persistent CastController per device, reconnecting on stale connections."""

    def __init__(self) -> None:
        self._controllers: dict[str, CastController] = {}
        self._device_info: dict[str, CastDevice] = {}
        self._device_locks: dict[str, asyncio.Lock] = {}
        self._registry_lock = asyncio.Lock()

    async def _lock_for(self, device_id: str) -> asyncio.Lock:
        async with self._registry_lock:
            if device_id not in self._device_locks:
                self._device_locks[device_id] = asyncio.Lock()
            return self._device_locks[device_id]

    def _evict(self, device_id: str) -> None:
        controller = self._controllers.pop(device_id, None)
        self._device_info.pop(device_id, None)
        if controller is not None:
            try:
                controller.disconnect()
            except Exception:
                pass

    async def _get_or_connect(
        self,
        device: CastDevice,
        loop: asyncio.AbstractEventLoop,
    ) -> CastController:
        device_id = device.uuid or device.ip
        controller = self._controllers.get(device_id)
        if controller is not None:
            return controller

        logger.info("Opening connection to %s (%s)", device.name, device.ip)
        controller = CastController(device)
        await loop.run_in_executor(None, controller.connect)
        self._controllers[device_id] = controller
        self._device_info[device_id] = device
        logger.info("Connection established: %s", device.name)
        return controller

    async def execute(self, device: CastDevice, fn: Callable[[CastController], T]) -> T:
        """Run fn(controller) on a connected controller, retrying once on stale connections."""
        device_id = device.uuid or device.ip
        lock = await self._lock_for(device_id)
        loop = asyncio.get_running_loop()

        async with lock:
            for attempt in range(2):
                controller = await self._get_or_connect(device, loop)
                try:
                    return await loop.run_in_executor(None, fn, controller)
                except (CastConnectionError, RequestFailed, OSError) as exc:
                    if attempt == 0:
                        logger.warning(
                            "Connection to %s failed (%s), reconnecting…",
                            device.name,
                            exc,
                        )
                        self._evict(device_id)
                        continue
                    raise

        raise RuntimeError("unreachable")

    def active_device_ids(self) -> list[str]:
        return list(self._controllers.keys())

    async def disconnect_all(self) -> None:
        async with self._registry_lock:
            for device_id in list(self._controllers.keys()):
                self._evict(device_id)
