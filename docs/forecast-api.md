# Forecast API v1

Each vehicle has four forecast sensors, backed by one `Forecast` model. Honeycomb
and other clients **read these values**; they must not compute a substitute 07:00
forecast from the charge target. No client integration is mandatory.

For a site named `Home` and vehicle named `ElLingo`, HA normally creates:

| Suggested entity ID | Value | Client mapping |
| --- | --- | --- |
| `sensor.home_ellingo_expected_finish` | Offset-aware timestamp, or unavailable | Honeycomb Charger detail slot 4b |
| `sensor.home_ellingo_expected_soc_at_07_00` | Battery percent, or unavailable | Slot 5b |
| `sensor.home_ellingo_expected_next_start` | Offset-aware timestamp, or unavailable | Slot 6b |
| `sensor.home_ellingo_forecast` | `scheduled`, `charging`, `provisional`, `no_charge_required`, `unavailable` | Shared status, provenance and reason |

HA may disambiguate entity IDs; users can rename them. Clients should use entity
selectors, not hard-coded names. Registry unique IDs are
`<config_entry_id>_<persistent_vehicle_key>_<kind>`. Editing a vehicle preserves
its key. Removing/re-adding creates a new identity. Device identity uses the same
entry/key pair. A future Car module uses the identical three scalar sensors.

All sensors have `schema_version: 1`, `car` (opaque vehicle key), `mode: log_only`,
`forecast_basis: proposed_schedule`, `updated_at`, `forecast_cutoff`, `valid`,
`provisional`, `reason`, and mapped `input_entities`. The aggregate additionally
exposes all three results, effective target, planning power, selected intervals
with AC kWh/price/kind, stage deadlines/results, price entity and assumptions.

`valid` means all planning stages have enough known capacity before their deadlines.
A particular scalar is available only when its own value can be justified. A
complete plan may finish after 07:00 and still have unavailable morning SoC if
unpriced gaps precede the cutoff. A provisional partial plan can have a justified
morning projection if prices cover the full cutoff. Always check each sensor's
availability as well as the status and reason. `updated_at` is calculation time,
not proof of source freshness; source freshness is checked independently.

## Calculation semantics

- `forecast_cutoff` is the strictly next 07:00 in the configured IANA timezone.
  At exactly 07:00 it refers to tomorrow. UTC interval arithmetic handles Danish
  spring-forward and repeated autumn hours without assuming a 24-hour day.
- Completion is the instant accumulated selected battery energy reaches the
  effective target. The last partial interval ends at `AC_kWh / power_kW` hours,
  not at its original price boundary. No full energy allocation means no completion
  forecast. Missing earlier stage deadlines can make `valid` false even if an
  eventual completion instant is calculable.
- Morning SoC is `current_soc + selected_AC_energy_before_cutoff * efficiency /
  capacity_kWh * 100`, capped by the effective target. Only remaining time in current
  intervals counts; charging before `updated_at` is already represented by live SoC.
  Incomplete price coverage yields unknown unless the target is already reached
  before the cutoff. Missing inputs, disconnected/away state and stale data yield
  unavailable. No-demand returns the current SoC, never a lower configured target.
- Next start is the first selected proposed start at/after the calculation instant.
  If a selected interval is current but charging is not observed, this means start
  now. When charging is already active, next-start is unavailable and status is
  `charging`; clients should display “Charging now”, not invent a future timestamp.
  No demand, no plan and missing data also have no next-start; distinguish by status.
- Observed charging power must be valid W/kW and caps the vehicle's estimate.
  Existing charging is projected through the remaining current known price interval;
  later time follows the proposal. The read-only integration cannot ensure stops.
- Cheap Boost is simulated only for the current contiguous known sub-threshold
  window. It may propose an effective target above the live limit. Its forecasts
  assume that higher limit is authorized by a separate controller. No such change
  is made by this integration. Future unobserved boost activations are not assumed.
- Constant AC power, usable battery capacity, configured constant efficiency,
  no driving and no outside charging are assumptions. Site budget excludes house
  loads; equal shares never exceed it, but unused shares are not redistributed.

## Synthetic attributes

These illustrative values are not measurements or actual forecasts:

```yaml
schema_version: 1
car: "persistent-vehicle-key"
expected_finish: "2026-10-24T03:45:00+00:00"
expected_soc_at_0700: 85
expected_next_start: "2026-10-23T23:15:00+00:00"
forecast_cutoff: "2026-10-24T05:00:00+00:00"
updated_at: "2026-10-23T21:00:00+00:00"
valid: true
provisional: false
mode: log_only
forecast_basis: proposed_schedule
reason: Complete scheduled plan
```

UTC timestamps above correspond to the site's Copenhagen local timezone; HA formats
its timestamp sensors for the viewer. The integration calculates inside the optimizer;
Honeycomb only formats and displays the results.

This file is the proposed coordination contract for honeycomb-menu-ng issue #126
and HA-EV-Charger-Brain issue #1. It has not been posted to or agreed by those projects.
