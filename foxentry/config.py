# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AVANTRO s.r.o.
"""
Configuration loading.

Configuration is read in this priority order:
  1. Environment variables (OS environment)
  2. The `config.env` file in the project root
  3. The `.env` file in the project root
  4. Default values

No third-party dependency - a simple, auditable parser.
The API key is NEVER written or printed anywhere.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def resource_dir() -> Path:
    """Read-only bundled files (HTML, assets). Works both frozen (PyInstaller)
    and when running from source. Frozen: the temp extraction dir (sys._MEIPASS);
    from source: the project root (parent of the `foxentry` package)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")).resolve()
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """Writable location for config.env, logs/, input/, output/, session.
    Frozen: next to the exe (portable). From source: the project root."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent   # portable: next to the exe
    return Path(__file__).resolve().parent.parent


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


# Read-only resources (bundled HTML at the project root) vs. writable data.
# From source both point at the project root, so behaviour is unchanged.
RESOURCE_ROOT = resource_dir()
DATA_ROOT = data_dir()

# Kept for backward compatibility. All historical ROOT uses are writable
# (config.env/.env, session, input/output/logs) -> the data location.
ROOT = DATA_ROOT

INPUT_DIR = DATA_ROOT / "input"
OUTPUT_DIR = DATA_ROOT / "output"
LOG_DIR = DATA_ROOT / "logs"


def _ensure_data_dirs() -> None:
    """At start make sure the writable folders exist (portable build runs from a
    read-only Program Files; the IO folders live next to the exe)."""
    for d in (INPUT_DIR, OUTPUT_DIR, LOG_DIR):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass


_ensure_data_dirs()


def _parse_env_file(path: Path) -> dict[str, str]:
    """Very simple .env file parser. Lines `KEY=value`, # = comment."""
    data: dict[str, str] = {}
    if not path.is_file():
        return data
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            data[key] = value
    return data


ALIASES = {                                   # new EN key -> old Czech aliases
    "LANGUAGE": ["JAZYK"],
    "TEST_SAMPLE": ["TESTOVACI_VZOREK"],
    "DEFAULT_COUNTRY": ["VYCHOZI_ZEME"],
    "INPUT_ENCODING": ["VSTUP_KODOVANI"],
    "OUTPUT_ENCODING": ["VYSTUP_KODOVANI"],
    "RATE_LIMIT_RESERVE": ["RATE_LIMIT_REZERVA"],
    "CSV_INJECTION_GUARD": ["CSV_INJEKCE_OCHRANA"],
}


class Config:
    """Holds all application settings."""

    def __init__(self) -> None:
        file_cfg: dict[str, str] = {}
        file_cfg.update(_parse_env_file(ROOT / "config.env"))
        file_cfg.update(_parse_env_file(ROOT / ".env"))

        def get(key: str, default: str = "") -> str:
            # config.env takes precedence (managed in the wizard); the OS environment is only
            # a fallback. The order used to be reversed and a stale env var silently overrode
            # the stored key -> 401. We also accept older Czech aliases.
            for k in (key, *ALIASES.get(key, [])):
                if k in file_cfg:
                    return file_cfg[k].strip()
            for k in (key, *ALIASES.get(key, [])):
                if k in os.environ:
                    return os.environ[k].strip()
            return default

        # determine where the API key came from (for log diagnostics)
        self.api_key: str = get("FOXENTRY_API_KEY", "")
        if "FOXENTRY_API_KEY" in file_cfg and file_cfg["FOXENTRY_API_KEY"].strip():
            self.api_key_source = "config.env/.env"
        elif "FOXENTRY_API_KEY" in os.environ:
            self.api_key_source = "OS environment"
        else:
            self.api_key_source = "—"
        # warn if an env var shadowed the stored key (informational only)
        self.api_key_env_shadow = bool(
            file_cfg.get("FOXENTRY_API_KEY", "").strip()
            and os.environ.get("FOXENTRY_API_KEY", "").strip()
            and file_cfg["FOXENTRY_API_KEY"].strip() != os.environ["FOXENTRY_API_KEY"].strip()
        )
        self.api_url: str = get("FOXENTRY_API_URL", "https://api.foxentry.com").rstrip("/")
        self.api_version: str = get("FOXENTRY_API_VERSION", "2.1")

        # App language (en default). Also accepts the older JAZYK key.
        self.lang: str = (get("LANGUAGE", "en") or "en").lower()

        # Default test batch size
        try:
            self.test_sample: int = max(1, int(get("TEST_SAMPLE", "5")))
        except ValueError:
            self.test_sample = 5

        # Default country for validations where it makes sense
        self.default_country: str = get("DEFAULT_COUNTRY", "CZ").upper() or "CZ"

        # Safety margin below the rate limit (0.0 - 1.0). 0.9 = run at 90% of the limit.
        try:
            self.rate_safety: float = float(get("RATE_LIMIT_RESERVE", "0.85"))
        except ValueError:
            self.rate_safety = 0.85
        self.rate_safety = min(max(self.rate_safety, 0.1), 1.0)

        # Network timeout (s)
        try:
            self.timeout: float = float(get("TIMEOUT", "30"))
        except ValueError:
            self.timeout = 30.0

        # Currency for the indicative price (CZK default; per the Foxentry Pay As You Go price list).
        self.currency: str = (get("CURRENCY", "CZK") or "CZK").upper()

        # File encoding.
        #  INPUT_ENCODING = "auto" -> automatic detection (BOM/UTF-8/CP1250/CP1252).
        #  A specific encoding can be forced, e.g. "cp1250" or "utf-8".
        self.input_encoding: str = get("INPUT_ENCODING", "auto") or "auto"
        #  OUTPUT_ENCODING - default UTF-8 with BOM (Excel shows accents correctly with it).
        self.output_encoding: str = get("OUTPUT_ENCODING", "utf-8-sig") or "utf-8-sig"

        # CSV/formula-injection guard: cells starting with = + - @ are prefixed with
        # an apostrophe in the output so Excel does not evaluate them as a formula. Default off
        # (keeps data fidelity); banks may enable it.
        self.csv_guard: bool = get("CSV_INJECTION_GUARD", "on").lower() in ("1", "on", "true", "ano", "yes")

        # Call logging. DEFAULT: OFF - no requests to disk. The user enables logging
        # for a specific run on the last step (Order/summary). When on, the whole
        # request and response are stored; the API key is masked in the headers.
        # include_details = a header making the API also return the received request (default off).
        # "ano" is the Czech word for "yes" - kept as an accepted alias for old CZ config.env
        _truthy = ("1", "on", "true", "ano", "yes")
        self.include_details: bool = get("INCLUDE_REQUEST_DETAILS", "off").lower() in _truthy
        self.log_requests: bool = get("LOG_REQUESTS", "off").lower() in _truthy

        # Optional "Install Excel" button uses pip (pypi.org). openpyxl is already vendored,
        # so the button is only a fallback. Air-gapped deployments can set ALLOW_PIP_INSTALL=off
        # to disable it entirely; runtime egress is then strictly api.foxentry.com. Default on.
        self.allow_pip_install: bool = get("ALLOW_PIP_INSTALL", "on").lower() in _truthy
        # In the frozen single-exe openpyxl is bundled and there is no pip at runtime,
        # so the install endpoint/button make no sense -> force off regardless of config.
        if is_frozen():
            self.allow_pip_install = False
        # Open the wizard UI as a chromeless app window (Chrome/Edge/Brave) when available,
        # else a normal browser tab. Turn off to always use the default browser.
        self.ui_app_mode: bool = get("UI_APP_MODE", "on").lower() in _truthy
        try:
            self.log_retention_days: int = max(0, int(get("LOG_RETENTION_DAYS", "7")))
        except ValueError:
            self.log_retention_days = 7
        try:
            self.concurrency: int = max(1, int(get("CONCURRENCY", "8")))
        except ValueError:
            self.concurrency = 8
        self.log_app: bool = get("LOG_APP", "on").lower() in _truthy
        self.LOG_DIR = LOG_DIR
        if self.log_requests or get("LOG_APP", "on").lower() in _truthy:
            self.LOG_DIR.mkdir(parents=True, exist_ok=True)

        # Folder paths (also exposed on the instance for convenience)
        self.INPUT_DIR = INPUT_DIR
        self.OUTPUT_DIR = OUTPUT_DIR
        # the output folder must exist
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def has_api_key(self) -> bool:
        return bool(self.api_key)

    def masked_key(self) -> str:
        """Safe key display for the log - only the first few characters."""
        k = self.api_key
        if not k:
            return "(not set)"
        if len(k) <= 8:
            return "*" * len(k)
        return k[:4] + "…" + k[-2:]


# Order and description of keys for writing config.env
CONFIG_KEYS = [
    "FOXENTRY_API_KEY", "LANGUAGE", "FOXENTRY_API_URL", "FOXENTRY_API_VERSION",
    "TEST_SAMPLE", "DEFAULT_COUNTRY", "INPUT_ENCODING", "OUTPUT_ENCODING",
    "RATE_LIMIT_RESERVE", "TIMEOUT", "CSV_INJECTION_GUARD", "CURRENCY",
    "INCLUDE_REQUEST_DETAILS", "LOG_REQUESTS", "LOG_RETENTION_DAYS",
    "CONCURRENCY", "LOG_APP",
]

_DEFAULTS = {
    "FOXENTRY_API_KEY": "", "LANGUAGE": "en",
    "FOXENTRY_API_URL": "https://api.foxentry.com", "FOXENTRY_API_VERSION": "2.1",
    "TEST_SAMPLE": "5", "DEFAULT_COUNTRY": "CZ", "INPUT_ENCODING": "auto",
    "OUTPUT_ENCODING": "utf-8-sig", "RATE_LIMIT_RESERVE": "0.85",
    "TIMEOUT": "30", "CSV_INJECTION_GUARD": "on", "CURRENCY": "CZK",
    "INCLUDE_REQUEST_DETAILS": "off", "LOG_REQUESTS": "off",
    "LOG_RETENTION_DAYS": "7", "CONCURRENCY": "8", "LOG_APP": "on",
}


def read_config_values() -> dict[str, str]:
    """Current values from config.env (filled in with defaults)."""
    file_ = _parse_env_file(ROOT / "config.env")
    for en, aliases in ALIASES.items():           # old CZ keys -> new EN
        if en not in file_:
            for a in aliases:
                if a in file_:
                    file_[en] = file_[a]
                    break
    out = dict(_DEFAULTS)
    for k in CONFIG_KEYS:
        if k in file_:
            out[k] = file_[k]
    return out


def save_config(values: dict) -> Path:
    """Write values to config.env (overwrites it with a clean, commented version)."""
    norm = dict(values)
    for en, aliases in ALIASES.items():           # also accept old CZ keys
        if en not in norm:
            for a in aliases:
                if a in norm:
                    norm[en] = norm[a]
                    break
    v = dict(_DEFAULTS)
    # MERGE: start from the existing config.env so a partial update (e.g. only CURRENCY
    # from the language switch) does not wipe other values including the API key.
    try:
        existing = _parse_env_file(ROOT / "config.env")
        for k in CONFIG_KEYS:
            if k in existing:
                v[k] = existing[k]
    except OSError:
        pass
    for k in CONFIG_KEYS:
        if k in norm and norm[k] is not None:
            v[k] = str(norm[k]).strip()
    rows = [
        "# Foxentry Data Cleaner - configuration",
        "# Saved from the in-app settings. Kept only on this computer.",
        "",
        f"FOXENTRY_API_KEY={v['FOXENTRY_API_KEY']}",
        f"LANGUAGE={v['LANGUAGE']}",
        "",
        f"FOXENTRY_API_URL={v['FOXENTRY_API_URL']}",
        f"FOXENTRY_API_VERSION={v['FOXENTRY_API_VERSION']}",
        f"TEST_SAMPLE={v['TEST_SAMPLE']}",
        f"DEFAULT_COUNTRY={v['DEFAULT_COUNTRY']}",
        f"INPUT_ENCODING={v['INPUT_ENCODING']}",
        f"OUTPUT_ENCODING={v['OUTPUT_ENCODING']}",
        f"RATE_LIMIT_RESERVE={v['RATE_LIMIT_RESERVE']}",
        f"TIMEOUT={v['TIMEOUT']}",
        f"CURRENCY={v['CURRENCY']}",
        f"CSV_INJECTION_GUARD={v['CSV_INJECTION_GUARD']}",
        f"INCLUDE_REQUEST_DETAILS={v['INCLUDE_REQUEST_DETAILS']}",
        f"LOG_REQUESTS={v['LOG_REQUESTS']}",
        f"LOG_RETENTION_DAYS={v['LOG_RETENTION_DAYS']}",
        f"CONCURRENCY={v['CONCURRENCY']}",
        f"LOG_APP={v['LOG_APP']}",
        "",
    ]
    path = ROOT / "config.env"
    path.write_text("\n".join(rows), encoding="utf-8")
    return path
