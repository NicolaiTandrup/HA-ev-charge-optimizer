# Safety, permissions and release gates

## Enforced preview boundary

The native component contains no call to HA's service registry, vehicle network
API, subprocess, switch, charger command or charge-limit writer. It registers no
command services and offers no Production mode. Its UI changes only its own config
entry. HA state reads, own storage writes and sensor publication are its permissions.
A real HA test spies on the service registry and checks zero service calls during
setup/publication; additional tests exercise source changes and invalid inputs.

The original Node-RED flow is preserved byte-for-byte, including its executor.
Nothing in cloud setup connects to the owner's HA installation or running Node-RED
system. Read-only proposals may differ from production actions; dashboards must show
the conditional forecast basis. A hypothetical Cheap Boost target is not evidence
that a real vehicle's charge limit was raised.

## Failure handling and privacy

Missing, malformed, nonfinite, out-of-range, stale, away or disconnected inputs do
not yield fabricated charging estimates. Required active-power failures make the
forecast unavailable. Bad/missing prices give no target-completion claim unless no
charging is required. Provisional plans contain only known allocations. A one-minute
coordinator refresh checks age even if HA emits no new state event.

Diagnostics omit mapped entity IDs, site/vehicle names and exact locations. Sensor
attributes necessarily expose mapped source entities for local troubleshooting.
Diagnostics still contain timestamps, percentages and planning limits; review them
before sharing. No telemetry or outbound integration API calls are present.

## Remaining gates

This is an installable read-only developer preview, not a stable release or approved
HACS catalog integration. Before any prerelease announcement:

- Run the added GitHub CI, hassfest and HACS metadata validation; local Python tests
  do not establish those external results.
- Review forecast assumptions and the data contract with the owners of Honeycomb
  issue #126 and Charger Brain issue #1. Consumers should select existing sensors.
- Trial manual installation/configuration on HA OS/Raspberry Pi, including real
  provider reporting cadence and supported price attributes. No such device trial
  was performed in cloud.
- Broaden representative reference scenarios before asserting complete behavioral
  parity. Test all Cheap Boost transitions against the live-controller design in
  an isolated simulation; never by sending development commands to a real vehicle.

Before replacing the Node-RED executor, additionally implement and review a separate
capability-based executor with explicit owner opt-in; live target/cable/site/freshness
checks; manual override and temporary-limit restore ownership; watchdog behavior;
restart recovery; command idempotency/rate limiting and failure diagnostics. Validate
site power measurement, shared allocation and real losses. Plan a backed-up migration
of helper consumers/history and a tested rollback. Keep the original controller until
the owner approves that migration. No release, deployment or mode switch is performed
by this branch.
