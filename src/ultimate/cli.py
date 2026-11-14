"""CLI entrypoint and ASCII wordmark banner for ULTIMATE."""

from __future__ import annotations

import argparse
import os
import sys

_WORDMARK = (
    " _   _ _   _____ ___ __  __    _  _____ _____ ",
    "| | | | | |_   _|_ _|  \\/  |  / \\|_   _| ____|",
    "| | | | |   | |  | || |\\/| | / _ \\ | | |  _|  ",
    "| |_| | |___| |  | || |  | |/ ___ \\| | | |___ ",
    " \\___/|_____|_| |___|_|  |_/_/   \\_\\_| |_____|",
)

_TAGLINE = "Tri-Anchor Autonomous OS | Laptop + Phone + Voice Core"


def print_banner() -> None:
    try:
        from rich.console import Console

        console = Console()
        for line in _WORDMARK:
            console.print(line, style="bold bright_blue", highlight=False, markup=False)
        console.print(f"      {_TAGLINE}", style="cyan", highlight=False, markup=False)
        console.print()
    except ImportError:
        for line in _WORDMARK:
            print(line)
        print(f"      {_TAGLINE}")
        print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ultimate", description="ULTIMATE Control CLI")
    sub = parser.add_subparsers(dest="command")

    srv = sub.add_parser("serve", help="Start the ULTIMATE FastAPI server")
    srv.add_argument("--host", default="0.0.0.0")
    srv.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    print_banner()

    if args.command == "serve" or args.command is None:
        import uvicorn

        from ultimate.server.app import create_app

        host = getattr(args, "host", "0.0.0.0")
        port = getattr(args, "port", 8000)
        app = create_app(api_key=os.environ.get("ULTIMATE_API_KEY"))
        uvicorn.run(app, host=host, port=port)
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
