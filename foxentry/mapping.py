# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AVANTRO s.r.o.
"""
Pairing columns -> validation tasks (as in the Foxentry app).

In the wizard, the client assigns a service and field to each column. Multiple columns can form
ONE record group (e.g. street + number + city + ZIP = one address = one call).
There can be several groups (Address 1, Address 2). The mapping builds a task list (`Task`),
each with its own per-service settings (`options`).

Everything sticks to confirmed Foxentry API options; "off" means the option is not sent.
"""

from __future__ import annotations

import re

from typing import Any

from . import i18n
from .endpoints import ENDPOINTS, KEY_TO_TYPE, SERVICE_ALIAS, SUBTYPES, TYPE_TO_KEY, subtype_to_field
from .classification import classify_columns
from .processor import Task

# Service order in the wizard (like the tabs in the app)
SERVICE_ORDER = ["location", "company", "email", "phone", "name"]


def _label(d: dict[str, str], lang: str) -> str:
    return d.get(lang) or d.get("en") or next(iter(d.values()))


def schema_for_ui(lang: str | None = None) -> list[dict[str, Any]]:
    """Services + field options (subtypes as in the app) + settings, localized."""
    lang = lang or i18n.get_lang()
    out = []
    for key in SERVICE_ORDER:
        typ = next(t for t, k in TYPE_TO_KEY.items() if k == key)
        fields = [{"field": api_field, "label": _label(lbl, lang),
                   "example": lbl.get("ex", ""),
                   "desc": _label(lbl["desc"], lang) if lbl.get("desc") else ""}
                  for (_st, api_field, lbl) in SUBTYPES[typ]]
        out.append({
            "service": key,
            "name": i18n.endpoint_name(key),
            "countries": i18n.countries(ENDPOINTS[key].supported_countries),
            "grouped": True,  # groups allowed for all (multiple addresses, multiple emails, user+domain...)
            "fields": fields,
            "settings": [_loc_setting(st, lang) for st in SETTINGS.get(key, [])],
            "warn": _label(_WARN[key], lang) if key in _WARN else "",
            "note": _label(_NOTE[key], lang) if key in _NOTE else "",
        })
    return out


def suggest_mapping(header: list[str], rows: list[dict[str, str]] | None = None) -> list[dict[str, Any]]:
    """
    Mapping suggestion based on column CONTENT (local classifier). When there is no data,
    it falls back to guessing from column names. Returns editable items for the wizard.
    """
    result = classify_columns(header, rows or [])
    suggestion: list[dict[str, Any]] = []
    for c in result["columns"]:
        # No automatic pairing. The content analysis is used ONLY to rank the options offered
        # in the picker (candidates); every column starts unmapped and the user maps it manually.
        suggestion.append({
            "column": c["columnName"],
            "service": None,
            "field": None,
            "group": 1,
            "subtype": None,
            "reasoning": "",
            "candidates": c.get("candidates", []),
        })
    return suggestion
# --- Per-service settings (human/marketing texts + tooltips) ----------------
# Each setting: id, type (select|checkbox|order), label, desc, default, options.
# Values map to OAS 2.1 options in _options_from_settings().

_CORRECT_OPTS = [
    ("full", {"cs": "Opravit vše", "en": "Correct everything"}),
    ("format", {"cs": "Jen sjednotit formát", "en": "Formatting only"}),
    ("suggestion", {"cs": "Jen navrhnout (needitovat)", "en": "Only suggest (don't change)"}),
    ("none", {"cs": "Neopravovat", "en": "Don't correct"}),
]
_CITY_OPTS = [
    ("minimal", {"cs": "Praha", "en": "Praha"}),
    ("basic", {"cs": "Praha 8", "en": "Praha 8"}),
    ("extended", {"cs": "Praha 8 - Karlín", "en": "Praha 8 - Karlín"}),
]
_ZIP_OPTS = [
    ("spaced", {"cs": "Formátované (130 00, 12-345…)", "en": "Formatted (130 00, 12-345…)"}),
    ("plain", {"cs": "Neformátované (13000)", "en": "Unformatted (13000)"}),
]
_COUNTRY_OPTS = [
    ("alpha2", {"cs": "CZ (kód)", "en": "CZ (code)"}),
    ("alpha3", {"cs": "CZE (kód)", "en": "CZE (code)"}),
    ("local", {"cs": "Česká republika", "en": "Česká republika"}),
    ("localShortened", {"cs": "Česko", "en": "Česko"}),
    ("international", {"cs": "Czech Republic", "en": "Czech Republic"}),
    ("internationalShortened", {"cs": "Czechia", "en": "Czechia"}),
]
_NUMFMT_OPTS = [
    ("e164", {"cs": "+420777074075", "en": "+420777074075"}),
    ("e123", {"cs": "+420 777 074 075", "en": "+420 777 074 075"}),
    ("national", {"cs": "777 074 075", "en": "777 074 075"}),
    ("raw", {"cs": "777074075 (jen číslice)", "en": "777074075 (digits only)"}),
]
_PHONE_VALID_OPTS = [
    ("basic", {"cs": "Základní (rychlé, levnější)", "en": "Basic (fast, cheaper)"}),
    ("extended", {"cs": "Rozšířená — operátor, typ, země", "en": "Extended — carrier, type, country"}),
]
_PREFIX_OPTS = [
    ("+420", {"cs": "Česko (+420)", "en": "Czechia (+420)"}),
    ("+421", {"cs": "Slovensko (+421)", "en": "Slovakia (+421)"}),
    ("+48", {"cs": "Polsko (+48)", "en": "Poland (+48)"}),
    ("+49", {"cs": "Německo (+49)", "en": "Germany (+49)"}),
    ("+43", {"cs": "Rakousko (+43)", "en": "Austria (+43)"}),
]
_PREFIX_DEFAULT = ["+420", "+421", "+48", "+49", "+43"]
_PREFIX_NEIGHBORS = {
    "+420": ["+420", "+421", "+48", "+49", "+43"],
    "+421": ["+421", "+420", "+48", "+43", "+49"],
    "+48":  ["+48", "+420", "+421", "+49", "+43"],
    "+49":  ["+49", "+43", "+420", "+48", "+421"],
    "+43":  ["+43", "+49", "+420", "+421", "+48"],
}
_COUNTRY_PREFIX = {"CZ": "+420", "SK": "+421", "PL": "+48", "DE": "+49", "AT": "+43"}


def _sel(sid, l_cs, l_en, d_cs, d_en, options, default):
    return {"id": sid, "type": "select", "label": {"cs": l_cs, "en": l_en},
            "desc": {"cs": d_cs, "en": d_en}, "options": options, "default": default}


def _chk(sid, l_cs, l_en, d_cs, d_en, default, **extra):
    d = {"id": sid, "type": "checkbox", "label": {"cs": l_cs, "en": l_en},
         "desc": {"cs": d_cs, "en": d_en}, "default": default}
    d.update(extra)
    return d


def _correct(what_cs, what_en):
    return _sel("correct", "Opravovat " + what_cs, "Fix " + what_en,
                "Jak se mají chovat automatické opravy.", "How automatic corrections behave.",
                _CORRECT_OPTS, "full")


_CITY = lambda: _sel("cityFormat", "Formát města", "City format",
                     "V jakém tvaru se vrátí město.", "How the city is returned.", _CITY_OPTS, "basic")
_ZIP = lambda: _sel("zipFormat", "Formát PSČ", "ZIP format",
                    "Formátované (mezera/pomlčka dle země), nebo bez.", "Formatted (space/dash per country) or plain.", _ZIP_OPTS, "spaced")
_COUNTRY = lambda: _sel("countryFormat", "Formát země", "Country format",
                        "Vrátit kód (CZ) nebo název země.", "Return a code (CZ) or a country name.",
                        _COUNTRY_OPTS, "alpha2")
_ENRICH = lambda what_cs, what_en: _chk("enrich", "Obohatit data (více informací)", "Enrich data (more info)",
                                        "Vrátí navíc " + what_cs + " Mírně zvyšuje cenu.",
                                        "Also returns " + what_en + " Slightly higher price.", False)

SETTINGS: dict[str, list[dict]] = {
    "location": [
        _correct("adresy", "addresses"),
        _CITY(), _ZIP(), _COUNTRY(),
        _chk("post_office", "Brát název pošty jako město", "Accept post office as city",
             "Když je místo města uvedený název pošty, uznat to jako platné.",
             "If a post-office name stands in for the city, accept it as valid.", True),
        _chk("add_country", "Doplnit výchozí zemi (když není namapovaná)", "Add default country (when not mapped)",
             "Když nenamapujete sloupec se zemí, přidá se do dotazu výchozí země z nastavení. "
             "Nechte vypnuté, pokud chcete posílat jen to, co jste namapovali.",
             "If you don’t map a country column, the default country from settings is added to the query. "
             "Leave off to send only what you mapped.", False),
        _ENRICH("GPS, kraj, okres a další detaily.", "GPS, region, district and more."),
    ],
    "company": [
        _correct("údaje firem", "company data"),
        _CITY(), _ZIP(), _COUNTRY(),
        _chk("terminated", "Zahrnout i zaniklé firmy", "Include terminated companies",
             "Hledat i ve firmách, které už zanikly.", "Also search companies that no longer exist.", True),
        _chk("add_country", "Doplnit výchozí zemi (když není namapovaná)", "Add default country (when not mapped)",
             "Když nenamapujete sloupec se zemí, přidá se do dotazu výchozí země z nastavení. "
             "Nechte vypnuté, pokud chcete posílat jen to, co jste namapovali.",
             "If you don’t map a country column, the default country from settings is added to the query. "
             "Leave off to send only what you mapped.", False),
        _ENRICH("adresu, právní formu, obory činnosti.", "address, legal form and activities."),
    ],
    "email": [
        _correct("e‑maily", "e‑mails"),
        _chk("reject_disposable", "Odmítat jednorázové e‑maily", "Reject disposable e‑mails",
             "Dočasné schránky (např. 10minutemail) označit jako neplatné.",
             "Mark temporary inboxes (e.g. 10minutemail) as invalid.", True),
        _chk("reject_phishing", "Odmítat podvodné (phishing) domény", "Reject phishing domains",
             "Známé podvodné domény označit jako neplatné.", "Mark known fraudulent domains as invalid.", True),
        _chk("reject_freemail", "Odmítat freemaily", "Reject freemails",
             "Gmail, Seznam apod. označit jako neplatné (když chcete jen firemní adresy).",
             "Mark Gmail, Seznam etc. as invalid (when you only want corporate addresses).", False),
    ],
    "phone": [
        _sel("validation", "Hloubka kontroly", "Validation depth",
             "Rozšířená navíc zjistí operátora, typ čísla a region (vyšší cena).",
             "Extended also detects carrier, number type and region (higher price).",
             _PHONE_VALID_OPTS, "basic"),
        _correct("čísla", "numbers"),
        _sel("numberFormat", "Formát čísla", "Number format",
             "V jakém tvaru se vrátí telefonní číslo.", "How the phone number is returned.",
             _NUMFMT_OPTS, "e164"),
        {"id": "prefixes", "type": "order",
         "label": {"cs": "Předvolby zemí (pořadí)", "en": "Country prefixes (order)"},
         "desc": {"cs": "Když číslo nemá předvolbu, zkusí se země v tomto pořadí. Pořadí změníte šipkami.",
                  "en": "When a number has no prefix, countries are tried in this order. Reorder with the arrows."},
         "options": _PREFIX_OPTS, "default": list(_PREFIX_DEFAULT)},
    ],
    "name": [
        _correct("jména", "names"),
        _chk("degrees", "Akceptovat tituly", "Accept academic titles",
             "Uzná „Ing. Jan Novák“ jako platné jméno.", "Treats Ing. titles as a valid name.", False),
        _chk("context", "Akceptovat dovětky (ml., st.)", "Accept context (jr., sr.)",
             "Uzná „Jan Novák ml.“ nebo „st.“ jako platné.", "Treats Jr./Sr. suffixes as valid.", False),
        _ENRICH("rod, oslovení (5. pád) a jmeniny.", "gender, vocative form and name day."),
    ],
}

_WARN = {
    "name": {"cs": "Jména umíme jen pro ČR a SK. U jiných zemí nečekejte spolehlivé výsledky.",
              "en": "Names are supported for CZ and SK only — other countries may be unreliable."},
}
_NOTE = {}


def _loc_setting(st: dict, lang: str) -> dict:
    out = {"id": st["id"], "type": st["type"], "label": _label(st["label"], lang),
           "desc": _label(st["desc"], lang) if st.get("desc") else "", "default": st["default"]}
    if st.get("options"):
        out["options"] = [{"value": v, "label": _label(lbl, lang)} for v, lbl in st["options"]]
    return out


def _sample(col: str, rows: list[dict[str, str]], n: int = 20) -> list[str]:
    out = []
    for r in rows[:n * 3]:
        v = (r.get(col) or "").strip()
        if v:
            out.append(v)
        if len(out) >= n:
            break
    return out


def _guess_zip(vz):
    if not vz:
        return None
    spaced = sum(1 for v in vz if re.search(r"\d{3}\s\d{2}", v))
    return "spaced" if spaced >= len(vz) / 2 else "plain"


def _guess_city(vz):
    if not vz:
        return None
    if any(" - " in v or " – " in v for v in vz):
        return "extended"
    if any(re.search(r"\s\d+$", v) for v in vz):
        return "basic"
    return "minimal"


def _guess_country(vz):
    if not vz:
        return None
    v = vz[0].strip()
    if len(v) == 2 and v.isalpha():
        return "alpha2"
    if len(v) == 3 and v.isalpha():
        return "alpha3"
    if any(c in v for c in "áčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ") or "republik" in v.lower():
        return "local"
    if "republic" in v.lower():
        return "international"
    return "alpha2"


def _guess_numformat(vz):
    if not vz:
        return None
    plus = sum(1 for v in vz if v.strip().startswith("+"))
    spaces = sum(1 for v in vz if " " in v.strip())
    if plus >= len(vz) / 2:
        return "e123" if spaces >= len(vz) / 2 else "e164"
    return "national" if spaces >= len(vz) / 2 else "e164"


def _guess_prefix(vz, default_country):
    counts = {}
    for v in vz:
        v = v.strip()
        for pfx in sorted(_PREFIX_NEIGHBORS, key=len, reverse=True):
            if v.startswith(pfx):
                counts[pfx] = counts.get(pfx, 0) + 1
                break
    if counts:
        dom = max(counts, key=counts.get)
    else:
        dom = _COUNTRY_PREFIX.get((default_country or "CZ").upper(), "+420")
    return list(_PREFIX_NEIGHBORS.get(dom, _PREFIX_DEFAULT))


def suggest_settings(suggestion, rows, default_country="CZ"):
    """From data (and the suggested mapping) preselect formats and prefix order."""
    def column(service, field):
        for m in suggestion:
            if m.get("service") == service and m.get("field") == field and m.get("column"):
                return m["column"]
        return None

    out = {}
    for svc in ("location", "company"):
        d = {}
        c = column(svc, "zip")
        if c:
            z = _guess_zip(_sample(c, rows))
            if z:
                d["zipFormat"] = z
        c = column(svc, "city")
        if c:
            z = _guess_city(_sample(c, rows))
            if z:
                d["cityFormat"] = z
        c = column(svc, "country")
        if c:
            z = _guess_country(_sample(c, rows))
            if z:
                d["countryFormat"] = z
        if d:
            out[svc] = d
    c = column("phone", "number")
    if c:
        vz = _sample(c, rows)
        td = {}
        nf = _guess_numformat(vz)
        if nf:
            td["numberFormat"] = nf
        td["prefixes"] = _guess_prefix(vz, default_country)
        out["phone"] = td
    return out


def _options_from_settings(service, s):
    """Build API `options` (OAS 2.1) from the setting values."""
    def val(k, d):
        v = s.get(k)
        return v if v not in (None, "") else d

    def on(k, d):
        v = s.get(k, d)
        return v in (True, "true", "on", "1", 1)

    o = {}
    if service == "location":
        o["correctionMode"] = val("correct", "full")
        o["cityFormat"] = val("cityFormat", "basic")
        o["zipFormat"] = (val("zipFormat", "spaced") == "spaced")
        o["countryFormat"] = val("countryFormat", "alpha2")
        o["acceptPostOfficeAsCity"] = on("post_office", True)
        if on("enrich", False):
            o["dataScope"] = "full"
    elif service == "company":
        o["correctionMode"] = val("correct", "full")
        o["cityFormat"] = val("cityFormat", "basic")
        o["zipFormat"] = (val("zipFormat", "spaced") == "spaced")
        o["countryFormat"] = val("countryFormat", "alpha2")
        o["includeTerminatedSubjects"] = on("terminated", True)
        if on("enrich", False):
            o["dataScope"] = "full"
    elif service == "email":
        o["validationType"] = "extended"
        o["correctionMode"] = val("correct", "full")
        o["acceptDisposableEmails"] = not on("reject_disposable", True)
        o["acceptPhishingDomains"] = not on("reject_phishing", True)
        o["acceptFreemails"] = not on("reject_freemail", False)
    elif service == "phone":
        o["validationType"] = val("validation", "basic")
        o["correctionMode"] = val("correct", "full")
        o["numberFormat"] = val("numberFormat", "e164")
        pref = s.get("prefixes")
        if isinstance(pref, list):
            pref = [pp for pp in pref if isinstance(pp, str) and pp.startswith("+")]
            if pref:
                o["preferredPrefixes"] = pref
    elif service == "name":
        o["correctionMode"] = val("correct", "full")
        o["acceptDegrees"] = on("degrees", False)
        o["acceptContext"] = on("context", False)
        o["dataScope"] = "full" if on("enrich", False) else "basic"
    return o

def build_tasks(
    mapping_: list[dict[str, Any]],
    settings: dict[str, dict[str, Any]] | None = None,
    default_country: str = "CZ",
    lang: str | None = None,
) -> list[Task]:
    """
    From the mapping (a list of {column, service, field, group}) build validation tasks.
    Columns with the same (service, group) are merged into ONE task = one API call.
    """
    settings = settings or {}
    lang = lang or i18n.get_lang()

    # group by (service, group)
    groups: dict[tuple[str, Any], dict[str, str]] = {}
    order: list[tuple[str, Any]] = []
    for m in mapping_:
        service = SERVICE_ALIAS.get(m.get("service"), m.get("service"))
        field = m.get("field")
        column = m.get("column")
        if not service or not field or not column:
            continue
        if service not in ENDPOINTS:
            continue
        key = (service, m.get("group", 1))
        if key not in groups:
            groups[key] = {}
            order.append(key)
        # last one wins if the same field were mapped twice
        groups[key][field] = column

    # how many groups each service has (for naming Address 1 / Address 2)
    group_count: dict[str, int] = {}
    for (service, _g) in order:
        group_count[service] = group_count.get(service, 0) + 1

    tasks: list[Task] = []
    group_index: dict[str, int] = {}
    for (service, g) in order:
        field_map = groups[(service, g)]
        if not field_map:
            continue
        ep = ENDPOINTS[service]
        group_index[service] = group_index.get(service, 0) + 1
        i = group_index[service]
        more = group_count[service] > 1
        base = KEY_TO_TYPE.get(service, service)  # EN type as the column prefix (location/company/...)
        group = f"{base}{i}" if more else base
        label = i18n.endpoint_name(service) + (f" {i}" if more else "")
        options = _options_from_settings(service, settings.get(service, {}))
        svc_settings = settings.get(service, {}) or {}
        fill = svc_settings.get("add_country") in (True, "true", "on", "1", 1)
        tasks.append(Task(endpoint=ep, field_map=field_map, options=options,
                           group=group, label=label, fill_country=fill))
    return tasks
