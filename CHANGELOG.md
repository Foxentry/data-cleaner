# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.1.0] - 2026-07-14

### Added

- **macOS ships as an app in a disk image.** Download `FoxentryDataCleaner-macos.dmg`, open it,
  drag the app to Applications, double-click. That is the whole thing. 2.0.0 shipped a bare Unix
  executable: a browser download strips its execute bit and Finder cannot open an extensionless
  file, so it needed a terminal and `chmod +x`. The disk image is now the only macOS download;
  for the command line the binary is inside the app:
  `"/Applications/Foxentry Data Cleaner.app/Contents/MacOS/FoxentryDataCleaner" --cli`.
- **The notarization ticket is stapled** to the app and to the disk image, so Gatekeeper clears
  them without asking Apple. A bare binary cannot be stapled, which is why 2.0.0 needed an
  internet connection on first launch.
- **The browser window is the app.** Close it and the app stops. The page says it is going
  away, the server schedules the stop, and anything that talks to it before the deadline cancels
  that - which is how a reload survives: it loads again and cancels its own shutdown. Switching
  to another window changes nothing, because nothing is being counted.
- **No console window on Windows and macOS.** The black box behind the browser is gone: people
  closed it by accident or left it running for days. Output goes to `logs/app.log`, and a
  failure to start puts up a native dialog rather than vanishing. `--cli` attaches to the
  console it was launched from. Linux keeps its console: it has no bundle and is run from a
  terminal anyway.
- **A Quit button in the wizard.** The app is a local server, and it used to be stopped with
  Ctrl+C in the console it prints to. A macOS app has no console. It works on every platform,
  and it ends the black window on Windows that people used to leave running for days.

### Fixed

- **Launching the app again reopens its window** instead of starting a second copy. The window
  is a browser window and browser windows get buried; relaunching is what a user does when one
  goes missing, and it used to leave them with two servers on two ports, one holding a
  half-finished run. The running copy is found by asking the port whether it is us, so a stale
  file left by a crash is not believed.
- **Cmd+Q stops the app the way the Quit button does**, rather than interrupting it in the
  middle of writing a row.
- **The macOS app can reach the API at all.** Every call failed with "unable to get local
  issuer certificate": `ssl.create_default_context()` asks OpenSSL for the system roots, and a
  frozen build on macOS gets none, because macOS keeps its roots in a keychain rather than a
  file. The roots are now read from the keychain - both of them, so a company's TLS-inspecting
  proxy is trusted too. Verification is never turned off.
- **The macOS app starts at once.** It was packed as a single file, so every launch unpacked
  40 MB of interpreter into a temporary folder before the window appeared - about four seconds
  of an icon twitching in the Dock. Inside a bundle there is nothing to be portable about, so
  the files simply lie next to each other now. Windows and Linux stay a single file: that is
  the whole point of them.
- **macOS no longer asks to "find devices on your local network".** The server binds to
  `127.0.0.1` and never leaves it, but the standard library resolves the host name on bind
  (`socket.getfqdn`), and on macOS that goes out over mDNS - which is what macOS 15 was asking
  about. For a tool whose whole pitch is that the data stays on the machine, that dialog said
  the opposite of the truth. There is nothing to look up on the loopback interface, so it is
  not looked up.

### Changed

- **The disk image explains itself.** The app on the left, the Applications folder on the
  right, an arrow between them. A plain image is two icons in an empty window, and the first
  person to open one ran the app from the disk image instead of installing it - which is the
  one thing a disk image exists to prevent.
- **The macOS app keeps its folder in `~/Documents/Foxentry Data Cleaner`** (`config.env`,
  `input/`, `output/`, `logs/`). It cannot write inside the app bundle: that breaks the code
  signature, and in `/Applications` it has no right to. Windows and Linux are unchanged - the
  executable stays portable and keeps its folder next to itself.


## [2.0.0] - 2026-07-14

This release makes the tool country-aware. It also corrects how results are counted: every
figure is now derived from the API's own verdict rather than from the text of a translated
label, so the same data produces the same numbers in every interface language and in every view.

It is a major release because two things that already existed changed their meaning: a column
in the result file, and a configuration key. Neither change fails loudly, so both are listed
first.

### Breaking

- **`<group>_suggestion` now lists every candidate the API offered, separated by `|`.** It used
  to hold only the first one. A pipeline that reads this column as a single value will now
  receive `Praha 1|Praha 2|Praha 3` where it previously received `Praha 1`. To keep the old
  behaviour, split on `|` and take the first element. The reason for the change: an address
  with no house number can come back with a dozen equally plausible candidates, and showing
  only the first presented a guess as if it were the answer.
- **`DEFAULT_COUNTRY` no longer means "the fallback country"; it now forces one country onto
  every run.** It used to apply only when the *"Add default country"* setting was switched on,
  and defaulted to `CZ`. That setting is gone: the country now comes from the new wizard step,
  which detects it from the data. **Leave `DEFAULT_COUNTRY` empty** unless you deliberately
  want to override the detection for every file. A country column in the data still wins, row
  by row.

### Added

- **Country step in the wizard.** A new step asks which country the data comes from. The
  country is detected from the file itself (a country column, phone prefixes, postal-code
  shapes, company legal forms, e-mail domains) and pre-filled together with the reason for the
  guess. The step is skipped when it would change nothing: for services that take no country,
  for phone numbers that already carry their prefix, and for a group that maps its own country
  column.
- **Country in the query.** For services that accept one (addresses, companies), the country is
  sent as part of the query, so the API can verify it, correct a wrong one and return it in the
  requested `countryFormat`. `dataSource` is deliberately left at its default: it would
  *restrict* the search to a single country rather than validate the value. A group that maps
  its own country column keeps the value from the data, row by row.
- **Coverage warnings.** When a service has no data for the chosen country, the wizard says so
  before the run rather than returning "invalid" for every row and charging for it. Registers
  and reference data are told apart: a company that is not in the CZ/HU/PL/SK registers really
  will come back invalid, whereas a foreign name is still recognised by the name database, only
  less reliably.
- **`<group>_proposal` column** — the API's technical verdict, exactly as returned. It does not
  change with the interface language, so it is the column to filter, pivot and count on.
- **`<group>_country` column** — the country the API confirmed, written out when the file did
  not carry one. Filling it in is part of the correction.
- **`invalid (format fixed only)` result status** — a value Foxentry reformatted that is still
  not a real one. A phone number can end up correctly formatted and still not exist.
- `foxentry/countries.py` — generated reference data (service coverage from the Foxentry
  OpenAPI specification, E.164 calling codes, postal-code shapes, country names). Regenerate
  with `tools/update_countries.py`; nothing is fetched at runtime.
- **The interface starts in the language of the operating system.** A Czech Windows, macOS or
  Linux brings up a Czech interface; anything else brings up English. Picking a language in the
  wizard writes it to `config.env` and that choice wins from then on. `LANGUAGE=` (empty) means
  "follow the system"; existing configurations keep whatever they already say.
- **Tests.** `tests/` holds a regression test for every bug that shipped or nearly shipped:
  the settings dialog writing a value the user never chose, whole names being sent to the
  first-name field, a failed correction counted as a rescue, the house number sent as a nested
  object. CI runs them on every change.
- **CI now enforces the claims this repository makes:** every file names the same release
  (`tools/check_release.py`), `countries.py` is reproducible from the Foxentry OpenAPI
  specification (`tools/update_countries.py --check`), every query the tool builds is one the
  API actually declares (`tools/check_query_schema.py`), and every GitHub Action is pinned to
  an immutable commit SHA (`tools/check_action_pins.py`). The query check is stricter than
  schema validation, which cannot catch a stray field: the query schemas do not set
  `additionalProperties: false`, so an unknown key is legal as far as the schema is concerned.
- **The release workflow verifies the tag before it builds anything.** `check_release.py --tag`
  runs first, so a tag that disagrees with the version in the files stops the release instead
  of publishing a binary that misstates its own version.

### Security

- **Every GitHub Action is pinned to an immutable commit SHA**, with the version in a trailing
  comment. A tag is a label its owner can move; the release workflow holds the code-signing
  credentials, so a moved tag there would run someone else's code with our certificate. CI
  fails if any workflow reintroduces a mutable tag.

### Changed

- **The report counts overlapping facts, not exclusive buckets.** A value can be several things
  at once: a partial correction is *corrected* **and** *invalid*; a valid value can carry
  a *suggestion*. Forcing each result into a single bucket produced five different kinds of
  "invalid" (one per suggestion count, one for format-only fixes). There is now exactly one
  "invalid", corrections count wherever they happened, and suggestions are a measure of their
  own. The percentages therefore do not add up to 100 %, and the report says so.
- **Every count in the wizard, the HTML report and the CLI is computed in one place**
  (`report.flag_counts`), from the API's `proposal` code and from whether the value is valid
  after the correction. Nothing reads the words in a translated label any more.
- **`<group>_note` writes the errors out in full**: severity, the API's own codes and the fields
  they relate to (`critical [SYNTAX/VALUE_PART_MISSING/PREFIX] numberFull: Value is missing the
  prefix.`), worst first. The severity matters — a record can be invalid on an `info` error alone,
  such as letter case, which a user may well accept. Errors used to be reduced to their
  description, so an error that arrives without one (the phone service sends `FORMAT/INVALID`
  with `description: null`) produced an empty note. Identical errors repeated once per field
  combination are merged rather than filling the cell and truncating everything after them, and
  a value that was corrected but is still invalid now shows both the errors and the correction.
- **All suggestions are written out**, shortest form, separated by `|`. An address with no house
  number can come back with a dozen equally plausible candidates; the result file used to show
  only the first, as if it were the answer.
- The tax number is available for Hungary as well, not only Slovakia and Poland. The field now
  names the national identifier it means in each country — SK (DIČ), PL (NIP), HU (adószám) —
  and recognises those names as column headers.
- Every mapping option states what the format *is* before showing an example. Phone formats are
  named after the standards they are (E.164, E.123) rather than described as "with/without
  spaces": separators differ by country, and a UK number is written 020 7946 0958.
- `DEFAULT_COUNTRY` now defaults to empty (detect from the file). Set it only to force one
  country for every run.
- Internal identifiers and comments are English-only; Czech remains a translation.

### Removed

- The **"Add default country (when not mapped)"** option in the address and company settings.
  The country now comes from the wizard's country step, which detects it from the data, applies
  it to every service that takes one, and warns when a service does not cover it.

### Fixed

- **The country detection is no longer switched off by simply saving the settings.** The
  settings dialog pre-filled the country field with `CZ` and wrote it to `config.env` on save,
  and `DEFAULT_COUNTRY` overrides detection. Every new user saves the settings once, to enter
  the API key, so detection was disabled for everyone from their first run. The field now
  defaults to empty, which means "detect it from each file".
- **A single "Sedláček" no longer turns a column of people into companies.** Legal-form markers
  were matched as substrings, and " se" sits inside "Sedláček" while " as" sits inside "Aslan".
  One such value in ten was enough to send a whole column of customers to the company service.
  They are matched as whole words now (`a.s.` stays one word, so it still reads as a company).
- **The values override a misleading header, in both directions.** A column headed *Jméno* that
  holds `Alza.cz a.s.` is a company; a column headed *Firma* that holds people is not. What gets
  sent is the data, not the header.
- **A column of full names is recognised as a full name.** A column headed *Name* or *Jméno*
  holding `Jan Novák` was mapped to the *first name* field, which validates it as a first name
  and correctly reports that no such name exists. The values now decide: two or more words and
  no digits means a full name, whatever the header calls the column. Headers such as
  *Jméno a příjmení* and *Full name* map to it directly as well.
- **The house number is no longer silently dropped.** The query is flat: the field is named
  `number.full`, dot and all. It was being sent as a nested object (`{"number": {"full": "16"}}`),
  which the API ignores as an unknown key — and then reports the house number it never received
  as valid. A file with the street and the house number in separate columns was therefore
  validated as a street: `Dietmar-Hopp-Allee 16` came back `valid` as `Dietmar-Hopp-Allee, 69190
  Walldorf`, and an address the API could not place produced suggestions for house numbers it had
  never been given. The same applies to `number.part1`, `number.part2` and the rest. (The
  *response* does nest them under `data.number`; the query does not.)
- **An empty value in a mapped column is now sent, not omitted.** Within a record that carries
  data, a blank cell in a mapped column goes into the query as an empty value instead of being
  left out of it. The two are not the same to the API: an absent field was never asked about, an
  empty one is a missing value — a defect the API reports and can correct, so a blank ZIP or
  country now gets filled in. The same file therefore produces more corrections than it did in
  1.0.1. A record with no data at all in any of its mapped columns is still skipped entirely: no
  query, no credit.
- **Which variant of a `oneOf` query is used is decided per row**, from what the row actually
  holds, rather than from which columns were mapped: `{prefix, number}` vs `numberFull` for
  phones, `{name, surname}` vs `nameSurname` for names, structured fields vs `full` for
  addresses. Sending an empty `surname` alongside a filled `nameSurname` claimed a surname was
  missing when it was right there.
- **A correction that leaves the value invalid is no longer counted as valid.** Validity is
  decided by `resultCorrected.isValid`, not by the proposal code alone. The correction is still
  counted as a correction; the value is counted as invalid.
- **The report no longer counts words.** Results used to be grouped by looking for keywords in
  the translated label, so the Czech "neplatné (opraven jen formát)" contained "oprav" and was
  counted as *rescued*, while the English text was counted as *invalid* — the same data produced
  different figures depending on the interface language.
- **The wizard's final screen and the HTML report now agree.** The wizard counted its bars
  itself, from the translated labels, while the report counted them from the API codes; the two
  disagreed on the same run. The wizard now displays what the server counted.
- Settings were never pre-filled from the data: the presets were derived from the column mapping
  before anything had been mapped, so they silently fell back to their defaults. A UK file now
  gets spaced international numbers (E.123) and `+44` first, instead of unspaced E.164 and Czech
  prefixes.
- The schema was only re-fetched when the country was changed by hand, so a country that had
  been detected for the user still produced stale defaults.
- Postal codes and phone prefixes were Czech-only. Prefixes now cover every country and postal
  codes are matched against the country of the data, so `NW1 6XE` is recognised as a postal code.
- A plain-text column was offered as a company name first, so a city such as "London" was
  proposed as a company. Companies are matched on their legal form instead, and a column whose
  header already says it is an address ("Address line 1/2/3") is offered address fields in the
  usual order: street, city, postal code.
- Company coverage was missing Hungary in the backend while the interface already listed it;
  both now read the same source.
- A run written in one language and resumed in another counted its already-processed rows
  incorrectly, because the markers for "empty" and "error" were matched against the current
  language only.

## [1.0.1] - 2026-06-21

### Added

- Signed Windows release: the `.exe` is Authenticode-signed via Azure Trusted Signing (with an
  RFC 3161 timestamp).
- Release integrity: each binary ships with a per-file SHA-256 checksum and a Sigstore
  build-provenance attestation.

### Changed

- Relicensed from the custom source-available license to the Apache License 2.0.
- Added a NOTICE file and an explicit trademark/brand-asset carve-out.
- Added SPDX license headers to the source files.
- Cross-platform builds (Windows / macOS / Linux) are published from CI on tagged releases.
- Workflow tokens scoped to least privilege (read by default; write per job).

### Fixed

- The documentation no longer references a whole-repository checksum manifest; integrity is
  verified against the release artifacts.

## [1.0.0] - 2026-06-19

### Added

- Initial release: local CSV/XLSX validation and correction through the Foxentry API.
- Single-page wizard (file → columns → settings → order) with EN/CS localization.
- Content-driven column classifier with per-column service and field suggestions.
- HTML report with a per-result breakdown and an enrichment summary.

### Security

- Loopback-only server (`127.0.0.1`) with a Host header check and a per-session token.
- Request logging is off by default; configurable retention and manual purge.
- Self-hosted font; a single runtime network destination (`api.foxentry.com`).
- TLS with certificate verification; the API key is stored only in the local `config.env` and
  is masked in logs.

[Unreleased]: https://github.com/Foxentry/data-cleaner/compare/v2.1.0...HEAD
[2.1.0]: https://github.com/Foxentry/data-cleaner/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/Foxentry/data-cleaner/compare/v1.0.1...v2.0.0
[1.0.1]: https://github.com/Foxentry/data-cleaner/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/Foxentry/data-cleaner/releases/tag/v1.0.0
