# Architecture and baseline review

## Product identity and decision

Keep **EV Charge Optimizer** as the recommended display name, repository
`NicolaiTandrup/HA-ev-charge-optimizer`, and unique integration domain
`ev_charge_optimizer`. Alternatives: **Charge Window** and **SiteCharge Planner**.
They are proposals only; no repository or integration identity is renamed.

Use a native HA custom integration with a dependency-free Python planner, explicit
HA entity adapters, one async coordinator per independent site, and a separately
owned future executor. Native HA gives config/options flows, entity registry,
state-change events, storage, diagnostics and normal dashboards on HA OS without
requiring Node-RED. The original flow remains useful as the authoritative live
controller and executable parity oracle. A Node-RED-first product would keep
production logic familiar but would still require external flow/helper setup and
would not itself be a HACS custom integration.

Current code uses supported HA 2026.10 APIs: config entries and `runtime_data`,
`async_forward_entry_setups`, `DataUpdateCoordinator`, coordinator-backed sensors,
entity selectors, `async_track_state_change_event`, `Store`, diagnostics, strings
and English translations. Python dependencies exist only in development; the
integration's `requirements` is empty. No architecture-specific binaries or
subprocesses are used by the deployed integration. Raspberry Pi compatibility
still needs an HA OS device trial.

## Complete baseline inventory

`node-red/EV-Charge-Optimizer-v1.2.json` contains 50 nodes. Its byte contents are
preserved. This review covers all function nodes and their surrounding routing,
timers, HA service outputs, CSV output and diagnostic paths.

| Component | Original nodes and behavior | Native boundary |
| --- | --- | --- |
| Snapshot | `pollbuild`, `readstate`, `pollwait`, `aggregate`: dynamic entity polling; cycle IDs; 5-second timeout; broker-first with raw Tesla fallback | Coordinator reads mapped HA states; missing/stale inputs remain unavailable |
| Scheduler | `inj30`, `injnow`: every 30 minutes/manual; price discovery precedes calculation | One-minute watchdog refresh and mapped state-change events |
| Planner | `calc`: two hard-coded vehicles/sites, site/location matching, capacities, staged rules, anchored deadlines, selected slots, costs and helper summaries | `planner.py`: pure inputs/outputs; arbitrary vehicles per site; stored rule anchors |
| Price discovery | `price_discover`: rank `real_energy` entity names/friendly names, parse attributes, retain cached data if unavailable | Explicit user-selected sensor and attribute; no heuristic discovery |
| Price feed | `price_link_in`, `price_adapter`: recursively normalize timestamped objects, numeric daily arrays, aliases and maps; select longest result, cache by source | `adapters.py`: strict timestamped rows and explicit unit multiplier; Nord Pool attribute support |
| Executor | `executor`, `executor_tick`: minute check; live broker state; Production gate; selected-window authorization; direct Tesla Fleet start/stop/limit service outputs | **Absent**. Forecast proposals do not contain executable HA actions |
| Cheap Boost | Executor's separate state machine: default enabled, strict price `<0.50 DKK/kWh`, temporary 80% target, contiguous cheap window, feasibility test, suppression, external limit protection, restore/retry | Stateful **simulation** only; no actual limits are changed |
| Watchdog | `watchdog_tick`: five-minute executor checks, 40-minute maximum plan age (30+10); blocks/records unhealthy scheduled starts | One-minute input age recheck; unavailable forecast sensors and reason attributes |
| Cost history | `cost_tick`, `cost_accum`: minute sampling, known site/cable/charging/price checks, W/kW heuristic, trapezoid AC energy and cost, ignore gaps over 3 minutes, helper totals | `history.py`: explicit units, interval price splitting, no post-restart extrapolation, HA total sensors |
| Distance history | `odometer_tick`, `odometer_accum`: five-minute manual/explicit/name discovery, miles conversion, baseline/rebase, reject >5000 km, cumulative total | Optional explicit odometer mapping, same baseline/rebase/outlier rules, persisted total; HA utility meters supply periods |
| Event updates | Broker-only event trigger, 2-second debounce, tolerance and Cheap Boost config triggers | All configured sources trigger coordinator refresh; HA coalesces refresh requests |
| Presentation | Helper action router to input_number/text/datetime/boolean services; CSV rows to `/share/ev_charge_optimizer.csv`; debug outputs | Standard sensors, structured attributes, recorder, diagnostics; no helper writes or CSV files |
| Initialization | CSV header injection/exec, global HA server configuration, comments and link routing | HA owns config persistence; no shell/exec node is deployed |

## Planning rules reproduced

Normal planning uses AC power `min(vehicle maximum, site kW / contenders)`. Idle
shares are not redistributed, matching the original conservative strategy rather
than claiming an optimized shared-capacity solution. Site capacity is the charging
budget after other house loads; the original three-phase conversion is
`3 * 230 * amps / 1000` (26 A = 17.94 kW).

Allocation stages use cumulative required energy:

1. Below 5%: chronological charging to 5%, over a six-hour priced horizon.
2. Below 10%: reach 10% within four hours; after a below-5 stage, the clock starts
   at that stage's last selected **price-slot end**.
3. Below 50%: reach up to 50% by next site-local 07:00; a long-trip deadline minus
   the safety margin can make this earlier.
4. Above 50%: complete the final target by an anchored 24-hour deadline when
   already above 50%, otherwise 24 hours after the to-50 stage's last slot end.
   A target >=85% activates the long-trip rule: next 06:30 minus 15 minutes by
   default. An explicit offset-aware deadline sensor overrides the default anchor.

A target below a stage ceiling caps that stage's demand. Negative prices are
supported. Price ordering repeatedly groups slots up to `remaining minimum +
tolerance` (default 0.005 DKK/kWh), then picks earliest first. It deliberately avoids
a non-transitive approximate-equality comparator. Past intervals are discarded;
current intervals start at the calculation instant. A known complete plan remains
valid without tomorrow's prices. Partial known capacity gives a provisional plan.

`RuleState` persists band/deadline and Cheap Boost state via HA storage. Default
anchors do not slide on every calculation or restart. Explicit externally supplied
deadlines are read on each update. An expired deadline stays expired until the rule
band or mapped deadline changes; restarting does not silently erase a missed rule.

## Forecast and adapter boundaries

`plan_site` returns `Forecast` values containing separate AC power/time allocations,
exact target completion and a calculated 07:00 battery level. `sensor.py` publishes
them. `coordinator.py` is the only HA state reader. Measured history is independent
of planned energy and uses actual charging power, never scheduled energy.

Vehicle adapters are entity mappings, so Tesla Fleet, another vendor, a charger
broker or templates can supply the same contract. Location gating is exact, with
no silent fallback to a different site's prices. Price adapters consume explicit
currency/kWh rows; hourly rows split into four equal-price quarters. Current Nord
Pool entities without forecast attributes require a template or other local
provider that publishes fetched timestamped price rows; there is no hidden Nord
Pool network call or dependency.

Future executor work must consume versioned planner output and independently check
live state, freshness, site membership, capabilities and manual authority. Do not
add command execution to the calculation module or have Honeycomb infer forecasts.
