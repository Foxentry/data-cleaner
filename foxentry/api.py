# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AVANTRO s.r.o.
"""
HTTP client for the Foxentry API.

Intentionally uses only the Python standard library (`urllib`, `ssl`, `json`),
so it introduces no external dependencies that would require a security
audit. TLS certificate verification is on (default `ssl` behavior).

Only HTTPS requests to the configured API address go out
(`api.foxentry.com`). No telemetry, no other connections.
"""

from __future__ import annotations

import csv
import datetime
import json
import os
import platform
import ssl
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import applog

_LOG_LOCK = threading.Lock()


def _try_json(s: str):
    try:
        return json.loads(s)
    except Exception:
        return None


class FoxentryError(Exception):
    """Generic API communication error."""


class AuthError(FoxentryError):
    """401/403 - bad key or restriction (IP)."""


class CreditError(FoxentryError):
    """402 - out of credits."""


class RateLimitError(FoxentryError):
    """429 - rate limit exceeded."""


class UnsupportedOptionError(FoxentryError):
    """400 - an option parameter is not supported for this endpoint/version."""

    def __init__(self, message: str, params: list[str] | None = None) -> None:
        super().__init__(message)
        self.params = params or []


@dataclass
class Limits:
    """Values from response headers - remaining credits and the rate limit."""
    credits_left: int | None = None
    credits_limit: int | None = None
    rate_limit: int | None = None          # number of requests
    rate_period: int | None = None         # za kolik sekund
    rate_remaining: int | None = None

    def throughput_per_s(self, safety: float) -> float:
        """Safe throughput in requests per second."""
        if self.rate_limit and self.rate_period:
            return max(0.2, (self.rate_limit / self.rate_period) * safety)
        return 3.0  # conservative default when the API reports no limits


@dataclass
class Response:
    """Result of a single API call."""
    data: dict
    limits: Limits
    http_status: int


class FoxentryClient:
    def __init__(self, api_key: str, api_url: str, api_version: str, timeout: float = 30.0,
                 *, include_details: bool = False, log_path: str | None = None,
                 user_agent: str | None = None) -> None:
        self._key = api_key
        self._url = api_url.rstrip("/")
        self._version = api_version
        self._timeout = timeout
        self._include_details = include_details
        self._log_path = log_path
        # Client identification in the Foxentry log (same style as the official SDK).
        self._ua = user_agent or (
            f"FoxentryCleaner (Python/{platform.python_version()}; ApiReference/{api_version or 'latest'})"
        )
        # Standard context with certificate verification (safe defaults).
        self._ssl = ssl.create_default_context()

    # ------------------------------------------------------------------ public

    def validate(self, path: str, query: dict, options: dict | None = None,
                custom_id: str | None = None, attempts: int = 4) -> Response:
        """
        Send one validation request. On 429/5xx it retries with a delay.
        """
        req_body: dict = {"request": {"query": query}}
        if options:
            req_body["request"]["options"] = options
        if custom_id:
            req_body["request"]["customId"] = custom_id

        last_error: Exception | None = None
        removed: set[str] = set()
        for attempt in range(attempts):
            try:
                return self._post(path, req_body)
            except UnsupportedOptionError as e:
                # the API rejected an option (different endpoint version) - remove it and retry.
                opts = req_body["request"].get("options") or {}
                to_remove = [p for p in e.params if p in opts] or list(opts.keys())
                if not to_remove or removed.issuperset(to_remove):
                    raise
                for p in to_remove:
                    opts.pop(p, None)
                    removed.add(p)
                if opts:
                    req_body["request"]["options"] = opts
                else:
                    req_body["request"].pop("options", None)
                applog.warn("%s – unsupported options %s, removing and retrying", path, to_remove)
                continue
            except RateLimitError as e:
                last_error = e
                wait = min(2 ** attempt, 15)
                applog.warn("429 %s – attempt %s/%s, waiting %ss", path, attempt + 1, attempts, wait)
                time.sleep(wait)
            except FoxentryError as e:
                # 5xx - short delay and retry; let other errors propagate
                msg = str(e)
                if msg.startswith("5") or "503" in msg or "500" in msg:
                    last_error = e
                    wait = min(2 ** attempt, 15)
                    applog.warn("5xx %s – attempt %s/%s, waiting %ss", path, attempt + 1, attempts, wait)
                    time.sleep(wait)
                else:
                    raise
        raise last_error or FoxentryError("Request failed.")

    # ------------------------------------------------------------------ internal

    def _post(self, path: str, req_body: dict) -> Response:
        url = f"{self._url}{path}"
        raw = json.dumps(req_body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=raw, method="POST")
        req.add_header("Authorization", f"Bearer {self._key}")
        if self._version:
            req.add_header("Api-Version", self._version)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", self._ua)
        if self._include_details:
            req.add_header("Foxentry-Include-Request-Details", "true")

        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self._timeout, context=self._ssl) as resp:
                body = resp.read().decode("utf-8")
                ms = (time.monotonic() - t0) * 1000.0
                limits = self._limits_from_headers(resp.headers)
                data = json.loads(body)
                self._log(path, req_body, resp.status, ms, data, None,
                          resp_headers=dict(resp.headers), raw=body)
                return Response(data=data, limits=limits, http_status=resp.status)
        except urllib.error.HTTPError as e:
            ms = (time.monotonic() - t0) * 1000.0
            try:
                detail_raw = e.read().decode("utf-8")
            except Exception:
                detail_raw = ""
            try:
                hdrs = dict(e.headers)
            except Exception:
                hdrs = {}
            self._log(path, req_body, e.code, ms, _try_json(detail_raw), detail_raw,
                      resp_headers=hdrs, raw=detail_raw)
            self._handle_http_error(e.code, detail_raw)
            raise
        except urllib.error.URLError as e:
            ms = (time.monotonic() - t0) * 1000.0
            self._log(path, req_body, None, ms, None, str(e.reason))
            raise FoxentryError(f"Network error: {e.reason}") from e

    def _request_header(self) -> dict:
        key = self._key or ""
        mask = ("Bearer ****" + key[-4:]) if len(key) >= 4 else "Bearer ****"
        h = {
            "Authorization": mask,
            "Api-Version": self._version,
            "User-Agent": self._ua,
        }
        if self._include_details:
            h["Foxentry-Include-Request-Details"] = "true"
        return h

    def _handle_http_error(self, status_code: int, detail_raw: str) -> None:
        desc = ""
        error_code = ""
        typ = ""
        subtyp = ""
        related: list[str] = []
        try:
            detail = json.loads(detail_raw)
            if isinstance(detail, dict):
                errors = detail.get("errors") or []
                if errors and isinstance(errors, list) and isinstance(errors[0], dict):
                    e0 = errors[0]
                    desc = e0.get("description", "") or ""
                    error_code = str(e0.get("code", "") or "")
                    typ = str(e0.get("type", "") or "")
                    subtyp = str(e0.get("subtype", "") or "")
                    related = [str(x) for x in (e0.get("relatedTo") or [])]
        except Exception:
            desc = ""
        # if there is no structured description, use the whole raw body (truncated)
        common = (f"[{error_code}] " if error_code else "") + (desc or detail_raw.strip()[:500])
        common = common.strip()
        if status_code == 400 and (typ == "OPTIONS" or subtyp == "PARAMETER_NOT_SUPPORTED"):
            raise UnsupportedOptionError(f"400 – {common}".strip(), params=related)
        if status_code == 401:
            raise AuthError(f"401 - invalid API key. {common}".strip())
        if status_code == 403:
            raise AuthError(
                f"403 - access denied (allowed key domains/IP or wrong key type). {common}".strip()
            )
        if status_code == 402:
            raise CreditError(f"402 - not enough credits on the project. {common}".strip())
        if status_code == 429:
            raise RateLimitError(f"429 - rate limit exceeded. {common}".strip())
        raise FoxentryError(f"{status_code} – API error. {common}".strip())

    def _log(self, path, req_body, status, ms, response, error, resp_headers=None, raw=None) -> None:
        if not self._log_path:
            return
        rec = {
            "ts": datetime.datetime.now().isoformat(timespec="milliseconds"),
            "endpoint": path, "status": status, "ms": round(ms, 1),
            "request_headers": self._request_header(),
            "request": req_body,
            "response_headers": resp_headers or {},
            "response": response,
        }
        # on errors (and when parsing fails) also store the exact raw response body
        if raw is not None and (status is None or status >= 400 or response is None):
            rec["response_raw"] = raw
        if error:
            rec["error"] = error
        # human-readable query and result for CSV
        try:
            q = (req_body.get("request", {}) or {}).get("query", {})
            query_txt = json.dumps(q, ensure_ascii=False)
        except Exception:
            query_txt = ""
        result_txt = ""
        try:
            rr = (response or {}).get("response", {}) if isinstance(response, dict) else {}
            res = rr.get("result") if isinstance(rr, dict) else None
            if isinstance(res, dict):
                if "isValid" in res:
                    result_txt = "valid" if res.get("isValid") else "invalid"
                if res.get("proposal"):
                    result_txt = (result_txt + " / " if result_txt else "") + str(res.get("proposal"))
        except Exception:
            pass
        try:
            os.makedirs(os.path.dirname(self._log_path), exist_ok=True)
            csv_path = (self._log_path[:-6] + ".csv") if self._log_path.endswith(".jsonl") else (self._log_path + ".csv")
            rec["result"] = result_txt
            csv_query = query_txt
            with _LOG_LOCK:
                with open(self._log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                is_new = not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0
                with open(csv_path, "a", encoding="utf-8-sig", newline="") as cf:
                    w = csv.writer(cf, delimiter=";")
                    if is_new:
                        w.writerow(["cas", "endpoint", "status", "ms", "query", "result", "error"])
                    w.writerow([rec["ts"], path, status, round(ms, 1),
                                csv_query, result_txt, error or ""])
        except Exception:
            pass

    @staticmethod
    def _limits_from_headers(headers) -> Limits:
        def ci(name: str) -> int | None:
            val = headers.get(name)
            if val is None:
                return None
            try:
                return int(val)
            except (TypeError, ValueError):
                return None

        return Limits(
            credits_left=ci("foxentry-daily-credits-left"),
            credits_limit=ci("foxentry-daily-credits-limit"),
            rate_limit=ci("foxentry-rate-limit"),
            rate_period=ci("foxentry-rate-limit-period"),
            rate_remaining=ci("foxentry-rate-limit-remaining"),
        )
