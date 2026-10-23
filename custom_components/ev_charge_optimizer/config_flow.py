"""One config entry per independent site; vehicles are configured through options."""

from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import DOMAIN, NAME


def entity(domains=None):
    return (
        selector.EntitySelector(selector.EntitySelectorConfig(domain=domains))
        if domains
        else selector.EntitySelector()
    )


def site_schema(defaults=None):
    defaults = defaults or {}
    fields = {
        "name": (str, "Home"),
        "currency": (vol.Match(r"^[A-Z]{3}$"), "DKK"),
        "timezone": (str, "Europe/Copenhagen"),
        "price_entity": (entity(["sensor"]), None),
        "price_attribute": (str, "slots"),
        "price_multiplier": (vol.All(vol.Coerce(float), vol.Range(min=0.000001)), 1.0),
        "grid_kw": (vol.All(vol.Coerce(float), vol.Range(min=0.1, max=1000)), 17.94),
        "tolerance": (vol.All(vol.Coerce(float), vol.Range(min=0)), 0.005),
        "stale_minutes": (vol.All(vol.Coerce(int), vol.Range(min=1, max=1440)), 40),
        "margin_minutes": (vol.All(vol.Coerce(int), vol.Range(min=0, max=240)), 15),
        "boost_enabled": (bool, True),
        "boost_threshold": (vol.Coerce(float), 0.5),
        "boost_target": (vol.All(vol.Coerce(float), vol.Range(min=0, max=100)), 80),
    }
    return vol.Schema(
        {
            vol.Required(k, default=defaults.get(k, d))
            if defaults.get(k, d) is not None
            else vol.Required(k): validator
            for k, (validator, d) in fields.items()
        }
    )


def vehicle_schema(defaults=None):
    defaults = defaults or {}
    fields = {
        "name": str,
        "soc_entity": entity(["sensor"]),
        "target_entity": entity(["sensor", "number", "input_number"]),
        "connected_entity": entity(["binary_sensor", "input_boolean"]),
        "charging_entity": entity(),
        "power_entity": entity(["sensor"]),
        "capacity_kwh": vol.All(vol.Coerce(float), vol.Range(min=1, max=500)),
        "max_kw": vol.All(vol.Coerce(float), vol.Range(min=0.1, max=100)),
        "efficiency": vol.All(vol.Coerce(float), vol.Range(min=0.1, max=1)),
    }
    initial = {"capacity_kwh": 75, "max_kw": 11, "efficiency": 1.0}
    schema = {
        vol.Required(k, default=defaults.get(k, initial.get(k)))
        if k in defaults or k in initial
        else vol.Required(k): v
        for k, v in fields.items()
    }
    for k, validator in {
        "location_entity": entity(),
        "location_value": str,
        "deadline_entity": entity(["sensor"]),
        "odometer_entity": entity(["sensor"]),
    }.items():
        schema[vol.Optional(k, default=defaults[k]) if defaults.get(k) else vol.Optional(k)] = (
            validator
        )
    return vol.Schema(schema)


def timezone_errors(data):
    try:
        ZoneInfo(data["timezone"])
    except ZoneInfoNotFoundError, ValueError:
        return {"timezone": "invalid_timezone"}
    return {}


class OptimizerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = timezone_errors(user_input) if user_input else {}
        if user_input and not errors:
            return self.async_create_entry(
                title=f"{NAME}: {user_input['name']}", data={**user_input, "vehicles": []}
            )
        return self.async_show_form(
            step_id="user", data_schema=site_schema(user_input), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptimizerOptionsFlow()


class OptimizerOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        return self.async_show_menu(
            step_id="init", menu_options=["site", "add_vehicle", "edit_vehicle", "remove_vehicle"]
        )

    def _config(self):
        return {**self.config_entry.data, **self.config_entry.options}

    async def async_step_site(self, user_input=None):
        errors = timezone_errors(user_input) if user_input else {}
        if user_input and not errors:
            return self.async_create_entry(title="", data={**self._config(), **user_input})
        return self.async_show_form(
            step_id="site", data_schema=site_schema(user_input or self._config()), errors=errors
        )

    async def async_step_add_vehicle(self, user_input=None):
        errors = {}
        if user_input:
            if user_input.get("location_entity") and not user_input.get("location_value"):
                errors["base"] = "location_value_required"
            else:
                config = self._config()
                config["vehicles"] = [
                    *config.get("vehicles", []),
                    {**user_input, "key": uuid4().hex},
                ]
                return self.async_create_entry(title="", data=config)
        return self.async_show_form(
            step_id="add_vehicle", data_schema=vehicle_schema(user_input), errors=errors
        )

    async def _choose(self, step, user_input):
        if user_input:
            self._selected = user_input["vehicle"]
            return None
        choices = {v["key"]: v["name"] for v in self._config().get("vehicles", [])}
        if not choices:
            return self.async_abort(reason="no_vehicles")
        return self.async_show_form(
            step_id=step, data_schema=vol.Schema({vol.Required("vehicle"): vol.In(choices)})
        )

    async def async_step_edit_vehicle(self, user_input=None):
        choice = await self._choose("edit_vehicle", user_input)
        return choice if choice else await self.async_step_vehicle()

    async def async_step_vehicle(self, user_input=None):
        config = self._config()
        current = next(v for v in config["vehicles"] if v["key"] == self._selected)
        errors = {}
        if user_input:
            if user_input.get("location_entity") and not user_input.get("location_value"):
                errors["base"] = "location_value_required"
            else:
                config["vehicles"] = [
                    {**user_input, "key": v["key"]} if v["key"] == self._selected else v
                    for v in config["vehicles"]
                ]
                return self.async_create_entry(title="", data=config)
        return self.async_show_form(
            step_id="vehicle", data_schema=vehicle_schema(user_input or current), errors=errors
        )

    async def async_step_remove_vehicle(self, user_input=None):
        choice = await self._choose("remove_vehicle", user_input)
        if choice:
            return choice
        config = self._config()
        config["vehicles"] = [v for v in config["vehicles"] if v["key"] != self._selected]
        return self.async_create_entry(title="", data=config)
