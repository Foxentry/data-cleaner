# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AVANTRO s.r.o.
"""
Check that every file agreeing on the version actually agrees on the version.

MAINTAINER TOOL. Six files carry the release number, and the ones a corporate reviewer
opens first - the SBOM, the security questionnaire, the documentation banner - are exactly
the ones nobody remembers to bump. The 1.0.1 release shipped with an SBOM that still said
1.0.0. This makes CI catch that instead of a customer.

    python tools/check_release.py             # all files must agree with foxentry/__init__.py
    python tools/check_release.py --tag v2.0.0    # ... and with the tag being released
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _read(relative: str) -> str:
    path = ROOT / relative
    if not path.exists():
        sys.exit(f"Missing file: {relative}")
    return path.read_text(encoding="utf-8")


def _find(relative: str, pattern: str) -> str:
    match = re.search(pattern, _read(relative))
    if not match:
        sys.exit(f"No version found in {relative} (pattern: {pattern})")
    return match.group(1)


def versions() -> dict[str, str]:
    """Every place the release number is written down."""
    sbom = json.loads(_read("compliance/sbom.cdx.json"))
    docs = _read("docs/documentation.html")
    banners = set(re.findall(r"v(\d+\.\d+\.\d+) &nbsp;·&nbsp; API:", docs))
    if len(banners) != 1:
        sys.exit(f"documentation.html: language banners disagree: {sorted(banners) or 'none found'}")

    # SECURITY.md holds a table, not a single number: the released series must be listed as
    # supported. It is the one file that is easy to forget, so it is checked here rather than
    # left to whoever remembers.
    supported = set(re.findall(r"\|\s*(\d+\.\d+)\.x\s*\|\s*:white_check_mark:", _read(".github/SECURITY.md")))

    return {
        "foxentry/__init__.py": _find("foxentry/__init__.py", r'__version__ = "([^"]+)"'),
        "packaging/version.txt": ".".join(
            _find("packaging/version.txt", r'"FileVersion", "([^"]+)"').split(".")[:3]),
        "compliance/sbom.cdx.json": sbom["metadata"]["component"]["version"],
        "compliance/VENDOR-SECURITY.md": _find("compliance/VENDOR-SECURITY.md", r"Version (\d+\.\d+\.\d+)\."),
        "docs/documentation.html": banners.pop(),
        "CHANGELOG.md": _find("CHANGELOG.md", r"## \[(\d+\.\d+\.\d+)\]"),
        ".github/SECURITY.md": _supported_series(supported),
    }


def _supported_series(supported: set) -> str:
    """The security policy lists series (`2.0.x`), not versions. Report it as a version so it
    lines up with the others; the caller compares only the major.minor part."""
    return ", ".join(sorted(supported)) or "none"


def main() -> None:
    parser = argparse.ArgumentParser(description="Check that the release version is consistent")
    parser.add_argument("--tag", help="the tag being released, e.g. v2.0.0")
    args = parser.parse_args()

    found = versions()
    expected = args.tag.lstrip("v") if args.tag else found["foxentry/__init__.py"]
    series = ".".join(expected.split(".")[:2])          # 2.0.0 -> 2.0

    width = max(len(f) for f in found)
    wrong = {}
    for file, version in found.items():
        ok = (series in version.split(", ")) if file == ".github/SECURITY.md" else (version == expected)
        if not ok:
            wrong[file] = version
    for file, version in found.items():
        print(f"  {'FAIL' if file in wrong else ' ok '}  {file:<{width}}  {version}")

    if wrong:
        sys.exit(f"\nExpected {expected} everywhere ({series}.x in the security policy). "
                 f"Bump: {', '.join(wrong)}")
    print(f"\nAll files agree on {expected}.")


if __name__ == "__main__":
    main()
