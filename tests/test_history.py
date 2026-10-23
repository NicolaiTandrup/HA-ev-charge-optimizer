from datetime import timedelta

import pytest

from custom_components.ev_charge_optimizer.history import History

from .test_planner import NOW, slots


def test_energy_trapezoid_and_price_boundary():
    h = History()
    h.sample_power(NOW, 4, True, slots([1, 2]))
    h.sample_power(NOW + timedelta(minutes=1), 6, True, slots([1, 2]))
    assert h.energy_kwh == pytest.approx(5 / 60)
    h.sample_power(NOW + timedelta(minutes=14), 6, True, slots([1, 2]))  # gap discarded
    h.sample_power(NOW + timedelta(minutes=16), 6, True, slots([1, 2]))
    assert h.cost == pytest.approx(5 / 60 + 0.1 + 0.2)


def test_no_energy_invented_on_restart_disconnect_or_price_gap():
    h = History()
    h.sample_power(NOW, 10, True, [])
    h.sample_power(NOW + timedelta(minutes=1), 10, True, [])
    h.sample_power(NOW + timedelta(minutes=2), 10, False, slots([1]))
    h.sample_power(NOW + timedelta(minutes=3), 10, True, slots([1]))
    assert h.energy_kwh == 0
    restored = History(**h.persistent())
    restored.sample_power(NOW + timedelta(hours=1), 10, True, slots([1] * 8))
    assert restored.energy_kwh == 0


def test_odometer_rebase_source_units_and_outlier():
    h = History()
    h.sample_odometer("odo", 0, "km")
    h.sample_odometer("odo", 10, "km")
    assert h.distance_km == 10
    h.sample_odometer("odo", 1, "km")
    h.sample_odometer("odo", 5002, "km")
    assert h.distance_km == 10 and h.last_odometer_km == 1
    h.sample_odometer("miles", 100, "mi")
    h.sample_odometer("miles", 101, "mi")
    assert h.distance_km == pytest.approx(11.609344)
