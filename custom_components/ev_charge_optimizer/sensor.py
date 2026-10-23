"""Stable, vendor-neutral forecast interface shared by all dashboards."""

from dataclasses import asdict

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, NAME

KINDS = {
    "forecast": ("Forecast", None, None),
    "energy_kwh": ("Measured charging energy", SensorDeviceClass.ENERGY, "kWh"),
    "cost": ("Measured charging cost", SensorDeviceClass.MONETARY, "DKK"),
    "distance_km": ("Driven distance", SensorDeviceClass.DISTANCE, "km"),
    "expected_finish": ("Expected finish", SensorDeviceClass.TIMESTAMP, None),
    "expected_soc_at_0700": ("Expected SoC at 07:00", SensorDeviceClass.BATTERY, PERCENTAGE),
    "expected_next_start": ("Expected next start", SensorDeviceClass.TIMESTAMP, None),
}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(
        ForecastSensor(coordinator, vehicle, kind)
        for vehicle in coordinator.config.get("vehicles", [])
        for kind in KINDS
        if kind != "distance_km" or vehicle.get("odometer_entity")
    )


class ForecastSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator, vehicle, kind):
        super().__init__(coordinator)
        self.key, self.kind = vehicle["key"], kind
        self.mapping = vehicle
        name, device_class, unit = KINDS[kind]
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{self.key}_{kind}"
        self._attr_device_class, self._attr_native_unit_of_measurement = device_class, unit
        if kind in ("energy_kwh", "distance_km", "cost"):
            self._attr_state_class = (
                SensorStateClass.TOTAL if kind == "cost" else SensorStateClass.TOTAL_INCREASING
            )
            if kind == "cost":
                self._attr_native_unit_of_measurement = coordinator.config.get("currency", "DKK")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.entry.entry_id}_{self.key}")},
            name=f"{coordinator.config['name']} {vehicle['name']}",
            manufacturer=NAME,
            model="Read-only forecast",
        )

    @property
    def forecast(self):
        return (self.coordinator.data or {}).get(self.key)

    @property
    def available(self):
        f = self.forecast
        if not super().available or f is None:
            return False
        return (
            self.kind in ("forecast", "energy_kwh", "cost", "distance_km")
            or getattr(f, self.kind) is not None
        )

    @property
    def native_value(self):
        f = self.forecast
        if f is None:
            return None
        if self.kind in ("energy_kwh", "cost", "distance_km"):
            history = self.coordinator.history.get(self.key)
            return round(getattr(history, self.kind), 6) if history else None
        return f.status if self.kind == "forecast" else getattr(f, self.kind)

    @property
    def extra_state_attributes(self):
        f = self.forecast
        if f is None:
            return {}
        attrs = {
            "car": self.key,
            "valid": f.valid,
            "provisional": f.provisional,
            "reason": f.reason,
            "updated_at": f.updated_at.isoformat() if f.updated_at else None,
            "forecast_cutoff": f.forecast_cutoff.isoformat() if f.forecast_cutoff else None,
            "mode": "log_only",
            "forecast_basis": "proposed_schedule",
            "schema_version": 1,
            "input_entities": {k: v for k, v in self.mapping.items() if k.endswith("_entity")},
        }
        if self.kind == "forecast":
            attrs.update(
                {
                    key: getattr(f, key).isoformat() if getattr(f, key) else None
                    for key in ("expected_finish", "expected_next_start")
                }
            )
            attrs.update(
                expected_soc_at_0700=f.expected_soc_at_0700,
                effective_target=f.effective_target,
                power_kw=f.power_kw,
                assumptions=f.assumptions,
                stages=f.stages,
                price_source=self.coordinator.config["price_entity"],
                selected_slots=[
                    {
                        **asdict(a),
                        "start": a.start.isoformat(),
                        "end": a.end.isoformat(),
                        "kwh": round(a.kwh, 6),
                    }
                    for a in f.allocations
                ],
            )
        return attrs
