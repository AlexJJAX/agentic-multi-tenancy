"""Optional maintenance commands; never used to launch the application."""

from __future__ import annotations

import argparse
import shutil

from app.settings import settings


def main() -> None:
    """Reset generated local state when explicitly requested."""

    parser = argparse.ArgumentParser(description="Local multi-tenant demo maintenance")
    parser.add_argument("command", choices=("reset",))
    args = parser.parse_args()
    if args.command == "reset" and settings.runtime_dir.exists():
        shutil.rmtree(settings.runtime_dir)
        print(f"Reset generated runtime state at {settings.runtime_dir}")


if __name__ == "__main__":
    main()
