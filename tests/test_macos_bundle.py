# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AVANTRO s.r.o.
"""
The macOS app must not write inside its own bundle, and must be quittable.

Both are invisible until a user hits them: writing into the bundle breaks the code signature
(and fails outright in /Applications), and an app with no console and no Quit button cannot be
stopped except by force.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from foxentry import config


def test_the_app_bundle_writes_to_documents(monkeypatch, tmp_path) -> None:
    """Inside a .app, the writable folder is in Documents, never in the bundle."""
    bundle = tmp_path / "Applications" / "Foxentry Data Cleaner.app" / "Contents" / "MacOS"
    bundle.mkdir(parents=True)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "executable", str(bundle / "FoxentryDataCleaner"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    data = config.data_dir()
    assert data == tmp_path / "Documents" / "Foxentry Data Cleaner"
    assert ".app/" not in str(data)


def test_a_plain_executable_stays_portable(monkeypatch, tmp_path) -> None:
    """Windows and Linux keep the folder next to the executable - copy it to a stick and the
    working folder travels with it."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "FoxentryDataCleaner.exe"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert config.data_dir() == tmp_path


WIZARD = (Path(__file__).resolve().parent.parent / "foxentry" / "wizard.html").read_text(encoding="utf-8")
SERVER = (Path(__file__).resolve().parent.parent / "foxentry" / "server.py").read_text(encoding="utf-8")


RUN_PY = (Path(__file__).resolve().parent.parent / "run.py").read_text(encoding="utf-8")
SPEC = (Path(__file__).resolve().parent.parent / "packaging" / "foxentry.spec").read_text(encoding="utf-8")


def test_the_window_closing_stops_the_app() -> None:
    """The page says it is going away; the server schedules the stop; anything that talks to it
    before the deadline cancels that. A reload cancels its own shutdown by loading."""
    assert '"/api/window-closing"' in SERVER
    assert "_note_browser" in SERVER, "any request must cancel a pending close"
    assert "pagehide" in WIZARD and "keepalive" in WIZARD


def test_it_is_not_a_heartbeat() -> None:
    """A heartbeat cannot work here, and this is the bug it caused.

    Browsers throttle timers in a background tab to one tick per minute, and `confirm()` blocks
    the event loop entirely. Both look exactly like a closed window. The first build of this
    feature used `setInterval`, and opening the Quit dialog and hesitating for four seconds
    killed the server underneath the user: the page stayed on screen and every button stopped
    working.
    """
    assert "setInterval" not in WIZARD, "a timer cannot decide whether the window is open"
    assert "_LAST_PING" not in SERVER


def test_a_reload_has_time_to_come_back() -> None:
    import re
    grace = float(re.search(r"_CLOSE_GRACE\s*=\s*([\d.]+)", SERVER).group(1))
    assert grace >= 3, "a reload on a slow machine must not be read as a closed window"


def test_a_windowed_build_can_still_speak() -> None:
    """No console means `sys.stdout is None` and every print() raises - the app would die
    before opening a window, with nothing to show for it."""
    assert "_silence_missing_streams" in RUN_PY
    assert "_fatal" in RUN_PY, "a crash with no console is a window that never appears"
    assert "_attach_console" in RUN_PY, "--cli still needs a console on Windows"


def test_the_console_is_off_where_there_is_a_window() -> None:
    assert 'console=not (sys.platform.startswith("win") or sys.platform == "darwin")' in SPEC


def test_the_app_can_be_quit_from_the_interface() -> None:
    """A macOS .app has no console, so Ctrl+C is not an answer."""
    assert 'onclick="quitApp()"' in WIZARD
    assert '"/api/quit"' in SERVER or "'/api/quit'" in SERVER


@pytest.mark.parametrize("key", ["quit_title", "quit_confirm", "quit_done"])
def test_the_quit_strings_exist_in_both_languages(key: str) -> None:
    assert WIZARD.count(f"{key}:") == 2


def test_the_loopback_server_does_not_ask_the_network_who_it_is() -> None:
    """`HTTPServer.server_bind()` resolves the host name, and on macOS that goes out over mDNS -
    which makes macOS 15 ask the user to allow "finding devices on your local network". On a
    tool that promises the data stays on the machine, that dialog is worse than a bug."""
    assert "class LoopbackServer" in SERVER
    assert "socketserver.TCPServer.server_bind" in SERVER
    assert "ThreadingHTTPServer((" not in SERVER, "the stock server resolves the host name"


def test_the_macos_app_is_not_packed_into_a_single_file() -> None:
    """A one-file build unpacks the whole interpreter on every launch. In a .app that buys
    nothing - the bundle is already the unit you move around - and costs four seconds of
    staring at the Dock."""
    assert '_ONEDIR = sys.platform == "darwin"' in SPEC
    assert "COLLECT(" in SPEC
    assert "exclude_binaries=_ONEDIR" in SPEC
