# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| latest commit on `main` | yes |

This is a local, single-user application with no release cadence yet, so the
supported version is the latest commit on the default branch.

## Reporting a vulnerability

**Please do not open a public GitHub issue for a security problem.**

Report privately through GitHub's built-in channel:

1. Go to the repository on GitHub
2. Open the **Security** tab
3. Click **Report a vulnerability** (GitHub Private Vulnerability Reporting)

Reports go directly to the maintainer without public disclosure.

## What to include

- Type of issue (e.g. path traversal, command injection via FFmpeg args,
  SSRF in stock-media fetch, dependency vulnerability)
- The commit hash and OS you tested on
- Step-by-step reproduction (the request, payload, or user input involved)
- Impact: what an attacker could achieve
- FFmpeg version, if the issue involves the render/export pipeline
- Suggested fix, if you have one

You will get an acknowledgment that the report was received. Please allow
reasonable time for investigation before any public disclosure; we will
coordinate with you on it.

## Scope notes

- The app is designed to run on `localhost` only; reports assuming it is
  deployed as a public multi-user service should say so explicitly.
- Vulnerabilities in third-party services (everyayah.com, QUL, QDC, Pexels,
  Pixabay, api.alquran.cloud) belong to those services, not this repository —
  but please still report any way this project could misuse them.
