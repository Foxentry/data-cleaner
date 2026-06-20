"""Open the local wizard UI like a standalone app window.

When a Chromium-based browser (Chrome / Edge / Brave / Chromium) is available we
launch it in *app mode* (``--app=URL``): a chromeless window with no address bar
or tabs, so it reads as a native app — while still using the user's own, system
browser (no bundled rendering engine, nothing extra to audit). If no such browser
is found, we fall back to the default browser tab. Both paths are best-effort:
the server keeps running regardless, the URL is always printed to the console.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _candidates() -> list[str]:
    """Chromium-based browser executables that support ``--app=``, in priority order."""
    if sys.platform.startswith("win"):
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pfx86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local = os.environ.get("LocalAppData", "")
        paths = [
            rf"{pf}\Google\Chrome\Application\chrome.exe",
            rf"{pfx86}\Google\Chrome\Application\chrome.exe",
            rf"{local}\Google\Chrome\Application\chrome.exe",
            rf"{pf}\Microsoft\Edge\Application\msedge.exe",          # preinstalled on Win 10/11
            rf"{pfx86}\Microsoft\Edge\Application\msedge.exe",
            rf"{pf}\BraveSoftware\Brave-Browser\Application\brave.exe",
        ]
        return [p for p in paths if p and Path(p).is_file()]
    if sys.platform == "darwin":
        apps = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
        return [p for p in apps if Path(p).is_file()]
    # linux
    names = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
             "microsoft-edge", "microsoft-edge-stable", "brave-browser"]
    out = []
    for n in names:
        p = shutil.which(n)
        if p:
            out.append(p)
    return out


def open_ui(url: str, app_mode: bool = True) -> str:
    """Open the wizard UI. Returns the mode actually used: 'app', 'browser', or 'none'."""
    if app_mode:
        for exe in _candidates():
            try:
                # --app => chromeless window. A unique --class/title helps the OS treat it
                # as its own window. We deliberately do NOT set --user-data-dir so we don't
                # leave a profile folder behind (portable build); the user's default profile is used.
                subprocess.Popen(
                    [exe, f"--app={url}", "--new-window"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return "app"
            except Exception:
                continue
    try:
        import webbrowser
        if webbrowser.open(url):
            return "browser"
    except Exception:
        pass
    return "none"
