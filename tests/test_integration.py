"""Exercise actual HA setup, entities, options, events, reload, and safety boundary."""

from datetime import timedelta
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_charge_optimizer.const import DOMAIN
from custom_components.ev_charge_optimizer.diagnostics import async_get_config_entry_diagnostics


def config():
    return {
        "name": "Test site",
        "timezone": "Europe/Copenhagen",
        "price_entity": "sensor.prices",
        "price_attribute": "slots",
        "grid_kw": 10,
        "tolerance": 0.005,
        "stale_minutes": 40,
        "boost_enabled": False,
        "vehicles": [
            {
                "key": "car1",
                "name": "Test car",
                "soc_entity": "sensor.car_soc",
                "target_entity": "number.car_target",
                "connected_entity": "binary_sensor.car_cable",
                "charging_entity": "sensor.car_charging",
                "power_entity": "sensor.car_power",
                "capacity_kwh": 100,
                "max_kw": 10,
                "efficiency": 1.0,
            }
        ],
    }


def states(hass):
    now = dt_util.utcnow()
    hass.states.async_set("sensor.car_soc", "60")
    hass.states.async_set("number.car_target", "61")
    hass.states.async_set("binary_sensor.car_cable", "on")
    hass.states.async_set("sensor.car_charging", "stopped")
    hass.states.async_set("sensor.car_power", "0", {"unit_of_measurement": "kW"})
    hass.states.async_set(
        "sensor.prices",
        "1",
        {
            "slots": [
                {
                    "start": now.isoformat(),
                    "end": (now + timedelta(minutes=15)).isoformat(),
                    "price": 1,
                }
            ]
        },
    )


async def setup(hass):
    states(hass)
    entry = MockConfigEntry(domain=DOMAIN, data=config(), title="Test site")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


async def test_setup_actual_forecast_entities_and_no_commands(hass):
    with patch("homeassistant.core.ServiceRegistry.async_call", new_callable=AsyncMock) as commands:
        entry = await setup(hass)
        sensors = hass.states.async_all("sensor")
        published = [s for s in sensors if s.entity_id.startswith("sensor.test_site_test_car")]
        assert len(published) == 6
        aggregate = next(s for s in published if s.entity_id.endswith("_forecast"))
        assert aggregate.state == "scheduled"
        assert aggregate.attributes["expected_soc_at_0700"] == 61
        assert aggregate.attributes["mode"] == "log_only"
        assert aggregate.attributes["forecast_basis"] == "proposed_schedule"
        assert aggregate.attributes["expected_finish"] is not None
        assert (
            next(s for s in published if "soc_at" in s.entity_id).attributes["unit_of_measurement"]
            == "%"
        )
        assert entry.runtime_data.rules["car1"].deadline is not None
        commands.assert_not_called()
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_entity_changes_replan_manual_limit_and_staleness(hass):
    entry = await setup(hass)
    hass.states.async_set("number.car_target", "60")
    await hass.async_block_till_done()
    # Request refresh explicitly too, to await coordinator debounce.
    await entry.runtime_data.async_refresh()
    assert entry.runtime_data.data["car1"].status == "no_charge_required"
    hass.states.async_set("sensor.car_soc", "unavailable")
    await entry.runtime_data.async_refresh()
    assert entry.runtime_data.data["car1"].expected_soc_at_0700 is None
    assert not entry.runtime_data.data["car1"].valid
    hass.states.async_set("sensor.car_soc", "60")
    with patch(
        "custom_components.ev_charge_optimizer.coordinator.dt_util.utcnow",
        return_value=dt_util.utcnow() + timedelta(hours=2),
    ):
        await entry.runtime_data.async_refresh()
        assert not entry.runtime_data.data["car1"].valid
    await hass.config_entries.async_unload(entry.entry_id)


async def test_restart_restores_anchor_and_diagnostics_redacts_names(hass):
    entry = await setup(hass)
    deadline = entry.runtime_data.rules["car1"].deadline
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.rules["car1"].deadline == deadline
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert "Test site" not in str(diagnostics) and "car_soc" not in str(diagnostics)
    await hass.config_entries.async_unload(entry.entry_id)


async def test_active_power_unit_failure_and_price_failure(hass):
    entry = await setup(hass)
    hass.states.async_set("sensor.car_charging", "charging")
    hass.states.async_set("sensor.car_power", "4000", {"unit_of_measurement": "W"})
    await entry.runtime_data.async_refresh()
    assert entry.runtime_data.data["car1"].power_kw == 4
    hass.states.async_set("sensor.car_power", "4000", {"unit_of_measurement": "bad"})
    await entry.runtime_data.async_refresh()
    assert not entry.runtime_data.data["car1"].valid
    hass.states.async_set("sensor.car_charging", "stopped")
    hass.states.async_set("sensor.prices", "unavailable")
    await entry.runtime_data.async_refresh()
    assert "Price source unavailable" in entry.runtime_data.data["car1"].reason
    await hass.config_entries.async_unload(entry.entry_id)


async def test_config_flow_timezone_and_add_edit_remove_vehicle(hass):
    data = {k: v for k, v in config().items() if k != "vehicles"}
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == FlowResultType.FORM
    invalid = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**data, "timezone": "invalid/zone"}
    )
    assert invalid["errors"] == {"timezone": "invalid_timezone"}
    with patch("custom_components.ev_charge_optimizer.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], data)
        assert result["type"] == FlowResultType.CREATE_ENTRY
        entry = result["result"]
        await hass.async_block_till_done()
    # Options run against a real config entry; configuration changes are saved by HA.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_vehicle"}
    )
    mapping = {k: v for k, v in config()["vehicles"][0].items() if k != "key"}
    result = await hass.config_entries.options.async_configure(result["flow_id"], mapping)
    assert result["type"] == FlowResultType.CREATE_ENTRY
    key = entry.options["vehicles"][0]["key"]
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "edit_vehicle"}
    )
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"vehicle": key})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**mapping, "max_kw": 7}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert (
        entry.options["vehicles"][0]["key"] == key and entry.options["vehicles"][0]["max_kw"] == 7
    )
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "remove_vehicle"}
    )
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"vehicle": key})
    assert result["type"] == FlowResultType.CREATE_ENTRY and entry.options["vehicles"] == []


async def test_cheap_boost_has_no_service_calls_and_history_survives_reload(hass):
    states(hass)
    now = dt_util.utcnow()
    hass.states.async_set("number.car_target", "60")
    # A single explicit two-hour interval is normalized to quarters.
    hass.states.async_set(
        "sensor.prices",
        ".4",
        {
            "slots": [
                {
                    "start": now.isoformat(),
                    "end": (now + timedelta(hours=2)).isoformat(),
                    "price": 0.4,
                }
            ]
        },
    )
    data = config()
    data["boost_enabled"] = True
    data["vehicles"][0]["odometer_entity"] = "sensor.car_odometer"
    hass.states.async_set("sensor.car_odometer", "100", {"unit_of_measurement": "km"})
    entry = MockConfigEntry(domain=DOMAIN, data=data, title="Boost site")
    entry.add_to_hass(hass)
    with patch("homeassistant.core.ServiceRegistry.async_call", new_callable=AsyncMock) as commands:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.runtime_data.data["car1"].effective_target == 80
        hass.states.async_set("sensor.car_odometer", "110", {"unit_of_measurement": "km"})
        await entry.runtime_data.async_refresh()
        assert entry.runtime_data.history["car1"].distance_km == 10
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.runtime_data.history["car1"].distance_km == 10
        hass.states.async_set("number.car_target", "65")
        await entry.runtime_data.async_refresh()
        assert entry.runtime_data.data["car1"].effective_target == 65
        commands.assert_not_called()
        await hass.config_entries.async_unload(entry.entry_id)


async def test_mapped_entity_event_requests_refresh(hass):
    entry = await setup(hass)
    with patch.object(
        entry.runtime_data, "async_request_refresh", new_callable=AsyncMock
    ) as refresh:
        hass.states.async_set("sensor.car_soc", "59")
        await hass.async_block_till_done()
        refresh.assert_awaited()
    await hass.config_entries.async_unload(entry.entry_id)
