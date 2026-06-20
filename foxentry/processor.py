# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AVANTRO s.r.o.
"""
Validation orchestration.

For each input file:
  1. Determine which validations to run based on the file name
     (emails -> email, combined -> everything present in the file).
  2. For each validation, find the matching columns (even partially filled).
  3. Build the output header.
  4. Send data to the API row by row and write the result.

Output columns per validation:
  <key>_result      - human-readable result (valid / corrected / INVALID ...)
  <key>_proposal    - technical code from the API (valid, invalidWithCorrection, ...)
  <column>_updated  - value after correction (overwritten if the API proposed a fix)
  <key>_suggestion  - alternative suggestion (if any)
  <key>_note        - reason for invalidity (if available)

Request rate stays under the rate limit reported in the API headers.
The app can be interrupted any time (Ctrl+C) - completed rows are on disk
and the next run resumes where it stopped.
"""

from __future__ import annotations

import json
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .api import AuthError, FoxentryClient, Limits, RateLimitError
from .endpoints import ENDPOINTS, KEY_TO_TYPE, FILENAME_PREFIXES, Endpoint, human_result
from . import applog
from .io_tables import StreamWriter, csv_to_xlsx, load_table
from . import i18n


@dataclass
class Task:
    """
    A single validation applied to a file.

    `field_map` = {api_field: column_name} - which columns make up this validation.
                 Multiple columns = one record group (e.g. street+city+ZIP = 1 address).
    `options`  = API options (per-service settings); when None, the endpoint
                 defaults are used.
    `group`    = internal key for output columns (distinguishes multiple groups of the
                 same type, e.g. "address1", "address2"). When empty, endpoint.key is used.
    `label`    = human-readable group name (e.g. "Address 1").
    """
    endpoint: Endpoint
    field_map: dict[str, str]
    options: dict | None = None
    group: str = ""
    label: str = ""
    fill_country: bool = False  # add default_country to the query when not mapped (address/company only)

    def __post_init__(self) -> None:
        if self.options is None:
            self.options = dict(self.endpoint.options)
        if not self.group:
            self.group = KEY_TO_TYPE.get(self.endpoint.key, self.endpoint.key)
        if not self.label:
            self.label = i18n.endpoint_name(self.endpoint.key)

    def has_data(self, row: dict[str, str]) -> bool:
        return any((row.get(s) or "").strip() for s in self.field_map.values())


@dataclass
class Stats:
    total_rows: int = 0
    api_calls: int = 0
    by_result: Counter = field(default_factory=Counter)
    errors: int = 0
    enriched: int = 0   # number of filled enrich cells (added data points)
    enriched_by_service: Counter = field(default_factory=Counter)  # breakdown per service
    deduplicated: int = 0   # calls saved by deduplication (repeated inputs)

    def as_dict(self) -> dict:
        return {
            "total_rows": self.total_rows,
            "api_calls": self.api_calls,
            "by_result": dict(self.by_result),
            "errors": self.errors,
            "enriched": self.enriched,
            "enriched_by_service": dict(self.enriched_by_service),
            "deduplicated": self.deduplicated,
        }


def tasks_from_filename(filename: str, header: list[str], default_country: str) -> list[Task]:
    """Build the task list from the file-name prefix and available columns."""
    base = filename.lower()
    keys: list[str] = []
    for prefix, eps in FILENAME_PREFIXES.items():
        if base.startswith(prefix):
            keys = eps
            break
    if not keys:
        # unknown name -> try all and let the available columns decide
        keys = list(ENDPOINTS.keys())

    tasks: list[Task] = []
    for key in keys:
        ep = ENDPOINTS[key]
        field_map = ep.detect_map(header)
        if field_map:  # endpoint has at least one usable column in the file
            tasks.append(Task(endpoint=ep, field_map=field_map))
    return tasks


def build_output_header(input_header: list[str], tasks: list[Task]) -> list[str]:
    """Original columns + result columns for each task (prefix = group)."""
    out = list(input_header)
    for u in tasks:
        k = u.group
        out.append(f"{k}_result")
        # _updated for each mapped field (in endpoint definition order)
        for fields in u.endpoint.fields:
            column = u.field_map.get(fields.api_field)
            if column:
                out.append(f"{column}_updated")
        out.append(f"{k}_suggestion")
        out.append(f"{k}_note")
    # enrich columns go all the way to the end - as separate columns
    for u in tasks:
        out.extend(_enrich_columns(u))
    # remove possible duplicates while keeping order
    seen: set[str] = set()
    unique: list[str] = []
    for c in out:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def count_api_calls(rows: list[dict[str, str]], tasks: list[Task]) -> int:
    """How many real API calls the run will consume (empty cells are not called)."""
    count = 0
    for r in rows:
        for u in tasks:
            if u.has_data(r):
                count += 1
    return count


def _primary_suggestion(u: Task, suggestions: list) -> str:
    if not suggestions:
        return ""
    data = suggestions[0].get("data") if isinstance(suggestions[0], dict) else None
    if not isinstance(data, dict):
        return ""
    extraction = u.endpoint.fields[0].extraction
    value = extraction(data) if extraction else None
    return "" if value is None else str(value)


def _is_enrich(u: Task) -> bool:
    """Does the task have enrichment enabled? dataScope full (address/company) or, for phone,
    extended validation (validationType extended) - which returns carrier/type.
    Only for services that actually have something to enrich (present in ENRICH_FIELDS)."""
    if u.endpoint.key not in ENRICH_FIELDS:
        return False
    o = u.options or {}
    return o.get("dataScope") in ("full", "extended") or o.get("validationType") == "extended"


def _enr_gender(data: dict) -> str:
    gmap = {1: i18n.t("enr_male"), 2: i18n.t("enr_female")}
    for d in (data.get("details") or []):
        if isinstance(d, dict) and d.get("type") in ("name", "nameSurname") and d.get("gender"):
            return gmap.get(d.get("gender"), "")
    return ""


def _enr_vocative(data: dict) -> str:
    return (data.get("vocativeNameSurname")
            or " ".join(x for x in (data.get("vocativeName"), data.get("vocativeSurname")) if x)
            or "").strip()


def _enr_nameday(country: str):
    """Name day for the given country in unified DD.MM. format (e.g. 04.04.)."""
    def f(data: dict) -> str:
        for d in (data.get("details") or []):
            if isinstance(d, dict) and d.get("type") == "name":
                for x in (d.get("nameDays") or []):
                    if isinstance(x, dict) and x.get("country") == country and x.get("day"):
                        try:
                            return f"{int(x['day']):02d}.{int(x['month']):02d}."
                        except (TypeError, ValueError):
                            return f"{x.get('day')}.{x.get('month')}."
        return ""
    return f


def _find_deep(data, keys) -> str:
    """Recursively (breadth-first) find the first value under a key from `keys` anywhere in the response."""
    from collections import deque
    want = {k.lower() for k in keys}
    q = deque([data])
    while q:
        cur = q.popleft()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if k.lower() in want:
                    if isinstance(v, bool):
                        continue
                    if isinstance(v, (int, float)):
                        return str(v)
                    if isinstance(v, str) and v.strip():
                        return v.strip()
            for v in cur.values():
                if isinstance(v, (dict, list)):
                    q.append(v)
        elif isinstance(cur, list):
            for v in cur:
                if isinstance(v, (dict, list)):
                    q.append(v)
    return ""


def _enr_deep(*keys: str):
    return lambda data: _find_deep(data, keys)


def _first_under_key(data, key):
    """BFS: return the first value (of any type) stored under the given key."""
    from collections import deque
    q = deque([data])
    while q:
        cur = q.popleft()
        if isinstance(cur, dict):
            if key in cur:
                return cur[key]
            for v in cur.values():
                if isinstance(v, (dict, list)):
                    q.append(v)
        elif isinstance(cur, list):
            for v in cur:
                if isinstance(v, (dict, list)):
                    q.append(v)
    return None


def _scal(v) -> str:
    """Scalar to text; bool -> yes/no, numbers -> str, otherwise -> ''."""
    if isinstance(v, bool):
        return i18n.t("enr_yes") if v else i18n.t("enr_no")
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return v.strip()
    return ""


def _enr_path(*keys: str):
    """Value at a key path. Finds the first occurrence of keys[0] (anywhere in the response),
    then descends through the remaining keys (dict -> .get, list -> first element). If the path
    hits a scalar earlier, it returns it (handles fields that are both string and object).
    """
    def f(data):
        cur = _first_under_key(data, keys[0])
        for k in keys[1:]:
            if isinstance(cur, list):
                cur = cur[0] if cur else None
            if isinstance(cur, dict):
                cur = cur.get(k)
            else:
                break
        return _scal(cur)
    return f


def _format_addr(obj) -> str:
    """Turn an address value into a readable string - handles a string, an object with 'full',
    and an object split into parts (street/no./ZIP/city)."""
    if isinstance(obj, str):
        return obj.strip()
    if isinstance(obj, dict):
        # Foxentry nests the address under 'data' (address.data.full) - unwrap it.
        if isinstance(obj.get("data"), dict):
            obj = obj["data"]
        for k in ("full", "formatted", "complete"):
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        street = obj.get("streetWithNumber") or obj.get("street") or ""
        if street and obj.get("number"):
            street = f"{street} {_scal(obj.get('number'))}".strip()
        zip_code = _scal(obj.get("zip") or obj.get("zipCode") or "")
        city = obj.get("city") or obj.get("municipality") or ""
        row2 = " ".join(x for x in [zip_code, city] if x).strip()
        return ", ".join(x for x in [str(street).strip(), row2] if x)
    return ""


def _enr_addr(*keys: str):
    """Like _enr_path, but formats the result via _format_addr (addresses)."""
    def f(data):
        cur = _first_under_key(data, keys[0])
        for k in keys[1:]:
            if isinstance(cur, list):
                cur = cur[0] if cur else None
            if isinstance(cur, dict):
                cur = cur.get(k)
            else:
                break
        return _format_addr(cur)
    return f


# Enrich columns per service (suffix, extractor). Names are verified against a real
# response. GPS/region/district are searched recursively (anywhere in the response) so they
# match even when nested; if the API does not return them at all, they stay empty.
ENRICH_FIELDS: dict[str, list] = {
    "name":  [("full", _enr_deep("nameSurname")),
               ("firstName", _enr_path("name")),
               ("surname", _enr_path("surname")),
               ("degreesBefore", _enr_path("degreesBefore")),
               ("degreesAfter", _enr_path("degreesAfter")),
               ("gender", _enr_gender), ("vocative", _enr_vocative),
               ("nameday_CZ", _enr_nameday("CZ")), ("nameday_SK", _enr_nameday("SK"))],
    "location": [("full", _enr_path("full")),
               ("state", _enr_path("state")),
               ("region", _enr_path("region")),
               ("district", _enr_path("district")),
               ("cityPart", _enr_path("cityPart")),
               ("cityDistrict", _enr_path("cityDistrict")),
               ("cadastralArea", _enr_path("cadastralArea")),
               ("latitude", _enr_deep("latitude", "lat")),
               ("longitude", _enr_deep("longitude", "lng", "lon", "long")),
               ("externalId", _enr_path("ids", "external")),
               ("internalId", _enr_path("ids", "internal"))],
    "company":  [("name", _enr_path("name")),
               ("registrationNumber", _enr_path("registrationNumber")),
               ("taxNumber", _enr_path("taxNumber")),
               ("vatNumber", _enr_path("vatNumber")),
               ("vatNumberSpecial", _enr_path("vatNumberSpecial")),
               ("address", _enr_addr("address", "data")),
               ("addressOfficial", _enr_addr("addressOfficial", "data")),
               ("legalForm", _enr_path("legalForm", "name")),
               ("nace", _enr_path("nace", "name")),
               ("vatStatus", _enr_path("vat", "status")),
               ("vatReliable", _enr_path("vat", "reliability", "reliable")),
               ("created", _enr_path("dates", "created")),
               ("terminated", _enr_path("dates", "terminated")),
               ("employees", _enr_path("employees", "category"))],
    "phone": [("carrier", _enr_path("carrier", "name")),
                ("carrierType", _enr_path("carrier", "type")),
                ("country", _enr_path("country", "code"))],
}


def _enrich_columns(u: Task) -> list[str]:
    """Names of enrich columns for a task (empty if not enriched)."""
    if not _is_enrich(u):
        return []
    return [f"{u.group}_{suffix}" for suffix, _ in ENRICH_FIELDS.get(u.endpoint.key, [])]


def _enrich_outputs(u: Task, data: dict | None) -> dict[str, object]:
    """Enrich column values from the response (each field separately)."""
    out: dict[str, object] = {}
    d = data if isinstance(data, dict) else {}
    for suffix, fn in ENRICH_FIELDS.get(u.endpoint.key, []):
        out[f"{u.group}_{suffix}"] = fn(d)
    return out



def _note_invalid(response: dict) -> str:
    """Build the note column. For corrected results, summarize what actually changed
    from `resultCorrected.fixes` (e.g. "city: Vysoká -> Chrastava"). For results that
    stay invalid, summarize what is wrong from `result.errors` (description + affected
    fields `relatedTo`). For untouched valid results it returns empty.
    """
    if not isinstance(response, dict):
        return ""
    result = response.get("result") or {}
    rc = response.get("resultCorrected")
    final_valid = rc.get("isValid") if isinstance(rc, dict) else result.get("isValid")
    if final_valid:
        # what was actually fixed (only meaningful when a correction happened)
        fixes = (rc.get("fixes") if isinstance(rc, dict) else None) or result.get("fixes") or []
        parts = []
        for fx in fixes:
            if not isinstance(fx, dict):
                continue
            fd = fx.get("data") or {}
            field = (fd.get("type") or fd.get("typeFrom") or fx.get("subtype") or "").strip()
            vf = _scal(fd.get("valueFrom")).strip()
            vt = _scal(fd.get("value")).strip()
            if vf and vt and vf != vt:
                body = f"{vf} \u2192 {vt}"
            elif vt:
                body = vt
            elif vf:
                body = vf
            else:
                continue
            parts.append(f"{field}: {body}" if field else body)
        parts = [p for p in dict.fromkeys(parts) if p]
        if parts:
            return (i18n.t("note_fixed") + ": " + " \u00b7 ".join(parts))[:500]
        return ""
    errors = (result.get("errors")
             or (rc.get("errors") if isinstance(rc, dict) else None) or [])
    labels = []
    for e in errors:
        if not isinstance(e, dict):
            continue
        d = (e.get("description") or "").strip()
        rel = e.get("relatedTo") or []
        if d:
            labels.append(d + (" (" + ", ".join(rel) + ")" if rel else ""))
    if not labels:
        inv = (result.get("dataTypes") or {}).get("invalid") or []
        if inv:
            labels.append(i18n.t("note_still_invalid") + ": " + ", ".join(dict.fromkeys(inv)))
    return " · ".join(dict.fromkeys(labels))[:500]


def _map_response(u: Task, row: dict[str, str], data: dict) -> dict[str, object]:
    """Build output values for one task on one row from the API response."""
    k = u.group
    out: dict[str, object] = {}

    response = data.get("response", {}) if isinstance(data, dict) else {}
    result = response.get("result", {}) or {}
    proposal = result.get("proposal")
    is_valid = result.get("isValid")
    corrected = response.get("resultCorrected")
    suggestions = response.get("suggestions") or []

    out[f"{k}_result"] = human_result(proposal, is_valid)

    # best available data for correction
    if isinstance(corrected, dict):
        best_data = corrected.get("data")
    elif is_valid:
        best_data = result.get("data")
    else:
        best_data = None

    for fields in u.endpoint.fields:
        column = u.field_map.get(fields.api_field)
        if not column:
            continue
        original = (row.get(column) or "").strip()
        new_value = None
        if isinstance(best_data, dict) and fields.extraction:
            new_value = fields.extraction(best_data)
        if new_value in (None, ""):
            new_value = original
        out[f"{column}_updated"] = new_value

    out[f"{k}_suggestion"] = _primary_suggestion(u, suggestions)
    out[f"{k}_note"] = _note_invalid(response)

    if _is_enrich(u):
        enr_data = (corrected.get("data") if isinstance(corrected, dict) else None) \
            or result.get("data")
        out.update(_enrich_outputs(u, enr_data))

    return out


def _empty_outputs(u: Task, row: dict[str, str], result_text: str) -> dict[str, object]:
    """Output columns for a row that is not sent to the API (empty data)."""
    k = u.group
    out: dict[str, object] = {f"{k}_result": result_text}
    for fields in u.endpoint.fields:
        column = u.field_map.get(fields.api_field)
        if column:
            out[f"{column}_updated"] = (row.get(column) or "").strip()
    out[f"{k}_suggestion"] = ""
    out[f"{k}_note"] = ""
    if _is_enrich(u):
        for sl in _enrich_columns(u):
            out[sl] = ""
    return out


@dataclass
class RunResult:
    stats: Stats
    output_csv: Path
    output_xlsx: Path | None
    completed: bool


def process(
    client: FoxentryClient,
    input_file: Path,
    output_csv: Path,
    rows: list[dict[str, str]],
    input_header: list[str],
    tasks: list[Task],
    default_country: str,
    rate_safety: float,
    row_limit: int | None = None,
    resume: bool = True,
    progress: Callable[[int, int, Stats], None] | None = None,
    make_xlsx: bool = True,
    output_encoding: str = "utf-8-sig",
    guard_csv: bool = False,
    concurrency: int = 8,
    on_call: Callable[[], None] | None = None,
) -> RunResult:
    """Main processing loop."""
    rows = rows[:row_limit] if row_limit is not None else rows

    output_header = build_output_header(input_header, tasks)
    write_row = StreamWriter(output_csv, output_header, encoding=output_encoding,
                          guard_csv=guard_csv)

    # resume: how many rows are already done
    done = 0
    if resume and output_csv.is_file():
        if not write_row.header_matches():
            raise RuntimeError(
                f"Output file {output_csv.name} has a different structure and cannot "
                f"be resumed. Delete/rename it and run again."
            )
        done = min(write_row.existing_rows(), len(rows))

    write_row.open_writer(resume=resume)
    stat = Stats(total_rows=len(rows))

    # resume: seed stats from already-processed rows so the report is valid
    # for the WHOLE file (not just the part after restart).
    if done > 0:
        res_columns = [f"{u.group}_result" for u in tasks]
        seed, seed_calls, seed_errors = write_row.load_results(
            res_columns, i18n.t("res_not_filled"), limit=done)
        stat.by_result.update(seed)
        stat.api_calls += seed_calls
        stat.errors += seed_errors

    # Shared token-bucket rate limiter (requests/s) across threads.
    # We start conservatively and after the first responses the rate adapts
    # to the real API limits (this avoids an initial burst of 429s under concurrency).
    bucket = _Bucket(min(2.0, _default_throughput(rate_safety)))
    concurrency = max(1, int(concurrency))
    key_gate = _KeyGate()   # workaround: a freshly created key may not be active immediately
    applog.info("Processing: rows=%s (resume from %s), concurrency=%s, start rate≈%.1f/s",
                len(rows), done, concurrency, bucket.rate)
    _hb = [time.monotonic()]
    _start = time.monotonic()

    _enr_columns = set()
    _enr_groups = {}   # group(service) -> set of its enrich columns
    for _u in tasks:
        cols = _enrich_columns(_u)
        if cols:
            _enr_columns.update(cols)
            _enr_groups.setdefault(_u.group, set()).update(cols)
    cache = _RespCache()   # per-run response deduplication

    def save_result(batch):
        _i, out_row, calls, errors, results, saved = batch
        write_row.write_row(out_row)
        stat.api_calls += calls
        stat.errors += errors
        stat.deduplicated += saved
        for k, n in results.items():
            stat.by_result[k] += n
        if _enr_columns:
            for grp, cols in _enr_groups.items():
                m = sum(1 for c in cols if str(out_row.get(c) or "").strip())
                if m:
                    stat.enriched += m
                    stat.enriched_by_service[grp] += m

    def heartbeat(done):
        now = time.monotonic()
        if now - _hb[0] >= 3.0 or done >= len(rows):
            _hb[0] = now
            elapsed = max(0.001, now - _start)
            actual = (done - done) / elapsed  # actual throughput, not the API limit
            applog.info("…progress %s/%s · calls=%s · errors=%s · rate≈%.1f/s",
                        done, len(rows), stat.api_calls, stat.errors, actual)

    try:
        if concurrency <= 1:
            for i in range(done, len(rows)):
                save_result(_process_row(i, rows[i], tasks, default_country,
                                             client, bucket, rate_safety, on_call, key_gate, cache))
                if progress:
                    progress(i + 1, len(rows), stat)
                heartbeat(i + 1)
        else:
            with ThreadPoolExecutor(max_workers=concurrency) as ex:
                futures = {i: ex.submit(_process_row, i, rows[i], tasks,
                                        default_country, client, bucket, rate_safety, on_call, key_gate, cache)
                           for i in range(done, len(rows))}
                # we write strictly in order (for resume); computation is parallel
                for i in range(done, len(rows)):
                    try:
                        batch = futures[i].result()
                    except Exception as e:  # safety: one row must not stop the whole run
                        applog.exception("Row %s failed unexpectedly: %s", i + 1, e)
                        row = rows[i]
                        vr: dict[str, object] = dict(row)
                        for u in tasks:
                            ch = _empty_outputs(u, row, i18n.t("res_error"))
                            ch[f"{u.group}_note"] = str(e)[:300]
                            vr.update(ch)
                        batch = (i, vr, 0, len(tasks), {i18n.t("res_error"): len(tasks)}, 0)
                    save_result(batch)
                    if progress:
                        progress(i + 1, len(rows), stat)
                    heartbeat(i + 1)

        completed = True
    except KeyboardInterrupt:
        completed = False
        applog.warn("Run interrupted by user.")
    finally:
        write_row.close_writer()
    applog.info("Processing finished: completed=%s · calls=%s · errors=%s",
                completed, stat.api_calls, stat.errors)

    output_xlsx: Path | None = None
    if completed and make_xlsx:
        xlsx = output_csv.with_suffix(".xlsx")
        if csv_to_xlsx(output_csv, xlsx, encoding=output_encoding):
            output_xlsx = xlsx

    return RunResult(
        stats=stat,
        output_csv=output_csv,
        output_xlsx=output_xlsx,
        completed=completed,
    )


def _default_throughput(safety: float) -> float:
    return Limits().throughput_per_s(safety)


def _interval_from_limits(limits: Limits, safety: float, current: float) -> float:
    throughput = limits.throughput_per_s(safety)
    if throughput > 0:
        return 1.0 / throughput
    return current


class _Bucket:
    """Token-bucket rate limiter shared across threads (req/s)."""

    def __init__(self, rate: float) -> None:
        self.rate = max(0.2, rate)
        # Bucket capacity must be at least 1 token. At a rate < 1 req/s,
        # `allow` would never accumulate a whole token (capped at rate < 1) and
        # acquire() would loop forever. Hence capacity = max(rate, 1).
        self.allow = max(self.rate, 1.0)
        self.t = time.monotonic()
        self.lock = threading.Lock()

    def _capacity(self) -> float:
        return max(self.rate, 1.0)

    def set_rate(self, r: float) -> None:
        with self.lock:
            self.rate = max(0.2, r)

    def acquire(self) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                self.allow = min(self._capacity(), self.allow + (now - self.t) * self.rate)
                self.t = now
                if self.allow >= 1:
                    self.allow -= 1
                    return
                wait = (1 - self.allow) / self.rate
            time.sleep(min(wait, 0.4))


class _KeyGate:
    """Workaround for a freshly created API key that is not registered yet.

    On the FIRST 401 error in a run it waits `wait_s` seconds once (other threads
    wait with it) and the request should be retried. If the key still fails, it is truly
    invalid. It waits at most once per whole run.
    """

    def __init__(self, wait_s: float = 20.0):
        self._lock = threading.Lock()
        self._cekani = wait_s
        self._uz_cekano = False
        self._hotovo = threading.Event()

    def wait_once(self) -> bool:
        """Return True if the request should be retried after the (one-time) wait."""
        with self._lock:
            if not self._uz_cekano:
                self._uz_cekano = True
                applog.warn("Invalid key (401) at the start of the run – a brand-new key may not be "
                            "active yet. Waiting %.0f s and retrying.", self._cekani)
                time.sleep(self._cekani)
                self._hotovo.set()
                return True
        # the first thread is already waiting/done - wait for it and retry too
        self._hotovo.wait(timeout=self._cekani + 5)
        return True


def _cache_key(path, query, options):
    """Stable key for deduplication: service + input + options (customId is ignored)."""
    return (path,
            json.dumps(query, sort_keys=True, ensure_ascii=False),
            json.dumps(options, sort_keys=True, ensure_ascii=False))


_CACHE_MAX = 250_000   # cap on unique cache entries (memory guard for large files)


class _RespCache:
    """Per-run result cache - the same input is queried from the API only once.
    Holds only the small mapped output (not the whole response). Thread-safe: a second query
    for the same key waits for the first. Above _CACHE_MAX, new keys are no longer cached
    (they validate normally), so memory stays bounded even for hundreds of thousands of unique rows."""
    def __init__(self, cap: int = _CACHE_MAX):
        self._lock = threading.Lock()
        self._hotovo: dict = {}
        self._eventy: dict = {}
        self._cap = cap

    def reserve(self, key):
        """Return (data, hit, owner). hit=ready data; owner=compute and call done/release."""
        with self._lock:
            if key in self._hotovo:
                return self._hotovo[key], True, False
            ev = self._eventy.get(key)
            if ev is None:
                if len(self._hotovo) >= self._cap:
                    return None, False, True  # cap reached: no cache, just compute
                self._eventy[key] = threading.Event()
                return None, False, True
        ev.wait(timeout=120)
        with self._lock:
            if key in self._hotovo:
                return self._hotovo[key], True, False
        return None, False, True  # owner timeout/failure -> compute it yourself

    def done(self, key, data):
        with self._lock:
            ev = self._eventy.pop(key, None)
            if ev is not None:   # store only properly reserved keys (respects the cap)
                self._hotovo[key] = data
        if ev:
            ev.set()

    def release(self, key):
        with self._lock:
            ev = self._eventy.pop(key, None)
        if ev:
            ev.set()


def _process_row(i, row, tasks, default_country, client, bucket, rate_safety, on_call=None, key_gate=None, cache=None):
    """Process one row (all services).
    Returns (index, output, calls, errors, results, dedup_saved)."""
    out_row: dict[str, object] = dict(row)
    calls = 0
    errors = 0
    saved = 0   # how many calls deduplication saved (the same input was already validated)
    results: dict[str, int] = {}
    for u in tasks:
        if not u.has_data(row):
            out_row.update(_empty_outputs(u, row, i18n.t("res_not_filled")))
            continue
        query = u.endpoint.query_from_row(row, u.field_map)
        options = dict(u.options or u.endpoint.options)
        if (u.fill_country and default_country and u.endpoint.key in ("location", "company")
                and "country" in [p.api_field for p in u.endpoint.fields] and "country" not in query):
            query["country"] = default_country

        # Per-run deduplication: the same (service+input+options) is queried from the API only once.
        key = _cache_key(u.endpoint.path, query, options) if cache is not None else None
        if key is not None:
            outputs_c, hit, _owner = cache.reserve(key)
            if hit:
                out_row.update(outputs_c)
                k = outputs_c[f"{u.group}_result"]
                results[k] = results.get(k, 0) + 1
                saved += 1
                if on_call:
                    try:
                        on_call(i + 1)
                    except Exception:
                        pass
                continue

        bucket.acquire()
        key_tried = False
        stored = False
        while True:
            try:
                resp = client.validate(u.endpoint.path, query, options, custom_id=f"row-{i + 1}")
                calls += 1
                bucket.set_rate(resp.limits.throughput_per_s(rate_safety))
                outputs = _map_response(u, row, resp.data)
                out_row.update(outputs)
                if key is not None:
                    cache.done(key, outputs)   # store only the small output, not the whole response
                    stored = True
                k = outputs[f"{u.group}_result"]
                results[k] = results.get(k, 0) + 1
                break
            except AuthError as e:
                # a fresh key may not be active yet -> wait once and retry
                if key_gate is not None and not key_tried and key_gate.wait_once():
                    key_tried = True
                    continue
                applog.warn("Row %s (%s): invalid key even after waiting – %s",
                            i + 1, u.endpoint.path, str(e)[:300])
                errors += 1
                error_out = _empty_outputs(u, row, i18n.t("res_error"))
                error_out[f"{u.group}_note"] = str(e)[:300]
                out_row.update(error_out)
                k = i18n.t("res_error")
                results[k] = results.get(k, 0) + 1
                break
            except RateLimitError as e:
                # the API reports a limit overflow despite internal retries -> slow down the whole run.
                new_rate = max(0.5, bucket.rate * 0.5)
                bucket.set_rate(new_rate)
                applog.warn("Row %s (%s): 429 rate limit, slowing to ≈%.1f/s",
                            i + 1, u.endpoint.path, new_rate)
                errors += 1
                error_out = _empty_outputs(u, row, i18n.t("res_error"))
                error_out[f"{u.group}_note"] = str(e)[:300]
                out_row.update(error_out)
                k = i18n.t("res_error")
                results[k] = results.get(k, 0) + 1
                break
            except Exception as e:  # a single failure must not end the whole run
                applog.warn("Row %s (%s): error – %s", i + 1, u.endpoint.path, str(e)[:500])
                errors += 1
                error_out = _empty_outputs(u, row, i18n.t("res_error"))
                error_out[f"{u.group}_note"] = str(e)[:300]
                out_row.update(error_out)
                k = i18n.t("res_error")
                results[k] = results.get(k, 0) + 1
                break
        # an owner that failed -> release waiters (they try themselves), do not cache the error
        if key is not None and not stored:
            cache.release(key)
        # live feedback after every call (even on error) - so the UI shows movement
        if on_call:
            try:
                on_call(i + 1)
            except Exception:
                pass
    return i, out_row, calls, errors, results, saved
