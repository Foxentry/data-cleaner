# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AVANTRO s.r.o.
"""
The macOS app must not write inside its own bundle, and must be quittable.

Both are invisible until a user hits them: writing into the bundle breaks the code signature
(and fails outright in /Applications), and an app with no console and no Quit button cannot be
stopped except by force.
"""

from __future__ import annotations

import json
import sys
import threading
import time
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


def test_the_watchdog_waits_out_a_reload_but_stops_a_close(monkeypatch) -> None:
    """`pagehide` fires on a reload AND a close, and nothing tells them apart. So the server
    does not decide: it schedules the stop and lets anything that talks to it cancel that. A
    reload is back in under a second; a closed window never comes back.

    This runs the real watchdog against a fake server, through all three transitions, rather
    than grepping the source for the strings that implement them."""
    from foxentry import server

    class FakeServer:
        def __init__(self):
            self.stopped = False

        def shutdown(self):
            self.stopped = True

    monkeypatch.setattr(server, "_CLOSE_GRACE", 0.3)
    monkeypatch.setattr(server, "_NO_CONSOLE", False)
    monkeypatch.setattr(server, "_SEEN_BROWSER", True)
    monkeypatch.setattr(server, "_CLOSING", 0.0)

    srv = FakeServer()
    threading.Thread(target=server._watchdog, args=(srv, time.monotonic()), daemon=True).start()

    server._CLOSING = time.monotonic()          # "going away"
    time.sleep(0.15)
    assert srv.stopped is False                 # still inside the grace - we wait

    server._CLOSING = 0.0                        # the reload arrived - cancel
    time.sleep(0.5)
    assert srv.stopped is False                 # a reload must not read as a close

    server._CLOSING = time.monotonic()           # a real close
    time.sleep(0.6)
    assert srv.stopped is True                  # the window is gone and nothing came back


def test_the_close_notice_and_the_cancel_are_wired_in_the_page() -> None:
    """The JS side cannot run in pytest, so the wiring itself stays a source check: the page
    must send the close notice, and it must use keepalive so the request survives the unloading
    page. The decision logic it drives is covered behaviourally above."""
    assert '"/api/window-closing"' in SERVER and "_note_browser" in SERVER
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


API = (Path(__file__).resolve().parent.parent / "foxentry" / "api.py").read_text(encoding="utf-8")


def test_tls_verification_is_never_turned_off() -> None:
    """A frozen macOS build gets no certificates from OpenSSL - macOS keeps its roots in a
    keychain - so every HTTPS call failed with "unable to get local issuer certificate". The
    answer is to hand it the roots the system trusts, never to stop checking them."""
    assert "_system_roots_pem" in API
    assert "CERT_NONE" not in API
    assert "check_hostname = False" not in API
    assert "_unverified" not in API


def test_the_corporate_proxy_root_is_included() -> None:
    """A company that inspects TLS puts its root in the System keychain. Read only Apple's own
    and the app fails inside exactly the networks it is written for."""
    assert "/Library/Keychains/System.keychain" in API


def test_a_second_launch_reopens_the_window() -> None:
    """The window is a browser window, and a browser window gets buried. When it does, the user
    relaunches the app - and a second server on a second port, one of them holding a
    half-finished run, is not what they asked for."""
    assert "_running_instance" in SERVER
    assert '"/api/whoami"' in SERVER, "the port has to be checked, not trusted"


def test_a_stale_instance_file_is_not_believed(tmp_path, monkeypatch) -> None:
    """After a crash the instance file points at a port that is gone - or at whatever took it
    since. A second launch must not trust it: it checks the port, and a dead one means no
    instance. Runs the real _running_instance() against a dead port, not a grep."""
    from foxentry import server
    monkeypatch.setattr(server, "_INSTANCE_FILE", tmp_path / ".foxentry-running.json")
    server._INSTANCE_FILE.write_text(
        json.dumps({"port": 59999, "token": "x", "pid": 1}), encoding="utf-8")   # 59999 = nothing
    assert server._running_instance() is None


def test_quitting_from_the_dock_is_not_a_kill() -> None:
    """Cmd+Q should stop the app the way the Quit button does, not interrupt it mid-row."""
    assert "signal.SIGTERM" in SERVER



def test_every_build_gets_its_own_number() -> None:
    """macOS caches Info.plist per bundle id + version. Ten test builds all calling themselves
    2.1.0 meant the system read the plist from the first one and ignored every fix after it -
    a fix that looked broken because it was never read."""
    assert "_BUILD" in SPEC
    assert 'os.environ.get("FOXENTRY_BUILD")' in SPEC
    assert '"CFBundleVersion": f"{_APP_VERSION}.{_BUILD}"' in SPEC


APPLAUNCH = (Path(__file__).resolve().parent.parent / "foxentry" / "applaunch.py").read_text(encoding="utf-8")


def test_the_dock_registration_is_not_wired_in() -> None:
    """Registering as a regular app put an icon in the Dock, but with no AppKit run loop it
    bounced forever and answered no clicks - worse than no icon. show_in_dock() is kept as a
    documented dead-end, but nothing calls it, and the bundle hides from the Dock."""
    assert "show_in_dock()" not in SERVER, "the broken Dock registration must stay unwired"
    assert '"LSUIElement": True' in SPEC


def test_it_does_nothing_off_macos(monkeypatch) -> None:
    import sys as _sys
    from foxentry import applaunch
    monkeypatch.setattr(_sys, "platform", "win32")
    assert applaunch.show_in_dock() is False


def test_linux_is_not_abandoned_when_no_browser_opens() -> None:
    """The give-up timer exists because a windowed build with no browser is an invisible process
    nobody can stop. Linux is run from a terminal: it prints its URL, Ctrl+C works, and people
    open that URL by hand or forward the port over SSH minutes later. It has to still be there."""
    assert "_NO_CONSOLE and not _SEEN_BROWSER" in SERVER
    assert 'sys.platform in ("win32", "darwin")' in SERVER


def test_a_handler_crash_is_logged_and_returned() -> None:
    """The tester hit a broken page with nothing in app.log. An unhandled error in a handler
    used to fall through to a blank 500 and write nothing; now it is logged with a traceback
    and returned as a 500 that names the log."""
    assert "_guard" in SERVER
    assert "applog.exception" in SERVER
    assert "see logs/app.log" in SERVER


def test_the_access_log_silence_does_not_swallow_errors() -> None:
    """`log_message` was overridden to `pass`, which also threw away the error path that records
    a failed request. `log_error` now routes those to the app log."""
    assert "def log_error" in SERVER


def test_startup_records_the_environment() -> None:
    """A bad report is undebuggable without knowing the platform, the build, and where files
    went. The startup lines carry all three."""
    assert "platform=%s" in SERVER and "frozen=%s" in SERVER and "data_dir=%s" in SERVER
