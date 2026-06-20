# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AVANTRO s.r.o.
"""
Local web server for the wizard (Python standard library only).

Listens only on 127.0.0.1 (never externally). Serves a single-page wizard
and a JSON API:
  GET  /                  -> wizard (wizard.html)
  GET  /api/init          -> language, service schema, file list, config state
  POST /api/config        -> save config.env (Save button)
  POST /api/upload?name=  -> save the uploaded file into input/
  POST /api/preview       -> file preview + mapping suggestion
  POST /api/estimate      -> credits/time estimate (1 test query)
  POST /api/run           -> start validation in the background
  GET  /api/progress      -> run progress
  GET  /download?name=    -> download/open an output file

No other connections; all work is local except Foxentry API calls.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from . import applog
from . import config as config_mod
from . import i18n, mapping
from . import io_tables
from . import __version__
from .api import AuthError, CreditError, FoxentryClient, Limits
from .endpoints import SERVICE_ALIAS
from .io_tables import FileError, StreamWriter, no_header, load_table
from .processor import build_output_header, count_api_calls, process
from .report import _format_time, marketing_metrics, create_report

SUPPORTED = (".csv", ".tsv", ".txt", ".xlsx", ".xlsm")
_WIZARD = config_mod.RESOURCE_ROOT / "foxentry" / "wizard.html"
_ASSETS = config_mod.RESOURCE_ROOT / "foxentry" / "assets"
# Session token + port - protects the local API from a foreign page/process (DNS rebinding).
_TOKEN = secrets.token_urlsafe(16)
_PORT: int | None = None
_SESSION_FILE = config_mod.DATA_ROOT / ".foxentry-session.json"
_SESSION_LOCK = threading.Lock()


def _load_session() -> dict:
    """Load saved settings/mapping (last file + per-file state)."""
    try:
        with _SESSION_LOCK:
            data = json.loads(_SESSION_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("files", {})
            # Backward-compat: remap old Czech service keys in saved mappings to the new English keys.
            for _rec in data.get("files", {}).values():
                for _m in (_rec.get("mapping") or []):
                    if isinstance(_m, dict) and _m.get("service") in SERVICE_ALIAS:
                        _m["service"] = SERVICE_ALIAS[_m["service"]]
            return data
    except (OSError, ValueError):
        pass
    return {"last_file": None, "files": {}, "price_per_credit": None}


def _save_session_record(payload: dict) -> None:
    """Save the state for one file and set it as the last one."""
    file = _safe_name(payload.get("file", "")) if payload.get("file") else None
    s = _load_session()
    if file:
        s["last_file"] = file
        s.setdefault("files", {})[file] = {
            "hasHeader": payload.get("hasHeader", True),
            "mapping": payload.get("mapping", []),
            "settings": payload.get("settings", {}),
            "scope": payload.get("scope", "test"),
            "limit": payload.get("limit"),
            "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    if payload.get("price_per_credit") is not None:
        s["price_per_credit"] = payload.get("price_per_credit")
    try:
        with _SESSION_LOCK:
            _SESSION_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _save_run_summary(file: str, summary: dict) -> None:
    """Save the summary of a finished run (to show the report after a restart)."""
    file = _safe_name(file)
    s = _load_session()
    rec = s.setdefault("files", {}).setdefault(file, {})
    rec["last_run"] = summary
    s["last_file"] = file
    try:
        with _SESSION_LOCK:
            _SESSION_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass

# last run state (local, single user)
_RUN: dict = {"active": False, "done": 0, "total": 0, "by_result": {},
              "calls": 0, "errors": 0, "finished": False, "ok": True,
              "outputs": [], "message": "", "run_time": 0.0, "jobs": []}
_RUN_LOCK = threading.Lock()


def _safe_name(name: str) -> str:
    return Path(name or "").name  # drop any path


def _list_files(cfg) -> list[str]:
    if not cfg.INPUT_DIR.is_dir():
        return []
    return sorted(
        p.name for p in cfg.INPUT_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED
        and not p.name.startswith(".") and p.stem.upper() not in ("PRECTI_ME", "README")
    )


def _find_probe(rows, tasks, done, limit, default_country):
    end = limit if limit is not None else len(rows)
    for i in range(done, min(end, len(rows))):
        for u in tasks:
            if u.has_data(rows[i]):
                q = u.endpoint.query_from_row(rows[i], u.field_map)
                if (u.fill_country and default_country and u.endpoint.key in ("location", "company")
                        and "country" not in q):
                    q["country"] = default_country
                return u, q
    return None, None


def _start_run(cfg, input_file: Path, rows, header, tasks, limit, log_run=False):
    """Runs in a separate thread; updates _RUN."""
    global _RUN
    output_csv = cfg.OUTPUT_DIR / f"{input_file.stem}_result.csv"

    start = time.monotonic()

    def progress(done, total, stat):
        with _RUN_LOCK:
            _RUN["done"] = done
            _RUN["total"] = total
            _RUN["calls"] = stat.api_calls
            _RUN["errors"] = stat.errors
            _RUN["by_result"] = dict(stat.by_result)
            _RUN["run_time"] = time.monotonic() - start

    def on_call(row):
        # After every API call (even between completed rows) - so the UI shows movement.
        with _RUN_LOCK:
            _RUN["live_calls"] = _RUN.get("live_calls", 0) + 1
            _RUN["current"] = row
            _RUN["run_time"] = time.monotonic() - start

    try:
        _logp = (str(cfg.LOG_DIR / ("requests-" + time.strftime("%Y%m%d-%H%M%S") + ".jsonl"))
                 if (log_run or cfg.log_requests) else None)
        client = FoxentryClient(cfg.api_key, cfg.api_url, cfg.api_version, cfg.timeout,
                                include_details=cfg.include_details, log_path=_logp)
        result = process(client, input_file, output_csv, rows, header, tasks,
                      default_country=cfg.default_country, rate_safety=cfg.rate_safety,
                      row_limit=limit, resume=True, progress=progress, make_xlsx=True,
                      output_encoding=cfg.output_encoding, guard_csv=cfg.csv_guard,
                      concurrency=cfg.concurrency, on_call=on_call)
        duration = time.monotonic() - start
        outputs = [result.output_csv.name]
        if result.output_xlsx:
            outputs.append(result.output_xlsx.name)
        if result.completed:
            report = cfg.OUTPUT_DIR / f"{input_file.stem}_report.html"
            create_report(report, input_file.name, tasks, result.stats, True,
                          result.output_csv, result.output_xlsx, duration)
            outputs.append(report.name)
        value = marketing_metrics(dict(result.stats.by_result),
                                      [u.endpoint.key for u in tasks])
        # enrichment per service, keyed by the (display-ready) task label
        enr_by_label: dict = {}
        for u in tasks:
            c = result.stats.enriched_by_service.get(u.group, 0)
            if c:
                enr_by_label[u.label] = enr_by_label.get(u.label, 0) + c
        enriched_total = getattr(result.stats, "enriched", 0)
        summary = {"file": input_file.name, "done": result.stats.total_rows,
                  "calls": result.stats.api_calls, "errors": result.stats.errors,
                  "by_result": dict(result.stats.by_result), "run_time": duration,
                  "jobs": [u.label for u in tasks], "outputs": outputs, "value": value,
                  "enriched": enriched_total, "enriched_by_service": enr_by_label,
                  "completed": result.completed, "date": time.strftime("%Y-%m-%d %H:%M")}
        applog.info("RUN done: %s, rows=%s, calls=%s, errors=%s, time=%.1fs, results=%s",
                    ("completed" if result.completed else "interrupted"),
                    result.stats.total_rows, result.stats.api_calls,
                    result.stats.errors, duration, dict(result.stats.by_result))
        if result.completed:
            _save_run_summary(input_file.name, summary)
        with _RUN_LOCK:
            _RUN.update(active=False, finished=True, ok=True, outputs=outputs,
                        done=result.stats.total_rows, by_result=dict(result.stats.by_result),
                        calls=result.stats.api_calls, errors=result.stats.errors, value=value,
                        enriched=enriched_total, enriched_by_service=enr_by_label,
                        completed=result.completed, run_time=duration)
    except Exception as e:
        applog.exception("RUN failed: %s", e)
        with _RUN_LOCK:
            _RUN.update(active=False, finished=True, ok=False, message=str(e)[:300])


class Handler(BaseHTTPRequestHandler):
    # silence the console
    def log_message(self, *a):  # noqa: N802
        pass

    # Security headers added to EVERY response. The server is loopback-only with no external
    # resources, so the risk is low, but these are a cheap defense and keep web scanners happy.
    # CSP allows 'unsafe-inline' because wizard.html uses inline scripts/styles, but it still
    # blocks all external sources, objects, framing, and <base> hijacking.
    _CSP = ("default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self' data:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'none'; "
            "form-action 'self'; "
            "frame-ancestors 'none'")

    def end_headers(self):  # noqa: N802
        self.send_header("Content-Security-Policy", self._CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    # ---------- helpers ----------
    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _raw(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(length) if length > 0 else b""

    # ---------- GET ----------
    def do_GET(self):  # noqa: N802
        path = urlparse(self.path)
        p = path.path
        if p.startswith("/api/") and not self._api_auth("GET"):
            return
        if p in ("/", "/index.html"):
            return self._file_token(_WIZARD)
        if p in ("/manual", "/documentation.html"):
            return self._serve_file(config_mod.RESOURCE_ROOT / "docs" / "documentation.html",
                                 "text/html; charset=utf-8")
        if p in ("/setup", "/setup-guide.html"):
            return self._serve_file(config_mod.RESOURCE_ROOT / "docs" / "setup-guide.html",
                                 "text/html; charset=utf-8")
        if p in ("/logs", "/log-viewer.html"):
            return self._file_token(config_mod.RESOURCE_ROOT / "docs" / "log-viewer.html")
        if p.startswith("/assets/"):
            return self._asset(p[len("/assets/"):])
        if p == "/api/logs":
            return self._json(self._list_logs())
        if p == "/api/logfile":
            q = parse_qs(path.query)
            return self._logfile(q.get("name", [""])[0])
        if p == "/api/init":
            return self._init()
        if p == "/api/schema":
            q = parse_qs(path.query)
            return self._schema(q.get("lang", [""])[0])
        if p == "/api/config":
            return self._json(config_mod.read_config_values())
        if p == "/api/progress":
            with _RUN_LOCK:
                return self._json(dict(_RUN))
        if p == "/download":
            q = parse_qs(path.query)
            return self._download(q.get("name", [""])[0])
        if p == "/favicon.ico":
            self.send_response(204); self.end_headers(); return
        self.send_response(404); self.end_headers()

    # ---------- POST ----------
    def do_POST(self):  # noqa: N802
        path = urlparse(self.path)
        p = path.path
        if p.startswith("/api/") and not self._api_auth("POST"):
            return
        if p == "/api/config":
            return self._save_config()
        if p == "/api/logs/clear":
            return self._json(self._delete_logs())
        if p == "/api/upload":
            q = parse_qs(path.query)
            return self._upload(q.get("name", [""])[0])
        if p == "/api/preview":
            return self._preview()
        if p == "/api/install-xlsx":
            return self._install_xlsx()
        if p == "/api/estimate":
            return self._estimate()
        if p == "/api/run":
            return self._run()
        if p == "/api/session":
            _save_session_record(self._body())
            return self._json({"ok": True})
        if p == "/api/reset":
            return self._reset()
        self.send_response(404); self.end_headers()

    # ---------- implementation ----------
    def _api_auth(self, method: str) -> bool:
        """Protect the local API: allow only a loopback Host (against DNS rebinding) and for
        POST also a matching session token (against CSRF from another page). Otherwise 403."""
        host = (self.headers.get("Host") or "").strip().lower()
        allowed = {f"127.0.0.1:{_PORT}", f"localhost:{_PORT}", f"[::1]:{_PORT}"}
        if host not in allowed:
            self.send_response(403); self.end_headers(); return False
        if method == "POST" and (self.headers.get("X-Auth") or "") != _TOKEN:
            self.send_response(403); self.end_headers(); return False
        return True

    def _serve_file(self, path: Path, ctype: str):
        try:
            data = path.read_bytes()
        except OSError:
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _file_token(self, path: Path):
        """Serves HTML and injects the session token into it (placeholder __AUTH_TOKEN__)."""
        try:
            txt = path.read_text(encoding="utf-8")
        except OSError:
            self.send_response(404); self.end_headers(); return
        data = txt.replace("__AUTH_TOKEN__", _TOKEN).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _asset(self, name: str):
        """Local static files (font/icon) - extension whitelist only, no path traversal."""
        name = _safe_name(name)
        types = {".woff2": "font/woff2", ".woff": "font/woff", ".svg": "image/svg+xml",
                ".css": "text/css; charset=utf-8", ".png": "image/png"}
        ext = Path(name).suffix.lower()
        if not name or ext not in types:
            self.send_response(404); self.end_headers(); return
        path = _ASSETS / name
        if not path.is_file():
            self.send_response(404); self.end_headers(); return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", types[ext])
        self.send_header("Cache-Control", "max-age=86400")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _delete_logs(self) -> dict:
        """Delete request logs (jsonl + csv) from the logs/ folder."""
        deleted = 0
        try:
            for pattern in ("requests-*.jsonl", "requests-*.csv", "probe.jsonl", "probe.csv"):
                for f in config_mod.LOG_DIR.glob(pattern):
                    try:
                        f.unlink(); deleted += 1
                    except OSError:
                        pass
        except OSError:
            pass
        applog.info("Request logs cleared: %s file(s)", deleted)
        return {"ok": True, "deleted": deleted}

    def _init(self):
        cfg = config_mod.Config()
        i18n.set_lang(cfg.lang)
        # Detect an unfinished run (the user closed the browser/app midway).
        sess = _load_session()
        lf = sess.get("last_file")
        rec = (sess.get("files") or {}).get(lf) if lf else None
        resume = None
        try:
            if rec and rec.get("mapping"):
                payload = {"file": lf, "mapping": rec.get("mapping", []),
                           "settings": rec.get("settings", {}),
                           "scope": rec.get("scope", "test"), "limit": rec.get("limit"),
                           "hasHeader": rec.get("hasHeader", True)}
                _c, _v, _h, _rows, _u, _limit, _hot = self._prepare(payload)
                end = _limit if _limit is not None else len(_rows)
                if 0 < _hot < end:
                    resume = {"file": lf, "done": _hot, "total": end,
                              "scope": rec.get("scope", "test"), "limit": rec.get("limit"),
                              "has_key": cfg.has_api_key()}
        except Exception:
            resume = None
        # Finished run -> offer the report directly (after restarting the app).
        last_report = None
        try:
            lr = rec.get("last_run") if rec else None
            if lr and lr.get("completed") and lr.get("outputs"):
                if (cfg.OUTPUT_DIR / lr["outputs"][0]).is_file():
                    last_report = lr
        except Exception:
            last_report = None
        self._json({
            "lang": cfg.lang,
            "langs": i18n.DOSTUPNE_JAZYKY,
            "services": mapping.schema_for_ui(cfg.lang),
            "files": _list_files(cfg),
            "default_country": cfg.default_country,
            "test_sample": cfg.test_sample,
            "has_key": cfg.has_api_key(),
            "key_hint": ((cfg.api_key[-4:] if len(cfg.api_key) > 8 else "")
                         if (cfg.has_api_key() and cfg.api_key) else None),
            "currency": cfg.currency,
            "session": sess,
            "resume": resume,
            "last_report": last_report,
            "allow_pip_install": cfg.allow_pip_install,
            "frozen": config_mod.is_frozen(),
            "app_version": __version__,
        })

    def _schema(self, lang):
        """Localized service schema (mapping + settings) for switching the UI language."""
        cfg = config_mod.Config()
        if lang not in i18n.DOSTUPNE_JAZYKY:
            lang = cfg.lang
        i18n.set_lang(lang)
        try:
            services = mapping.schema_for_ui(lang)
        finally:
            i18n.set_lang(cfg.lang)
        self._json({"ok": True, "lang": lang, "services": services})

    def _save_config(self):
        values = self._body()
        path = config_mod.save_config(values)
        # update the language for subsequent responses
        i18n.set_lang(values.get("LANGUAGE", "en"))
        self._json({"ok": True, "path": str(path)})

    def _install_xlsx(self):
        """Install openpyxl: pinned version, wheel only, isolated into vendor/.
        The user's global environment is not changed. The endpoint is behind the Host+token check."""
        import subprocess
        import sys
        import importlib
        if io_tables.MA_OPENPYXL:
            return self._json({"ok": True})
        if not config_mod.Config().allow_pip_install:
            applog.info("openpyxl install requested but ALLOW_PIP_INSTALL=off; refusing.")
            return self._json({"ok": False, "error": "disabled"})
        target = str(config_mod.ROOT / "vendor")
        cmd = [sys.executable, "-m", "pip", "install",
               "--no-input", "--disable-pip-version-check",
               "--only-binary=:all:",      # never build from source
               "--target", target,         # isolated next to the app
               "openpyxl==3.1.5"]          # pinned version
        try:
            applog.info("Installing openpyxl: %s", " ".join(cmd))
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
            if proc.returncode != 0:
                applog.warn("pip install openpyxl failed: %s",
                            (proc.stderr or proc.stdout or "")[:500])
                return self._json({"ok": False, "command": " ".join(cmd),
                                   "error": (proc.stderr or proc.stdout or "pip failed")[-400:]})
            if target not in sys.path:
                sys.path.insert(0, target)
            importlib.invalidate_caches()
            io_tables.openpyxl = importlib.import_module("openpyxl")
            io_tables.MA_OPENPYXL = True
            applog.info("openpyxl installed into vendor/.")
            return self._json({"ok": True, "command": " ".join(cmd),
                               "output": (proc.stdout or "")[-400:]})
        except Exception as e:  # noqa: BLE001
            applog.warn("openpyxl install: error %s", str(e)[:300])
            return self._json({"ok": False, "command": " ".join(cmd), "error": str(e)[:300]})

    def _upload(self, name):
        name = _safe_name(name)
        if not name or Path(name).suffix.lower() not in SUPPORTED:
            return self._json({"ok": False, "error": "unsupported file type"}, 400)
        cfg = config_mod.Config()
        cfg.INPUT_DIR.mkdir(parents=True, exist_ok=True)
        (cfg.INPUT_DIR / name).write_bytes(self._raw())
        self._json({"ok": True, "name": name})

    def _preview(self):
        data = self._body()
        cfg = config_mod.Config()
        i18n.set_lang(cfg.lang)
        input_file = cfg.INPUT_DIR / _safe_name(data.get("file", ""))
        if not input_file.is_file():
            return self._json({"ok": False, "error": "file not found"}, 404)
        if input_file.suffix.lower() in (".xlsx", ".xlsm") and not io_tables.MA_OPENPYXL:
            return self._json({"ok": False, "error_code": "xlsx_missing",
                               "error": "openpyxl required"})
        try:
            header, rows, enc_info = load_table(input_file, cfg.input_encoding)
        except FileError as e:
            return self._json({"ok": False, "error": str(e)}, 400)
        from . import classification
        if "hasHeader" in data:
            has_header = bool(data.get("hasHeader"))
        else:
            has_header = classification.classify_columns(header, rows)["hasHeaderRow"]
        if not has_header:
            header, rows = no_header(header, rows)
        sample = [[r.get(h, "") for h in header] for r in rows[:12]]
        suggestion = mapping.suggest_mapping(header, rows)
        self._json({
            "ok": True, "header": header, "rows": sample, "total": len(rows),
            "encoding": enc_info, "hasHeaderRow": has_header,
            "suggestion": suggestion,
            "suggested_settings": mapping.suggest_settings(suggestion, rows, cfg.default_country),
        })

    def _prepare(self, data):
        """Shared: load the file, build tasks, determine the limit and done count."""
        cfg = config_mod.Config()
        i18n.set_lang(cfg.lang)
        input_file = cfg.INPUT_DIR / _safe_name(data.get("file", ""))
        if not input_file.is_file():
            raise FileError("file not found")
        header, rows, _ = load_table(input_file, cfg.input_encoding)
        if not data.get("hasHeader", True):
            header, rows = no_header(header, rows)
        tasks = mapping.build_tasks(data.get("mapping", []), data.get("settings", {}),
                                     cfg.default_country, cfg.lang)
        if not tasks:
            raise FileError("no validations mapped")
        scope = data.get("scope", "test")
        if scope == "full":
            limit = None
        elif scope == "manual":
            try:
                n = int(data.get("limit") or 0)
            except (TypeError, ValueError):
                n = 0
            if n < 1:
                n = min(cfg.test_sample, len(rows))
            limit = max(1, min(n, len(rows)))
        else:  # test
            limit = min(cfg.test_sample, len(rows))
        # done (resume)
        output_csv = cfg.OUTPUT_DIR / f"{input_file.stem}_result.csv"
        done = 0
        if output_csv.is_file():
            writer = StreamWriter(output_csv, build_output_header(header, tasks),
                               cfg.output_encoding)
            if writer.header_matches():
                done = min(writer.existing_rows(), len(rows))
        return cfg, input_file, header, rows, tasks, limit, done

    def _estimate(self):
        data = self._body()
        try:
            cfg, input_file, header, rows, tasks, limit, done = self._prepare(data)
        except FileError as e:
            return self._json({"ok": False, "error": str(e)}, 400)
        end = limit if limit is not None else len(rows)
        from . import pricing
        price = pricing.compute_price(tasks, rows[done:end], cfg.currency)
        # Dedup-aware: billed validations = unique queries (same as the real run).
        calls = sum(it["calls"] for it in price["items"])
        raw_calls = sum(it.get("raw_calls", it["calls"]) for it in price["items"])
        # The probe is optional - price and time are computed locally regardless of connectivity.
        client = FoxentryClient(cfg.api_key, cfg.api_url, cfg.api_version, cfg.timeout,
                                include_details=cfg.include_details,
                                log_path=str(cfg.LOG_DIR / "probe.jsonl") if cfg.log_requests else None)
        u, q = _find_probe(rows, tasks, done, limit, cfg.default_country)
        limits = Limits()
        connected, conn_error, conn_detail = True, None, None
        probe_ms = None
        try:
            if u is not None:
                _p0 = time.monotonic()
                resp = client.validate(u.endpoint.path, q, dict(u.options or {}), custom_id="probe")
                probe_ms = (time.monotonic() - _p0) * 1000.0
                limits = resp.limits
        except AuthError as e:
            connected, conn_error, conn_detail = False, "auth", str(e)
        except CreditError as e:
            connected, conn_error, conn_detail = False, "credit", str(e)
        except Exception as e:
            connected, conn_error, conn_detail = False, "probe", str(e)[:200]
        throughput = limits.throughput_per_s(cfg.rate_safety)
        if not throughput:                      # without a successful probe, estimate the rate conservatively
            throughput = max(1.0, 5.0 * cfg.rate_safety)
        # Parallel processing (cfg.concurrency threads) hides API latency,
        # so the run is limited by the rate limit, not by waiting for responses. Effective rate
        # = min(rate limit, concurrency / latency).
        latency_s = (probe_ms / 1000.0) if probe_ms else 0.7
        eff_rate = min(throughput, cfg.concurrency / latency_s) if latency_s > 0 else throughput
        eff_rate = max(0.2, eff_rate)
        eta = calls / eff_rate if eff_rate else 0
        self._json({
            "ok": True, "connected": connected, "conn_error": conn_error,
            "conn_detail": conn_detail,
            "calls": calls, "raw_calls": raw_calls, "deduped": raw_calls - calls,
            "remaining": done, "total": len(rows),
            "scope_rows": end - done,
            "credits_left": limits.credits_left, "credits_limit": limits.credits_limit,
            "rate": round(eff_rate, 1), "rate_estimated": True,
            "rate_period": limits.rate_period, "eta": _format_time(eta),
            "probe_ms": (round(probe_ms) if probe_ms else None),
            "per_call_s": round(1.0 / eff_rate, 2) if eff_rate else None,
            "jobs": [{"label": x.label, "fields": list(x.field_map.values())} for x in tasks],
            "price": price["total"], "currency": price["currency"],
            "price_symbol": price["symbol"], "price_items": price["items"],
        })

    def _run(self):
        global _RUN
        data = self._body()
        _save_session_record(data)
        with _RUN_LOCK:
            if _RUN.get("active"):
                return self._json({"ok": False, "error": "already running"}, 409)
        try:
            cfg, input_file, header, rows, tasks, limit, done = self._prepare(data)
        except FileError as e:
            return self._json({"ok": False, "error": str(e)}, 400)
        with _RUN_LOCK:
            _RUN.clear()
            _tot = len(rows) if limit is None else limit
            _RUN.update(active=True, done=min(done, _tot), total=_tot,
                        by_result={}, calls=0, errors=0, finished=False, ok=True,
                        outputs=[], message="", completed=False, run_time=0.0,
                        live_calls=0, current=done, resume_from=done,
                        jobs=[u.label for u in tasks])
        applog.info("RUN start: file=%s, rows=%s, scope=%s, concurrency=%s, resume_from=%s",
                    input_file.name, (limit if limit is not None else len(rows)), data.get("scope"),
                    cfg.concurrency, done)
        applog.info("API key: source=%s, ends with ****%s", cfg.api_key_source,
                    (cfg.api_key[-4:] if cfg.api_key else "—"))
        if getattr(cfg, "api_key_env_shadow", False):
            applog.warn("Warning: the FOXENTRY_API_KEY environment variable differs from config.env. "
                        "The config.env key will be used. If the run fails with 401, "
                        "check/remove the system FOXENTRY_API_KEY variable.")
        t = threading.Thread(target=_start_run,
                             args=(cfg, input_file, rows, header, tasks, limit,
                                   bool(data.get("log"))), daemon=True)
        t.start()
        self._json({"ok": True})

    def _reset(self):
        data = self._body()
        file = _safe_name(data.get("file", "")) if data.get("file") else None
        cfg = config_mod.Config()
        if file:
            stem = Path(file).stem
            for suf in ("_result.csv", "_result.xlsx", "_report.html"):
                try:
                    (cfg.OUTPUT_DIR / f"{stem}{suf}").unlink()
                except OSError:
                    pass
            s = _load_session()
            r = (s.get("files") or {}).get(file)
            if r and "last_run" in r:
                r.pop("last_run", None)
                try:
                    with _SESSION_LOCK:
                        _SESSION_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
                except OSError:
                    pass
        self._json({"ok": True})

    def _list_logs(self):
        """List of request logs (jsonl) in logs/ - newest first."""
        out = []
        try:
            for f in config_mod.LOG_DIR.glob("requests-*.jsonl"):
                try:
                    st = f.stat()
                    out.append({"name": f.name, "size": st.st_size, "modified": st.st_mtime})
                except OSError:
                    continue
        except OSError:
            pass
        out.sort(key=lambda r: r["modified"], reverse=True)
        return {"logs": out}

    def _logfile(self, name):
        """Return the contents of a specific request log (safe *.jsonl name from logs/ only)."""
        name = _safe_name(name)
        if not (name.startswith("requests-") and name.endswith(".jsonl")):
            self.send_response(400); self.end_headers(); return
        path = config_mod.LOG_DIR / name
        if not path.is_file():
            self.send_response(404); self.end_headers(); return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _download(self, name):
        name = _safe_name(name)
        cfg = config_mod.Config()
        path = cfg.OUTPUT_DIR / name
        if not path.is_file():
            self.send_response(404); self.end_headers(); return
        ctype = ("text/html; charset=utf-8" if name.endswith(".html")
                 else "text/csv; charset=utf-8" if name.endswith(".csv")
                 else "application/octet-stream")
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store, must-revalidate")
        if not name.endswith(".html"):
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _cleanup_logs(cfg) -> None:
    """Delete request logs older than LOG_RETENTION_DAYS (0 = keep)."""
    days = getattr(cfg, "log_retention_days", 0)
    if not days:
        return
    cutoff = time.time() - days * 86400
    try:
        for pattern in ("requests-*.jsonl", "requests-*.csv"):
            for f in cfg.LOG_DIR.glob(pattern):
                try:
                    if f.stat().st_mtime < cutoff:
                        f.unlink()
                except OSError:
                    pass
    except OSError:
        pass


def start_server(port: int = 0, open_writer: bool = True) -> None:
    global _PORT
    cfg = config_mod.Config()
    i18n.set_lang(cfg.lang)
    applog.set_value(cfg.LOG_DIR, cfg.log_app)
    _cleanup_logs(cfg)
    applog.info("Server starting (port=%s, concurrency=%s, api_version=%s)",
                port or "auto", cfg.concurrency, cfg.api_version)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    actual_port = server.server_address[1]
    _PORT = actual_port
    url = f"http://127.0.0.1:{actual_port}/"
    print()
    print("  🦊  " + i18n.t("app_title"))
    print(f"      {i18n.t('server_running', url=url)}")
    print(f"      {i18n.t('server_stop')}")
    if open_writer:
        try:
            from . import applaunch
            applaunch.open_ui(url, app_mode=config_mod.Config().ui_app_mode)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  " + i18n.t("server_bye"))
        server.shutdown()
