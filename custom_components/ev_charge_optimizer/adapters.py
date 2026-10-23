"""Explicit timestamped HA price entity contract; no vendor discovery or API calls."""

from datetime import datetime, timedelta
from math import isfinite

from .planner import PriceSlot, utc, validate_slots


def parse_prices(
    attributes: dict, attribute: str = "slots", multiplier: float = 1.0
) -> list[PriceSlot]:
    """Normalize slots or Nord Pool raw_today/raw_tomorrow; reject ambiguity.

    Numeric day arrays are deliberately unsupported: they are ambiguous on DST days.
    Explicit hourly prices are expanded to 15-minute intervals, without interpolation.
    """
    rows = attributes.get(attribute)
    if attribute == "raw_today":
        rows = [*attributes.get("raw_today", []), *attributes.get("raw_tomorrow", [])]
    if not isinstance(rows, list) or not isfinite(multiplier) or multiplier <= 0:
        raise ValueError("Expected a timestamped price array and positive unit multiplier")
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Prices require explicit start/end timestamps")
        start, end = (utc(datetime.fromisoformat(str(row[k]))) for k in ("start", "end"))
        price = float(row.get("price", row.get("value"))) * multiplier
        if not isfinite(price) or end <= start or (end - start).total_seconds() % 900:
            raise ValueError("Price intervals must be finite multiples of 15 minutes")
        while start < end:
            result.append(PriceSlot(start, start + timedelta(minutes=15), price))
            start += timedelta(minutes=15)
    return validate_slots(result)
