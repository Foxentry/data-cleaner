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
    """The browser is the window. The page says "still here" every couple of seconds, and the
    server stops when that stops - a close and a reload are indistinguishable to the page, so
    there is no way to react to a close instantly, and a grace period is what keeps F5 from
    killing the app."""
    assert '"/api/ping"' in SERVER
    assert "_watchdog" in SERVER
    assert '/api/ping' in WIZARD and "setInterval" in WIZARD


def test_the_grace_period_survives_a_reload() -> None:
    """A reload is back within a second. The grace has to be longer than that, and long enough
    that a slow page load does not read as a closed window."""
    import re
    grace = float(re.search(r"_PING_GRACE\s*=\s*([\d.]+)", SERVER).group(1))
    every = float(re.search(r"_PING_EVERY\s*=\s*([\d.]+)", SERVER).group(1))
    assert every < grace, "the page must ping more often than the server gives up"
    assert grace >= 2 * every, "one missed ping must not be enough to kill the app"


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
