# -*- mode: python ; coding: utf-8 -*-
# Build (run from anywhere):  pyinstaller packaging/foxentry.spec --clean
#   -> dist/FoxentryDataCleaner.exe
# Must run on the TARGET OS (PyInstaller does not cross-compile). Windows here.
import os
import sys
from datetime import datetime
from PyInstaller.utils.hooks import collect_submodules

# This spec lives in packaging/. Resolve every path from the spec's own folder so
# the build does not depend on the current working directory.
SPEC_DIR = SPECPATH                       # injected by PyInstaller = packaging/
ROOT = os.path.dirname(SPEC_DIR)          # repo root


def R(*parts):
    return os.path.join(ROOT, *parts)


def _version_from_package() -> str:
    """The one place the version lives. Repeating it here is how SBOMs go stale."""
    with open(R("foxentry", "__init__.py"), encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("__version__"):
                return line.split('"')[1]
    raise SystemExit("no __version__ in foxentry/__init__.py")


_APP_VERSION = _version_from_package()

# The build number, and it must differ on every build.
#
# macOS caches Info.plist per bundle identifier + version. Ten test builds that all called
# themselves 2.1.0 meant LaunchServices read the plist from the FIRST one and ignored the rest -
# so a fix to the plist looked like it had not worked, when in fact it had never been read.
# CI passes its run number; a local build gets the clock.
_BUILD = os.environ.get("FOXENTRY_BUILD") or datetime.now().strftime("%Y%m%d%H%M")


# Read-only bundled resources. Layout of this project:
#   - wizard.html + assets/ live INSIDE the foxentry/ package
#   - the HTML guides (documentation, setup-guide, log-viewer) live in docs/
# At runtime config.RESOURCE_ROOT == sys._MEIPASS, so destinations must match:
#   "foxentry/..." -> _MEIPASS/foxentry/...    "docs" -> _MEIPASS/docs/...
datas = [
    (R("foxentry", "wizard.html"), "foxentry"),
    (R("foxentry", "assets"), "foxentry/assets"),
    (R("docs", "documentation.html"), "docs"),
    (R("docs", "setup-guide.html"), "docs"),
    (R("docs", "log-viewer.html"), "docs"),
]

# openpyxl is bundled so XLSX works offline with no pip at runtime.
hidden = collect_submodules("openpyxl") + ["et_xmlfile"]

a = Analysis(
    [R("run.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

# Per-OS packaging details. PyInstaller does not cross-compile: this spec runs on
# each target OS in CI and picks the right icon / version resource there.
if sys.platform.startswith("win"):
    _icon = R("foxentry", "assets", "icon.ico")
    _version = os.path.join(SPEC_DIR, "version.txt")   # Windows version resource
elif sys.platform == "darwin":
    _icon = R("foxentry", "assets", "icon.icns")
    _version = None
else:  # linux
    _icon = None                                        # no embedded icon on Linux
    _version = None

# Windows and Linux: one file. That is the whole point of them - download it, put it where you
# like, run it. The bootloader unpacks the interpreter to a temp folder on each start, which
# costs a second or two, and that is the price of a single portable file.
#
# macOS: NOT one file. Inside a .app bundle there is nothing to be portable about - the bundle
# IS the unit you move around. Packing it into a single file only means unpacking 40 MB into a
# temp folder on every launch, and the app sat there for four seconds doing it before the
# window appeared. In a bundle the files simply lie next to each other and it starts at once.
_ONEDIR = sys.platform == "darwin"

exe = EXE(
    pyz,
    a.scripts,
    [] if _ONEDIR else a.binaries,
    [] if _ONEDIR else a.datas,
    [],
    exclude_binaries=_ONEDIR,
    name="FoxentryDataCleaner",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                                   # UPX can trip antivirus heuristics; leave off
    # No console window on the desktop platforms: the browser IS the window, and a black box
    # sitting behind it is what people close by accident or leave running for days. A windowed
    # build has no stdout, so `run.py` sends output to logs/app.log and puts a native dialog up
    # if the app cannot start - a crash with no console is otherwise a window that never opens.
    # `--cli` attaches to the console it was launched from.
    # Linux has no bundle and is run from a terminal, so it keeps its console.
    console=not (sys.platform.startswith("win") or sys.platform == "darwin"),
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=_version,
    icon=_icon,
)

# macOS: wrap the executable in a .app bundle.
#
# The bare Unix binary we used to ship could not be double-clicked: a browser download strips
# the execute bit, and Finder has nothing to do with an extensionless file. It needed a
# terminal and `chmod +x`, which is not a desktop app. A bundle also lets the notarization
# ticket be STAPLED to it - a loose binary cannot be stapled, so it needed Apple online on
# first launch.
#
# The app writes nothing inside the bundle (that would break the signature and fail in
# /Applications): `config.data_dir()` puts its folder in ~/Documents instead.
if _ONEDIR:
    collected = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name="FoxentryDataCleaner",
    )
    app = BUNDLE(
        collected,
        name="Foxentry Data Cleaner.app",
        icon=_icon,
        bundle_identifier="cz.avantro.foxentry.datacleaner",
        version=_APP_VERSION,
        info_plist={
            "CFBundleShortVersionString": _APP_VERSION,      # what the user sees: 2.1.0
            "CFBundleVersion": f"{_APP_VERSION}.{_BUILD}",   # what macOS caches on: unique
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "NSHumanReadableCopyright": "Copyright 2026 AVANTRO s.r.o. Apache-2.0.",
            # A Dock icon. The app has no window of its own - the browser is the window - so the
            # icon does not open anything. It is there because a running app with no trace in
            # the Dock has no trace anywhere: bury the browser window behind other windows and
            # the user has nothing to click and no way to tell the app is still running.
            #
            # Clicking the icon cannot bring the window back (this is not an AppKit app), so
            # LAUNCHING IT AGAIN does instead: a second launch finds the first one and reopens
            # its window rather than starting a second server. That is what a user does anyway.
            "LSUIElement": False,
        },
    )
