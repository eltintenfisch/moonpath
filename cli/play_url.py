#!/usr/bin/env python3
"""Play a media URL on a Cast device."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from moonpath import CastController, discover_devices
from moonpath.controller import guess_content_type, run_interactive_controls
from moonpath.discovery import select_device
from moonpath.errors import main_fail, setup_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Play a URL on a Google Cast device")
    parser.add_argument("--device", required=True, help="Device name (substring match)")
    parser.add_argument("--url", required=True, help="Media URL to play")
    parser.add_argument(
        "--content-type",
        help="MIME type (default: inferred from URL extension)",
    )
    parser.add_argument(
        "--no-interactive",
        action="store_true",
        help="Play and exit without interactive controls",
    )
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
        content_type = args.content_type or guess_content_type(args.url)
        controller.play_url(args.url, content_type=content_type, stream_type="BUFFERED")

        if args.no_interactive:
            print(controller.get_status().format())
            return

        run_interactive_controls(controller)
    except Exception as exc:
        main_fail(exc, operation="play_url", device_name=args.device)
    finally:
        if controller is not None:
            controller.disconnect()


if __name__ == "__main__":
    main()
