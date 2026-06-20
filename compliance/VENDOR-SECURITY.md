# Vendor Security Questionnaire — Foxentry Data Cleaner

Pre-filled answers for supplier/security reviews. Version 1.0.0.

### Hosting & architecture
Locally run desktop tool. It starts a small web server bound **only** to `127.0.0.1`
(loopback); it is never exposed to the network. There is no Foxentry-operated server
component for this tool — it runs entirely on the customer's machine.

### Data flow
- **What leaves the machine:** only the column values the user explicitly maps and that
  are actually filled in a row (e.g. an email, a phone number, an address). Unmapped
  columns are never sent.
- **To whom:** the Foxentry API (`https://api.foxentry.com`), which acts as the data
  processor for validation/correction.
- **Where data is stored:** locally — inputs under `input/`, results under `output/`.
  Request logging is **off by default**; when enabled, logs stay local with configurable
  retention and a manual purge.
- **Retention/deletion:** controlled by the customer on their own filesystem; the tool
  adds no external storage.

### Encryption in transit
TLS to the Foxentry API with certificate verification enabled. No plaintext transport.

### Secrets management
The API key is stored only in the local `config.env`. It is **masked** in any log output
and never transmitted anywhere except as the Bearer credential to the Foxentry API.

### Telemetry / analytics
None. The tool performs no analytics, tracking, or usage reporting.

### Network destinations (egress)
- **Runtime:** exactly one — `https://api.foxentry.com`.
- **Optional "Install Excel" button only:** `pypi.org` and `files.pythonhosted.org`,
  used solely if a user chooses to (re)install `openpyxl` via pip. `openpyxl` is already
  vendored, so this is a fallback and can be disabled (config `ALLOW_PIP_INSTALL=off`)
  for air-gapped deployments — after which runtime egress is strictly `api.foxentry.com`.

### Dependencies / SBOM
Two vendored PyPI components — `openpyxl` 3.1.5 (MIT) and `et_xmlfile` 2.0.0 (MIT) — plus
the Mulish font (OFL-1.1). Machine-readable SBOM: `sbom.cdx.json` (CycloneDX). Hashed
pins: `requirements-locked.txt`.

### Licensing
Application code is licensed under **Apache-2.0** (see `LICENSE`). The Foxentry name, logos, and brand assets are **trademarked** (all rights reserved) and are not covered by the Apache License — see `LICENSE`/`NOTICE`. Bundled components: openpyxl & et_xmlfile (MIT), Mulish font (OFL-1.1).

### Integrity
Release binaries are published with a per-file SHA-256 checksum (`.sha256`) and a Sigstore
build-provenance attestation (verify with `gh attestation verify`). The source is pinned to a
signed git tag; per-file hashes for the vendored libraries are in `vendor/*/RECORD`. The product
is plain, non-compiled Python — fully readable and auditable.

### Vulnerability disclosure
See `SECURITY.md` (contact, supported versions, scope).
