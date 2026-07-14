# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AVANTRO s.r.o.
"""
Guess which country a file's data comes from.

Knowing the country lets the wizard do three things: send it in the query for the
services that accept one (so the API can verify and correct it), pre-select sensible
formats and prefixes, and warn when a service cannot serve that country.

Nothing here talks to the network - every signal is read from the file itself.
Several weak signals are combined instead of trusting a single one, because any
one of them can be missing or misleading:

    country column   an explicit country value      decisive
    phone prefix     "+44 20 7946 0958" -> GB       strong
    postal code      "NW1 6XE" -> GB                strong (often ambiguous)
    company suffix   "Tesco PLC" -> GB              medium
    email TLD        "...@bbc.co.uk" -> GB          weak

The result carries the reasons, so the wizard can tell the user *why* a country
was picked rather than just asserting it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import countries as C

# How much one matching cell contributes, per signal.
_W_COUNTRY = 6.0
_W_PHONE = 3.0
_W_ZIP = 2.0
_W_SUFFIX = 1.5
_W_TLD = 0.5

# Rows scanned. Enough to be representative, small enough to stay instant.
_SAMPLE = 200

_RE_EMAIL = re.compile(r"[^@\s]+@([^@\s]+\.[a-z]{2,})$", re.IGNORECASE)
_RE_PHONE = re.compile(r"^\+\d[\d\s\-()./]{4,}$")

# ccTLDs whose country is not simply the TLD in upper case.
_TLD_COUNTRY = {"uk": "GB", "co.uk": "GB", "eu": None, "com": None,
                "org": None, "net": None, "info": None}


@dataclass
class Detection:
    """The winning country plus why it won."""

    country: str | None = None
    confidence: float = 0.0          # 0.0 - 1.0
    reasons: list[str] = field(default_factory=list)   # signal names, for i18n
    scores: dict[str, float] = field(default_factory=dict)

    @property
    def is_confident(self) -> bool:
        return self.country is not None and self.confidence >= 0.5

    def as_dict(self) -> dict:
        return {
            "country": self.country,
            "confidence": round(self.confidence, 2),
            "reasons": self.reasons,
            "scores": {k: round(v, 1) for k, v in
                       sorted(self.scores.items(), key=lambda kv: -kv[1])[:5]},
        }


def _country_from_text(value: str) -> str | None:
    """Recognise an explicit country value: "GB" or a country name in any supported language."""
    text = value.strip()
    if not text:
        return None
    upper = text.upper()
    if len(upper) == 2 and upper in C.CALLING_CODES:
        return upper
    for code in C.NAMES_EN:
        if text.casefold() == C.NAMES_EN[code].casefold():
            return code
        if text.casefold() == C.NAMES_CS.get(code, "").casefold():
            return code
    return None


def _tld_country(value: str) -> str | None:
    match = _RE_EMAIL.match(value.strip())
    if not match:
        return None
    domain = match.group(1).lower()
    for suffix in (".".join(domain.split(".")[-2:]), domain.split(".")[-1]):
        if suffix in _TLD_COUNTRY:
            return _TLD_COUNTRY[suffix]
        code = suffix.upper()
        if len(code) == 2 and code in C.CALLING_CODES:
            return code
    return None


def _suffix_countries(value: str) -> list[str]:
    text = f" {value.strip().casefold()} "
    hits = []
    for code, suffixes in C.COMPANY_SUFFIXES.items():
        if any(f" {s} " in text or text.rstrip().endswith(f" {s}") for s in suffixes):
            hits.append(code)
    return hits


def detect_country(rows: list[dict[str, str]]) -> Detection:
    """
    Score every country against the sample rows and return the best one.

    Ambiguous signals are split across the countries they fit (a "130 00" ZIP
    matches CZ, SK and GR), so a signal that cannot discriminate cannot dominate.
    """
    scores: dict[str, float] = {}
    tally: dict[str, int] = {}

    def vote(code: str | None, weight: float, signal: str) -> None:
        if not code:
            return
        scores[code] = scores.get(code, 0.0) + weight
        tally[signal] = tally.get(signal, 0) + 1

    for row in rows[:_SAMPLE]:
        for value in row.values():
            value = (value or "").strip()
            if not value or len(value) > 120:
                continue

            explicit = _country_from_text(value)
            if explicit:
                vote(explicit, _W_COUNTRY, "country")
                continue

            if _RE_PHONE.match(value):
                vote(C.country_of_prefix(value), _W_PHONE, "phone")
                continue

            if "@" in value:
                vote(_tld_country(value), _W_TLD, "email")
                continue

            zip_hits = C.countries_matching_zip(value)
            if zip_hits:
                for code in zip_hits:
                    vote(code, _W_ZIP / len(zip_hits), "zip")

            for code in _suffix_countries(value):
                vote(code, _W_SUFFIX, "company")

    if not scores:
        return Detection()

    best = max(scores, key=lambda k: scores[k])
    total = sum(scores.values())
    confidence = scores[best] / total if total else 0.0

    # Signal names, not sentences: the caller translates them ("why_phone" -> "phone
    # prefixes" / "telefonních předvoleb"). Returning English text here would leak it
    # into the Czech interface.
    reasons = [signal for signal in ("country", "phone", "zip", "company", "email")
               if tally.get(signal)]

    return Detection(country=best, confidence=confidence, reasons=reasons, scores=scores)


def coverage_warnings(services: list[str], country: str | None) -> list[dict]:
    """
    Services that cannot validate this country.

    The service stays enabled - we only tell the user what to expect, because
    every row would come back invalid and still cost credits.
    """
    if not country:
        return []
    warnings = []
    for service in services:
        if not C.supports(service, country):
            warnings.append({
                "service": service,
                "country": country,
                "supported": C.covered_countries(service),
            })
    return warnings
