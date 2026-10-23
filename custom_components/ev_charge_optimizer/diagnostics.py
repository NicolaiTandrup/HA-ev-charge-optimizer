"""Diagnostics omit entity IDs, site/vehicle names, and location mappings."""

from dataclasses import asdict

from homeassistant.components.diagnostics import async_redact_data


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data
    return {
        "mode": "log_only",
        "site_limits": {
            k: coordinator.config[k] for k in ("grid_kw", "tolerance", "stale_minutes")
        },
        "forecasts": [
            async_redact_data(asdict(f), {"allocations"}) for f in (coordinator.data or {}).values()
        ],
    }
