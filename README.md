# EV Charge Optimizer

Native Home Assistant **read-only development preview**, with a pure Python charging
planner and actual forecast sensor calculations. The committed Node-RED v1.2 flow
remains the production controller. This integration cannot start/stop charging,
change charge limits, or deploy itself.

For each vehicle it calculates the expected completion instant, expected battery
level at the site's next 07:00, and next proposed charging start. These are
**conditional on following the proposed schedule**, not promises about what an
independent controller will do. Unknown estimates are unavailable, with a reason.
No dependency on Tesla, Node-RED, Honeycomb, or another custom integration is required.

Features include independent sites, multiple vehicles sharing available grid
capacity, 15-minute prices, deterministic price-tolerance groups, staged minimum
SoC rules, long-trip deadlines, Cheap Boost simulation, configurable efficiency,
source freshness protection, persistent rule anchors, and measured energy/cost
and optional driven-distance history.

- [Architecture and full baseline review](docs/architecture.md)
- [Behavioral parity and intentional differences](docs/parity.md)
- [Installation, UI configuration, synthetic examples and rollback](docs/configuration.md)
- [Forecast API and dashboard contract](docs/forecast-api.md)
- [Safety model and remaining release gates](docs/safety.md)

## Development

Tested with Home Assistant **2026.10.2**, Python **3.14.8**, and Node.js 24.

```sh
uv venv --python 3.14.8
uv pip sync --require-hashes requirements-dev.lock
.venv/bin/ruff check custom_components tests
.venv/bin/ruff format --check custom_components tests
.venv/bin/python -m pytest
```

Node.js is required for the parity tests that execute the original JavaScript.
For this Codex cloud workspace, `bash scripts/setup-cloud.sh` installs the pinned
runtime/dependencies outside the checkout and runs checks. No service or credentials
are needed for the isolated Home Assistant tests. Do not create another worktree
unless explicitly requested; cloud tasks are already isolated.

The repository includes HACS metadata and CI workflows. It has **not** been accepted
into the HACS default catalog or validated on a physical Raspberry Pi/HA OS system.
No release is published. Treat this as an installable developer preview pending the
gates documented in [safety.md](docs/safety.md).
