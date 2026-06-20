# -*- mode: python ; coding: utf-8 -*-
# Build (run from anywhere):  pyinstaller packaging/foxentry.spec --clean
#   -> dist/FoxentryDataCleaner.exe
# Must run on the TARGET OS (PyInstaller does not cross-compile). Windows here.
import os
import sys
from PyInstaller.utils.hooks import collect_submodules

# This spec lives in packaging/. Resolve every path from the spec's own folder so
# the build does not depend on the current working directory.
SPEC_DIR = SPECPATH                       # injected by PyInstaller = packaging/
ROOT = os.path.dirname(SPEC_DIR)          # repo root


def R(*parts):
    return os.path.join(ROOT, *parts)


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

# --onefile is the default for EXE() when COLLECT is not used.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="FoxentryDataCleaner",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                                   # UPX can trip antivirus heuristics; leave off
    console=True,                                # small console prints the localhost URL + errors
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=_version,
    icon=_icon,
)
