"""Windows release entry point: command-line access and built-in self-test."""

from file_integrity_timeline.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
