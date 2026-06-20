# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AVANTRO s.r.o.
"""
Interactive text interface / interactive CLI.

Language follows the LANGUAGE setting in config.env (default en).
Language follows the LANGUAGE setting in config.env (default en).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from . import config as config_mod
from . import i18n
from .api import AuthError, CreditError, FoxentryClient, Limits
from .io_tables import FileError, StreamWriter, load_table
from .processor import (
    Task,
    build_output_header,
    count_api_calls,
    tasks_from_filename,
    process,
)
from .report import _format_time, create_report

SUPPORTED = (".csv", ".tsv", ".txt", ".xlsx", ".xlsm")


def _hr() -> None:
    print("-" * 60)


def _heading(text: str) -> None:
    print()
    _hr()
    print(f"  {text}")
    _hr()


def _ask(question: str, default_val: str = "") -> str:
    try:
        resp = input(question).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit(0)
    return resp or default_val


def _confirm(question: str, default_yes: bool = True) -> bool:
    hint = "[Y/n]" if default_yes else "[y/N]"
    resp = _ask(f"{question} {hint}: ").lower()
    if not resp:
        return default_yes
    return resp in ("a", "ano", "y", "yes")


def _select_file(cfg: config_mod.Config) -> Path:
    files = sorted(
        p for p in cfg.INPUT_DIR.iterdir()
        if p.is_file()
        and p.suffix.lower() in SUPPORTED
        and not p.name.startswith(".")
        and p.stem.upper() not in ("PRECTI_ME", "README")
    ) if cfg.INPUT_DIR.is_dir() else []

    if not files:
        print()
        print("  " + i18n.t("no_files_intro"))
        print()
        print("  " + i18n.t("no_files_how"))
        print("  " + i18n.t("no_files_1"))
        print("  " + i18n.t("no_files_2"))
        print("  " + i18n.t("no_files_3"))
        print("  " + i18n.t("no_files_4"))
        print()
        raise SystemExit(1)

    if len(files) == 1:
        return files[0]

    print("\n  " + i18n.t("select_file") + "\n")
    for i, p in enumerate(files, 1):
        print(f"   {i}) {p.name}")
    print()
    while True:
        choice = _ask("  " + i18n.t("file_num", n=len(files)), "1")
        if choice.isdigit() and 1 <= int(choice) <= len(files):
            return files[int(choice) - 1]
        print("  " + i18n.t("invalid_choice"))


def _describe_tasks(tasks: list[Task]) -> None:
    print("\n  " + i18n.t("recognized"))
    for u in tasks:
        columns = ", ".join(u.field_map.values())
        print(i18n.t("validation_line",
                     name=i18n.endpoint_name(u.endpoint.key),
                     cols=columns,
                     countries=i18n.countries(u.endpoint.supported_countries)))


def _find_probe_query(rows, tasks, done, limit, default_country):
    end = limit if limit is not None else len(rows)
    for i in range(done, min(end, len(rows))):
        for u in tasks:
            if u.has_data(rows[i]):
                q = u.endpoint.query_from_row(rows[i], u.field_map)
                if u.endpoint.key in ("location", "company"):
                    q.setdefault("country", default_country)
                return u, q
    return None, None


def _read_limits(client, tasks, rows, done, limit, default_country) -> Limits:
    u, q = _find_probe_query(rows, tasks, done, limit, default_country)
    if u is None:
        return Limits()
    print("  " + i18n.t("probe"))
    resp = client.validate(u.endpoint.path, q, dict(u.endpoint.options), custom_id="probe")
    return resp.limits


def _progress(done: int, total: int, stat) -> None:
    ratio = done / total if total else 1.0
    length = 24
    full = int(length * ratio)
    bar = "#" * full + "." * (length - full)
    sys.stdout.write(f"\r  [{bar}] {done}/{total} ({ratio * 100:4.1f} %)   ")
    sys.stdout.flush()


def main() -> int:
    cfg = config_mod.Config()
    i18n.set_lang(cfg.lang)

    print()
    print("  🦊  " + i18n.t("app_title"))
    print("      " + i18n.t("app_subtitle"))

    if not cfg.has_api_key():
        _heading(i18n.t("nokey_title"))
        print("  " + i18n.t("nokey_intro"))
        print()
        for k in ("nokey_1", "nokey_2", "nokey_3", "nokey_4"):
            print("  " + i18n.t(k))
        print()
        print("  " + i18n.t("nokey_get"))
        print("  " + i18n.t("nokey_docs"))
        return 1

    print("      " + i18n.t("api_key_line", key=cfg.masked_key(), url=cfg.api_url))

    input_file = _select_file(cfg)

    try:
        header, rows, enc_info = load_table(input_file, cfg.input_encoding)
    except FileError as e:
        print("\n  " + i18n.t("file_load_failed", e=e))
        return 1

    _heading(i18n.t("file_header", name=input_file.name))
    print("  " + i18n.t("rows_with_data", n=len(rows)))
    print("  " + i18n.t("encoding", info=enc_info))
    print("  " + i18n.t("columns", cols=", ".join(header)))

    if not rows:
        print("\n  " + i18n.t("no_data"))
        return 1

    tasks = tasks_from_filename(input_file.name, header, cfg.default_country)
    if not tasks:
        print("\n  " + i18n.t("no_recognized_1"))
        print("  " + i18n.t("no_recognized_2"))
        return 1
    _describe_tasks(tasks)

    output_csv = cfg.OUTPUT_DIR / f"{input_file.stem}_result.csv"
    output_header = build_output_header(header, tasks)
    done = 0
    if output_csv.is_file():
        check = StreamWriter(output_csv, output_header, cfg.output_encoding)
        if check.header_matches():
            done = min(check.existing_rows(), len(rows))
            if 0 < done < len(rows):
                print("\n  " + i18n.t("resume_found", n=done + 1))
            elif done >= len(rows):
                print("\n  " + i18n.t("already_done", n=done))
                if not _confirm("  " + i18n.t("revalidate_q"), default_yes=False):
                    return 0
                output_csv.unlink(missing_ok=True)
                done = 0
        else:
            print("\n  " + i18n.t("diff_struct", name=output_csv.name))
            if _confirm("  " + i18n.t("overwrite_q"), default_yes=False):
                output_csv.unlink(missing_ok=True)
            else:
                return 0

    _heading(i18n.t("scope_header"))
    print(i18n.t("scope_opt1", n=cfg.test_sample))
    print(i18n.t("scope_opt2", n=len(rows)))
    print()
    choice = _ask("  " + i18n.t("scope_prompt"), "1")
    if choice == "2":
        limit = None
        range_txt = i18n.t("scope_full", n=len(rows))
    else:
        limit = min(cfg.test_sample, len(rows))
        range_txt = i18n.t("scope_test", n=limit)

    remaining = (limit if limit is not None else len(rows)) - done
    if remaining <= 0:
        print("\n  " + i18n.t("nothing_left"))
        return 0

    _heading(i18n.t("estimate_header"))
    _logp = (str(cfg.LOG_DIR / ("requests-cli-" + time.strftime("%Y%m%d-%H%M%S") + ".jsonl"))
             if cfg.log_requests else None)
    client = FoxentryClient(cfg.api_key, cfg.api_url, cfg.api_version, cfg.timeout,
                            include_details=cfg.include_details, log_path=_logp)
    try:
        limits = _read_limits(client, tasks, rows, done, limit, cfg.default_country)
    except AuthError as e:
        print("\n  " + i18n.t("cannot_connect", e=e))
        print("  " + i18n.t("check_key"))
        return 1
    except CreditError as e:
        print(f"\n  {e}")
        print("  " + i18n.t("credit_topup"))
        return 1
    except Exception as e:
        print("\n  " + i18n.t("verify_failed", e=e))
        return 1

    end = limit if limit is not None else len(rows)
    api_calls = count_api_calls(rows[done:end], tasks)
    throughput = limits.throughput_per_s(cfg.rate_safety)
    eta_s = api_calls / throughput if throughput else 0

    print("  " + i18n.t("est_scope", txt=range_txt))
    print("  " + i18n.t("est_rows", n=remaining))
    print("  " + i18n.t("est_calls", n=api_calls))
    if limits.credits_left is not None:
        left = (i18n.t("est_credits_of", left=limits.credits_left, limit=limits.credits_limit)
                if limits.credits_limit else str(limits.credits_left))
        print("  " + i18n.t("est_credits", left=left))
        if api_calls > limits.credits_left:
            print("  ⚠  " + i18n.t("est_warn1"))
            print("     " + i18n.t("est_warn2"))
    print("  " + i18n.t("est_rate", rate=f"{throughput:.1f}",
                        rl=limits.rate_limit or "?", rp=limits.rate_period or "?"))
    print("  " + i18n.t("est_eta", eta=_format_time(eta_s)))
    print()
    print("  " + i18n.t("privacy1"))
    print("  " + i18n.t("privacy2"))
    print()

    if not _confirm("  " + i18n.t("run_confirm"), default_yes=True):
        print("  " + i18n.t("cancelled"))
        return 0

    _heading(i18n.t("running"))
    start = time.monotonic()
    result = process(
        client=client, input_file=input_file, output_csv=output_csv, rows=rows,
        input_header=header, tasks=tasks, default_country=cfg.default_country,
        rate_safety=cfg.rate_safety, row_limit=limit, resume=True,
        progress=_progress, make_xlsx=True, output_encoding=cfg.output_encoding,
        guard_csv=cfg.csv_guard, concurrency=cfg.concurrency,
    )
    duration = time.monotonic() - start
    print()

    _heading(i18n.t("done") if result.completed else i18n.t("interrupted"))
    stat = result.stats
    print("  " + i18n.t("processed_rows", n=stat.total_rows))
    print("  " + i18n.t("api_calls", n=stat.api_calls))
    for name, count in sorted(stat.by_result.items(), key=lambda x: -x[1]):
        print(f"    {name:<34} {count}")
    if stat.errors:
        print("  " + i18n.t("comm_errors", n=stat.errors))

    print()
    print("  " + i18n.t("results_csv", p=result.output_csv))
    if result.output_xlsx:
        print("  " + i18n.t("results_xlsx", p=result.output_xlsx))

    if result.completed:
        report = cfg.OUTPUT_DIR / f"{input_file.stem}_report.html"
        create_report(report, input_file.name, tasks, stat, True,
                       result.output_csv, result.output_xlsx, duration)
        print("  " + i18n.t("report_html", p=report))
    else:
        print()
        print("  " + i18n.t("interrupted_1"))
        print("  " + i18n.t("interrupted_2"))

    print()
    return 0
