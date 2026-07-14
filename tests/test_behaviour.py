# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AVANTRO s.r.o.
"""
The behaviour that has broken before, pinned down.

Every test here corresponds to a bug that shipped or nearly shipped. They are not a general
suite; they are the fence around the holes we have already fallen into.
"""

from __future__ import annotations

import pytest

from foxentry import i18n
from foxentry.classification import _is_full_name
from foxentry.endpoints import ENDPOINTS
from foxentry.mapping import suggest_mapping
from foxentry.report import flags_for


# --- The classifier sent whole names to the "first name" field -----------------------------
def _first_candidate(header: str, values: list[str], country: str = "CZ") -> str:
    rows = [{header: v} for v in values]
    candidate = (suggest_mapping([header], rows, country)[0].get("candidates") or [{}])[0]
    return f"{candidate.get('service')}/{candidate.get('field')}"


FULL_NAMES = ["Jan Novák", "Anna Müller", "Eva Malá", "Petr Svoboda"]


@pytest.mark.parametrize("header", ["Jméno a příjmení", "Full name", "Name", "Jméno", "Příjmení",
                                    "Zákazník", "Customer"])
def test_a_column_of_whole_names_is_a_whole_name_column(header: str) -> None:
    """The values decide, not the header. "Jan Novák" in a column called "Jméno" is still a
    whole name, and sending it as a first name spends a credit to be told it does not exist."""
    assert _first_candidate(header, FULL_NAMES) == "name/nameSurname"


@pytest.mark.parametrize("header,values,expected", [
    ("Jméno", ["Jan", "Petr", "Eva"], "name/name"),
    ("Příjmení", ["Novák", "Svoboda", "Malá"], "name/surname"),
    ("Město", ["Praha", "Brno", "Ostrava"], "location/city"),
    ("PSČ", ["110 00", "602 00", "702 00"], "location/zip"),
    ("Firma", ["Alza.cz a.s.", "ČEZ a.s.", "Seznam.cz, a.s."], "company/name"),
    ("E-mail", ["a@b.cz", "c@d.cz", "e@f.cz"], "email/email"),
])
def test_the_columns_that_worked_still_work(header, values, expected) -> None:
    assert _first_candidate(header, values) == expected


@pytest.mark.parametrize("values,expected", [
    (["Jan Sedláček", "Anna Aslan", "Eva Semerádová"], True),   # " se" is inside "Sedláček"
    (["Ludwig van Beethoven", "Jan de Vries"], True),           # particles are part of a name
    (["Ústí nad Labem", "Rožnov pod Radhoštěm"], False),        # "nad"/"pod" join a place name
    (["AVANTRO s.r.o.", "SAP SE"], False),
    (["Jan", "Eva", "Petr"], False),
])
def test_what_counts_as_a_whole_name(values, expected) -> None:
    assert _is_full_name(values) is expected


# --- The report counted words, and counted a failed correction as a rescue ------------------
@pytest.mark.parametrize("outcome,expected", [
    ("valid", {"valid"}),
    ("validWithSuggestion", {"valid", "suggestion"}),
    ("invalid", {"invalid"}),
    ("invalidWithSuggestion", {"invalid", "suggestion"}),
    ("invalidWithCorrection", {"valid", "corrected"}),
    ("invalidWithPartialCorrection", {"invalid", "corrected"}),
    # A correction the API says did not produce a valid value: corrected AND still invalid.
    ("invalidWithCorrection+stillInvalid", {"invalid", "corrected"}),
])
def test_a_result_can_be_several_things_at_once(outcome, expected) -> None:
    assert flags_for(outcome) == expected


# --- The house number was sent as a nested object and silently dropped ----------------------
def test_the_house_number_goes_in_a_flat_key() -> None:
    """`number.full` is the name of the field, dot and all. Nested, the API ignores it as an
    unknown key and then reports the house number it never received as valid."""
    field_map = {"street": "S", "number.full": "H", "city": "C", "zip": "Z"}
    query = ENDPOINTS["location"].query_from_row(
        {"S": "Dietmar-Hopp-Allee", "H": "16", "C": "Walldorf", "Z": "69190"}, field_map)
    assert query["number.full"] == "16"
    assert "number" not in query


def test_one_of_variants_are_never_mixed() -> None:
    """`full` and the structured fields are alternatives. Sending both is not a richer query,
    it is an invalid one."""
    field_map = {"full": "F", "street": "S", "number.full": "H", "city": "C"}
    structured = ENDPOINTS["location"].query_from_row(
        {"F": "anything", "S": "Königsallee", "H": "92", "C": "Düsseldorf"}, field_map)
    assert "full" not in structured and structured["number.full"] == "92"

    joined = ENDPOINTS["location"].query_from_row(
        {"F": "Königsallee 92, Düsseldorf", "S": "", "H": "", "C": ""}, field_map)
    assert joined == {"full": "Königsallee 92, Düsseldorf"}


# --- The language of the operating system ---------------------------------------------------
@pytest.mark.parametrize("tag,expected", [
    ("cs_CZ.UTF-8", "cs"),
    ("cs-CZ", "cs"),
    ("cs_CZ:cs", "cs"),        # the GNU LANGUAGE list form, read as a config key as well
    ("en_US.UTF-8", "en"),
    ("de_DE.UTF-8", ""),       # not translated -> caller decides
    ("C", ""),
    ("", ""),
])
def test_locale_tags_are_understood(tag, expected) -> None:
    assert i18n.normalize_lang(tag) == expected


def test_every_string_exists_in_both_languages() -> None:
    assert set(i18n.STRINGS["en"]) == set(i18n.STRINGS["cs"])
