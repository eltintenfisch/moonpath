"""Allow running as python -m moonpath."""

from moonpath.cli_app import main

if __name__ == "__main__":
    raise SystemExit(main())
