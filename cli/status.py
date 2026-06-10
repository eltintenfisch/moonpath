#!/usr/bin/env python3
"""Print playback status for a Cast device."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from moonpath import CastController, discover_devices
from moonpath.discovery import select_device
from moonpath.errors import main_fail, setup_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show Google Cast playback status")
    parser.add_argument("--device", required=True, help="Device name (substring match)")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_logging(args.verbose)

    controller = None
    try:
        devices = discover_devices()
        device = select_device(devices, args.device)
        controller = CastController(device)
        print(controller.get_status().format())
    except Exception as exc:
        main_fail(exc, operation="status", device_name=args.device)
    finally:
        if controller is not None:
            controller.disconnect()


if __name__ == "__main__":
    main()
