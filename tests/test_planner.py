from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.ev_charge_optimizer.adapters import parse_prices
from custom_components.ev_charge_optimizer.planner import (
    PriceSlot,
    RuleState,
    Vehicle,
    next_clock,
    ordered_prices,
    plan_site,
)

NOW = datetime(2026, 10, 23, 20, tzinfo=UTC)
V = Vehicle("car", 60, 70, 100, 10)


def slots(prices, start=NOW):
    return [
        PriceSlot(start + timedelta(minutes=15 * i), start + timedelta(minutes=15 * (i + 1)), p)
        for i, p in enumerate(prices)
    ]


def plan(v=V, prices=None, **kwargs):
    return plan_site(
        [v],
        prices if prices is not None else slots([1] * 80),
        NOW,
        timezone="Europe/Copenhagen",
        grid_kw=10,
        boost_enabled=False,
        **kwargs,
    )[v.key]


def test_cheapest_and_exact_completion():
    f = plan(replace(V, target=61), slots([2, 1, 3]))
    assert f.expected_next_start == NOW + timedelta(minutes=15)
    assert f.expected_finish == NOW + timedelta(minutes=21)
    assert sum(a.kwh for a in f.allocations) == pytest.approx(1)
    assert f.valid


def test_price_groups_anchored_to_minimum():
    data = slots([1.008, 1.004, 1])
    assert [s.price for s in ordered_prices(data, 0.005)] == [1.004, 1, 1.008]
    assert plan(replace(V, target=61), slots([1.004, 1])).allocations[0].start == NOW


def test_cross_midnight_and_cutoff():
    f = plan()
    assert f.forecast_cutoff == datetime(2026, 10, 24, 5, tzinfo=UTC)
    assert f.expected_soc_at_0700 == 70


@pytest.mark.parametrize(
    ("date", "cutoff", "hours"),
    [
        (datetime(2026, 3, 28, 23, tzinfo=UTC), datetime(2026, 3, 29, 5, tzinfo=UTC), 6),
        (datetime(2026, 10, 24, 22, tzinfo=UTC), datetime(2026, 10, 25, 6, tzinfo=UTC), 8),
    ],
)
def test_danish_dst(date, cutoff, hours):
    assert next_clock(date, "Europe/Copenhagen", 7) == cutoff
    assert (cutoff - date).total_seconds() / 3600 == hours
    f = plan_site(
        [replace(V, soc=10, target=50)],
        slots([1] * 40, date),
        date,
        timezone="Europe/Copenhagen",
        grid_kw=10,
        boost_enabled=False,
    )["car"]
    assert f.forecast_cutoff == cutoff and f.expected_soc_at_0700 == 50


def test_exact_0700_means_next_day():
    assert next_clock(datetime(2026, 10, 24, 5, tzinfo=UTC), "Europe/Copenhagen", 7) == datetime(
        2026, 10, 25, 6, tzinfo=UTC
    )


def test_missing_prices_not_target_substitution():
    f = plan(prices=slots([1]))
    assert f.provisional and not f.valid
    assert f.expected_finish is None and f.expected_soc_at_0700 is None
    assert f.expected_next_start == NOW


def test_known_complete_plan_does_not_require_tomorrow_prices():
    f = plan(replace(V, target=61), slots([1]))
    assert f.valid and f.expected_soc_at_0700 == 61


def test_shared_site_power_cap_and_independent_sites():
    vehicles = [V, replace(V, key="b", max_kw=3)]
    forecasts = plan_site(
        vehicles,
        slots([1] * 80),
        NOW,
        timezone="Europe/Copenhagen",
        grid_kw=10,
        boost_enabled=False,
    )
    assert forecasts["car"].power_kw == 5
    assert forecasts["b"].power_kw == 3
    assert (
        max(
            sum(a.kw for f in forecasts.values() for a in f.allocations if a.start <= NOW < a.end),
            0,
        )
        <= 10
    )
    assert plan().power_kw == 10


def test_immediate_minimum_soc_then_price_order():
    f = plan(replace(V, soc=4, target=10, capacity_kwh=100), slots([9, 9, 1, 1, 1, 1]))
    assert f.allocations[0].start == NOW
    assert f.allocations[0].kwh >= 1
    assert [s["rule"] for s in f.stages] == ["immediate_to_5", "to_10_within_4h"]


def test_long_trip_margin():
    deadline = NOW + timedelta(hours=2)
    f = plan(replace(V, target=85, deadline=deadline), slots([1] * 20))
    assert not f.valid
    assert all(a.end <= deadline - timedelta(minutes=15) for a in f.allocations)
    assert f.stages[-1]["deadline"] == (deadline - timedelta(minutes=15)).isoformat()


def test_efficiency_and_partial_current_slot():
    prices = slots([1] * 5, NOW - timedelta(minutes=5))
    f = plan(replace(V, target=61, efficiency=0.8), prices)
    assert f.allocations[0].start == NOW
    assert f.expected_finish == NOW + timedelta(minutes=7.5)


def test_past_and_non_contiguous_intervals():
    prices = slots([0], NOW - timedelta(minutes=15)) + slots([9, 1, 9, 1])
    f = plan(replace(V, target=64), prices)
    assert [a.start for a in f.allocations] == [
        NOW + timedelta(minutes=15),
        NOW + timedelta(minutes=45),
    ]
    assert f.expected_finish == NOW + timedelta(minutes=54)


@pytest.mark.parametrize(
    "v",
    [
        replace(V, fresh=False),
        replace(V, connected=False),
        replace(V, soc=float("nan")),
        replace(V, charging=True),
    ],
)
def test_invalid_vehicle_unavailable(v):
    f = plan(v)
    assert f.expected_finish is None and f.expected_soc_at_0700 is None
    assert not f.valid


def test_no_demand():
    f = plan(replace(V, target=50))
    assert f.status == "no_charge_required" and f.expected_soc_at_0700 == 60
    assert f.expected_next_start is None and f.expected_finish is None


def test_actual_charging_power_and_start_status():
    f = plan(replace(V, charging=True, actual_kw=4))
    assert f.power_kw == 4 and f.status == "charging"
    assert f.expected_next_start is None


def test_anchors_survive_recalculation_and_restart():
    state = {}
    plan_site(
        [V],
        slots([1] * 120),
        NOW,
        timezone="Europe/Copenhagen",
        grid_kw=10,
        states=state,
        boost_enabled=False,
    )
    deadline = state["car"].deadline
    restored = {"car": RuleState(**vars(state["car"]))}
    later = NOW + timedelta(hours=1)
    plan_site(
        [V],
        slots([1] * 120),
        later,
        timezone="Europe/Copenhagen",
        grid_kw=10,
        states=restored,
        boost_enabled=False,
    )
    assert restored["car"].deadline == deadline


def test_cheap_boost_and_external_change():
    state = {}

    def run(v, prices, now=NOW):
        return plan_site([v], prices, now, timezone="Europe/Copenhagen", grid_kw=10, states=state)[
            "car"
        ]

    f = run(replace(V, soc=70, target=70), slots([0.4] * 8))
    assert f.effective_target == 80 and f.expected_finish == NOW + timedelta(hours=1)
    assert state["car"].boost_active
    changed = run(replace(V, soc=71, target=72), slots([0.4] * 8))
    assert changed.effective_target == 72 and not state["car"].boost_active
    run(V, slots([0.5] * 8))
    assert state["car"].boost_window_end is None


def test_boost_suppressed_for_whole_window():
    state = {}

    def run(v, now):
        return plan_site(
            [v], slots([0.4] * 4), now, timezone="Europe/Copenhagen", grid_kw=10, states=state
        )["car"]

    assert run(replace(V, soc=20, target=70), NOW).effective_target == 70
    assert state["car"].boost_suppressed
    assert run(replace(V, soc=70, target=70), NOW + timedelta(minutes=15)).effective_target == 70


def test_overlap_and_naive_prices_rejected():
    assert not plan(prices=slots([1]) + slots([2])).valid
    assert not plan(prices=[PriceSlot(NOW.replace(tzinfo=None), NOW, 1)]).valid


def test_nord_pool_hourly_normalization_and_units():
    data = {
        "raw_today": [
            {"start": NOW.isoformat(), "end": (NOW + timedelta(hours=1)).isoformat(), "value": 500}
        ],
        "raw_tomorrow": [],
    }
    parsed = parse_prices(data, "raw_today", 0.001)
    assert len(parsed) == 4 and all(s.price == 0.5 for s in parsed)
    with pytest.raises(ValueError):
        parse_prices({"slots": [1, 2, 3]})


def test_current_charging_takes_precedence_over_later_cheaper_interval():
    f = plan(replace(V, target=61, charging=True, actual_kw=4), slots([9, 1, 1]))
    assert f.allocations[0].start == NOW
    assert f.status == "charging" and f.expected_finish == NOW + timedelta(minutes=15)


def test_current_charging_without_current_price_is_unknown():
    f = plan(replace(V, charging=True, actual_kw=4), slots([1] * 20, NOW + timedelta(minutes=15)))
    assert f.expected_soc_at_0700 is None and not f.valid
    assert f.reason == "Active charging has no current price interval"


def test_full_cutoff_coverage_can_give_partial_soc_without_completion():
    v = replace(V, soc=10, target=80, max_kw=1)
    f = plan(v, slots([1] * 36))
    assert f.expected_finish is None and f.provisional
    assert f.expected_soc_at_0700 == 19


@pytest.mark.parametrize("tolerance", [float("nan"), float("inf"), -1])
def test_invalid_tolerance_fails_without_looping(tolerance):
    assert not plan(tolerance=tolerance).valid
