# Functional parity and deviations

The Node-RED flow is authoritative for production. This preview is not an executor
replacement. `tests/test_reference.py` runs its committed JavaScript `calc` function
under Node.js with a fixed clock, synthetic HA snapshot and price cache. Five cases
compare selected starts, allocated kWh and plan validity: cheapest slot, tolerance
groups, below-5 safety, morning target and incomplete long-trip capacity. The native
forecast's exact interval end intentionally differs from the original whole-slot
`planEnd`. This is representative planner parity, not exhaustive executor parity.

| Behavior | Native status and evidence | Difference / impact |
| --- | --- | --- |
| 15-minute cheapest selection, equivalent-price groups | Implemented; deterministic tests and executable reference cases | Exact interval ends reflect energy actually required |
| SoC stages and long-trip margin | Implemented; reference cases and native deadline tests | Efficiency configurable; default 1.0 matches original arithmetic |
| Stable deadlines / restart | Stored rule state, reload and pure restart tests | Corrupt stored rules reset safely; expired anchors do not roll silently |
| Multiple vehicles/sites | Per-site coordinator and equal shares, power cap tests | Invalid connected vehicles retain a conservative share; boost-capable vehicles may reserve shares even at normal target |
| Unknown tomorrow prices | Known complete plans accepted; otherwise provisional | 07:00 forecast becomes unavailable if gaps could change its result; target is never substituted |
| Completion / 07:00 / next start | Calculated forecast model and real HA sensor tests | New API, not existing `planEnd` helper aliases |
| DST / midnight | UTC arithmetic and site-local civil cutoffs, spring/fall tests | Fixes implicit Node.js host-timezone dependence |
| Actual charging | Current observed power caps forecast; current interval charged before later slots | Conditional continuation through current interval; future follows proposal |
| Cheap Boost | Continuous current cheap-window simulation, strict threshold, feasibility/suppression state, external-change tests | No real target increase, retry or restore. Forecast remains explicitly conditional |
| External limit change during boost | Cancel simulation, hold off rest of cheap window | Original clears active/suppressed and can immediately reconsider; native intentionally preserves manual intent |
| Missing/stale inputs | Fail closed, per-input age checks, minute refresh | Stricter than baseline plan-age-only health; providers must report regularly |
| Price formats | Explicit timestamped slots / Nord Pool-style raw rows; unit multiplier | No recursive guessing, numeric daily arrays, name auto-discovery or stale-cache fallback; use templates for unsupported feeds |
| Vehicle adapters | Explicit UI entity mappings, exact optional location gating | No implicit vendor fallback or automatic site guessing |
| Priority | Original staged safety/deadline rules within each vehicle | No new cross-vehicle urgency optimization; equal reservations remain conservative |
| Cost / energy | Persisted measured AC energy and cost totals; trapezoid tests | Require both interval endpoints eligible; split cost at price boundaries; downtime not counted |
| Distance | Persisted explicit odometer total, km/mi, rebase/outlier tests | No name-based discovery; fixes baseline zero-odometer baseline truthiness issue |
| Daily/weekly/monthly/yearly summaries | HA utility meters documented | No duplicate period aggregation engine or helper creation |
| Watchdog and diagnosis | Input freshness, aggregate status/reason, diagnostics | No charging intervention, command-block CSV or operational authorization |
| Production Tesla actions | Intentionally absent; HA service-call spy test | Owner's Node-RED system must continue controlling charging |
| Helper/CSV output | Replaced by native entities/recorder | Existing helper consumers need an explicit migration; no automatic aliases |

## Safety observations in the original code

The original executor has an active-boost restore branch that can enqueue a charge
limit restore when leaving Production, before its later nonproduction guard. This
is a code-review finding, not a live-system test. The native preview avoids this
class of risk entirely by having no service-call or command path. The baseline
file and running system are unchanged.

Reference testing does not prove all price parser formats, operational executor
transitions, daily meter behavior or real vehicle timing are equivalent. Those
remain explicit production replacement gates.
