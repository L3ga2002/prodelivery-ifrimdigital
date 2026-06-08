# Changelog

## 2026-06-08

- Migrated ProDelivery into the IfrimDigital local projects workspace.
- Removed old external-builder artifacts from the active copy.
- Created local backend/frontend env files.
- Added local preview scripts:
  - `dev-start.ps1`
  - `dev-stop.ps1`
- Simplified backend requirements to a maintainable dependency set.
- Verified local backend, frontend build, and preview.
- Created IfrimDigital OpenClaw reviewer/implementation agent team.
- Added `ifrim-quality-reviewer` for scorecard-style static code quality review.
- Added project memory folder `.ifrim/`.
- Added central projects registry at `..\PROJECTS.md`.
- Prepared GitHub-safe baseline by removing hardcoded demo passwords from versionable README/tests/UI code, generating initial driver/restaurant passwords, and ignoring local upload artifacts.
