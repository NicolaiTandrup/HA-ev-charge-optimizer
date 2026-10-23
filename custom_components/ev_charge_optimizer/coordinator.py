"""Entity snapshots, persistent rule anchors, and event driven recalculation."""

import logging
from dataclasses import asdict
from datetime import datetime, timedelta
from math import isfinite

from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .adapters import parse_prices
from .const import DOMAIN
from .history import History
from .planner import Forecast, RuleState, Vehicle, next_clock, plan_site

_LOGGER = logging.getLogger(__name__)
DATETIME_FIELDS = ("deadline", "boost_window_end", "boost_manual_window")


class OptimizerCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(
            hass, _LOGGER, name=DOMAIN, config_entry=entry, update_interval=timedelta(minutes=1)
        )
        self.entry = entry
        self.config = {**entry.data, **entry.options}
        self.rules = {}
        self.saved_rules = {}
        self.history = {}
        self.history_store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.history")
        self.store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.rules")

    async def async_load(self):
        history = await self.history_store.async_load() or {}
        for key, record in history.items():
            try:
                self.history[key] = History(**record)
            except ValueError, TypeError:
                _LOGGER.warning("Ignoring invalid stored history")
        saved = await self.store.async_load() or {}
        for key, record in saved.items():
            try:
                data = dict(record)
                for name in DATETIME_FIELDS:
                    data[name] = datetime.fromisoformat(data[name]) if data.get(name) else None
                self.rules[key] = RuleState(**data)
            except ValueError, TypeError:
                _LOGGER.warning("Ignoring invalid stored rule state")

    async def async_save(self):
        """Flush pending snapshots before reload can construct new Store objects."""
        await self.store.async_save(self.saved_rules)
        await self.history_store.async_save(
            {key: h.persistent() for key, h in self.history.items()}
        )

    @callback
    def async_listen(self):
        entities = {self.config["price_entity"]}
        for vehicle in self.config.get("vehicles", []):
            entities.update(
                value for key, value in vehicle.items() if key.endswith("_entity") and value
            )
        self.entry.async_on_unload(
            async_track_state_change_event(self.hass, entities, self._changed)
        )

    @callback
    def _changed(self, event):
        self.hass.async_create_task(self.async_request_refresh())

    def _state(self, entity_id, now):
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable", "none", ""):
            raise ValueError("Mapped entity missing or unavailable")
        # last_reported follows repeated identical reports; last_changed does not.
        age = (now - state.last_reported).total_seconds()
        if age < -60 or age > self.config.get("stale_minutes", 40) * 60:
            raise ValueError("Mapped entity stale")
        return state

    def _number(self, entity_id, now):
        value = float(self._state(entity_id, now).state)
        if not isfinite(value):
            raise ValueError("Nonfinite state")
        return value

    def _boolean(self, entity_id, now):
        value = self._state(entity_id, now).state.lower()
        if value not in (
            "on",
            "off",
            "charging",
            "stopped",
            "connected",
            "disconnected",
            "complete",
        ):
            raise ValueError("Unrecognized binary state")
        return value in ("on", "charging", "connected")

    async def _async_update_data(self):
        now = dt_util.utcnow()
        config = self.config
        timezone = config["timezone"]
        errors, vehicles = {}, []
        for mapping in config.get("vehicles", []):
            key = mapping["key"]
            try:
                connected = self._boolean(mapping["connected_entity"], now)
                if mapping.get("location_entity"):
                    connected = (
                        connected
                        and self._state(mapping["location_entity"], now).state
                        == mapping["location_value"]
                    )
                charging = self._boolean(mapping["charging_entity"], now)
                power = None
                if charging:
                    power_state = self._state(mapping["power_entity"], now)
                    power = self._number(mapping["power_entity"], now)
                    unit = power_state.attributes.get("unit_of_measurement")
                    if unit not in ("W", "kW"):
                        raise ValueError("Charging power requires W or kW")
                    power /= 1000 if unit == "W" else 1
                    if power <= 0:
                        raise ValueError("Active charging requires positive power")
                deadline = None
                if mapping.get("deadline_entity"):
                    deadline = datetime.fromisoformat(
                        self._state(mapping["deadline_entity"], now).state
                    )
                    if deadline.tzinfo is None:
                        raise ValueError("Deadline requires an offset-aware timestamp sensor")
                vehicles.append(
                    Vehicle(
                        key=key,
                        soc=self._number(mapping["soc_entity"], now),
                        target=self._number(mapping["target_entity"], now),
                        capacity_kwh=mapping["capacity_kwh"],
                        max_kw=mapping["max_kw"],
                        connected=connected,
                        charging=charging,
                        actual_kw=power,
                        efficiency=mapping.get("efficiency", 1),
                        deadline=deadline,
                    )
                )
            except (ValueError, TypeError, KeyError) as err:
                errors[key] = str(err)
                vehicles.append(Vehicle(key, 0, 100, 1, 1, fresh=False))
        price_error = None
        try:
            state = self._state(config["price_entity"], now)
            slots = parse_prices(
                dict(state.attributes), config["price_attribute"], config.get("price_multiplier", 1)
            )
        except (ValueError, TypeError, KeyError, OverflowError) as err:
            slots, price_error = [], str(err)
        result = plan_site(
            vehicles,
            slots,
            now,
            timezone=timezone,
            grid_kw=config["grid_kw"],
            states=self.rules,
            tolerance=config.get("tolerance", 0.005),
            margin_minutes=config.get("margin_minutes", 15),
            boost_enabled=config.get("boost_enabled", True),
            boost_threshold=config.get("boost_threshold", 0.5),
            boost_target=config.get("boost_target", 80),
        )
        for key, reason in errors.items():
            result[key] = Forecast(
                reason=reason, updated_at=now, forecast_cutoff=next_clock(now, timezone, 7)
            )
        if price_error:
            for forecast in result.values():
                if forecast.status != "no_charge_required":
                    forecast.reason = f"Price source unavailable: {price_error}"
        saved = {}
        for key, rule in self.rules.items():
            saved[key] = asdict(rule)
            for name in DATETIME_FIELDS:
                saved[key][name] = getattr(rule, name).isoformat() if getattr(rule, name) else None
        self.saved_rules = saved
        self.store.async_delay_save(lambda: saved, 1)
        by_key = {v.key: v for v in vehicles}
        for mapping in config.get("vehicles", []):
            key = mapping["key"]
            vehicle = by_key[key]
            history = self.history.setdefault(key, History())
            history.sample_power(
                now,
                vehicle.actual_kw or 0,
                vehicle.fresh and vehicle.connected and vehicle.charging,
                slots,
            )
            if mapping.get("odometer_entity"):
                try:
                    reading = self._state(mapping["odometer_entity"], now)
                    history.sample_odometer(
                        mapping["odometer_entity"],
                        self._number(mapping["odometer_entity"], now),
                        reading.attributes.get("unit_of_measurement"),
                    )
                except ValueError, TypeError:
                    pass
        history_saved = {key: h.persistent() for key, h in self.history.items()}
        self.history_store.async_delay_save(lambda: history_saved, 1)
        return result
