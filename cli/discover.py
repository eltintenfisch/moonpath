#!/usr/bin/env python3
"""List Cast devices on the local network."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from moonpath import discover_devices
from moonpath.discovery import DEFAULT_DISCOVERY_TIMEOUT
from moonpath.errors import main_fail, setup_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover Google Cast devices")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_DISCOVERY_TIMEOUT,
        help="Discovery timeout in seconds",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_logging(args.verbose)

    try:
        devices = discover_devices(timeout=args.timeout)
    except Exception as exc:
        main_fail(exc, operation="discover")

    if not devices:
        print("No Cast devices found.")
        return

    for device in devices:
        print(f"name: {device.name}")
        print(f"ip: {device.ip}")
        print(f"model: {device.model or '-'}")
        print(f"uuid: {device.uuid or '-'}")
        print()


if __name__ == "__main__":
    main()
