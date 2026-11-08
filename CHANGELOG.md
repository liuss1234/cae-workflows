# Changelog

All notable repository-level changes are recorded here. Releases follow Semantic Versioning and use `vMAJOR.MINOR.PATCH` tags.

## Unreleased

## v1.0.1 - 2026-11-07

### Changed

- Redact real oven geometry dimensions, component counts, topology statistics, enumerated boundaries and outlet tables from the public skill.
- Leave geometry-related template lengths and boundary lists unfilled; use independent synthetic fixtures for self-tests.
- Keep structure types, reusable methods and relative diagnostic conclusions; private engineering inputs and results remain unchanged.

## v1.0.0 - 2026-11-07

### Added

- Add software-specific Fluent, Pointwise, and Tecplot CAE skills based on publicly accessible CFD workflow topics, with source links and validation boundaries.
- Allow packaging selected workflow ZIPs without rebuilding unrelated packages.
- Oven supply-flow skill covering geometry decisions, STAR prism-layer evidence, QFlux/Slurm diagnostics and synchronized outlet statistics.
- A single workflow registry for documentation, validation, and packaging.
- Standard repository tests, lint configuration, contribution templates, and maintenance guidance.

### Changed

- Repository validation now covers Python 3.8 and 3.11 on Windows and Linux.
- The README is limited to discovery and first-use guidance; maintenance details live under `docs/`.
