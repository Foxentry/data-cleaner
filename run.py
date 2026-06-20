#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AVANTRO s.r.o.
"""
Foxentry Data Cleaner launcher.

Default: opens the wizard in the browser (local server).
  python run.py
Text mode (no browser):
  python run.py --cli
"""

import sys

if sys.version_info < (3, 9):
    sys.stderr.write("Python 3.9+ required / Python 3.9 or newer is required.\n")
    raise SystemExit(1)

# Vendored dependencies - isolated next to the app, without touching the
# global environment. openpyxl is installed here too (UI button / offline).
# In a frozen build openpyxl is bundled by PyInstaller, so skip the vendor hack.
import pathlib as _pathlib
if not getattr(sys, "frozen", False):
    _vendor = _pathlib.Path(__file__).resolve().parent / "vendor"
    if _vendor.is_dir() and str(_vendor) not in sys.path:
        sys.path.insert(0, str(_vendor))


def main() -> int:
    args = sys.argv[1:]
    if "--cli" in args:
        from foxentry.cli import main as cli_main
        return cli_main()
    # default: web wizard
    from foxentry.server import start_server
    port = 0
    if "--port" in args:
        try:
            port = int(args[args.index("--port") + 1])
        except (ValueError, IndexError):
            port = 0
    open_writer = "--no-open" not in args
    start_server(port=port, open_writer=open_writer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
