# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Changed
- Relicensed from the custom source-available license to Apache License 2.0.
- Added NOTICE and an explicit trademark/brand-asset carve-out.
- Added SPDX license headers to source files.

## [1.0.0] - 2026-06-19

### Added
- Initial release: local CSV/XLSX validation and correction via the Foxentry API.
- Single-page wizard (file → columns → settings → order) with EN/CS localization.
- Content-driven column classifier and per-column service/field suggestions.
- HTML report with per-result breakdown and enrichment summary.

### Security
- Loopback-only server (`127.0.0.1`) with a Host header check and a per-session token.
- Request logging is off by default; configurable retention and manual purge.
- Self-hosted font; a single runtime network destination (`api.foxentry.com`).
- TLS with certificate verification; the API key is stored only in the local
  `config.env` and is masked in logs.
