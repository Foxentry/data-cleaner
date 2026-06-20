# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AVANTRO s.r.o.
"""
Foxentry price list (Pay As You Go) - price per validation.

Source: official Foxentry price list "API - Pay As You Go".
Currency order in tuples: (CZK, EUR_SK, EUR, PLN, USD).
Emails and phones have two rates by `validationType` (basic / extended).
Names are billed by whether the task validates only the name (name) or
name and surname together (nameSurname).
"""
from __future__ import annotations

import json
from typing import Any, Iterable

# (CZK, EUR_SK, EUR, PLN, USD)
CURRENCIES = ["CZK", "EUR_SK", "EUR", "PLN", "USD"]
CURRENCY_SYMBOL = {"CZK": "Kč", "EUR_SK": "€", "EUR": "€", "PLN": "zł", "USD": "$"}
CURRENCY_LABEL = {
    "CZK": "CZK (Kč)", "EUR_SK": "EUR - SK (€)", "EUR": "EUR - other (€)",
    "PLN": "PLN (zł)", "USD": "USD ($)",
}
_IDX = {m: i for i, m in enumerate(CURRENCIES)}

# service (endpoint.key) -> variant -> prices per currency
CENIK: dict[str, dict[str, tuple[float, ...]]] = {
    "location": {"default": (0.139, 0.0058, 0.0072, 0.029, 0.0090)},
    "company":  {"default": (0.199, 0.0083, 0.0104, 0.042, 0.0130)},
    "email":  {"basic":    (0.099, 0.0041, 0.0052, 0.021, 0.0064),
               "extended": (0.249, 0.0104, 0.0130, 0.052, 0.0162)},
    "phone": {"basic":    (0.099, 0.0041, 0.0052, 0.021, 0.0064),
                "extended": (0.399, 0.0166, 0.0208, 0.084, 0.0260)},
    "name":  {"name":        (0.055, 0.0023, 0.0028, 0.011, 0.0035),
               "nameSurname": (0.109, 0.0045, 0.0057, 0.023, 0.0071)},
}

# Datascope surcharge for enrichment - added to Validate when
# options have dataScope=full (extended/full for companies). Emails and phones have no
# surcharge; their extension is already a different Validate rate (validationType extended).
# Source: official Foxentry price list (Datascope - Information ... full/extended).
DATASCOPE_SURCHARGE: dict[str, dict[str, tuple[float, ...]]] = {
    "location": {"full":     (0.099, 0.0041, 0.0052, 0.021, 0.0064)},
    "company":  {"extended": (0.249, 0.0104, 0.0130, 0.052, 0.0162),
               "full":     (0.399, 0.0166, 0.0208, 0.084, 0.0260)},
    "name":  {"name":        (0.050, 0.0021, 0.0026, 0.010, 0.0032),
               "nameSurname": (0.099, 0.0041, 0.0052, 0.021, 0.0064)},
}


def normalize_currency(currency: str | None) -> str:
    currency = (currency or "CZK").upper().replace("-", "_").replace(" ", "_")
    return currency if currency in _IDX else "CZK"


def _variant(service: str, options: dict[str, Any] | None, fields: Iterable[str]) -> str:
    options = options or {}
    if service in ("email", "phone"):
        return "extended" if options.get("validationType") == "extended" else "basic"
    if service == "name":
        fl = set(fields or [])
        if "nameSurname" in fl or ("name" in fl and "surname" in fl):
            return "nameSurname"
        return "name"
    return "default"


def _datascope_surcharge(service: str, options: dict[str, Any] | None,
                         fields: Iterable[str], idx: int) -> float:
    """Enrich surcharge (dataScope full / extended for companies) in the chosen currency."""
    options = options or {}
    ds = options.get("dataScope")
    tab = DATASCOPE_SURCHARGE.get(service)
    if not tab:
        return 0.0
    if service == "company":
        row = tab.get(ds) if ds in ("extended", "full") else None
    elif service == "location":
        row = tab.get("full") if ds == "full" else None
    elif service == "name" and ds == "full":
        row = tab.get(_variant("name", options, fields)) or tab.get("name")
    else:
        row = None
    return row[idx] if row else 0.0


def _base_rate(service: str, options: dict[str, Any] | None,
                    fields: Iterable[str], idx: int) -> float:
    """Rate for the validation itself (without the enrich surcharge) in the chosen currency."""
    tab = CENIK.get(service)
    if not tab:
        return 0.0
    var = _variant(service, options, fields)
    row = tab.get(var) or next(iter(tab.values()))
    return row[idx]


def price_per_validation(service: str, options: dict[str, Any] | None,
                     fields: Iterable[str], currency: str = "CZK") -> float:
    """Price per validation of the given task in the chosen currency (incl. enrich surcharge)."""
    if service not in CENIK:
        return 0.0
    idx = _IDX[normalize_currency(currency)]
    return _base_rate(service, options, fields, idx) \
        + _datascope_surcharge(service, options, fields, idx)


def compute_price(tasks, rows, currency: str = "CZK") -> dict:
    """Indicative price per run: rate x number of calls for each task.

    Each item is split into validation (`unit_base`) and enrichment (`unit_enrich`),
    so the summary can be itemized. `unit`/`subtotal` remain the sum (backward compatibility).
    """
    currency = normalize_currency(currency)
    idx = _IDX[currency]
    items = []
    total = 0.0
    for u in tasks:
        # Dedup-aware: bill only UNIQUE queries (same as the run - repeated
        # inputs are validated once). raw_calls = rows with data (before deduplication).
        raw_calls = 0
        seen = set()
        calls = 0
        for r in rows:
            if not u.has_data(r):
                continue
            raw_calls += 1
            key = json.dumps(u.endpoint.query_from_row(r, u.field_map), sort_keys=True, ensure_ascii=False)
            if key in seen:
                continue
            seen.add(key)
            calls += 1
        fields = list(u.field_map.keys())
        base = _base_rate(u.endpoint.key, u.options, fields, idx)
        enr = _datascope_surcharge(u.endpoint.key, u.options, fields, idx)
        unit = base + enr
        sub = calls * unit
        total += sub
        items.append({
            "label": u.label, "service": u.endpoint.key,
            "calls": calls, "raw_calls": raw_calls,
            "deduped": raw_calls - calls,
            "unit": round(unit, 4),
            "unit_base": round(base, 4), "unit_enrich": round(enr, 4),
            "enrich": enr > 0,
            "subtotal": round(sub, 2),
            "subtotal_base": round(calls * base, 2),
            "subtotal_enrich": round(calls * enr, 2),
        })
    return {"currency": currency, "symbol": CURRENCY_SYMBOL[currency],
            "total": round(total, 2), "items": items}
