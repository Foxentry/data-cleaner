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

from . import countries as C
from . import i18n
from .endpoints import ENDPOINTS, KEY_TO_TYPE, SERVICE_ALIAS, SUBTYPES, TYPE_TO_KEY
from .classification import classify_columns
from .processor import Task

# Service order in the wizard (like the tabs in the app)
SERVICE_ORDER = ["location", "company", "email", "phone", "name"]


def _label(d: dict[str, str], lang: str) -> str:
    return d.get(lang) or d.get("en") or next(iter(d.values()))


def schema_for_ui(lang: str | None = None, country: str | None = None) -> list[dict[str, Any]]:
    """
    Services + field options + settings, localized and tied to a country.

    `country` is the country the data comes from (detected or picked by the user).
    It only changes the examples and defaults shown - never what the API supports.
    """
    lang = lang or i18n.get_lang()
    settings = settings_for(country)
    out = []
    for key in SERVICE_ORDER:
        typ = next(t for t, k in TYPE_TO_KEY.items() if k == key)
        fields = [{"field": api_field, "label": _label(lbl, lang),
                   "example": lbl.get("ex", ""),
                   "desc": _label(lbl["desc"], lang) if lbl.get("desc") else ""}
                  for (_st, api_field, lbl) in SUBTYPES[typ]]
        covered = C.covered_countries(key)
        out.append({
            "service": key,
            "name": i18n.endpoint_name(key),
            "countries": i18n.countries(ENDPOINTS[key].supported_countries),
            "covered": covered,                       # [] means worldwide
            "supported": C.supports(key, country),    # False -> the wizard warns
            "takes_country": ENDPOINTS[key].takes_country,   # is a country sent in the query?
            "grouped": True,
            "fields": fields,
            "settings": [_loc_setting(st, lang) for st in settings.get(key, [])],
            "warn": _coverage_warning(key, country, lang),
            "note": _label(_NOTE[key], lang) if key in _NOTE else "",
        })
    return out


# Field examples shown in the column picker. The built-in ones are Czech; when we
# know the country of the data we show an example the user will actually recognise.
def _coverage_warning(service: str, country: str | None, lang: str) -> str:
    """
    Tell the user up front when a service cannot validate their country.

    The service stays on - we only set expectations, because every row would come
    back invalid and still cost credits.
    """
    if not country or C.supports(service, country):
        return ""
    covered = ", ".join(C.covered_countries(service))
    # A register either holds the subject or it does not. A reference database still
    # recognises foreign values, only less reliably - saying "will come back invalid"
    # there would simply be untrue.
    key = "warn_not_covered" if C.is_strict(service) else "warn_low_coverage"
    return i18n.t(key,
                  service=i18n.endpoint_name(service),
                  country=C.name(country, lang),
                  covered=covered)


def suggest_mapping(header: list[str], rows: list[dict[str, str]] | None = None,
                    country: str | None = None) -> list[dict[str, Any]]:
    """
    Mapping suggestion based on column CONTENT (local classifier). When there is no data,
    it falls back to guessing from column names. Returns editable items for the wizard.

    `country` is the detected country of the file - it makes the postal-code and
    address guesses fit that country instead of assuming a Czech file.
    """
    result = classify_columns(header, rows or [], country=country)
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
# --- Option tables -----------------------------------------------------------
# Labels and examples are taken VERBATIM from the Foxentry OpenAPI specification
# (the `description` of each option). They are Czech because the documentation is:
# inventing per-country samples would mean showing behaviour we cannot vouch for
# (there is no "Praha 8 - Karlin" equivalent for London). Each option leads with
# what the format IS, and the documented example follows.
#
# The country of the data still drives what genuinely depends on it: the prefix
# order, and the country sent in the query for addresses and companies.

_CITY_OPTS = [
    ("minimal", {"cs": "Minimální — Praha", "en": "Minimal — Praha"}),
    ("basic", {"cs": "Základní — Praha 8", "en": "Basic — Praha 8"}),
    ("extended", {"cs": "Rozšířený — Praha 8 - Karlín", "en": "Extended — Praha 8 - Karlín"}),
]
_ZIP_OPTS = [
    ("spaced", {"cs": "Místní formát — 130 00", "en": "Locally formatted — 130 00"}),
    ("plain", {"cs": "Bez formátování — 13000", "en": "Plain — 13000"}),
]
_COUNTRY_OPTS = [
    ("alpha2", {"cs": "ISO kód, 2 písmena — CZ", "en": "ISO code, 2 letters — CZ"}),
    ("alpha3", {"cs": "ISO kód, 3 písmena — CZE", "en": "ISO code, 3 letters — CZE"}),
    ("local", {"cs": "Místní název — Česká republika", "en": "Local name — Česká republika"}),
    ("localShortened", {"cs": "Zkrácený místní název — Česko",
                        "en": "Local name, shortened — Česko"}),
    ("international", {"cs": "Mezinárodní název — Czech republic",
                       "en": "International name — Czech republic"}),
    ("internationalShortened", {"cs": "Zkrácený mezinárodní název — Czechia",
                                "en": "International name, shortened — Czechia"}),
]
_NUMFMT_OPTS = [
    ("e164", {"cs": "E.164 — mezinárodní, bez oddělovačů — +420607123456",
              "en": "E.164 — international, no separators — +420607123456"}),
    ("e123", {"cs": "E.123 — mezinárodní, formátovaný — +420 607 123 456",
              "en": "E.123 — international, formatted — +420 607 123 456"}),
    ("national", {"cs": "Národní — tvar obvyklý v dané zemi — 607 123 456",
                  "en": "National — as written in that country — 607 123 456"}),
    ("raw", {"cs": "Jen číslice, bez předvolby — 607123456",
             "en": "Digits only, no prefix — 607123456"}),
]
_PHONE_VALID_OPTS = [
    ("basic", {"cs": "Základní (rychlé, levnější)", "en": "Basic (fast, cheaper)"}),
    ("extended", {"cs": "Rozšířená — operátor, typ, země", "en": "Extended — carrier, type, country"}),
]


def _prefix_opts(country):
    """
    Prefixes offered for reordering: the country of the data first, then its neighbours.

    This one IS country-specific, and legitimately so - the calling codes are
    ITU-T E.164 assignments, and the order changes what the API actually does with
    numbers written without a prefix.
    """
    order = C.prefix_order(country) or C.prefix_order("CZ")
    return [(prefix, {"cs": f"{C.name(C.PREFIX_TO_COUNTRY.get(prefix, ''), 'cs')} ({prefix})",
                      "en": f"{C.name(C.PREFIX_TO_COUNTRY.get(prefix, ''), 'en')} ({prefix})"})
            for prefix in order]


def _prefix_default(country):
    return C.prefix_order(country) or C.prefix_order("CZ")


# English is the source, Czech the translation - so the English string comes first here too.
# A reader opening this file should meet the English labels, not have to scroll past Czech ones.
def _sel(sid, label_en, label_cs, desc_en, desc_cs, options, default):
    return {"id": sid, "type": "select", "label": {"en": label_en, "cs": label_cs},
            "desc": {"en": desc_en, "cs": desc_cs}, "options": options, "default": default}


def _chk(sid, label_en, label_cs, desc_en, desc_cs, default, **extra):
    d = {"id": sid, "type": "checkbox", "label": {"en": label_en, "cs": label_cs},
         "desc": {"en": desc_en, "cs": desc_cs}, "default": default}
    d.update(extra)
    return d


def _correct(what_en, what_cs):
    return _sel("correct", "Fix " + what_en, "Opravovat " + what_cs,
                "How automatic corrections behave.", "Jak se mají chovat automatické opravy.",
                _CORRECT_OPTS, "full")


def _enrich(what_en, what_cs):
    return _chk("enrich", "Enrich data (more info)", "Obohatit data (více informací)",
                "Also returns " + what_en + " Slightly higher price.",
                "Vrátí navíc " + what_cs + " Mírně zvyšuje cenu.", False)


def settings_for(country: str | None = None) -> dict[str, list[dict]]:
    """
    Per-service settings, with every example tied to the country of the data.

    Built per call (not a module constant) because the examples change with the
    country the user picked in the wizard.
    """
    return {
        "location": [
            _correct("addresses", "adresy"),
            _sel("cityFormat", "City format", "Formát města",
                 "How the city is returned.", "V jakém tvaru se vrátí město.",
                 _CITY_OPTS, "basic"),
            _sel("zipFormat", "ZIP format", "Formát PSČ",
                 "Formatted (space/dash per country) or plain.",
                 "Formátované (mezera/pomlčka dle země), nebo bez.",
                 _ZIP_OPTS, "spaced"),
            _sel("countryFormat", "Country format", "Formát země",
                 "Return a code (CZ) or a country name.", "Vrátit kód (CZ) nebo název země.",
                 _COUNTRY_OPTS, "alpha2"),
            _chk("post_office", "Accept post office as city", "Brát název pošty jako město",
                 "If a post-office name stands in for the city, accept it as valid.",
                 "Když je místo města uvedený název pošty, uznat to jako platné.", True),
            _enrich("GPS, region, district and more.", "GPS, kraj, okres a další detaily."),
        ],
        "company": [
            _correct("company data", "údaje firem"),
            _sel("cityFormat", "City format", "Formát města",
                 "How the city is returned.", "V jakém tvaru se vrátí město.",
                 _CITY_OPTS, "basic"),
            _sel("zipFormat", "ZIP format", "Formát PSČ",
                 "Formatted (space/dash per country) or plain.",
                 "Formátované (mezera/pomlčka dle země), nebo bez.",
                 _ZIP_OPTS, "spaced"),
            _sel("countryFormat", "Country format", "Formát země",
                 "Return a code (CZ) or a country name.", "Vrátit kód (CZ) nebo název země.",
                 _COUNTRY_OPTS, "alpha2"),
            _chk("terminated", "Include terminated companies", "Zahrnout i zaniklé firmy",
                 "Also search companies that no longer exist.",
                 "Hledat i ve firmách, které už zanikly.", True),
            _enrich("address, legal form and activities.", "adresu, právní formu, obory činnosti."),
        ],
        "email": [
            _correct("e‑mails", "e‑maily"),
            _chk("reject_disposable", "Reject disposable e‑mails", "Odmítat jednorázové e‑maily",
                 "Mark temporary inboxes (e.g. 10minutemail) as invalid.",
                 "Dočasné schránky (např. 10minutemail) označit jako neplatné.", True),
            _chk("reject_phishing", "Reject phishing domains", "Odmítat podvodné (phishing) domény",
                 "Mark known fraudulent domains as invalid.",
                 "Známé podvodné domény označit jako neplatné.", True),
            _chk("reject_freemail", "Reject freemails", "Odmítat freemaily",
                 "Mark Gmail, Seznam etc. as invalid (when you only want corporate addresses).",
                 "Gmail, Seznam apod. označit jako neplatné (když chcete jen firemní adresy).", False),
        ],
        "phone": [
            _sel("validation", "Validation depth", "Hloubka kontroly",
                 "Extended also detects carrier, number type and region (higher price).",
                 "Rozšířená navíc zjistí operátora, typ čísla a region (vyšší cena).",
                 _PHONE_VALID_OPTS, "basic"),
            _correct("numbers", "čísla"),
            _sel("numberFormat", "Number format", "Formát čísla",
                 "How the phone number is returned.", "V jakém tvaru se vrátí telefonní číslo.",
                 _NUMFMT_OPTS, "e164"),
            {"id": "prefixes", "type": "order",
             "label": {"cs": "Předvolby zemí (pořadí)", "en": "Country prefixes (order)"},
             "desc": {"cs": "Uplatní se jen u čísel bez předvolby — zkusí se v tomto pořadí. "
                            "Pořadí změníte šipkami.",
                      "en": "Only applies to numbers written without a prefix — they are tried "
                            "in this order. Reorder with the arrows."},
             "options": _prefix_opts(country), "default": _prefix_default(country)},
        ],
        "name": [
            _correct("names", "jména"),
            _chk("degrees", "Accept academic titles", "Akceptovat tituly",
                 "Treats Ing. titles as a valid name.", "Uzná „Ing. Jan Novák“ jako platné jméno.", False),
            _chk("context", "Accept context (jr., sr.)", "Akceptovat dovětky (ml., st.)",
                 "Treats Jr./Sr. suffixes as valid.", "Uzná „Jan Novák ml.“ nebo „st.“ jako platné.", False),
            _enrich("gender, vocative form and name day.", "rod, oslovení (5. pád) a jmeniny."),
        ],
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


def _guess_zip(values):
    """
    Formatted or plain postal codes?

    Any separator counts - a space (CZ "130 00", GB "NW1 6XE"), a dash
    (PL "00-001") or a letter block (NL "1012 AB"). Looking only for the Czech
    "NNN NN" shape made every foreign file look unformatted.
    """
    if not values:
        return None
    formatted = sum(1 for v in values if re.search(r"[\s-]", v.strip()))
    return "spaced" if formatted >= len(values) / 2 else "plain"


def _guess_city(values):
    if not values:
        return None
    if any(" - " in v or " – " in v for v in values):
        return "extended"
    if any(re.search(r"\s\d+$", v) for v in values):
        return "basic"
    return "minimal"


def _guess_country(values):
    """Which shape does the country column use - a code, or a name?"""
    if not values:
        return None
    value = values[0].strip()
    if len(value) == 2 and value.isalpha():
        return "alpha2"
    if len(value) == 3 and value.isalpha():
        return "alpha3"
    # A name: is it the English one, or a local/translated one?
    folded = value.casefold()
    for code, english in C.NAMES_EN.items():
        if folded == english.casefold():
            return "international"
    return "local"


def _guess_numformat(vz):
    if not vz:
        return None
    plus = sum(1 for v in vz if v.strip().startswith("+"))
    spaces = sum(1 for v in vz if " " in v.strip())
    if plus >= len(vz) / 2:
        return "e123" if spaces >= len(vz) / 2 else "e164"
    return "national" if spaces >= len(vz) / 2 else "e164"


def _guess_prefix(values, country):
    """
    Prefix order for the API: whatever the data actually uses, most common first.

    Falls back to the country of the data when no number carries a prefix.
    """
    counts: dict[str, int] = {}
    for value in values:
        code = C.country_of_prefix(value)
        if code:
            prefix = C.prefix_of(code)
            if prefix:
                counts[prefix] = counts.get(prefix, 0) + 1

    if counts:
        dominant = max(counts, key=lambda k: counts[k])
        order = [dominant]
        for prefix in C.prefix_order(C.PREFIX_TO_COUNTRY.get(dominant)):
            if prefix not in order:
                order.append(prefix)
        # keep any other prefix that really occurs in the file
        for prefix in sorted(counts, key=lambda k: -counts[k]):
            if prefix not in order:
                order.append(prefix)
        return order

    return C.prefix_order(country) or C.prefix_order("CZ")


def suggest_settings(mapping_, rows, country=None):
    """
    Pre-select formats and prefix order from what is actually in the file.

    `mapping_` is the wizard's column list. Columns the user has already mapped
    win; for the rest we fall back to the classifier's best candidate, so the
    settings are useful on the very first render - before anything is mapped.
    (Reading only confirmed mappings meant this returned nothing at all and every
    preset silently fell back to its hard-coded default.)
    """
    def column(service, field):
        # 1) a column the user mapped explicitly
        for item in mapping_ or ():
            if (item.get("service") == service and item.get("field") == field
                    and item.get("column")):
                return item["column"]
        # 2) otherwise the classifier's best guess - the strongest one, not merely
        #    the first in file order. An id column can score a weak 4 as a phone
        #    number, and picking that over the real phone column (150) would read
        #    the formats off the wrong data.
        best_column, best_score = None, 0.0
        for item in mapping_ or ():
            if item.get("service"):
                continue  # mapped to something else - do not second-guess the user
            top = (item.get("candidates") or [None])[0]
            if not top or top.get("service") != service or top.get("field") != field:
                continue
            if top.get("score", 0) > best_score:
                best_column, best_score = item.get("column"), top.get("score", 0)
        return best_column

    out: dict[str, dict] = {}

    for service in ("location", "company"):
        settings: dict[str, object] = {}
        col = column(service, "zip")
        if col:
            guess = _guess_zip(_sample(col, rows))
            if guess:
                settings["zipFormat"] = guess
        col = column(service, "city")
        if col:
            guess = _guess_city(_sample(col, rows))
            if guess:
                settings["cityFormat"] = guess
        col = column(service, "country")
        if col:
            guess = _guess_country(_sample(col, rows))
            if guess:
                settings["countryFormat"] = guess
        if settings:
            out[service] = settings

    col = column("phone", "number")
    if col:
        values = _sample(col, rows)
        phone: dict[str, object] = {}
        guess = _guess_numformat(values)
        if guess:
            phone["numberFormat"] = guess
        phone["prefixes"] = _guess_prefix(values, country)
        out["phone"] = phone

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
    country: str | None = None,
    lang: str | None = None,
) -> list[Task]:
    """
    From the mapping (a list of {column, service, field, group}) build validation tasks.
    Columns with the same (service, group) are merged into ONE task = one API call.

    `country` is where the data comes from. It is sent as part of the query for the
    services that accept one (addresses, companies), so the API can verify it and
    correct it; None means "mixed data - send no country".
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
        # A group that maps its own country column already has one for every row -
        # that value wins, so we do not add a global one on top of it.
        task_country = None if "country" in field_map else country
        tasks.append(Task(endpoint=ep, field_map=field_map, options=options,
                          group=group, label=label, country=task_country))
    return tasks
