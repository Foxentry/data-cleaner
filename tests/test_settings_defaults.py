# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AVANTRO s.r.o.
"""
The settings dialog must not write a value the user never chose.

This bug has been shipped twice, with two different keys, and both times it silently disabled
a feature rather than failing:

* `DEFAULT_COUNTRY` was pre-filled with `CZ`. Every new user opens the settings once, to enter
  their API key. Saving wrote `DEFAULT_COUNTRY=CZ`, and that overrides the country detected
  from the file - so country detection was dead for everyone from their first run.
* `LANGUAGE` then repeated it: the dialog had no "follow the system" option, so it fell back
  to `en`, and the first save wrote `LANGUAGE=en` over the language taken from the OS.

Nothing fails when this happens. The tests below are therefore about the empty default itself,
not about a symptom: a settings field whose value is "detect it" must be empty in the dialog,
and must have a way to say "detect it" in the first place.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WIZARD = (Path(__file__).resolve().parent.parent / "foxentry" / "wizard.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("element,key", [("c_country", "DEFAULT_COUNTRY"), ("c_lang", "LANGUAGE")])
def test_dialog_does_not_invent_a_value(element: str, key: str) -> None:
    """openConfig() must fall back to "", never to a value of its own."""
    match = re.search(rf'getElementById\("{element}"\)\.value\s*=\s*c\.{key}\s*\|\|\s*"([^"]*)"', WIZARD)
    assert match, f"openConfig() no longer fills {element} from c.{key} - update this test"
    assert match.group(1) == "", (
        f'openConfig() falls back to "{match.group(1)}" for {key}. Saving the settings would '
        f"write that value and switch the detection off. The fallback must be empty."
    )


def test_language_select_can_say_follow_the_system() -> None:
    """An empty LANGUAGE means "use the OS language" - the dropdown has to be able to express it."""
    select = re.search(r'<select id="c_lang".*?</select>', WIZARD, re.S)
    assert select, "the language select is gone - update this test"
    assert '<option value=""' in select.group(0), (
        'the language dropdown has no empty option, so it cannot say "follow the system" and '
        "the first save will pin the language to whatever it happens to show"
    )


def test_country_field_is_empty_in_the_markup() -> None:
    """The markup itself must not carry a country either - the dialog is shown before openConfig()
    runs in some paths."""
    field = re.search(r'<input id="c_country"[^>]*>', WIZARD)
    assert field, "the country field is gone - update this test"
    value = re.search(r'value="([^"]*)"', field.group(0))
    assert not value or value.group(1) == "", (
        f'the country input is hard-coded to "{value.group(1)}" in the HTML'
    )
