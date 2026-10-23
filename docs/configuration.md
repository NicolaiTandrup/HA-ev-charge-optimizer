# Installation, configuration and rollback

## Install manually for review

1. Back up Home Assistant. Leave the production Node-RED flow and its mode/settings
   unchanged. HA **2026.10.2 or later** is required by this preview's HACS metadata;
   this version is the tested target.
2. Copy only `custom_components/ev_charge_optimizer/` into your HA configuration's
   `custom_components/` directory. Do not copy the cloud virtual environment or
   install development requirements in HA OS.
3. Restart Home Assistant. Under **Settings → Devices & services → Add integration**,
   choose **EV Charge Optimizer** and add one site. This creates no commands or
   external account connections.
4. On the integration entry, choose **Configure → Add vehicle**. Repeat per vehicle.
   Use Configure to edit/remove vehicles or change site settings. Add another
   integration entry for an independent site.

HACS custom-repository installation is an intended distribution path after the
branch is reviewed/merged and metadata gates pass: add this repository as an
**Integration**, download it, and restart HA. HACS default-catalog acceptance and a
release tag are not established by the files in this branch. Manual installation
above is the current developer test path. Do not advertise this as stable.

## Site settings

- **Name**: human-facing site name.
- **Timezone**: IANA name such as `Europe/Copenhagen`; this determines 07:00 and
  long-trip deadlines independently of the browser/server timezone.
- **Price sensor / attribute**: a sensor exposing `slots`, or timestamped
  `raw_today`/`raw_tomorrow` arrays. Selecting `raw_today` combines both raw arrays.
  The sensor state itself must be available, even though prices come from attributes.
- **Price multiplier**: converts source prices to currency/kWh. Use 1 for DKK/kWh,
  0.001 for DKK/MWh, or 0.01 for øre/kWh. There is no currency conversion. Select
  the matching currency code (default `DKK`). Prefer all-in tariffs if desired;
  taxes and fees are not inferred.
- **Available charging kW**: site budget after other house demand. For a 3-phase
  26 A, 230 V supply the theoretical total is 17.94 kW. Set a smaller budget when
  house loads require it. This preview does not measure or actively balance loads.
- **Price tolerance**: default 0.005 currency/kWh (0.5 øre at DKK).
- **Maximum source age**: default 40 minutes, applies to all mapped inputs including
  prices. Reports of the same value refresh age via HA `last_reported`. Daily price
  sensors and rarely reported limit entities may need a larger bound or a source
  that reports regularly. Changing a stale limit is not required; configure a suitable
  reporting source/age bound. The integration does not poll a vehicle API itself.
- **Long-trip margin**: default 15 minutes before the selected deadline.
- **Cheap Boost**: simulate strict price below 0.50 currency/kWh and an 80% temporary
  target by default. **Disable simulation** if the real controller will not raise
  limits and follow Cheap Boost. These settings do not change actual vehicle limits.

## Vehicle settings

Map SoC (%), live charge limit (%), cable-connected binary state, charging state,
and measured AC charging power. Supported charging states: `on`, `off`, `charging`,
`stopped`, `connected`, `disconnected`, `complete`. For other vendor strings, supply
a template binary sensor. Power must carry an explicit `W` or `kW` unit. It is
required for a forecast when charging is observed, and for measured energy/cost.
Set usable battery kWh, maximum AC kW and AC-to-battery efficiency (default 1.0 for
baseline parity; enter a realistic measured value if known).

Optional **location entity/value** gates eligibility by an exact string comparison.
For vehicles that move between multiple sites, configure this mapping on each site
so a plugged-in vehicle is not planned at both sites. A missing configured location
is unavailable, not implicitly “home”. Each independently mapped vehicle has its own
persistent ID; edit rather than remove/re-add to retain identity and history.

An optional **deadline timestamp sensor** supplies an explicit offset-aware deadline.
Use an ISO timestamp with a timezone; a naive `input_datetime` is deliberately not
accepted, because its interpretation would be ambiguous around DST. Targets >=85%
apply the long-trip safety margin to that deadline.

An optional **odometer sensor** with `km` or `mi` enables the driven-distance entity.
A first reading or source change establishes a baseline; decreases rebase without
adding distance; >5000 km jumps are rejected. Distance and measured energy/cost totals
are per configured site/vehicle entry. Do not combine totals from duplicate mappings
without checking overlap.

## Synthetic local HA sources

The following template entities are examples only. Substitute real mapped sources
for actual use. They invoke no vehicle services.

```yaml
template:
  - sensor:
      - name: Demo EV SoC
        unit_of_measurement: "%"
        state: 60
      - name: Demo EV Target
        unit_of_measurement: "%"
        state: 61
      - name: Demo EV Charging
        state: stopped
      - name: Demo EV Power
        unit_of_measurement: kW
        state: 0
      - name: Demo EV Prices
        state: ready
        attributes:
          slots: >-
            {% set t = now().replace(second=0, microsecond=0) %}
            {{ [dict(start=t.isoformat(),
                     end=(t + timedelta(minutes=15)).isoformat(), price=1.0)] }}
    binary_sensor:
      - name: Demo EV Cable
        state: true
```

Configure a 100 kWh battery, 10 kW cap, 10 kW site budget, efficiency 1, and disable
Cheap Boost. From 60% to 61%, the proposed completion is six minutes after calculation;
07:00 SoC is 61%. The example does not charge anything. Its changing price timestamp
makes it suitable for a short demonstration, not a production price source.

## Recorder and period summaries

Forecast sensors are calculated; **Measured charging energy** and **Measured charging
cost** use observed charging power and known prices. Recorder supplies history.
Cost can decrease with negative prices and therefore uses `total`, while energy
and driven distance use `total_increasing`. They do not include unobserved downtime.
No historical helper values are imported automatically. For day/week/month/year
summaries, add HA Utility Meter helpers using the measured energy or driven-distance
sensor. Select each required cycle. Preserve your existing Node-RED utility meters
while comparing results; do not add the two controllers' totals together.

## Rollback

Remove the integration entry under Devices & services, then remove only
`custom_components/ev_charge_optimizer/` and restart HA if uninstalling completely.
HA registry/history/storage cleanup follows HA's normal integration lifecycle; keep
backups if you need measured totals. The integration never modifies production
Node-RED, helpers, charge limits, modes or vehicle settings, so no controller restore
command is needed. Continue using the original flow. Replacing it requires a separate
owner-approved production migration.
