# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AVANTRO s.r.o.
"""
HTML run-report generator.

The report is 100% self-contained (no external scripts, fonts or CSS - all inline),
works offline. Text adapts to the current language (i18n).
"""

from __future__ import annotations

import html
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import i18n
from .processor import ERROR_PROPOSAL, STILL_INVALID, Stats, Task, is_enrich

# Everything below is decided by the API's own `proposal` code - never by the words in
# the translated result. Matching on text meant the Czech "neplatné (opraven jen formát)"
# contained "oprav" and was counted as a rescue, while the English label was not: the same
# rows produced different numbers depending on the interface language.
#
# What the codes mean (Foxentry API):
#   *Correction*  a correction was made - even a partial one, and even when the value
#                 stays invalid afterwards (a phone number can be reformatted and still
#                 not exist). It is still a correction.
#   *Suggestion*  the API has candidates but cannot decide - the user must pick.
#   valid / invalid / unknown  the verdict itself.

_FLAG_COLOR = {
    "valid": "#3fb950",
    "corrected": "#58a6ff",
    "invalid": "#f85149",
    "suggestion": "#d29922",
    "uncertain": "#a371f7",
    "error": "#db6d28",
}

# The order the bars appear in.
_FLAG_ORDER = ("valid", "corrected", "invalid", "suggestion", "uncertain", "error")


def flags_for(outcome: str | None) -> set:
    """
    What is true about one result. A row can be several things at once, so these are
    NOT buckets - they are facts, and they overlap on purpose:

      valid       the value is valid once Foxentry is done with it
      corrected   Foxentry changed something (a partial fix counts - it is still work done)
      invalid     the value is not valid once Foxentry is done with it
      suggestion  the API offered candidates and cannot decide - the user has to pick

    A partial correction is BOTH corrected and invalid: the formatting was fixed, the
    value still does not exist. A `validWithSuggestion` is BOTH valid and a suggestion.
    Forcing these into one bucket each is what produced five different kinds of "invalid".

    Whether a correction actually made the value valid is decided by
    `resultCorrected.isValid`, which `processor.outcome_for()` has already folded into
    the code as `STILL_INVALID` - never by the proposal code on its own.
    """
    code = (outcome or "").strip()
    if code == ERROR_PROPOSAL:
        return {"error"}
    if not code:
        return set()

    still_invalid = code.endswith(STILL_INVALID)
    if still_invalid:
        code = code[:-len(STILL_INVALID)]

    out = set()
    corrected = "Correction" in code
    partial = "PartialCorrection" in code
    if "Suggestion" in code:
        out.add("suggestion")
    if corrected:
        out.add("corrected")

    if code.startswith("valid"):
        out.add("valid")
    elif code.startswith("invalid"):
        # A correction only rescues the value if the value is valid afterwards. A partial
        # one never is; a reformatted phone number that still does not exist is not either.
        out.add("valid" if (corrected and not partial and not still_invalid) else "invalid")
    else:
        out.add("uncertain")        # unknown*
    return out


def flag_counts(by_outcome: dict | None) -> list[dict]:
    """The bars, computed once for every surface that shows them (HTML report, wizard, CLI).

    Returns them in display order: [{flag, count, pct, color}, …]. `pct` is out of all
    validated values, so the bars overlap and do not add up to 100 % - see `flags_for()`.
    """
    flags: Counter = Counter()
    validated = 0
    for outcome, n in (by_outcome or {}).items():
        f = flags_for(outcome)
        if not f:
            continue
        validated += n
        for name in f:
            flags[name] += n
    total = validated or 1
    return [{"flag": f, "count": flags[f], "pct": round(100.0 * flags[f] / total, 1),
             "color": _color_for(f)}
            for f in _FLAG_ORDER if flags.get(f)]


def _color_for(flag: str) -> str:
    return _FLAG_COLOR.get(flag, "#8b949e")


def _esc(x) -> str:
    return html.escape(str(x))


def marketing_metrics(by_outcome: dict | None, services: list[str] | None = None) -> dict:
    """Value metrics (input/output error rate, rescued), counted from the API's own codes."""
    flags: Counter = Counter()
    validated = 0
    input_file = 0
    for outcome, n in (by_outcome or {}).items():
        f = flags_for(outcome)
        if not f or "error" in f:
            continue
        validated += n
        for name in f:
            flags[name] += n
        if (outcome or "").startswith("invalid"):
            input_file += n          # the value arrived wrong, whatever happened next

    rescued = flags["corrected"]     # every correction counts, partial ones included
    output = flags["invalid"]        # what is still wrong once Foxentry is done

    def _r(x: int) -> float:
        return round(100.0 * x / validated, 1) if validated else 0.0

    return {
        "validated": validated,
        "rescued": rescued,
        "input_rate": _r(input_file),
        "output_rate": _r(output),
        "rescued_rate": _r(rescued),
        "services": list(dict.fromkeys(services or [])),  # unique, keeps order
    }


def _value_card_html(mtr: dict, enriched: int = 0) -> str:
    """HTML 'Foxentry value' card (for the standalone report)."""
    if not mtr.get("validated"):
        return ""
    if mtr["input_rate"] > 0 or mtr["rescued"] > 0:
        summary = i18n.t("rep_value_summary", inp=mtr["input_rate"], out=mtr["output_rate"],
                         n=mtr["rescued"], pct=mtr["rescued_rate"])
    else:
        summary = i18n.t("rep_value_clean")
    if enriched > 0:
        summary += " " + i18n.t("rep_enriched_summary", n=enriched)
    bullets = []
    for key in mtr["services"]:
        txt = i18n.t("rep_ben_" + key)
        if txt and txt != "rep_ben_" + key:
            bullets.append(f"<li>{_esc(txt)}</li>")
    bullets_html = (f'<ul style="margin:.9rem 0 0;padding-left:1.1rem;line-height:1.75">'
                    f'{"".join(bullets)}</ul>') if bullets else ""
    enr_kpi = (f'<div class="kpi"><div class="num" style="color:#a371f7">{enriched}</div>'
               f'<div class="lbl">{i18n.t("rep_enriched_count")}</div></div>') if enriched > 0 else ""
    return f"""
  <div class="card"><h2>{i18n.t('rep_value_title')}</h2>
    <div class="kpis">
      <div class="kpi"><div class="num" style="color:#d29922">{mtr['input_rate']} %</div><div class="lbl">{i18n.t('rep_in_err')}</div></div>
      <div class="kpi"><div class="num" style="color:#3fb950">{mtr['output_rate']} %</div><div class="lbl">{i18n.t('rep_out_err')}</div></div>
      <div class="kpi"><div class="num" style="color:#58a6ff">{mtr['rescued']} <span style="font-size:.5em;color:#8b949e">({mtr['rescued_rate']} %)</span></div><div class="lbl">{i18n.t('rep_rescued')}</div></div>
      {enr_kpi}
    </div>
    <div class="pill" style="margin-top:1rem">{_esc(summary)}</div>
    {bullets_html}
  </div>"""


def create_report(path: Path, filename: str, tasks: list[Task], stat: Stats,
                  completed: bool, output_csv: Path, output_xlsx: Path | None,
                  duration_s: float) -> None:
    # The bars are independent facts about the results, not slices of a pie: a row can be
    # corrected AND still invalid, or valid AND carry a suggestion. They therefore overlap,
    # and the percentages are of all validated values - they do not add up to 100 %.
    bars = flag_counts(getattr(stat, "by_outcome", {}) or {})
    max_v = max((b["count"] for b in bars), default=1)

    rows = []
    for bar in bars:
        flag, count, proc = bar["flag"], bar["count"], bar["pct"]
        width = max(2, int(100 * count / max_v))
        rows.append(f"""
        <div class="bar-row">
          <div class="bar-label">{_esc(i18n.t("cat_" + flag))}</div>
          <div class="bar-track"><div class="bar-fill" style="width:{width}%;background:{bar["color"]}"></div></div>
          <div class="bar-value">{count} <span class="muted">({proc:.1f} %)</span></div>
        </div>""")
    if rows:
        rows.append(f"""
        <div class="pill" style="margin-top:.9rem">{_esc(i18n.t("rep_overlap"))}</div>""")

    def _job_label(u: Task) -> str:
        s = _esc(i18n.endpoint_name(u.endpoint.key))
        if is_enrich(u):
            s += f' <span class="enr">+ {i18n.t("rep_enriched")}</span>'
        return s
    listing = ", ".join(_job_label(u) for u in tasks)
    is_enriched = any(is_enrich(u) for u in tasks)
    # Enrichment chart: how many data points were added per service (bars like the results).
    enr_service = getattr(stat, "enriched_by_service", {}) or {}
    group_key = {u.group: u.endpoint.key for u in tasks}
    enr_rows = []
    if enr_service:
        emax = max(enr_service.values()) or 1
        for grp, count in sorted(enr_service.items(), key=lambda x: -x[1]):
            width = max(2, int(100 * count / emax))
            label = _esc(i18n.endpoint_name(group_key.get(grp, grp)))
            enr_rows.append(f"""
        <div class="bar-row">
          <div class="bar-label">{label}</div>
          <div class="bar-track"><div class="bar-fill" style="width:{width}%;background:#a371f7"></div></div>
          <div class="bar-value">{count} <span class="muted">{_esc(i18n.t('rep_enriched_unit'))}</span></div>
        </div>""")
    enr_card = (f'\n  <div class="card"><h2>{i18n.t("rep_enrich_title")}</h2>{"".join(enr_rows)}</div>') if enr_rows else (
        f'\n  <div class="card"><h2>{i18n.t("rep_enrich_title")}</h2>'
        f'<div class="pill" style="color:#d29922">{i18n.t("rep_enrich_empty")}</div></div>' if is_enriched else "")
    value_card = _value_card_html(
        marketing_metrics(getattr(stat, "by_outcome", {}), [u.endpoint.key for u in tasks]),
        getattr(stat, "enriched", 0))
    status = i18n.t("rep_status_done") if completed else i18n.t("rep_status_interrupted")
    status_color = "#3fb950" if completed else "#d29922"
    duration_txt = _format_time(duration_s)
    lang = i18n.get_lang()

    files = [f"<li><code>{_esc(output_csv.name)}</code> - {i18n.t('rep_csv_desc')}</li>"]
    if output_xlsx:
        files.append(f"<li><code>{_esc(output_xlsx.name)}</code> - {i18n.t('rep_xlsx_desc')}</li>")

    html_content = f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{i18n.t('rep_title')} - {_esc(filename)}</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg%20version%3D%221.1%22%20id%3D%22Vrstva_1%22%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20xmlns%3Axlink%3D%22http%3A%2F%2Fwww.w3.org%2F1999%2Fxlink%22%20x%3D%220px%22%20y%3D%220px%22%20viewBox%3D%220%200%20236.3%20236.2%22%20style%3D%22enable-background%3Anew%200%200%20236.3%20236.2%3B%22%20xml%3Aspace%3D%22preserve%22%3E%20%3Cstyle%20type%3D%22text%2Fcss%22%3E%20.st0%7Bfill%3A%23E74600%3B%7D%20.st1%7Bfill%3A%23CC3000%3B%7D%20.st2%7Bfill%3A%23FF6102%3B%7D%20%3C%2Fstyle%3E%20%3Cg%20id%3D%22Obd%C3%A9ln%C3%ADk_1_kopie_3_2_%22%3E%20%3Cg%20id%3D%22XMLID_42_%22%3E%20%3Cpath%20id%3D%22XMLID_3_%22%20class%3D%22st0%22%20d%3D%22M115.3%2C120.8c7.7%2C18.5%2C33.8%2C54.7%2C38.9%2C61c3.6%2C4.5%2C79.2%2C53.4%2C82.1%2C54.5V0%22%2F%3E%20%3C%2Fg%3E%20%3C%2Fg%3E%20%3Cg%20id%3D%22Obd%C3%A9ln%C3%ADk_1_kopie_2_2_%22%3E%20%3Cg%20id%3D%22XMLID_49_%22%3E%20%3Cpolygon%20id%3D%22XMLID_59_%22%20class%3D%22st1%22%20points%3D%22115.3%2C120.8%20115.1%2C121.2%2071.7%2C184.9%20114.4%2C236.2%20236.3%2C236.2%20%22%2F%3E%20%3C%2Fg%3E%20%3C%2Fg%3E%20%3Cg%20id%3D%22Obd%C3%A9ln%C3%ADk_1_kopie_4_2_%22%3E%20%3Cg%20id%3D%22XMLID_29_%22%3E%20%3Cpath%20id%3D%22XMLID_41_%22%20class%3D%22st2%22%20d%3D%22M43.9%2C154.7C14.2%2C184.5%2C0%2C236.2%2C0%2C236.2h115.3V120.8C115.3%2C120.9%2C71.8%2C126.9%2C43.9%2C154.7z%22%2F%3E%20%3C%2Fg%3E%20%3C%2Fg%3E%20%3Cg%20id%3D%22Obd%C3%A9ln%C3%ADk_1_2_%22%3E%20%3Cg%20id%3D%22XMLID_43_%22%3E%20%3Cpolygon%20id%3D%22XMLID_53_%22%20class%3D%22st2%22%20points%3D%22115.3%2C0%20115.3%2C120.8%20236.3%2C120.8%20%22%2F%3E%20%3C%2Fg%3E%20%3C%2Fg%3E%20%3C%2Fsvg%3E">
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:2.5rem 1.25rem; background:#0d1117; color:#e6edf3;
    font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; line-height:1.55; }}
  .wrap {{ max-width:820px; margin:0 auto; }}
  h1 {{ font-size:1.4rem; margin:0 0 .35rem; font-weight:600; }}
  .sub {{ color:#8b949e; font-size:.85rem; margin-bottom:2rem; }}
  .card {{ background:#161b22; border:1px solid #30363d; border-radius:10px; padding:1.25rem 1.4rem; margin-bottom:1.1rem; }}
  .card h2 {{ font-size:.8rem; text-transform:uppercase; letter-spacing:.08em; color:#8b949e; margin:0 0 1rem; font-weight:600; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:1rem; }}
  .kpi .num {{ font-size:1.9rem; font-weight:700; }}
  .kpi .lbl {{ color:#8b949e; font-size:.8rem; }}
  .bar-row {{ display:grid; grid-template-columns:230px 1fr 120px; align-items:center; gap:.8rem; margin-bottom:.55rem; font-size:.85rem; }}
  .bar-track {{ background:#0d1117; border:1px solid #21262d; border-radius:6px; height:22px; overflow:hidden; }}
  .bar-fill {{ height:100%; border-radius:5px 0 0 5px; }}
  .bar-value {{ text-align:right; }}
  .muted {{ color:#6e7681; }}
  code {{ background:#0d1117; border:1px solid #21262d; padding:.1rem .4rem; border-radius:5px; font-size:.85em; }}
  ul {{ margin:.4rem 0; padding-left:1.2rem; }} li {{ margin:.25rem 0; }}
  .stav {{ display:inline-block; padding:.15rem .6rem; border-radius:999px; font-size:.8rem; border:1px solid {status_color}55; color:{status_color}; }}
  .pill {{ color:#8b949e; font-size:.8rem }}
  .enr {{ display:inline-block; font-size:.72rem; color:#a371f7; border:1px solid #a371f755; border-radius:999px; padding:.02rem .45rem; }}
  @media (max-width:560px) {{ .bar-row {{ grid-template-columns:1fr; gap:.2rem }} }}
</style></head>
<body><div class="wrap">
  <h1 style="display:flex;align-items:center;gap:.55rem"><img src="data:image/svg+xml,%3Csvg%20version%3D%221.1%22%20id%3D%22Vrstva_1%22%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20xmlns%3Axlink%3D%22http%3A%2F%2Fwww.w3.org%2F1999%2Fxlink%22%20x%3D%220px%22%20y%3D%220px%22%20viewBox%3D%220%200%20236.3%20236.2%22%20style%3D%22enable-background%3Anew%200%200%20236.3%20236.2%3B%22%20xml%3Aspace%3D%22preserve%22%3E%20%3Cstyle%20type%3D%22text%2Fcss%22%3E%20.st0%7Bfill%3A%23E74600%3B%7D%20.st1%7Bfill%3A%23CC3000%3B%7D%20.st2%7Bfill%3A%23FF6102%3B%7D%20%3C%2Fstyle%3E%20%3Cg%20id%3D%22Obd%C3%A9ln%C3%ADk_1_kopie_3_2_%22%3E%20%3Cg%20id%3D%22XMLID_42_%22%3E%20%3Cpath%20id%3D%22XMLID_3_%22%20class%3D%22st0%22%20d%3D%22M115.3%2C120.8c7.7%2C18.5%2C33.8%2C54.7%2C38.9%2C61c3.6%2C4.5%2C79.2%2C53.4%2C82.1%2C54.5V0%22%2F%3E%20%3C%2Fg%3E%20%3C%2Fg%3E%20%3Cg%20id%3D%22Obd%C3%A9ln%C3%ADk_1_kopie_2_2_%22%3E%20%3Cg%20id%3D%22XMLID_49_%22%3E%20%3Cpolygon%20id%3D%22XMLID_59_%22%20class%3D%22st1%22%20points%3D%22115.3%2C120.8%20115.1%2C121.2%2071.7%2C184.9%20114.4%2C236.2%20236.3%2C236.2%20%22%2F%3E%20%3C%2Fg%3E%20%3C%2Fg%3E%20%3Cg%20id%3D%22Obd%C3%A9ln%C3%ADk_1_kopie_4_2_%22%3E%20%3Cg%20id%3D%22XMLID_29_%22%3E%20%3Cpath%20id%3D%22XMLID_41_%22%20class%3D%22st2%22%20d%3D%22M43.9%2C154.7C14.2%2C184.5%2C0%2C236.2%2C0%2C236.2h115.3V120.8C115.3%2C120.9%2C71.8%2C126.9%2C43.9%2C154.7z%22%2F%3E%20%3C%2Fg%3E%20%3C%2Fg%3E%20%3Cg%20id%3D%22Obd%C3%A9ln%C3%ADk_1_2_%22%3E%20%3Cg%20id%3D%22XMLID_43_%22%3E%20%3Cpolygon%20id%3D%22XMLID_53_%22%20class%3D%22st2%22%20points%3D%22115.3%2C0%20115.3%2C120.8%20236.3%2C120.8%20%22%2F%3E%20%3C%2Fg%3E%20%3C%2Fg%3E%20%3C%2Fsvg%3E" alt="Foxentry" style="height:26px">{i18n.t('rep_title')}</h1>
  <div class="sub">{i18n.t('rep_file')} <strong>{_esc(filename)}</strong> &nbsp;·&nbsp;
    {datetime.now().strftime("%d.%m.%Y %H:%M")} &nbsp;·&nbsp; <span class="stav">{status}</span></div>

  <div class="card"><h2>{i18n.t('rep_summary')}</h2>
    <div class="grid">
      <div class="kpi"><div class="num">{stat.total_rows}</div><div class="lbl">{i18n.t('rep_rows')}</div></div>
      <div class="kpi"><div class="num">{stat.api_calls}</div><div class="lbl">{i18n.t('rep_calls')}</div></div>
      <div class="kpi"><div class="num">{duration_txt}</div><div class="lbl">{i18n.t('rep_time')}</div></div>
      <div class="kpi"><div class="num" style="color:{'#f85149' if stat.errors else '#3fb950'}">{stat.errors}</div><div class="lbl">{i18n.t('rep_errors')}</div></div>
    </div>
    <div class="pill" style="margin-top:1rem">{i18n.t('rep_validations')}: {listing}</div>
    {f'<div class="pill" style="margin-top:.5rem">{i18n.t("rep_enrich_note")}</div>' if is_enriched else ''}
    {f'<div class="pill" style="margin-top:.5rem;color:#3fb950">{i18n.t("rep_dedup_note", n=getattr(stat, "deduplicated", 0))}</div>' if getattr(stat, "deduplicated", 0) > 0 else ''}
  </div>

  <div class="card"><h2>{i18n.t('rep_by_type')}</h2>
    {''.join(rows) if rows else f'<div class="muted">{i18n.t("rep_no_data")}</div>'}
  </div>{enr_card}
{value_card}

  <div class="card"><h2>{i18n.t('rep_outputs')}</h2>
    <ul>{''.join(files)}</ul>
    <div class="pill">{i18n.t('rep_updated_note')}</div>
  </div>

  <div class="sub" style="margin-top:2rem;text-align:center">{i18n.t('rep_footer')}</div>
</div></body></html>"""
    path.write_text(html_content, encoding="utf-8")


def _format_time(s: float) -> str:
    s = int(round(s))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min {s % 60} s"
    return f"{s // 3600} h {(s % 3600) // 60} min"
