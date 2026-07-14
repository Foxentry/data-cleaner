# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AVANTRO s.r.o.
"""The vendored dependencies live in vendor/, which is how the app itself imports them."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))
