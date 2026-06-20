# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AVANTRO s.r.o.
"""
Local column classification by CONTENT (no connection whatsoever).

Scans a sample of values in each column and heuristically decides which type/subtype
of data it most likely is - in the style of the prompt Foxentry uses in the app, but
fully offline (regular expressions + small dictionaries). Data takes precedence over the header.

Returns a structure similar to the app:
{
  "hasHeaderRow": bool,
  "columns": [{columnIndex, columnName, reasoning, type, subtype, group}]
}
where type/subtype are from the allowed combinations (see endpoints.SUBTYPES) or None.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from . import i18n
from .endpoints import ENDPOINTS, SUBTYPES, TYPE_TO_KEY, _norm


def _describe(typ, subtyp):
    lang = i18n.get_lang()
    for st, _api, lbl in SUBTYPES.get(typ, []):
        if st == subtyp:
            return f"{i18n.endpoint_name(TYPE_TO_KEY[typ])} · {lbl.get(lang) or lbl.get('en')}"
    return f"{typ}/{subtyp}"

# --- vzory -----------------------------------------------------------------
_RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_RE_DOMAIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}$")
_RE_ZIP_CZSK = re.compile(r"^\d{3}\s?\d{2}$")
_RE_ZIP_PL = re.compile(r"^\d{2}-\d{3}$")
_RE_ICO = re.compile(r"^\d{8}$")
_RE_DIC = re.compile(r"^[A-Za-z]{2}\d{8,12}$")
_RE_PREFIX = re.compile(r"^(\+|00)\d{1,4}$")
_RE_HOUSENUM = re.compile(r"^\d{1,4}\s*[/\\-]?\s*\d{0,4}\s*[a-zA-Z]?$")
# street with number: starts with a letter (street name), ends with a house number after a space
# (e.g. "Kaštanová 435/127", "Na Slanici 378"). Must NOT match company names with a stray digit.
_RE_STREET_NUM = re.compile(r"^[A-Za-zÀ-ž].*\s\d{1,4}\s*[/\\-]?\s*\d{0,4}\s*[a-zA-Z]?$")
_RE_LETTERS = re.compile(r"^[A-Za-zÀ-ž'’.\- ]+$")
_RE_IPV4 = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")           # 119.144.153.66 - not a contact field
_RE_DECIMAL = re.compile(r"^[+-]?\d{1,3}\.\d+$")            # -162.266418 / 49.376 - coordinate/amount

_COUNTRIES = {
    "cz", "sk", "pl", "cze", "svk", "pol", "de", "deu", "at", "aut",
    "cesko", "ceska republika", "ceskarepublika", "czech republic", "czechia",
    "slovensko", "slovak republic", "polsko", "polska", "poland",
    "rakousko", "nemecko", "deutschland", "germany", "austria",
}
_COMPANY_SUFFIX = ("s.r.o", "sro", "a.s", "as.", " as", "spol.", "spol ", "k.s", "v.o.s",
                 "z.s", "o.p.s", "ltd", "gmbh", " se", "plc", "inc", "kft", "sp. z o.o",
                 "družstvo", "druzstvo")
# Strong, unambiguous company markers - enough on a single value, even with digits/brackets
# in it (e.g. "DESTILA, s.r.o.(0)"). Deliberately excludes short/ambiguous ones (" as", " se").
_COMPANY_STRONG = ("s.r.o", "spol.", "v.o.s", "o.p.s", "z.s.", "gmbh", " ltd", "kft",
                   "plc", " inc", "sp. z o.o", "družstvo", "druzstvo", "a.s.", " a. s.")
# small dictionary to tell a name from a city (incomplete, just a helper booster)
_CITIES = {"praha", "brno", "ostrava", "plzen", "liberec", "olomouc", "zlin", "kladno",
          "hranice", "bratislava", "kosice", "warszawa", "krakow", "wien", "berlin"}

# Unambiguous formats - a single sample is enough to match (cannot be confused with anything else).
# Weaker signals (address etc.) need more matching samples (see classify_columns).
_STRONG = {
    "email/email", "email/domain", "location/zip",
    "company/registrationNumber", "company/vatNumber",
    "phone/prefix", "phone/number",
}
_MIN_SAMPLES_WEAK = 2   # weak signals need at least this many matching samples

# Header names that denote an internal identifier (row id, record id, ...). Numeric IDs can
# accidentally pass IČO/ZIP shape checks, so such columns are never auto-validated.
_ID_HEADERS = {"id", "rid", "uid", "guid", "rowid", "recordid", "objectid",
               "kod", "key", "poradi", "index", "rowindex", "seq", "sequence"}


def _is_id_header(name: str) -> bool:
    n = _norm(name)
    if not n:
        return False
    return n in _ID_HEADERS or (len(n) >= 3 and n.endswith("id"))


def _looks_identifier(vals: list[str], header: str) -> bool:
    """Decide from CONTENT (not from a fixed header list) whether a numeric column is an
    internal identifier rather than a real-world value. Signals, in order of strength:
      - the numeric series is monotonic in row order (auto-increment / sorted key) — a real
        attribute (IČO, ZIP, phone) is not sorted across a customer list;
      - the header reads like an identifier (id / ...id / code / ...) and the content is numeric.
    A numeric column with neither signal is left to the format scoring (could be a real ZIP/IČO).
    """
    nonempty = [v.strip() for v in vals if v and v.strip()]
    if len(nonempty) < 4:
        return False
    pure = [v for v in nonempty if v.isdigit()]
    if len(pure) < 0.7 * len(nonempty):   # not really a numeric column
        return False
    ints = [int(v) for v in pure]
    distinct = len(set(pure))
    inc = all(ints[i] <= ints[i + 1] for i in range(len(ints) - 1))
    dec = all(ints[i] >= ints[i + 1] for i in range(len(ints) - 1))
    monotonic = (inc or dec) and distinct >= 4
    return monotonic or _is_id_header(header)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _is_zip(s: str) -> bool:
    return bool(_RE_ZIP_CZSK.match(s) or _RE_ZIP_PL.match(s))


def _ico_valid(s: str) -> bool:
    """Czech/Slovak company ID (IČO) - checksum verification (mod 11). Eliminates
    random 8-digit numbers (invoices, IDs) so they are not flagged as IČO."""
    if not re.fullmatch(r"\d{8}", s):
        return False
    d = [int(c) for c in s]
    suma = sum((8 - i) * d[i] for i in range(7))
    m = suma % 11
    check = 1 if m == 0 else (0 if m == 1 else 11 - m)
    return check == d[7]


def _classify_value(s: str) -> str | None:
    """One value -> best 'type/subtype' or '_letters_'/None."""
    s = s.strip()
    if not s:
        return None
    low = s.lower()
    dig = _digits(s)

    # not contact fields: IP addresses and decimal numbers / GPS coordinates
    if _RE_IPV4.match(s) or _RE_DECIMAL.match(s):
        return None

    if _RE_EMAIL.match(s):
        return "email/email"
    if _RE_DIC.match(s):
        return "company/vatNumber"
    if _is_zip(s):
        return "location/zip"
    if _ico_valid(s):
        return "company/registrationNumber"
    if _RE_PREFIX.match(s) and len(dig) <= 4:
        return "phone/prefix"
    if s.startswith(("+", "00")) and 8 <= len(dig) <= 15 and not re.search(r"[A-Za-zÀ-ž]", s):
        return "phone/number"
    # national phone: digits and spaces only (optionally ()/-), 9-12 digits, and explicitly NOT a
    # decimal/IP (no '.'/','), not negative. This stops coordinates and IPs from looking like phones.
    if ("." not in s and "," not in s and not s.startswith("-")
            and re.fullmatch(r"[\d\s()/+\-]+", s)
            and 9 <= len(re.sub(r"[\s()/+\-]", "", s)) <= 12
            and re.sub(r"[\s()/+\-]", "", s).isdigit()):
        return "phone/number"
    # strong company marker anywhere (even with digits/brackets) -> company name, never a street
    if any(suf in low for suf in _COMPANY_STRONG):
        return "company/name"
    if "," in s and re.search(r"\d{3}\s?\d{2}", s) and re.search(r"[A-Za-zÀ-ž]", s) and len(s) >= 12:
        return "location/full"
    if _RE_HOUSENUM.match(s) and not _is_zip(s) and ("/" in s or "-" in s or re.search(r"\d\s*[a-zA-Z]$", s)):
        return "location/number.full"
    if _RE_STREET_NUM.match(s) and re.search(r"[A-Za-zÀ-ž]", s) and re.search(r"\d", s):
        return "location/streetWithNumber"
    if "@" not in s and _RE_DOMAIN.match(s) and not dig.isdigit() or ("@" not in s and _RE_DOMAIN.match(s) and "." in s and not s.replace(".", "").isdigit()):
        return "email/domain"
    if _RE_LETTERS.match(s):
        # We do NOT guess a name from content ("two capitalized words" yields many false positives
        # like "Start Date", "Ad Schedule"). First/last name is matched only by
        # the header (see _header_hint / _resolve_letters). Here just text = "_letters_".
        if low in _COUNTRIES:
            return "location/country"
        if any(suf in low for suf in _COMPANY_SUFFIX):
            return "company/name"
        return "_letters_"
    return None


def _header_hint(header_name: str) -> tuple[str, str] | None:
    """Guess (type, subtype) from the column name via field aliases."""
    n = _norm(header_name)
    if not n:
        return None
    for typ, subs in SUBTYPES.items():
        key = TYPE_TO_KEY[typ]
        ep = ENDPOINTS[key]
        for (subtyp, api_field, _lbl) in subs:
            fields = next((p for p in ep.fields if p.api_field == api_field), None)
            if fields and n in fields.normalized_aliases():
                return (typ, subtyp)
    return None


def _resolve_letters(header_hint, samples) -> tuple[str | None, str | None, str]:
    """The column is textual (city/street/name/surname/company/country) - the header decides."""
    if header_hint and header_hint[0] in ("location", "name", "company"):
        return header_hint[0], header_hint[1], i18n.t("cls_header_resolved")
    low = [s.strip().lower() for s in samples if s.strip()]
    if low and sum(1 for s in low if s in _COUNTRIES) >= len(low) / 2:
        return "location", "country", i18n.t("cls_country")
    if low and sum(1 for s in low if any(x in s for x in _COMPANY_SUFFIX)) >= max(2, (len(low) + 1) // 2):
        return "company", "name", i18n.t("cls_company")
    if low and sum(1 for s in low if s in _CITIES) >= len(low) / 2:
        return "location", "city", i18n.t("cls_city")
    # without a header we cannot safely tell name/surname/street/city apart -> leave it to the user
    return None, None, i18n.t("cls_ambiguous")


def suggest_candidates(samples, hint, max_n: int = 4):
    """Liberal suggestion of the most likely (service, field) candidates for the picker.
    Looser than auto-mapping - it also offers less certain options, sorted by score.
    Returns [{service, field, label, score}] (service=endpoint key, field=api_field)."""
    score: dict[tuple[str, str], float] = {}

    def add_(typ, subtyp, w):
        if not typ or not subtyp:
            return
        if not any(st == subtyp for st, _, _ in SUBTYPES.get(typ, [])):
            return
        score[(typ, subtyp)] = score.get((typ, subtyp), 0.0) + w

    n = len(samples) or 1

    # 1) header - a strong signal. "ulice"/"street" is ambiguous between street-only and
    # street-with-number, so it boosts BOTH siblings equally and the content decides which wins.
    if hint:
        if hint[0] == "location" and hint[1] in ("street", "streetWithNumber"):
            add_("location", "street", 100)
            add_("location", "streetWithNumber", 100)
        else:
            add_(hint[0], hint[1], 100)

    # 2) content - recognized formats (email, ZIP, IČO/DIČ, phone, address...)
    labels = [l for l in (_classify_value(s) for s in samples) if l and l != "_letters_"]
    cnt = Counter(labels)
    for lab, c in cnt.items():
        if "/" in lab:
            t, st = lab.split("/", 1)
            add_(t, st, 40 * (c / n))

    # 3) company suffix (even a minority) -> company/name
    low = [s.strip().lower() for s in samples if s.strip()]
    suff = sum(1 for s in low if any(x in s for x in _COMPANY_SUFFIX))
    if suff:
        add_("company", "name", 30 * (suff / n) + 10)

    # 4) countries / cities (textual content)
    if low:
        if sum(1 for s in low if s in _COUNTRIES) >= 1:
            add_("location", "country", 25 * (sum(1 for s in low if s in _COUNTRIES) / n))
        if sum(1 for s in low if s in _CITIES) >= 1:
            add_("location", "city", 25 * (sum(1 for s in low if s in _CITIES) / n))

    # 5) textual column with no other signal -> offer common textual targets
    letters = sum(1 for s in samples if _RE_LETTERS.match(s or ""))
    if letters >= max(1, 0.6 * n) and not labels and not suff:
        if hint and hint[0] in ("location", "name", "company"):
            add_(hint[0], hint[1], 50)
        else:
            add_("company", "name", 8)
            add_("name", "name", 6)
            add_("name", "surname", 5)
            add_("location", "city", 5)
            add_("location", "street", 4)

    out = []
    for (typ, subtyp), w in sorted(score.items(), key=lambda x: -x[1])[:max_n]:
        key = TYPE_TO_KEY.get(typ)
        api_field = next((a for st, a, _ in SUBTYPES.get(typ, []) if st == subtyp), None)
        if not key or not api_field:
            continue
        out.append({"service": key, "field": api_field,
                    "label": _describe(typ, subtyp), "score": round(w, 1)})
    return out


def classify_columns(header: list[str], rows: list[dict[str, str]],
                       sample: int = 10) -> dict[str, Any]:
    """Main entry point - classifies all columns by content."""
    columns = []
    # detect whether the header is actually data
    header_as_data = sum(1 for h in header if _classify_value(h) not in (None, "_letters_"))
    has_header = header_as_data < max(1, len(header) // 2)

    for idx, col in enumerate(header):
        samples = [(r.get(col) or "").strip() for r in rows[:sample]]
        samples = [s for s in samples if s]
        hint = _header_hint(col)

        if not samples:
            # RULE 1: empty column -> map nothing (nothing to validate or compare).
            columns.append({"columnIndex": idx, "columnName": col,
                            "reasoning": i18n.t("cls_empty"), "type": None, "subtype": None, "group": 1,
                            "candidates": suggest_candidates(samples, hint)})
            continue

        # RULE 2: data present -> decide by CONTENT (and enough matching samples).
        labels = [l for l in (_classify_value(s) for s in samples) if l]
        cnt = Counter(labels)
        typ = subtyp = None
        reasoning = ""
        ctx = {}  # flags for the 2nd context pass

        if cnt:
            top, n = cnt.most_common(1)[0]
            frac = n / len(samples)
            if top == "_letters_":
                # textual column (name/surname/city/street/company/country) - header decides, otherwise content
                typ, subtyp, reasoning = _resolve_letters(hint, samples)
                # text with no clear determination, but header/content hints at an address ->
                # leave to the 2nd pass (may be a city if a street already exists).
                if typ is None:
                    if hint and hint[0] == "location" and hint[1] in ("street", "city"):
                        ctx["letters_addr"] = hint[1]
                    elif not (hint and hint[0] == "name"):
                        # unresolved text without a name-header -> possibly a city (decided by context)
                        ctx["unresolved_letters"] = True
            else:
                strong = top in _STRONG
                # unambiguous format (email, ZIP, IČO/DIČ, phone) -> 1 sample is enough;
                # weaker signal (address etc.) -> at least _MIN_SAMPLES_WEAK matches and higher agreement
                enough = strong or (n >= _MIN_SAMPLES_WEAK and frac >= 0.6)
                if frac >= 0.5 and enough:
                    typ, subtyp = top.split("/", 1)
                    if typ == "location":
                        # for addresses, content is more reliable than the column name
                        reasoning = i18n.t("cls_data_match", pct=int(frac*100), label=_describe(typ, subtyp))
                    elif hint and hint[0] == typ and hint[1] != subtyp:
                        reasoning = i18n.t("cls_header_refined")
                        subtyp = hint[1]
                    elif hint and hint[0] != typ:
                        reasoning = i18n.t("cls_data_wins", label=_describe(typ, subtyp))
                    else:
                        reasoning = i18n.t("cls_data_match", pct=int(frac*100), label=_describe(typ, subtyp))
                else:
                    # too little data / ambiguous -> better map nothing
                    typ = subtyp = None
                    reasoning = i18n.t("cls_none")
        # if data does not look like anything recognizable -> map nothing (no fallback to the header)

        # House number is a weak/ambiguous signal: nobody validates bare house numbers.
        # The column is a candidate only if it has at least one value with a slash/letter (typical
        # house-number shape) and mostly small numbers -> this distinguishes it from amounts (which have no slash).
        # Confirmed only in the 2nd pass, and only if a street/address is in the table.
        if typ in (None, "location"):
            shaped = sum(1 for s in samples if _classify_value(s) == "location/number.full")
            bareint = sum(1 for s in samples if re.fullmatch(r"\d{1,4}", s))
            if shaped >= 1 and (shaped + bareint) >= max(2, 0.6 * len(samples)):
                ctx["maybe_housenum"] = True
                if subtyp == "number.full":
                    typ = subtyp = None
                    reasoning = i18n.t("cls_none")

        # verify the combination is allowed
        if typ and subtyp and not any(st == subtyp for st, _, _ in SUBTYPES.get(typ, [])):
            typ = subtyp = None
            reasoning = i18n.t("cls_none")

        # header fallback: content matches no known format, but the column name clearly names a
        # field whose format is locale-specific (e.g. a foreign ZIP like "SW1A 1AA", "1234 AB").
        if typ is None and hint == ("location", "zip") and samples:
            codeish = sum(1 for s in samples
                          if re.search(r"\d", s) and len(s) <= 10
                          and re.fullmatch(r"[A-Za-z0-9 \-]+", s or ""))
            if codeish >= max(2, 0.6 * len(samples)) and not _looks_identifier(samples, col):
                typ, subtyp = "location", "zip"
                reasoning = i18n.t("cls_header_fallback")

        # numeric validatable fields can be impersonated by internal IDs. Suppress them when the
        # column looks like an identifier by CONTENT (monotonic series) or an id-like header -
        # unless the header explicitly names THIS field (then the header wins).
        if ((typ == "company" and subtyp in ("registrationNumber", "vatNumber"))
                or (typ == "location" and subtyp == "zip")
                or typ == "phone"):
            if _looks_identifier(samples, col) and _header_hint(col) != (typ, subtyp):
                typ = subtyp = None
                reasoning = i18n.t("cls_id_col")

        columns.append({"columnIndex": idx, "columnName": col,
                        "reasoning": reasoning or i18n.t("cls_none"),
                        "type": typ, "subtype": subtyp, "group": 1, "_ctx": ctx,
                        "candidates": suggest_candidates(samples, hint)})

    _context_pass(columns)
    for c in columns:
        c.pop("_ctx", None)
    _assign_groups(columns)
    return {"hasHeaderRow": has_header, "columns": columns}


def _demote_by_owner(columns: list[dict], typ: str, subtyp: str, reason_key: str) -> None:
    """If some column is *named* as this field (header alias matches, e.g. "IČO" -> registrationNumber,
    "PSČ" -> zip), then any OTHER column classified as the same field only by content shape
    (numeric IDs etc.) is not the real one -> unmap it. Works even if the named column is empty."""
    owners = [c for c in columns if _header_hint(c["columnName"]) == (typ, subtyp)]
    if not owners:
        return
    for c in columns:
        if c["type"] == typ and c["subtype"] == subtyp and c not in owners:
            c["type"] = c["subtype"] = None
            c["reasoning"] = i18n.t(reason_key)


def _context_pass(columns: list[dict]) -> None:
    """2nd pass - decides with regard to the other columns in the table.

    - Confirm a house number only when a street / street-with-number
      / full address is already mapped (nobody validates a bare house number).
    - De-duplicate confusable strong fields by header ownership (ZIP/IČO/DIČ): a numeric ID
      column can look like a ZIP or an IČO; if a column literally named so exists, it wins.
    - A textual column that could be street OR city: if a street already exists,
      it is more likely a city.
    """
    _demote_by_owner(columns, "location", "zip", "cls_dup_zip")
    _demote_by_owner(columns, "company", "registrationNumber", "cls_dup_company")
    _demote_by_owner(columns, "company", "vatNumber", "cls_dup_company")

    has_street = any(c["type"] == "location" and c["subtype"] in ("street", "streetWithNumber", "full")
                   for c in columns)
    has_city = any(c["type"] == "location" and c["subtype"] == "city" for c in columns)
    has_zip = any(c["type"] == "location" and c["subtype"] == "zip" for c in columns)

    for c in columns:
        ctx = c.get("_ctx") or {}
        if ctx.get("maybe_housenum"):
            if has_street:
                c["type"], c["subtype"] = "location", "number.full"
                c["reasoning"] = i18n.t("cls_housenum_ctx")
            # otherwise stays unmapped (no standalone house numbers)
        elif ctx.get("letters_addr"):
            # street/city unclear from content: if a street already exists, treat it as a city
            if has_street and not has_city:
                c["type"], c["subtype"] = "location", "city"
                c["reasoning"] = i18n.t("cls_city_ctx")
                has_city = True
        elif ctx.get("unresolved_letters"):
            # leftover textual column in a clear address table (street + ZIP present) -> city
            if has_street and has_zip and not has_city:
                c["type"], c["subtype"] = "location", "city"
                c["reasoning"] = i18n.t("cls_city_ctx")
                has_city = True


def _assign_groups(columns: list[dict]) -> None:
    """
    Skupiny podle typu. Pravidla:
      - a subtype does not repeat within one group,
      - a second "anchor" (street / street-with-number / full address, or company name)
        starts a new group => two addresses in a row = Address 1 and Address 2.
    """
    KOTVY = {"location": {"street", "streetWithNumber", "full"}, "company": {"name"}}
    content: dict[str, list[dict]] = {}  # type -> [{"subs": set, "kotva": bool}]
    for c in columns:
        if not c["type"]:
            continue
        typ = c["type"]
        st = c["subtype"]
        is_anchor = st in KOTVY.get(typ, set())
        groups = content.setdefault(typ, [])
        placed = False
        for gi, g in enumerate(groups, start=1):
            if st in g["subs"]:
                continue
            if is_anchor and g["kotva"]:
                continue
            g["subs"].add(st)
            g["kotva"] = g["kotva"] or is_anchor
            c["group"] = gi
            placed = True
            break
        if not placed:
            groups.append({"subs": {st}, "kotva": is_anchor})
            c["group"] = len(groups)
