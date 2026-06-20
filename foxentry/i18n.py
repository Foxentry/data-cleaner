# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AVANTRO s.r.o.
"""
Internationalization.

The default language is English (en). Adding another language is easy - just
add a dictionary to `STRINGS`. The language is set in the config (LANGUAGE=en|cs).

Default language is English (en). Adding a language = add a dict to STRINGS.
Language is set in the config file (LANGUAGE=en|cs).
"""

from __future__ import annotations

DOSTUPNE_JAZYKY = ["en", "cs"]
LANGUAGE_NAMES = {"en": "English", "cs": "Čeština"}

_AKTUALNI = "en"


def set_lang(lang: str) -> None:
    global _AKTUALNI
    lang = (lang or "en").lower()
    _AKTUALNI = lang if lang in STRINGS else "en"


def get_lang() -> str:
    return _AKTUALNI


def t(msg_id: str, **kw) -> str:
    tabulka = STRINGS.get(_AKTUALNI, STRINGS["en"])
    text = tabulka.get(msg_id) or STRINGS["en"].get(msg_id) or msg_id
    if kw:
        try:
            return text.format(**kw)
        except (KeyError, IndexError):
            return text
    return text


# Endpoint names and supported countries by language
def endpoint_name(key: str) -> str:
    return t(f"ep_{key}")


def countries(token: str) -> str:
    if token == "worldwide":
        return t("country_worldwide")
    if token == "europe":
        return t("country_europe")
    return token  # country codes are language-neutral (CZ, SK, PL)


STRINGS: dict[str, dict[str, str]] = {
    # ============================================================= ENGLISH
    "en": {
        "app_title": "Foxentry Data Cleaner",
        "app_subtitle": "Validation of emails, addresses, phones, names and companies via Foxentry API",
        "api_key_line": "API key: {key}   ·   API: {url}",

        "nokey_title": "Missing API key",
        "nokey_intro": "The application needs your Foxentry API key.",
        "nokey_1": "1) Open the file `config.env` (a template is in `config.example.env`),",
        "nokey_2": "   or run the app without --cli to set it in the wizard.",
        "nokey_3": "2) Fill in:  FOXENTRY_API_KEY=your_key",
        "nokey_4": "3) Save and run the application again.",
        "nokey_get": "You can obtain the key in your project administration at app.foxentry.com.",
        "nokey_docs": "See `docs/documentation.html` for details.",

        "no_files_intro": "There are no files to validate in the `input` folder.",
        "no_files_how": "How to proceed:",
        "no_files_1": " 1) Put a CSV or Excel file with your contact data into the `input` folder",
        "no_files_2": "    (e.g. emails.csv, addresses.csv, combined.csv).",
        "no_files_3": " 2) Fill in your data (only the columns you have).",
        "no_files_4": " 3) Save it into the `input` folder and run again.",

        "select_file": "Select a file to validate:",
        "file_num": "File number [1-{n}]: ",
        "invalid_choice": "Invalid choice.",

        "file_header": "File: {name}",
        "rows_with_data": "Rows with data: {n}",
        "encoding": "Encoding:    {info}",
        "columns": "Columns:     {cols}",
        "no_data": "The file contains no data to validate.",

        "recognized": "Recognized validations:",
        "validation_line": "  • {name}: {cols}  (countries: {countries})",
        "no_recognized_1": "No column we can validate was recognized in the file.",
        "no_recognized_2": "Please check that the file has a header row, or map the columns manually.",

        "resume_found": "Found partial output - resuming from row {n}.",
        "already_done": "This file is already fully validated ({n} rows).",
        "revalidate_q": "Validate again from the start?",
        "diff_struct": "Output {name} has a different structure.",
        "overwrite_q": "Overwrite it and start over?",

        "scope_header": "Validation scope",
        "scope_opt1": " 1) Test batch    - first {n} rows  (recommended for a trial)",
        "scope_opt2": " 2) Full database - all {n} rows",
        "scope_prompt": "Choice [1/2], default 1: ",
        "scope_test": "test batch ({n} rows)",
        "scope_full": "full database ({n} rows)",
        "nothing_left": "There is nothing left to validate in this scope.",

        "estimate_header": "Estimate",
        "probe": "Verifying access and checking limits (1 test query)...",
        "cannot_connect": "Cannot connect: {e}",
        "check_key": "Check the API key in `config.env` (and any IP restriction).",
        "credit_topup": "Top up credits in your project administration at app.foxentry.com.",
        "verify_failed": "Could not verify API access: {e}",
        "est_scope": "Scope:               {txt}",
        "est_rows": "Rows to process:     {n}",
        "est_calls": "API calls (credits): ~{n}",
        "est_credits": "Credits remaining:   {left}",
        "est_credits_of": "{left} of {limit}",
        "est_warn1": "WARNING: validation may use more credits than you have available.",
        "est_warn2": "         When exhausted, the run stops and can be resumed later.",
        "est_rate": "Rate:                ~{rate} queries/s (rate limit {rl}/{rp} s)",
        "est_eta": "Estimated run time:  ~{eta}",
        "privacy1": "Note: only filled-in fields are sent to api.foxentry.com (HTTPS).",
        "privacy2": "      Your data stays with you. The run can be stopped anytime (Ctrl+C).",
        "run_confirm": "Start validation?",
        "cancelled": "Cancelled.",

        "running": "Validation running",
        "done": "Done",
        "interrupted": "Interrupted",
        "processed_rows": "Rows processed: {n}",
        "api_calls": "API calls:      {n}",
        "comm_errors": "Comm. errors:   {n}",
        "results_csv": "Results (CSV):   {p}",
        "results_xlsx": "Results (Excel): {p}",
        "report_html": "Report (HTML):   {p}",
        "interrupted_1": "The run was interrupted. Completed rows are saved.",
        "interrupted_2": "Run the app again with the same file - it resumes automatically.",

        "file_load_failed": "Failed to load file:\n  {e}",
        "err_xls_unsupported": "The old .xls format is not supported. Open the file in Excel and save it as .xlsx or CSV (UTF-8).",

        # validation result labels
        "res_valid": "valid",
        "res_valid_sugg": "valid (suggestion available)",
        "res_valid_corr": "valid (corrected)",
        "res_invalid": "invalid",
        "res_corrected": "corrected",
        "res_partial": "partially corrected",
        "res_invalid_sugg": "invalid (suggestion available)",
        "res_corrected_sugg": "corrected (suggestion available)",
        "res_partial_sugg": "partially corrected (suggestion available)",
        "res_unknown": "uncertain",
        "res_unknown_sugg": "uncertain (suggestion available)",
        "res_unknown_corr": "uncertain (corrected)",
        "res_unknown_partial": "uncertain (partially corrected)",
        "res_unknown_corr_sugg": "uncertain (corrected, suggestion available)",
        "res_unknown_partial_sugg": "uncertain (partially corrected, suggestion available)",
        "res_unverified": "unverified",
        "res_not_filled": "(empty)",
        "res_error": "error",
        "note_still_invalid": "Still invalid",
        "note_fixed": "Fixed",
        "enr_gender": "gender", "enr_male": "male", "enr_female": "female",
        "enr_yes": "yes", "enr_no": "no",
        "enr_vocative": "vocative (5th case)", "enr_namedays": "name days",
        "rep_enriched": "enriched",
        "rep_enrich_note": "Enriched services add extra columns at the end with additional data (gender, vocative, name days, GPS, region…).",
        "enc_sep": "delimiter",
        "sep_comma": "comma",
        "sep_semicolon": "semicolon",
        "sep_tab": "tab",
        "enc_xlsx": "xlsx (Unicode)",
        "server_running": "Wizard running at {url}",
        "server_stop": "Leave this window open. Press Ctrl+C to stop.",
        "server_bye": "Stopped.",
        "cls_data_match": "{pct}% of values match: {label}",
        "cls_header_resolved": "resolved from the header",
        "cls_header_refined": "data is an address; header set the subtype",
        "cls_data_wins": "data looks like {label} (header suggested otherwise) — data wins",
        "cls_from_header": "classified from the column name",
        "cls_mixed_header": "mixed values; classified from the header",
        "cls_weak": "weak signal; best guess: {label}",
        "cls_country": "values look like country names/codes",
        "cls_company": "values contain a company suffix (s.r.o./a.s./…)",
        "cls_city": "values match known city names",
        "cls_housenum_ctx": "house number — matched only because a street/address is already mapped",
        "cls_city_ctx": "ambiguous street/city — a street is already mapped, so treated as city",
        "cls_dup_zip": "looks like a ZIP, but another column is the actual ZIP — left unmapped",
        "cls_dup_company": "looks like a company ID, but another column is named as it — left unmapped",
        "cls_id_col": "internal identifier column — not a validatable value",
        "cls_header_fallback": "format not recognized, but the column name indicates this field",
        "cls_ambiguous": "text values; ambiguous without a clear header",
        "cls_empty_header": "empty column; classified from the header",
        "cls_empty": "empty column",
        "cls_none": "no confident match",

        # endpointy
        "ep_email": "Email addresses",
        "ep_phone": "Phone numbers",
        "ep_name": "Names and surnames",
        "ep_location": "Addresses",
        "ep_company": "Companies (Reg.No/VAT)",
        "country_worldwide": "worldwide",
        "country_europe": "30+ Europe",

        # report
        "rep_title": "Validation report",
        "rep_file": "File",
        "rep_status_done": "Completed",
        "rep_status_interrupted": "Interrupted - will resume on next run",
        "rep_summary": "Summary",
        "rep_rows": "rows processed",
        "rep_calls": "API calls",
        "rep_time": "run time",
        "rep_errors": "comm. errors",
        "rep_validations": "Validations",
        "rep_by_type": "Results by type",
        "rep_no_data": "No data.",
        "rep_value_title": "Foxentry value",
        "rep_in_err": "Input error rate",
        "rep_out_err": "Output error rate",
        "rep_rescued": "Data rescued",
        "rep_enriched_count": "Data points added",
        "rep_enrich_title": "Enriched data (per service)",
        "rep_enriched_unit": "data points",
        "rep_enrich_empty": "Enrichment was enabled, but the API returned no extra data for these records. Check that the API key/project has the dataScope (full) entitlement.",
        "rep_dedup_note": "Saved {n} duplicate validations — repeated records were validated only once (fewer credits used).",
        "rep_enriched_summary": "On top of that, Foxentry added {n} extra data points (enrichment fields such as GPS, region, gender, carrier or company details).",
        "rep_value_summary": "Foxentry lowered the data error rate from {inp} % to {out} % — it automatically fixed {n} records ({pct} %) that would otherwise stay wrong.",
        "rep_value_clean": "Your data was already clean — no errors to fix on input.",
        "rep_ben_email": "Invalid e-mail addresses won't be contacted → higher deliverability and a better sender reputation.",
        "rep_ben_location": "Corrected postal addresses cut undelivered and returned shipments.",
        "rep_ben_phone": "Validated phone numbers mean fewer failed calls and SMS.",
        "rep_ben_name": "Properly formatted names (case, vocative) improve personalization.",
        "rep_ben_company": "Verified company data (reg. no. / VAT) makes invoicing and records more accurate.",
        "rep_outputs": "Output files",
        "rep_csv_desc": "results (CSV, UTF-8)",
        "rep_xlsx_desc": "results (Excel)",
        "rep_updated_note": "Columns with the _updated suffix contain values after correction. The _proposal column is the technical code from Foxentry API.",
        "rep_footer": "Generated locally. Your data did not leave this computer except for individual validation queries to api.foxentry.com.",
    },

    # ============================================================= CZECH
    "cs": {
        "app_title": "FOXENTRY – čistič dat",
        "app_subtitle": "Validace e-mailů, adres, telefonů, jmen a firem přes Foxentry API",
        "api_key_line": "API klíč: {key}   ·   API: {url}",

        "nokey_title": "Chybí API klíč",
        "nokey_intro": "Aplikace potřebuje váš Foxentry API klíč.",
        "nokey_1": "1) Otevřete soubor `config.env` (vzor je v `config.example.env`),",
        "nokey_2": "   nebo spusťte aplikaci bez --cli a zadejte klíč v průvodci.",
        "nokey_3": "2) Vyplňte řádek:  FOXENTRY_API_KEY=vas_klic",
        "nokey_4": "3) Uložte a spusťte aplikaci znovu.",
        "nokey_get": "Klíč získáte v administraci projektu na app.foxentry.com.",
        "nokey_docs": "Podrobnosti najdete v souboru `docs/documentation.html`.",

        "no_files_intro": "Ve složce `input` nejsou žádné soubory k validaci.",
        "no_files_how": "Postup:",
        "no_files_1": " 1) Vložte do složky `input` soubor CSV nebo Excel s kontaktními daty",
        "no_files_2": "    (e.g. emails.csv, addresses.csv, combined.csv).",
        "no_files_3": " 2) Vyplňte do ní svá data (stačí jen sloupce, které máte).",
        "no_files_4": " 3) Uložte ji do složky `input` a spusťte aplikaci znovu.",

        "select_file": "Vyberte soubor k validaci:",
        "file_num": "Číslo souboru [1-{n}]: ",
        "invalid_choice": "Neplatná volba.",

        "file_header": "Soubor: {name}",
        "rows_with_data": "Řádků s daty: {n}",
        "encoding": "Kódování:    {info}",
        "columns": "Sloupce:     {cols}",
        "no_data": "Soubor neobsahuje žádná data k validaci.",

        "recognized": "Rozpoznané validace:",
        "validation_line": "  • {name}: {cols}  (země: {countries})",
        "no_recognized_1": "V souboru nebyl rozpoznán žádný sloupec, který umíme validovat.",
        "no_recognized_2": "Zkontrolujte, že soubor má řádek se záhlavím, nebo namapujte sloupce ručně.",

        "resume_found": "Nalezen rozpracovaný výstup - navážeme od řádku {n}.",
        "already_done": "Tento soubor je už celý zvalidovaný ({n} řádků).",
        "revalidate_q": "Zvalidovat znovu od začátku?",
        "diff_struct": "Výstup {name} má jinou strukturu.",
        "overwrite_q": "Přepsat ho a začít znovu?",

        "scope_header": "Rozsah validace",
        "scope_opt1": " 1) Testovací várka  - prvních {n} řádků  (doporučeno na zkoušku)",
        "scope_opt2": " 2) Celá databáze    - všech {n} řádků",
        "scope_prompt": "Volba [1/2], výchozí 1: ",
        "scope_test": "testovací várka ({n} řádků)",
        "scope_full": "celá databáze ({n} řádků)",
        "nothing_left": "V tomto rozsahu už není co validovat.",

        "estimate_header": "Odhad",
        "probe": "Ověřuji přístup a zjišťuji limity (1 testovací dotaz)...",
        "cannot_connect": "Nelze se připojit: {e}",
        "check_key": "Zkontrolujte API klíč v `config.env` (a případné omezení na IP adresu).",
        "credit_topup": "Dobijte kredity v administraci projektu na app.foxentry.com.",
        "verify_failed": "Nepodařilo se ověřit přístup k API: {e}",
        "est_scope": "Rozsah:              {txt}",
        "est_rows": "Řádků ke zpracování: {n}",
        "est_calls": "Volání API (kreditů): ~{n}",
        "est_credits": "Zbývá kreditů:       {left}",
        "est_credits_of": "{left} z {limit}",
        "est_warn1": "POZOR: validace může spotřebovat víc kreditů, než máte k dispozici.",
        "est_warn2": "       Po vyčerpání se běh zastaví a později na něj lze navázat.",
        "est_rate": "Tempo:               ~{rate} dotazů/s (rate limit {rl}/{rp} s)",
        "est_eta": "Odhad doby běhu:     ~{eta}",
        "privacy1": "Pozn.: ven jdou jen vyplněná pole na api.foxentry.com (HTTPS).",
        "privacy2": "       Data zůstávají u vás. Běh lze kdykoliv přerušit (Ctrl+C).",
        "run_confirm": "Spustit validaci?",
        "cancelled": "Zrušeno.",

        "running": "Validace běží",
        "done": "Hotovo",
        "interrupted": "Přerušeno",
        "processed_rows": "Zpracováno řádků: {n}",
        "api_calls": "Volání API:       {n}",
        "comm_errors": "Chyb komunikace:  {n}",
        "results_csv": "Výsledky (CSV):   {p}",
        "results_xlsx": "Výsledky (Excel): {p}",
        "report_html": "Přehled (HTML):   {p}",
        "interrupted_1": "Běh byl přerušen. Hotové řádky jsou uložené.",
        "interrupted_2": "Spusťte aplikaci znovu se stejným souborem - naváže se automaticky.",

        "file_load_failed": "Soubor se nepodařilo načíst:\n  {e}",
        "err_xls_unsupported": "Starý formát .xls není podporován. Otevřete soubor v Excelu a uložte jako .xlsx nebo CSV (UTF-8).",

        "res_valid": "platné",
        "res_valid_sugg": "platné (existuje návrh)",
        "res_valid_corr": "platné (opraveno)",
        "res_invalid": "neplatné",
        "res_corrected": "opraveno",
        "res_partial": "částečně opraveno",
        "res_invalid_sugg": "neplatné (existuje návrh)",
        "res_corrected_sugg": "opraveno (existuje návrh)",
        "res_partial_sugg": "částečně opraveno (existuje návrh)",
        "res_unknown": "nejisté",
        "res_unknown_sugg": "nejisté (existuje návrh)",
        "res_unknown_corr": "nejisté (opraveno)",
        "res_unknown_partial": "nejisté (částečně opraveno)",
        "res_unknown_corr_sugg": "nejisté (opraveno, existuje návrh)",
        "res_unknown_partial_sugg": "nejisté (částečně opraveno, existuje návrh)",
        "res_unverified": "neověřeno",
        "res_not_filled": "(nevyplněno)",
        "res_error": "chyba",
        "note_still_invalid": "Stále nevalidní",
        "note_fixed": "Opraveno",
        "enr_gender": "rod", "enr_male": "muž", "enr_female": "žena",
        "enr_yes": "ano", "enr_no": "ne",
        "enr_vocative": "5. pád", "enr_namedays": "jmeniny",
        "rep_enriched": "obohaceno",
        "rep_enrich_note": "Obohacené služby přidávají na konec sloupce navíc s doplňujícími údaji (rod, 5. pád, jmeniny, GPS, region…).",
        "enc_sep": "oddělovač",
        "sep_comma": "čárka",
        "sep_semicolon": "středník",
        "sep_tab": "tabulátor",
        "enc_xlsx": "xlsx (Unicode)",
        "server_running": "Průvodce běží na {url}",
        "server_stop": "Nechte toto okno otevřené. Zastavíte ho přes Ctrl+C.",
        "server_bye": "Zastaveno.",
        "cls_data_match": "{pct} % hodnot odpovídá: {label}",
        "cls_header_resolved": "určeno podle hlavičky",
        "cls_header_refined": "data jsou adresa; hlavička určila subtyp",
        "cls_data_wins": "data vypadají jako {label} (hlavička napovídala jinak) — rozhodla data",
        "cls_from_header": "určeno podle názvu sloupce",
        "cls_mixed_header": "smíšené hodnoty; určeno podle hlavičky",
        "cls_weak": "slabý signál; nejlepší odhad: {label}",
        "cls_country": "hodnoty vypadají jako názvy/kódy zemí",
        "cls_company": "hodnoty obsahují firemní příponu (s.r.o./a.s./…)",
        "cls_city": "hodnoty odpovídají známým městům",
        "cls_housenum_ctx": "číslo popisné — napárováno jen proto, že už je v tabulce ulice/adresa",
        "cls_city_ctx": "ulice/obec nejednoznačné — ulice už je namapovaná, bráno jako obec",
        "cls_dup_zip": "vypadá jako PSČ, ale skutečné PSČ je v jiném sloupci — ponecháno nenamapované",
        "cls_dup_company": "vypadá jako IČO, ale to je v jiném (pojmenovaném) sloupci — ponecháno nenamapované",
        "cls_id_col": "interní identifikátor — není co validovat",
        "cls_header_fallback": "formát nerozpoznán, ale název sloupce odpovídá tomuto poli",
        "cls_ambiguous": "textové hodnoty; bez jasné hlavičky nejednoznačné",
        "cls_empty_header": "prázdný sloupec; určeno podle hlavičky",
        "cls_empty": "prázdný sloupec",
        "cls_none": "bez jistého určení",
        "ep_email": "E-mailové adresy",
        "ep_phone": "Telefonní čísla",
        "ep_name": "Jména a příjmení",
        "ep_location": "Adresy",
        "ep_company": "Firmy (IČO/DIČ)",
        "country_worldwide": "celý svět",
        "country_europe": "30+ Evropa",

        "rep_title": "Report validace",
        "rep_file": "Soubor",
        "rep_status_done": "Dokončeno",
        "rep_status_interrupted": "Přerušeno - po dalším spuštění se naváže",
        "rep_summary": "Souhrn",
        "rep_rows": "zpracovaných řádků",
        "rep_calls": "volání API",
        "rep_time": "doba běhu",
        "rep_errors": "chyb komunikace",
        "rep_validations": "Validace",
        "rep_by_type": "Výsledky podle typu",
        "rep_no_data": "Žádná data.",
        "rep_value_title": "Přínos Foxentry",
        "rep_in_err": "Chybovost na vstupu",
        "rep_out_err": "Chybovost na výstupu",
        "rep_rescued": "Zachráněno dat",
        "rep_enriched_count": "Doplněných údajů",
        "rep_enrich_title": "Doplněná data (podle služby)",
        "rep_enriched_unit": "údajů",
        "rep_enrich_empty": "Obohacení bylo zapnuté, ale API pro tyto záznamy žádná data navíc nevrátilo. Ověřte, že API klíč/projekt má oprávnění na dataScope (full).",
        "rep_dedup_note": "Ušetřeno {n} duplicitních validací — opakující se záznamy se ověřily jen jednou (méně spotřebovaných kreditů).",
        "rep_enriched_summary": "Navíc Foxentry doplnil {n} dalších údajů (např. GPS, region, rod, operátor nebo údaje o firmě).",
        "rep_value_summary": "Foxentry snížil chybovost dat z {inp} % na {out} % — automaticky opravil {n} záznamů ({pct} %), které by jinak zůstaly chybné.",
        "rep_value_clean": "Vaše data byla už čistá — na vstupu nebylo co opravovat.",
        "rep_ben_email": "Na nevalidní e-maily už nemusíte posílat → vyšší doručitelnost a lepší reputace odesílatele.",
        "rep_ben_location": "Opravené poštovní adresy snižují počet nedoručených a vrácených zásilek.",
        "rep_ben_phone": "Ověřená telefonní čísla = méně neúspěšných hovorů a SMS.",
        "rep_ben_name": "Správně formátovaná jména (velikost písmen, 5. pád) zlepšují personalizaci.",
        "rep_ben_company": "Ověřené firemní údaje (IČO/DIČ) zpřesní fakturaci a evidenci.",
        "rep_outputs": "Výstupní soubory",
        "rep_csv_desc": "výsledky (CSV, UTF-8)",
        "rep_xlsx_desc": "výsledky (Excel)",
        "rep_updated_note": "Sloupce s příponou _updated obsahují hodnoty po korekci. Sloupec _proposal je technický kód z Foxentry API.",
        "rep_footer": "Vygenerováno lokálně. Data neopustila tento počítač kromě jednotlivých validačních dotazů na api.foxentry.com.",
    },
}
