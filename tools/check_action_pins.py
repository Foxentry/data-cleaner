# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AVANTRO s.r.o.
"""
Check that every GitHub Action is pinned to an immutable commit SHA.

MAINTAINER TOOL, run in CI.

    python tools/check_action_pins.py

A tag is a label. `actions/checkout@v7` means "whatever v7 points at today", and whoever
controls that repository can move it tomorrow. In `release.yml` that matters more than
anywhere else: those jobs hold the code-signing credentials, so a moved tag would run
someone else's code with our certificate.

A 40-character commit SHA cannot be moved. Every action therefore carries one, with the
human-readable version in a trailing comment so the file stays readable and Dependabot can
still propose updates:

    uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0

This is what the OpenSSF Scorecard Pinned-Dependencies check looks for, and the repository
carries that badge. The check exists so the claim cannot quietly stop being true.
"""

from __future__ import annotations

import pathlib
import re
import sys

WORKFLOWS = pathlib.Path(__file__).resolve().parent.parent / ".github" / "workflows"

USES = re.compile(r"^\s*-?\s*uses:\s*(?P<action>[^@\s]+)@(?P<ref>\S+)(?:\s*#\s*(?P<version>\S+))?")
SHA = re.compile(r"^[0-9a-f]{40}$")


def main() -> None:
    unpinned: list[str] = []
    pinned = 0

    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        for number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), 1):
            match = USES.match(line)
            if not match:
                continue
            action, ref, version = match["action"], match["ref"], match["version"]

            # A local action (./.github/actions/…) is our own code, not a third party's.
            if action.startswith("./"):
                continue

            if not SHA.match(ref):
                unpinned.append(f"{workflow.name}:{number}  {action}@{ref}")
            elif not version:
                unpinned.append(f"{workflow.name}:{number}  {action}@{ref[:12]}… "
                                f"(pinned, but no version comment)")
            else:
                pinned += 1
                print(f"   ok   {workflow.name:18} {action}@{version}")

    if unpinned:
        print("\nNot pinned to an immutable commit SHA:", file=sys.stderr)
        for item in unpinned:
            print(f"  {item}", file=sys.stderr)
        sys.exit("\nPin them: uses: owner/action@<40-char sha> # vX.Y.Z")

    print(f"\nAll {pinned} actions are pinned to a commit SHA.")


if __name__ == "__main__":
    main()
