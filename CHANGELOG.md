# Changelog

All notable changes to CFD Sentinel are documented here.

## 0.1.0 - 2026-07-28

Initial public alpha release.

### Added

- Fluent journal preflight audit for initialization, periodic, and final saves.
- Safe hardened-copy generation without modifying the source journal.
- Configurable checkpoint intervals with 1000 iterations as the default.
- Paired `.cas.h5` and `.dat.h5` checkpoint generation and verification.
- Protection against interactive overwrite dialogs for generated checkpoints.
- Runtime process and existing-log monitoring.
- Fatal-marker and stalled-progress email alerts using environment-only SMTP
  credentials.
- English and Chinese documentation, examples, and Apache-2.0 licensing.
- Windows and Linux CI coverage on Python 3.9 and 3.12.

### Known limitations

- Automatic journal rewriting supports only explicit standalone Fluent
  initialization and iteration commands.
- Scheme-generated loops, GUI transcripts, and recovery initialization policies
  require manual review or a future adapter.
