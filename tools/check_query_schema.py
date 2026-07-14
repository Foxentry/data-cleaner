# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AVANTRO s.r.o.
"""
Check that every query the tool builds is one the Foxentry API actually declares.

MAINTAINER TOOL, run in CI.

    pip install PyYAML
    python tools/check_query_schema.py --oas <path to a checkout of github.com/Foxentry/OAS>

Why this exists
---------------
The house number was being sent as `{"number": {"full": "16"}}`. The field is called
`number.full` - a flat name that happens to contain a dot. The API does not reject an
unknown key, it ignores it, so nothing failed: the query was accepted, the house number was
dropped, and the address was returned as *valid* without it. A file with the street and the
number in separate columns was quietly validated as a street.

Nothing caught it, because JSON Schema validation cannot: the query schemas do not set
`additionalProperties: false`, so an unknown key is legal as far as the schema is concerned.
This check is therefore stricter than the schema. Every key the tool sends must be a
DECLARED property of the query, and its type must match what the OAS says it is.

Each scenario below is a way a customer can split a value across columns - a street and a
house number apart, a phone prefix and the number apart, a first name and a surname apart -
because that is where field names stop being obvious and start being guessed.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

try:
    import yaml
except ImportError:
    sys.exit("Missing build dependency. Run: pip install PyYAML")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from foxentry.endpoints import ENDPOINTS  # noqa: E402

BODIES = {
    "email": "email/EmailValidationBody.yaml",
    "phone": "phone/PhoneValidationBody.yaml",
    "name": "name/NameValidationBody.yaml",
    "company": "company/CompanyValidationBody.yaml",
    "location": "location/LocationValidationBody.yaml",
}

# (service, what the user did, mapped columns, one row)
SCENARIOS = [
    ("email", "one column", {"email": "E"}, {"E": "anna@firma.de"}),

    ("phone", "SPLIT prefix + number", {"prefix": "P", "number": "N"},
     {"P": "+49", "N": "1512 3456789"}),
    ("phone", "SPLIT, prefix empty on this row", {"prefix": "P", "number": "N"},
     {"P": "", "N": "1512 3456789"}),
    ("phone", "one column", {"number": "N"}, {"N": "+49 1512 3456789"}),

    ("name", "SPLIT first name + surname", {"name": "F", "surname": "S"},
     {"F": "Anna", "S": "Müller"}),
    ("name", "one column", {"nameSurname": "C"}, {"C": "Anna Müller"}),
    ("name", "both mapped, row holds the joined one", {"name": "F", "surname": "S", "nameSurname": "C"},
     {"F": "", "S": "", "C": "Anna Müller"}),
    ("name", "both mapped, row holds the split ones", {"name": "F", "surname": "S", "nameSurname": "C"},
     {"F": "Anna", "S": "Müller", "C": ""}),

    ("location", "SPLIT street + house number + ZIP + city",
     {"street": "S", "number.full": "H", "zip": "Z", "city": "C", "country": "K"},
     {"S": "Dietmar-Hopp-Allee", "H": "16", "Z": "69190", "C": "Walldorf", "K": "DE"}),
    ("location", "SPLIT house number into part1 + part2",
     {"street": "S", "number.part1": "A", "number.part2": "B", "city": "C"},
     {"S": "Jeseniova", "A": "1151", "B": "55", "C": "Praha"}),
    ("location", "SPLIT house number into digits + letter",
     {"street": "S", "number.part1Number": "A", "number.part1Letter": "B", "city": "C"},
     {"S": "Hauptstr.", "A": "27", "B": "a", "C": "München"}),
    ("location", "street and number in one column",
     {"streetWithNumber": "SN", "zip": "Z", "city": "C"},
     {"SN": "Königsallee 92", "Z": "40212", "C": "Düsseldorf"}),
    ("location", "whole address in one column", {"full": "F"},
     {"F": "Königsallee 92, 40212 Düsseldorf"}),
    ("location", "both mapped, row holds the structured fields",
     {"full": "F", "street": "S", "number.full": "H", "city": "C"},
     {"F": "x", "S": "Königsallee", "H": "92", "C": "Düsseldorf"}),
    ("location", "both mapped, row holds only the full address",
     {"full": "F", "street": "S", "number.full": "H", "city": "C"},
     {"F": "Königsallee 92", "S": "", "H": "", "C": ""}),

    ("company", "SPLIT name + reg. no. + VAT + tax no.",
     {"name": "N", "registrationNumber": "R", "vatNumber": "V", "taxNumber": "T"},
     {"N": "SAP SE", "R": "HRB 719915", "V": "DE143454214", "T": ""}),
    ("company", "registration number only", {"registrationNumber": "R"}, {"R": "27082440"}),
]


def variants(query_schema: dict) -> list[dict]:
    """Every key-set the query allows, one per `oneOf` branch, with each key's declared type."""
    found: list[dict] = []

    def walk(node: dict, inherited: dict) -> None:
        properties = dict(inherited)
        properties.update(node.get("properties") or {})
        branches = node.get("oneOf") or node.get("anyOf") or []
        if branches:
            for branch in branches:
                walk(branch, properties)
        else:
            found.append(properties)

    walk(query_schema, {})
    return found


def failures(query: dict, allowed: list[dict]) -> list[str]:
    """Empty when the query fits one of the allowed key-sets. Otherwise the closest miss."""
    misses = []
    for properties in allowed:
        errors = []
        for key, value in query.items():
            if key not in properties:
                errors.append(f"key {key!r} is not a field of this query")
                continue
            declared = properties[key].get("type")
            declared = declared if isinstance(declared, list) else [declared]
            actual = "object" if isinstance(value, dict) else "string"
            if actual not in declared:
                errors.append(f"{key!r} is declared {declared}, we send {actual}")
        if not errors:
            return []
        misses.append(errors)
    return min(misses, key=len) if misses else []


def main() -> None:
    parser = argparse.ArgumentParser(description="Check every query against the Foxentry OAS")
    parser.add_argument("--oas", required=True, type=pathlib.Path,
                        help="path to a checkout of github.com/Foxentry/OAS")
    args = parser.parse_args()

    root = args.oas / "components" / "schemas" / "requests"
    allowed = {}
    for service, relative in BODIES.items():
        path = root / relative
        if not path.exists():
            sys.exit(f"OAS file not found: {path}")
        allowed[service] = variants(yaml.safe_load(path.read_text(encoding="utf-8"))["properties"]["query"])

    broken = 0
    for service, what, field_map, row in SCENARIOS:
        query = ENDPOINTS[service].query_from_row(row, field_map)
        errors = failures(query, allowed[service])
        broken += bool(errors)
        print(f"  {'FAIL' if errors else ' ok '}  {service:9} {what:42} {json.dumps(query, ensure_ascii=False)}")
        for error in errors:
            print(f"          {error}")

    if broken:
        sys.exit(f"\n{broken} of {len(SCENARIOS)} queries do not match the OAS.")
    print(f"\nAll {len(SCENARIOS)} queries match the OAS.")


if __name__ == "__main__":
    main()
