# Security Policy

## Reporting a vulnerability

If you discover a security issue in Foxentry Data Cleaner, please report it privately.

- **Contact:** security@foxentry.com
- **Preferred content:** a description of the issue, affected version, reproduction
  steps, and impact. Please do not include real personal data in your report.
- **Please do not** open a public issue or disclose the vulnerability publicly until we
  have had a chance to investigate and respond.
- **First response:** we aim to acknowledge a report within **5 business days** and to
  agree on a remediation timeline based on severity.

## Supported versions

| Version | Supported          |
|---------|--------------------|
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

## Scope

Foxentry Data Cleaner is a **locally run desktop tool**. Its built-in web server binds
only to the loopback interface (`127.0.0.1`) and is not exposed to the network.

**In scope:** the application source code in this repository (server, processing,
classification, report, and UI), and the integrity of the bundled assets.

**Out of scope:** the remote Foxentry API service (report API issues separately to the
Foxentry team), third-party libraries (report upstream — see compliance/THIRD-PARTY-NOTICES.md),
and issues that require an already-compromised local machine or operating-system
account.

## Security model

The tool's security design (loopback-only server with a Host check and a per-session
token, request logging off by default with retention/manual purge, a single runtime
network destination, a self-hosted font, and TLS certificate verification) is described
in `docs/documentation.html`. Build integrity can be verified with `compliance/SHA256SUMS.txt`.
