# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AVANTRO s.r.o.
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


def show_in_dock() -> bool:
    """Ask macOS to keep this process in the Dock. NOT CALLED - kept as a record of what does
    not work.

    Registering as a regular app does put an icon in the Dock, but there is no AppKit run loop
    to service it: the icon bounces without end and ignores every click. That is worse than no
    icon. A working Dock presence needs a native macOS app, which this - a Python process
    serving a browser UI - is not. Left here so the next person does not rediscover it the hard
    way.

    The app is a Python process that runs a web server; the window it shows is a browser
    window. macOS gives a Dock icon to processes that register with the window server, and a
    plain Python process never does - the icon appears for a moment at launch and is dropped.
    `LSUIElement: false` in the bundle does not change that: there is nothing to hold the icon.

    So we register: `[[NSApplication sharedApplication] setActivationPolicy:Regular]`, called
    straight through the Objective-C runtime with ctypes. No new dependency, about thirty lines.

    If any of it fails, we carry on without a Dock icon - exactly as before. A missing icon is a
    blemish; an app that will not start is not.
    """
    if sys.platform != "darwin":
        return False
    try:
        import ctypes
        import ctypes.util

        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        ctypes.cdll.LoadLibrary("/System/Library/Frameworks/AppKit.framework/AppKit")

        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]

        # objc_msgSend has no single signature - it is cast per call.
        send_id = ctypes.cast(objc.objc_msgSend,
                              ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p))
        send_policy = ctypes.cast(objc.objc_msgSend,
                                  ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p,
                                                   ctypes.c_void_p, ctypes.c_long))

        app_class = objc.objc_getClass(b"NSApplication")
        app = send_id(app_class, objc.sel_registerName(b"sharedApplication"))
        if not app:
            return False
        # NSApplicationActivationPolicyRegular = 0: an app with a Dock icon.
        return bool(send_policy(app, objc.sel_registerName(b"setActivationPolicy:"), 0))
    except Exception:
        return False
