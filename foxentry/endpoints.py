# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AVANTRO s.r.o.
"""
Definitions of validation types (endpoints) and column mapping.

This is where the app's "smarts" live:
  - Each validation type knows which columns in the file belong to it
    (recognizes Czech and English names; case-insensitive).
  - From each row, ONLY the filled fields are sent to the API.
    If the client only has an `address` column (full), full is sent.
    If they have split `street / city / zip`, the split form is sent.
  - From the response, the result is mapped back to `_updated` columns.

No magic behavior - everything is readably described in `ENDPOINTS`.
"""

from __future__ import annotations

from . import countries as C
from dataclasses import dataclass, field
from typing import Callable


def _norm(name: str) -> str:
    """Normalize a column name for comparison (no diacritics, lowercase)."""
    table = str.maketrans("áčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ", "acdeeinorstuuyzacdeeinorstuuyz")
    return name.strip().lower().translate(table).replace(" ", "").replace("-", "").replace("_", "")


@dataclass
class FieldMapping:
    """One API query field and the column names that match it."""
    api_field: str          # field name in the Foxentry API query (e.g. "email", "number.full")
    aliases: list[str]       # accepted column names in the file
    # function that extracts the corrected value for this field from `data` in the response
    extraction: Callable[[dict], object] | None = None

    def normalized_aliases(self) -> set[str]:
        return {_norm(a) for a in self.aliases}


def _any_filled(query: dict, keys) -> bool:
    """Does the row carry a real value for any of these fields? (nested ones included)"""
    for key in keys:
        value = query.get(key)
        if isinstance(value, dict):
            if any(str(v or "").strip() for v in value.values()):
                return True
        elif str(value or "").strip():
            return True
    return False


@dataclass
class Endpoint:
    """Definition of a single validation type."""
    key: str               # internal key (email, location, phone, name, company)
    name: str              # human-readable name
    path: str              # API path, e.g. "/email/validate"
    fields: list[FieldMapping]
    options: dict = field(default_factory=dict)
    # the query is built like this: for each `field`, take the value from the matching
    # column; empty ones are skipped. At least one non-empty must remain.
    supported_countries: str = "Worldwide"

    @property
    def takes_country(self) -> bool:
        """Does this endpoint accept a country in the query? (addresses and companies do)"""
        return any(f.api_field == "country" for f in self.fields)

    def query_from_row(self, row: dict[str, str], field_map: dict[str, str]) -> dict:
        """
        Build the query from the mapped columns.

        A column the user mapped is sent even when it is empty on this row - as "". An absent
        field and an empty one do not mean the same thing to the API: absent says "we never
        asked about this", empty says "this value is missing", which is a defect the API
        reports and can fix (invalidWithCorrection). Leaving an empty ZIP or country out of
        the query meant the correction never happened.

        This only applies WITHIN a record that has something to validate. The caller builds a
        query only for a group that carries at least one value (`Task.has_data`), so a record
        whose mapped columns are all empty is never sent and never charged.

        `field_map` = {api_field: actual_column_name} (derived from the file header).
        """
        q: dict[str, object] = {}
        for p in self.fields:
            column = field_map.get(p.api_field)
            if not column:
                continue
            # `number.full` is the name of the field, dot and all - the query is flat. It is
            # NOT `{"number": {"full": ...}}`: the API ignores that as an unknown key, and
            # then reports the house number it never received as valid. See the OAS
            # (LocationValidationBody: `number.full`, `number.part1`, ...). The *response*
            # nests them under `data.number`; the query does not.
            q[p.api_field] = (row.get(column) or "").strip()

        # email: the query accepts only the `email` field (OAS 2.1)
        if self.key == "email":
            q = {"email": q["email"]} if "email" in q else {}
        # phone: the query is oneOf {prefix, number} OR {numberFull}, and the first
        # variant REQUIRES both keys - so when both columns are mapped, both are sent
        # (an empty prefix as "", which the API then fills from the preferred prefixes).
        if self.key == "phone":
            if "prefix" in field_map and "number" in field_map:
                q = {"prefix": q.get("prefix", ""), "number": q.get("number", "")}
            elif "number" in field_map:
                q = {"numberFull": q.get("number", "")}
            else:
                q = {}   # a prefix on its own is not enough to validate
        # name: the query is oneOf {name,surname} OR {nameSurname} (additionalProperties:
        # false), so the two variants must never be mixed. Which one to use is decided by
        # what this ROW actually holds - sending an empty "surname" alongside a filled
        # "nameSurname" would claim a surname is missing when it is right there.
        if self.key == "name" and "nameSurname" in q and ("name" in q or "surname" in q):
            if _any_filled(q, ("name", "surname")):
                q.pop("nameSurname", None)
            else:
                q.pop("name", None)
                q.pop("surname", None)
        # address: same principle. `full` and the structured fields describe the same
        # thing, so send whichever this row has - structured wins when it carries data,
        # because it is more precise. The house number is spelled `number.full`,
        # `number.part1`, ... so it is matched by prefix, not by name. `country` belongs to
        # neither variant: it is sent with both.
        if self.key == "location" and "full" in q:
            named = ("streetWithNumber", "street", "city", "zip")
            struct = tuple(k for k in q if k in named or k.startswith("number."))
            if _any_filled(q, struct):
                q.pop("full", None)
            else:
                for key in struct:
                    q.pop(key, None)
        return q

    def detect_map(self, header: list[str]) -> dict[str, str]:
        """Find which file columns belong to which API field."""
        norm_header = {_norm(h): h for h in header}
        field_map: dict[str, str] = {}
        for p in self.fields:
            for alias in p.normalized_aliases():
                if alias in norm_header:
                    field_map[p.api_field] = norm_header[alias]
                    break
        return field_map


# --- extraction helpers for a value from the response ---------------------------------

def _get(data: dict, *path: str):
    cur = data
    for k in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _phone_number(data: dict):
    if not isinstance(data, dict):
        return None
    return (
        data.get("numberFull")
        or (f"{data.get('prefix', '')}{data.get('number', '')}".strip() or None)
    )


# --- DEFINITIONS OF ALL ENDPOINTS ---------------------------------------------------

ENDPOINTS: dict[str, Endpoint] = {
    "email": Endpoint(
        key="email",
        name="Email addresses",
        path="/email/validate",
        supported_countries="worldwide",
        options={"validationType": "extended", "correctionMode": "full"},
        fields=[
            FieldMapping(
                "email",
                ["email", "e-mail", "mail", "emailova_adresa", "email_address", "e_mail"],
                extraction=lambda d: _get(d, "email"),
            ),
        ],
    ),

    "phone": Endpoint(
        key="phone",
        name="Phone numbers",
        path="/phone/validate",
        supported_countries="worldwide",
        options={"validationType": "extended", "correctionMode": "full"},
        fields=[
            FieldMapping(
                "number",
                ["telefon", "phone", "telefonni_cislo", "phone_number", "cislo",
                 "mobil", "tel", "number_with_prefix", "numberwithprefix",
                 "number_full", "numberfull", "number", "phone_local", "cislo_bez_predvolby"],
                extraction=_phone_number,
            ),
            FieldMapping(
                "prefix",
                ["predvolba", "prefix", "country_code"],
                extraction=lambda d: _get(d, "prefix"),
            ),
        ],
    ),

    "name": Endpoint(
        key="name",
        name="Names and surnames",
        path="/name/validate",
        supported_countries=", ".join(C.COVERAGE["name"]),
        options={"correctionMode": "full", "acceptDegrees": True,
                 "acceptContext": True, "dataScope": "full"},
        fields=[
            FieldMapping(
                "name",
                ["jmeno", "name", "first_name", "krestni_jmeno", "firstname"],
                extraction=lambda d: _get(d, "name"),
            ),
            FieldMapping(
                "surname",
                ["prijmeni", "surname", "last_name", "lastname", "family_name"],
                extraction=lambda d: _get(d, "surname"),
            ),
            FieldMapping(
                "nameSurname",
                ["cele_jmeno", "jmeno_prijmeni", "full_name", "name_surname", "namesurname"],
                extraction=lambda d: _get(d, "nameSurname"),
            ),
        ],
    ),

    "location": Endpoint(
        key="location",
        name="Addresses",
        path="/location/validate",
        supported_countries="europe",
        options={"correctionMode": "full", "acceptPostOfficeAsCity": True},
        fields=[
            FieldMapping(
                "full",
                ["adresa", "full_address", "cela_adresa", "full", "address"],
                extraction=lambda d: _get(d, "full"),
            ),
            FieldMapping(
                "streetWithNumber",
                ["ulice_cislo", "street_number", "streetwithnumber", "ulice_s_cislem"],
                extraction=lambda d: _get(d, "streetWithNumber"),
            ),
            FieldMapping(
                "street",
                ["ulice", "street"],
                extraction=lambda d: _get(d, "street"),
            ),
            FieldMapping(
                "number.full",
                ["cislo_popisne", "house_number", "cislo_domu", "number", "housenumber",
                 "cp", "cislo"],
                extraction=lambda d: _get(d, "number", "full"),
            ),
            FieldMapping("number.part1", ["cislo_popisne_cast1", "number_part1"],
                         extraction=lambda d: _get(d, "number", "part1")),
            FieldMapping("number.part1Number", ["cislo_popisne_cislo1"],
                         extraction=lambda d: _get(d, "number", "part1Number")),
            FieldMapping("number.part1Letter", ["cislo_popisne_pismeno1"],
                         extraction=lambda d: _get(d, "number", "part1Letter")),
            FieldMapping("number.part2", ["cislo_orientacni", "number_part2"],
                         extraction=lambda d: _get(d, "number", "part2")),
            FieldMapping("number.part2Number", ["cislo_orientacni_cislo"],
                         extraction=lambda d: _get(d, "number", "part2Number")),
            FieldMapping("number.part2Letter", ["cislo_orientacni_pismeno"],
                         extraction=lambda d: _get(d, "number", "part2Letter")),
            FieldMapping(
                "city",
                ["mesto", "obec", "city", "town", "misto", "lokalita", "mestoobec"],
                extraction=lambda d: _get(d, "city"),
            ),
            FieldMapping(
                "zip",
                ["psc", "zip", "postal_code", "zip_code", "psc_kod", "postal",
                 "zipcode", "post_code", "postcode", "postalcode"],
                extraction=lambda d: _get(d, "zip"),
            ),
            FieldMapping(
                "country",
                ["zeme", "country", "stat"],
                extraction=lambda d: _get(d, "country"),
            ),
        ],
    ),

    "company": Endpoint(
        key="company",
        name="Companies (Reg.No/VAT)",
        path="/company/validate",
        supported_countries=", ".join(C.COVERAGE["company"]),
        options={"correctionMode": "full"},
        fields=[
            FieldMapping(
                "name",
                ["nazev_firmy", "company_name", "firma", "company", "nazev", "obchodni_jmeno"],
                extraction=lambda d: _get(d, "name"),
            ),
            FieldMapping(
                "registrationNumber",
                ["ico", "registration_number", "reg_number", "ic"],
                extraction=lambda d: _get(d, "registrationNumber"),
            ),
            FieldMapping(
                "vatNumber",
                ["dic", "vat", "vat_number", "dic_vat"],
                extraction=lambda d: _get(d, "vatNumber"),
            ),
            FieldMapping(
                "taxNumber",
                ["danove_cislo", "tax_number", "taxnumber", "tax_id",
                 "nip",                       # Poland
                 "adoszam", "adószám"],       # Hungary
                extraction=lambda d: _get(d, "taxNumber"),
            ),
            FieldMapping(
                "country",
                ["zeme", "country", "stat"],
                extraction=lambda d: _get(d, "country"),
            ),
        ],
    ),
}


# --- Subtypy ve stylu aplikace (type/subtype) -----------------------------------
# Maps a classification "subtype" to the actual API field (query path).
TYPE_TO_KEY = {
    "location": "location", "company": "company", "email": "email",
    "name": "name", "phone": "phone",
}
KEY_TO_TYPE = {v: k for k, v in TYPE_TO_KEY.items()}

# Backward-compat: old Czech service keys persisted in .foxentry-session.json (and any old
# saved mappings) are remapped to the current English keys on load. New code never writes these.
SERVICE_ALIAS = {"telefon": "phone", "jmeno": "name", "adresa": "location", "firma": "company"}

# Allowed type/subtype combinations and their labels (CZ/EN) + API field.
# (subtype, api_field, {en, cs})
SUBTYPES: dict[str, list[tuple[str, str, dict[str, str]]]] = {
    "location": [
        ("full", "full", {"en": "Full address", "cs": "Celá adresa", "ex": "Thámova 137/6, 186 00 Praha 8"}),
        ("streetWithNumber", "streetWithNumber", {"en": "Street + number", "cs": "Ulice s číslem", "ex": "Thámova 137/6"}),
        ("street", "street", {"en": "Street only", "cs": "Jen ulice", "ex": "Thámova"}),
        ("number.full", "number.full", {"en": "House number", "cs": "Číslo popisné/orientační", "ex": "137/6"}),
        ("number.part1", "number.part1", {"en": "Descriptive number", "cs": "Číslo popisné", "ex": "137"}),
        ("number.part2", "number.part2", {"en": "Orientation number", "cs": "Číslo orientační", "ex": "6"}),
        ("city", "city", {"en": "City", "cs": "Město / obec", "ex": "Praha 8"}),
        ("zip", "zip", {"en": "ZIP code", "cs": "PSČ", "ex": "186 00"}),
        ("country", "country", {"en": "Country", "cs": "Země", "ex": "CZ"}),
    ],
    "company": [
        ("name", "name", {"en": "Company name", "cs": "Název firmy", "ex": "AVANTRO s.r.o."}),
        ("registrationNumber", "registrationNumber", {"en": "Registration number", "cs": "IČO", "ex": "04997476"}),
        ("vatNumber", "vatNumber", {"en": "VAT number", "cs": "DIČ", "ex": "CZ04997476"}),
        ("taxNumber", "taxNumber", {"en": "Tax number", "cs": "Daňové číslo", "ex": "2120884337",
                                    "desc": {"en": "National tax number — SK (DIČ), PL (NIP), HU (adószám)",
                                             "cs": "Národní daňové číslo — SK (DIČ), PL (NIP), HU (adószám)"}}),
        ("country", "country", {"en": "Country", "cs": "Země", "ex": "CZ"}),
    ],
    "email": [
        ("email", "email", {"en": "Email", "cs": "E-mail", "ex": "petr@firma.cz"}),
    ],
    "name": [
        ("name", "name", {"en": "First name", "cs": "Jméno", "ex": "Petr"}),
        ("surname", "surname", {"en": "Surname", "cs": "Příjmení", "ex": "Novák"}),
        ("nameSurname", "nameSurname", {"en": "Full name", "cs": "Celé jméno", "ex": "Petr Novák"}),
    ],
    "phone": [
        ("number", "number", {"en": "Phone number", "cs": "Telefonní číslo", "ex": "+420 607 123 456"}),
        ("prefix", "prefix", {"en": "Dial prefix", "cs": "Předvolba", "ex": "+420"}),
    ],
}


def subtype_to_field(typ: str, subtyp: str) -> str | None:
    for st, api_field, _ in SUBTYPES.get(typ, []):
        if st == subtyp:
            return api_field
    return None


# Maps a template name (by file prefix) to endpoint(s).
# File "emaily*.csv" / "emails*.csv" -> email validation, etc.
FILENAME_PREFIXES: dict[str, list[str]] = {
    # Czech
    "emaily": ["email"],
    "email": ["email"],
    "telefony": ["phone"],
    "telefon": ["phone"],
    "jmena": ["name"],
    "jmeno": ["name"],
    "adresy": ["location"],
    "adresa": ["location"],
    "firmy": ["company"],
    "firma": ["company"],
    "kombinovany": ["email", "phone", "name", "location", "company"],
    # anglicky
    "emails": ["email"],
    "phones": ["phone"],
    "phone": ["phone"],
    "names": ["name"],
    "name": ["name"],
    "addresses": ["location"],
    "address": ["location"],
    "companies": ["company"],
    "company": ["company"],
    "combined": ["email", "phone", "name", "location", "company"],
}


def human_result(proposal: str | None, is_valid, corrected_valid=None) -> str:
    """
    Convert the technical `proposal` into readable text in the current language.

    `corrected_valid` is `resultCorrected.isValid`. The API reports
    "invalidWithCorrection" both when the fix makes a value valid and when it only
    tidies up the formatting of a value that stays invalid - a phone number can end
    up neatly formatted and still not exist. Calling both "corrected" hides that,
    so the two are told apart here.

    The number of suggestions deliberately does NOT enter the label. Invalid is invalid
    whether one address matched or ten; putting the count here split a single outcome
    into a different bar per count in the report. How many there were belongs in the
    row's `_suggestion` cell.
    """
    from . import i18n
    if corrected_valid is False and proposal in (
            "invalidWithCorrection", "invalidWithPartialCorrection",
            "invalidWithCorrectionWithSuggestion",
            "invalidWithPartialCorrectionWithSuggestion"):
        return i18n.t("res_invalid_reformatted")

    if proposal is None:
        if is_valid is True:
            return i18n.t("res_valid")
        if is_valid is False:
            return i18n.t("res_invalid")
        return i18n.t("res_unverified")
    field_map = {
        "valid": "res_valid",
        "validWithSuggestion": "res_valid_sugg",
        "validWithCorrection": "res_valid_corr",
        "invalid": "res_invalid",
        "invalidWithCorrection": "res_corrected",
        "invalidWithPartialCorrection": "res_partial",
        "invalidWithSuggestion": "res_invalid_sugg",
        "invalidWithCorrectionWithSuggestion": "res_corrected_sugg",
        "invalidWithPartialCorrectionWithSuggestion": "res_partial_sugg",
        "unknown": "res_unknown",
        "unknownWithSuggestion": "res_unknown_sugg",
        "unknownWithCorrection": "res_unknown_corr",
        "unknownWithPartialCorrection": "res_unknown_partial",
        "unknownWithCorrectionWithSuggestion": "res_unknown_corr_sugg",
        "unknownWithPartialCorrectionWithSuggestion": "res_unknown_partial_sugg",
    }
    key = field_map.get(proposal)
    if key:
        return i18n.t(key)
    # fallback: convert an unknown proposal from camelCase to lowercase (uniform format)
    import re
    return re.sub(r"(?<!^)(?=[A-Z])", " ", str(proposal)).lower()
