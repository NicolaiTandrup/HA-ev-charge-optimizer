# Validation record

Validated in the cloud workspace on 2026-10-23 with CPython 3.14.8, Home Assistant
2026.10.2, pytest-homeassistant-custom-component 0.13.373, Ruff 0.17.2 and Node.js
24.19.0. Runtime dependencies are development-only, pinned with artifact hashes in
`requirements-dev.lock`.

- `bash scripts/setup-cloud.sh`: repeated successfully; 153 dependencies checked
  against the hashed lock; lint/format checks passed; **45 tests passed**.
- `python -m pytest --cov=custom_components.ev_charge_optimizer
  --cov-report=term-missing --cov-fail-under=90`: **45 passed**, **94.91%** statement
  coverage (609 statements, 31 uncovered). No skipped tests in this run.
- Five parameterized parity scenarios execute the untouched baseline JavaScript;
  native selected starts, AC kWh and complete/incomplete status match those cases.
- Real isolated HA tests load the integration and publish sensors, exercise config
  and options flows, source-change events, stale/missing state, active power units,
  manual charge-limit changes, Cheap Boost without service calls, and reload of
  rule anchors and measured distance.
- Pure tests cover price groups, exact partial completion, cross-midnight/Danish
  spring and autumn DST, 07:00 projections, missing prices, power shares/caps,
  minimum SoC, long-trip deadlines, efficiency, disjoint/past intervals, invalid
  inputs/configuration, Cheap Boost suppression and accounting boundaries.
- The tracked baseline has no diff; all changes are new native integration,
  documentation, development configuration and test files.

GitHub CI, hassfest and HACS action workflows are supplied but **not executed** by
this local validation. Physical HA OS/Raspberry Pi installation, real vehicle
integration behavior and cross-project acceptance are **not validated**. No stable
or prerelease publication or production deployment occurred.

Git read access to the repository was verified. Requests to `api.github.com` were
blocked at the network proxy (CONNECT 403); adding that hostname is saved in the
environment configuration draft. An API authentication/authorization conclusion
cannot be made from the network denial. Recheck after applying the network change.
