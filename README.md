# Foxentry Data Cleaner

[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/Foxentry/data-cleaner/badge)](https://scorecard.dev/viewer/?uri=github.com/Foxentry/data-cleaner)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
<!-- After registering the project at https://www.bestpractices.dev, add its badge here:
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/<ID>/badge)](https://www.bestpractices.dev/projects/<ID>) -->

A local application that validates and corrects data (emails, phones, names, addresses,
companies) from your CSV / Excel files via the [Foxentry API](https://foxentry.dev).
It runs as a small **wizard in your browser**, served by a local Python process — similar to
the Foxentry web app. **Your data stays with you** (input/output files never leave the machine;
request logs are off by default); only individual fields are sent over HTTPS for validation,
nothing else.

> 🇨🇿 Czech guide: open `docs/documentation.html` and switch to **CS**. The whole app can run in
> Czech (language switch in the wizard header).

## Quick start

There are two ways to run the tool. For locked-down / corporate workstations use **A**;
auditors and developers can always use **B**. Both work on **Windows, macOS and Linux**.

### A. Standalone app (Windows / macOS / Linux) — no Python, no pip

1. Download the build for your operating system from the project **Releases**:
   - **Windows** → `FoxentryDataCleaner.exe`
   - **macOS** → `FoxentryDataCleaner-macos`
   - **Linux** → `FoxentryDataCleaner-linux`
2. (Optional but recommended) verify it before running:
   - **Signature** — *Windows:* right-click → *Properties* → *Digital Signatures* (issuer:
     AVANTRO s.r.o.), or `signtool verify /pa FoxentryDataCleaner.exe`. *macOS:* the build is
     codesigned + notarized, so Gatekeeper verifies it automatically. *Linux:* unsigned by
     convention — use the checksum/provenance below.
   - **Checksum:** each release binary ships with a `.sha256` file — `Get-FileHash <file> -Algorithm SHA256`
     on Windows, `sha256sum <file>` on macOS/Linux.
   - **Provenance (all OSes):** `gh attestation verify <file> -R Foxentry/data-cleaner`.
3. Run it. A small console prints the local URL and the wizard opens in your browser.
   `config.env`, `input/`, `output/`, `logs/` are created **next to the binary** (portable) — keep
   it in a user-writable folder, not in a read-only location (e.g. `Program Files`).
4. **API key:** on first run open Settings (gear ⚙), paste your key, **Save**. Excel/XLSX works
   out of the box (openpyxl is bundled — no pip).

> The standalone build removes the main corporate friction (no Python install, no launcher script,
> and — on Windows — an Authenticode signature SmartScreen recognises; on macOS, Apple
> notarization). The security model is unchanged: loopback-only, session token, TLS on, request
> logging off by default.

### B. Run from source (any OS, audit-friendly)

1. **Install Python 3.9+** (from [python.org](https://www.python.org/downloads/);
   on Windows tick *Add Python to PATH*).
2. **Run it:**
   - **Windows:** double-click `START.bat`
   - **macOS:** double-click `START.command`
   - **Linux:** `./START.sh` (or `python3 run.py`)

   The wizard opens in your browser.
3. **API key:** on first run the Settings panel opens (gear icon ⚙). Paste your key and click
   **Save** — it is written to `config.env` next to the app. Get the key at
   [app.foxentry.com](https://app.foxentry.com).
4. **(Optional) Excel support:** `pip install -r requirements.txt`. Without it everything works
   via CSV. (openpyxl is also pre-bundled in `vendor/`.)

## How the wizard works

1. **File** — pick a file from `input/` or drag & drop a CSV/XLSX to upload it.
2. **Mapping** — for each column choose a service (Address, Company, Email, Phone, Name) and a
   field. **Groups matter:** several columns can form ONE record — e.g. street + city + ZIP =
   one address = one validation. Two addresses per row → group 1 and group 2.
3. **Settings** — per-service options (auto-correct, accept post office as city, format number,
   strict/smart name validation, …). These map to Foxentry API options.
4. **Run** — see a credit & time estimate, confirm, watch progress, open the results.

Results land in `output/` (`*_result.csv`, `*_result.xlsx`, `*_report.html`). The run can be
stopped anytime and **resumes** where it left off.

### Text mode

`python run.py --cli` runs a no-browser text mode that detects the validation type from the file
name. Put a CSV or Excel file with your contact data into the `input/` folder and run it.

## Language

Default is **English**. Switch in the wizard header (EN / CS) or the Settings panel; the choice is
saved to `config.env` (`LANGUAGE=en|cs`). More languages = a small change in `foxentry/i18n.py`.

## Security & documents

- `docs/documentation.html` — user guide (EN/CS): data-flow diagram, mapping/groups explainer,
  plus the privacy/security & technical overview for corporate/bank reviews (tech stack,
  dependencies/SBOM, GDPR, security controls, audit steps, guarantees, vendor questionnaire).
  Open it in the app via the **Manual** button (route `/manual`).
- `docs/setup-guide.html` — how to get a Foxentry API key (route `/setup`).
- `compliance/` — audit pack (`SECURITY.md`, SBOM, third-party notices, hashed dependency pins).
  See [Structure](#structure) below.

Network: the only outbound connection is HTTPS to `api.foxentry.com`. The wizard UI is served on
`127.0.0.1` (loopback only — not reachable from the network). No telemetry. Networking uses the
Python standard library only (TLS verification on); the sole optional dependency is `openpyxl`.
`config.env`, `input/`, `output/` are git-ignored.

## Structure

The folder is grouped so a non-technical user sees only what they need to run it, while developers
and auditors keep a clear, conventional layout.

```
data-cleaner/
├─ README.md                what this is
├─ LICENSE                  Apache-2.0
├─ NOTICE                   Apache-2.0 attribution notices
├─ CHANGELOG.md             version history
├─ START.bat / .command / .sh   launchers (Windows / macOS / Linux) — double-click
├─ run.py                   entry point (wizard; --cli for text mode)
├─ config.example.env       config template → copy to config.env
├─ requirements.txt         optional: openpyxl==3.1.5 (pre-bundled in vendor/)
│
├─ input/                   ← put your data files here
├─ output/                  ← results + report land here
│
├─ foxentry/                source code (readable, commented)
│   ├─ server.py            local wizard server (stdlib http.server)
│   ├─ wizard.html          the wizard UI (served locally)
│   ├─ assets/              fonts, icons, icon.ico / icon.icns
│   └─ …                    config.py, mapping.py, i18n.py, processor.py, …
│
├─ docs/                    HTML guides (also served by the app)
│   ├─ documentation.html   user + reviewer manual (EN/CS)
│   ├─ setup-guide.html     getting an API key
│   └─ log-viewer.html      request-log viewer (served at /logs)
│
├─ compliance/              audit pack (for reviewers)
│   ├─ SECURITY.md  THIRD-PARTY-NOTICES.md  VENDOR-SECURITY.md
│   ├─ sbom.cdx.json (CycloneDX SBOM)
│   └─ requirements-locked.txt  hashed dependency pins
│
├─ packaging/               single-exe build inputs (PyInstaller)
│   ├─ foxentry.spec        build recipe
│   └─ version.txt          Windows version resource
│
├─ .github/                 SECURITY.md (GitHub policy) + workflows (release, scorecard)
├─ vendor/                  bundled openpyxl (offline Excel support)
└─ logs/                    request logs (off by default)
```

> End users normally get the **single standalone binary** for their OS (one file, nothing to sort)
> — this folder layout is the "run from source" / audit view.

## Debug / logs

Request logging is **off by default** — nothing is written to disk. You enable it for a specific
run on the last step (Order/summary). Once enabled, the **full request and response** are stored in
`logs/requests-*.jsonl` and `.csv` (the API key in headers is masked) — view them at `/logs`. To
keep it always on: `LOG_REQUESTS=on`; retention via `LOG_RETENTION_DAYS` (default 7) plus clearing
from the log viewer. Requests are identified in the Foxentry log via the User-Agent
`FoxentryCleaner (Python/…; ApiReference/2.1)`; the default `Api-Version` is `2.1`.

## License

Foxentry Data Cleaner is open source under the Apache License 2.0 (see [LICENSE](LICENSE)). The
"Foxentry" name, logos, and brand assets in `foxentry/assets/` are trademarks of AVANTRO s.r.o.
and are NOT covered by the Apache License — all rights reserved. Bundled third-party components are
licensed separately (see [THIRD-PARTY-NOTICES.md](compliance/THIRD-PARTY-NOTICES.md)).

Compliance artifacts: [`SECURITY.md`](compliance/SECURITY.md), [`CHANGELOG.md`](CHANGELOG.md),
[`VENDOR-SECURITY.md`](compliance/VENDOR-SECURITY.md), [`sbom.cdx.json`](compliance/sbom.cdx.json)
(CycloneDX SBOM), and [`requirements-locked.txt`](compliance/requirements-locked.txt) (hashed
dependency pins).

## Distribution & integrity

The tool can be distributed two ways:

- **Source** (audit-friendly): plain, non-compiled Python (no binaries), pinned to a signed git
  tag; per-file hashes for the bundled libraries are in `vendor/*/RECORD`. Launchers are plain
  scripts; on Windows, **SmartScreen** may warn on unsigned scripts (expected).

- **Standalone binary** (one file, no Python): built with **PyInstaller**, one per OS, in CI
  (`.github/workflows/release.yml`, triggers on `v*` tags). PyInstaller does not cross-compile, so
  each binary is built on its own runner:

  * **Windows** (`windows-latest`) → `FoxentryDataCleaner.exe`, Authenticode-signed via Azure
    Trusted Signing; embeds the `.ico` icon + version resource.
  * **macOS** (`macos-latest`) → `FoxentryDataCleaner-macos`, codesigned and notarized with an
    Apple Developer ID; embeds the `.icns` icon.
  * **Linux** (`ubuntu-latest`) → `FoxentryDataCleaner-linux` (unsigned by convention).

  **Integrity of releases:** each binary is published with a per-file **SHA-256** checksum
  (`.sha256`) and a **Sigstore build-provenance attestation** (GitHub `attest-build-provenance`),
  verifiable with `gh attestation verify <file> -R Foxentry/data-cleaner`. Build locally with
  `pyinstaller packaging/foxentry.spec --clean`. Build inputs: `packaging/foxentry.spec`,
  `packaging/version.txt`, `foxentry/assets/icon.ico` (Windows) and `foxentry/assets/icon.icns`
  (macOS).

On launch the wizard opens in a chromeless **app window** (Chrome/Edge/Brave/Chromium via `--app`)
for a standalone-app feel, falling back to a normal browser tab. It still uses the system browser —
no bundled engine. Force a plain tab with `UI_APP_MODE=off`.

> Note: PyInstaller builds are not bit-for-bit reproducible; trust comes from the **signature +
> provenance attestation**, not from matching hashes across machines.
