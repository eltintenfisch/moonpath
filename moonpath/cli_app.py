"""Unified Moonpath CLI for Nereid and other callers."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from typing import Any

from moonpath.controller import CastController, guess_content_type
from moonpath.discovery import DEFAULT_DISCOVERY_TIMEOUT, discover_devices, resolve_device
from moonpath.errors import log_failure, setup_logging
from moonpath.json_api import (
    device_to_json,
    error_payload,
    status_to_json,
    success_payload,
    write_json,
)
from moonpath.models import CastDevice


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="moonpath", description="Google Cast control")
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--verbose", action="store_true", help="Enable debug logging on stderr")
    parent.add_argument("--json", action="store_true", help="Emit JSON on stdout")

    device_parent = argparse.ArgumentParser(add_help=False)
    device_parent.add_argument("--device-id", required=True, help="Cast device UUID")
    device_parent.add_argument(
        "--device-host",
        help="Device IP/hostname from discover (skips mDNS scan when set)",
    )
    device_parent.add_argument(
        "--device-port",
        type=int,
        default=8009,
        help="Cast port from discover (default: 8009)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    discover = subparsers.add_parser(
        "discover",
        parents=[parent],
        help="List Cast devices on the network",
    )
    discover.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_DISCOVERY_TIMEOUT,
        help="Discovery timeout in seconds",
    )

    subparsers.add_parser(
        "status",
        parents=[parent, device_parent],
        help="Show playback status",
    )

    play_url = subparsers.add_parser("play-url", parents=[parent, device_parent], help="Play a media URL")
    play_url.add_argument("--url", required=True, help="Media URL")
    play_url.add_argument("--content-type", help="MIME type (inferred from URL if omitted)")
    play_url.add_argument(
        "--position",
        type=float,
        help="Start position in seconds (buffered media only)",
    )
    play_url.add_argument("--subtitles-url", help="WebVTT subtitles URL for Cast")
    play_url.add_argument(
        "--subtitles-lang",
        default="en-US",
        help="Subtitle language tag (default: en-US)",
    )

    play_radio = subparsers.add_parser(
        "play-radio",
        parents=[parent, device_parent],
        help="Play an internet radio stream",
    )
    play_radio.add_argument("--url", required=True, help="Radio stream URL")
    play_radio.add_argument(
        "--content-type",
        default="audio/mpeg",
        help="MIME type (default: audio/mpeg)",
    )

    subparsers.add_parser("pause", parents=[parent, device_parent], help="Pause playback")
    subparsers.add_parser("resume", parents=[parent, device_parent], help="Resume playback")
    subparsers.add_parser("stop", parents=[parent, device_parent], help="Stop playback")

    seek = subparsers.add_parser("seek", parents=[parent, device_parent], help="Seek buffered media")
    seek.add_argument(
        "--position",
        type=float,
        required=True,
        help="Position in seconds from the start of the track",
    )

    volume = subparsers.add_parser("volume", parents=[parent, device_parent], help="Set playback volume")
    volume.add_argument("--level", type=float, required=True, help="Volume level 0.0-1.0")

    mute = subparsers.add_parser("mute", parents=[parent, device_parent], help="Mute or unmute playback")
    mute.add_argument(
        "--muted",
        choices=("true", "false"),
        required=True,
        help="true to mute, false to unmute",
    )

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(args.verbose)

    handlers: dict[str, Callable[[argparse.Namespace], Any]] = {
        "discover": cmd_discover,
        "status": cmd_status,
        "play-url": cmd_play_url,
        "play-radio": cmd_play_radio,
        "pause": cmd_pause,
        "resume": cmd_resume,
        "stop": cmd_stop,
        "seek": cmd_seek,
        "volume": cmd_volume,
        "mute": cmd_mute,
    }

    operation = args.command
    try:
        result = handlers[operation](args)
    except Exception as exc:
        sys.exit(fail(operation, exc, json_mode=args.json))

    emit_success(operation, result, json_mode=args.json)


def fail(operation: str, exc: BaseException, *, json_mode: bool) -> int:
    log_failure(exc, operation=operation)
    if json_mode:
        write_json(error_payload(operation, exc))
    return 1


def emit_success(operation: str, result: dict[str, Any], *, json_mode: bool) -> None:
    if json_mode:
        write_json(success_payload(operation, **result))
        return

    _emit_human(operation, result)


def _emit_human(operation: str, result: dict[str, Any]) -> None:
    if operation == "discover":
        devices = result.get("devices", [])
        if not devices:
            print("No Cast devices found.")
            return
        for device in devices:
            print(f"id: {device['id']}")
            print(f"name: {device['name']}")
            print(f"host: {device['host']}")
            print(f"model: {device['model'] or '-'}")
            print()
        return

    if "volume" in result:
        volume = result["volume"]
        print(f"level: {volume['level']}")
        print(f"muted: {volume['muted']}")
        if "status" in result:
            print()
    if "status" in result:
        status = result["status"]
        for key, value in status.items():
            print(f"{key}: {value}")
        return

    if "devices" in result:
        _emit_human("discover", result)


def _resolve_from_args(args: argparse.Namespace) -> CastDevice:
    host = getattr(args, "device_host", None)
    port = getattr(args, "device_port", None)
    return resolve_device(
        args.device_id,
        host=host,
        port=port,
    )


def with_controller(args: argparse.Namespace, fn: Callable[[CastController, CastDevice], Any]) -> dict[str, Any]:
    device = _resolve_from_args(args)
    controller = CastController(device)
    try:
        return fn(controller, device)
    finally:
        controller.disconnect()


def cmd_discover(args: argparse.Namespace) -> dict[str, Any]:
    devices = discover_devices(timeout=args.timeout)
    return {
        "devices": [
            device_to_json(device)
            for device in devices
            if device.uuid is not None
        ],
    }


def cmd_status(args: argparse.Namespace) -> dict[str, Any]:
    def run(controller: CastController, device: CastDevice) -> dict[str, Any]:
        status = controller.get_status()
        assert device.uuid is not None
        return {"status": status_to_json(status, device.uuid)}

    return with_controller(args, run)


def cmd_play_url(args: argparse.Namespace) -> dict[str, Any]:
    def run(controller: CastController, device: CastDevice) -> dict[str, Any]:
        content_type = args.content_type or guess_content_type(args.url)
        start_position = args.position if args.position is not None and args.position > 0 else None
        subtitles_url = args.subtitles_url.strip() if args.subtitles_url else None
        controller.play_url(
            args.url,
            content_type=content_type,
            start_position=start_position,
            subtitles_url=subtitles_url,
            subtitles_lang=args.subtitles_lang,
        )
        status = controller.wait_for_playback()
        assert device.uuid is not None
        return {"status": status_to_json(status, device.uuid)}

    return with_controller(args, run)


def cmd_play_radio(args: argparse.Namespace) -> dict[str, Any]:
    def run(controller: CastController, device: CastDevice) -> dict[str, Any]:
        content_type = args.content_type or guess_content_type(args.url, default="audio/mpeg")
        controller.play_radio(args.url, content_type=content_type)
        status = controller.wait_for_playback()
        assert device.uuid is not None
        return {"status": status_to_json(status, device.uuid)}

    return with_controller(args, run)


def cmd_pause(args: argparse.Namespace) -> dict[str, Any]:
    def run(controller: CastController, device: CastDevice) -> dict[str, Any]:
        controller.pause()
        status = controller.get_status()
        assert device.uuid is not None
        return {"status": status_to_json(status, device.uuid)}

    return with_controller(args, run)


def cmd_resume(args: argparse.Namespace) -> dict[str, Any]:
    def run(controller: CastController, device: CastDevice) -> dict[str, Any]:
        controller.resume()
        status = controller.get_status()
        assert device.uuid is not None
        return {"status": status_to_json(status, device.uuid)}

    return with_controller(args, run)


def cmd_stop(args: argparse.Namespace) -> dict[str, Any]:
    def run(controller: CastController, device: CastDevice) -> dict[str, Any]:
        controller.stop()
        status = controller.get_status()
        assert device.uuid is not None
        return {"status": status_to_json(status, device.uuid)}

    return with_controller(args, run)


def cmd_seek(args: argparse.Namespace) -> dict[str, Any]:
    def run(controller: CastController, device: CastDevice) -> dict[str, Any]:
        controller.seek(args.position)
        status = controller.get_status()
        assert device.uuid is not None
        return {"status": status_to_json(status, device.uuid)}

    return with_controller(args, run)


def cmd_volume(args: argparse.Namespace) -> dict[str, Any]:
    def run(controller: CastController, device: CastDevice) -> dict[str, Any]:
        controller.set_volume(args.level)
        status = controller.get_status()
        assert device.uuid is not None
        return {
            "volume": {
                "level": status.volume_level,
                "muted": status.volume_muted,
            },
            "status": status_to_json(status, device.uuid),
        }

    return with_controller(args, run)


def cmd_mute(args: argparse.Namespace) -> dict[str, Any]:
    def run(controller: CastController, device: CastDevice) -> dict[str, Any]:
        controller.set_volume_muted(args.muted == "true")
        status = controller.get_status()
        assert device.uuid is not None
        return {
            "volume": {
                "level": status.volume_level,
                "muted": status.volume_muted,
            },
            "status": status_to_json(status, device.uuid),
        }

    return with_controller(args, run)


if __name__ == "__main__":
    sys.exit(main())
