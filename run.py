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


def _attach_console() -> None:
    """Windowed builds have no console, and `print()` on a `None` stdout raises.

    The GUI does not need one - it talks through the browser. But `--cli` does, so on Windows
    we attach to the console that launched us (cmd, PowerShell). Started from Explorer there is
    none, so we open one.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        if not kernel32.AttachConsole(-1):       # -1 = the parent's console
            kernel32.AllocConsole()
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
        sys.stdin = open("CONIN$", "r", encoding="utf-8", errors="replace")
    except Exception:
        pass


def _silence_missing_streams() -> None:
    """A windowed build has `sys.stdout is None`. Every `print()` would raise, so the app would
    die before it ever opened a window - with nothing to show for it. Send them to the log
    instead: a failure has to be diagnosable, and there is no console to read."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        from foxentry.config import LOG_DIR
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        sink = open(LOG_DIR / "app.log", "a", encoding="utf-8", errors="replace", buffering=1)
    except Exception:
        import os
        sink = open(os.devnull, "w")
    if sys.stdout is None:
        sys.stdout = sink
    if sys.stderr is None:
        sys.stderr = sink


def _fatal(exc: BaseException) -> None:
    """Without a console, a crash is a window that never appears. Say something."""
    from foxentry.config import LOG_DIR
    message = f"Foxentry Data Cleaner could not start.\n\n{exc}\n\nSee {LOG_DIR / 'app.log'}"
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "Foxentry Data Cleaner", 0x10)
        elif sys.platform == "darwin":
            import subprocess
            # The message goes in as an ARGUMENT, not baked into the script. A path in the
            # exception text carries double quotes, and interpolating those straight into the
            # AppleScript breaks its syntax - so the one dialog that exists to show a
            # startup failure would itself fail, silently, inside the try/except.
            script = ('on run argv\n'
                      '  display alert "Foxentry Data Cleaner" message (item 1 of argv) as critical\n'
                      'end run')
            subprocess.run(["osascript", "-e", script, str(exc)], check=False)
        else:
            sys.stderr.write(message + "\n")
    except Exception:
        pass


def main() -> int:
    args = sys.argv[1:]
    if "--cli" in args:
        _attach_console()
        from foxentry.cli import main as cli_main
        return cli_main()
    _silence_missing_streams()
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
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as exc:                  # noqa: BLE001 - last resort, then re-raise
        _fatal(exc)
        raise
