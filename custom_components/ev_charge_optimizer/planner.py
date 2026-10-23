"""Pure, deterministic planning. No HA imports, I/O, or charging commands.

All arithmetic uses UTC instants. Local civil times are used only for rule deadlines.
Energy allocations describe AC input; battery energy includes configured efficiency.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from math import isfinite
from zoneinfo import ZoneInfo

QUARTER = timedelta(minutes=15)
EPS = 1e-7


def utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Timestamp must include a timezone")
    return value.astimezone(UTC)


def next_clock(now: datetime, timezone: str, hour: int, minute: int = 0) -> datetime:
    now = utc(now)
    local = now.astimezone(ZoneInfo(timezone))
    candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if utc(candidate) <= now:
        candidate = (local + timedelta(days=1)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
    return utc(candidate)


@dataclass(frozen=True)
class PriceSlot:
    start: datetime
    end: datetime
    price: float


@dataclass(frozen=True)
class Vehicle:
    key: str
    soc: float
    target: float
    capacity_kwh: float
    max_kw: float
    connected: bool = True
    charging: bool = False
    actual_kw: float | None = None
    efficiency: float = 1.0
    fresh: bool = True
    deadline: datetime | None = None


@dataclass
class RuleState:
    """Persist anchors so periodic recalculation and restarts cannot slide deadlines."""

    band: str = ""
    deadline: datetime | None = None
    boost_window_end: datetime | None = None
    boost_suppressed: bool = False
    boost_active: bool = False
    boost_original: float | None = None
    boost_manual_window: datetime | None = None


@dataclass(frozen=True)
class Allocation:
    start: datetime
    end: datetime
    kw: float
    price: float
    kind: str = "scheduled"

    @property
    def kwh(self) -> float:
        return self.kw * (self.end - self.start).total_seconds() / 3600


@dataclass
class Forecast:
    expected_finish: datetime | None = None
    expected_soc_at_0700: float | None = None
    expected_next_start: datetime | None = None
    forecast_cutoff: datetime | None = None
    updated_at: datetime | None = None
    valid: bool = False
    provisional: bool = False
    reason: str = "Missing inputs"
    status: str = "unavailable"
    effective_target: float | None = None
    power_kw: float | None = None
    allocations: list[Allocation] = field(default_factory=list)
    stages: list[dict] = field(default_factory=list)
    assumptions: str = "Proposed schedule followed; constant AC power; configured efficiency; observed charging continues through the current interval, then the proposal is followed; no driving or other charging. Read-only mode cannot enforce this schedule."


def ordered_prices(slots: list[PriceSlot], tolerance: float) -> list[PriceSlot]:
    remaining = list(slots)
    ordered = []
    while remaining:
        floor = min(s.price for s in remaining)
        group = sorted(
            (s for s in remaining if s.price <= floor + tolerance + 1e-9),
            key=lambda s: (s.start, s.price),
        )
        ordered.extend(group)
        remaining = [s for s in remaining if s not in group]
    return ordered


def validate_slots(slots: list[PriceSlot]) -> list[PriceSlot]:
    result = sorted(
        (PriceSlot(utc(s.start), utc(s.end), s.price) for s in slots), key=lambda s: s.start
    )
    for i, slot in enumerate(result):
        if not isfinite(slot.price) or slot.end - slot.start != QUARTER:
            raise ValueError("Prices must be finite, non-overlapping 15-minute intervals")
        if i and result[i - 1].end > slot.start:
            raise ValueError("Overlapping price intervals")
    return result


def _band(v: Vehicle) -> str:
    if v.soc >= v.target:
        return "reached"
    if v.target >= 85:
        return "long_trip"
    if v.soc < 5:
        return "below_5"
    if v.soc < 10:
        return "below_10"
    if v.soc < 50:
        return "below_50"
    return "above_50"


def _anchor(v: Vehicle, now: datetime, timezone: str, state: RuleState) -> datetime | None:
    band = _band(v)
    if state.band != band or state.deadline is None:
        state.band = band
        state.deadline = {
            "long_trip": next_clock(now, timezone, 6, 30),
            "below_5": now,
            "below_10": now + timedelta(hours=4),
            "below_50": next_clock(now, timezone, 7),
            "above_50": now + timedelta(hours=24),
            "reached": now,
        }[band]
    return utc(v.deadline) if v.deadline else state.deadline


def _boost(
    v: Vehicle,
    slots: list[PriceSlot],
    now: datetime,
    power: float,
    state: RuleState,
    enabled: bool,
    threshold: float,
    target: float,
) -> datetime | None:
    current = next(
        (i for i, s in enumerate(slots) if s.start <= now < s.end and s.price < threshold), None
    )
    if current is None:
        state.boost_active = state.boost_suppressed = False
        state.boost_window_end = None
        state.boost_manual_window = None
        return None
    end = slots[current].end
    for slot in slots[current + 1 :]:
        if slot.start != end or slot.price >= threshold:
            break
        end = slot.end
    if state.boost_window_end is None or state.boost_window_end <= now:
        state.boost_suppressed = False
        state.boost_active = False
    state.boost_window_end = end
    if (
        state.boost_active
        and state.boost_original is not None
        and abs(v.target - state.boost_original) > 0.25
    ):
        # Read-only simulation never changes the real charge limit: any live change is external.
        state.boost_active = False
        state.boost_manual_window = end
    if (
        not enabled
        or not v.connected
        or v.target >= target
        or v.soc >= target
        or state.boost_manual_window == end
    ):
        state.boost_active = False
        return None
    if not state.boost_active and not state.boost_suppressed:
        hours = v.capacity_kwh * (target - v.soc) / 100 / (power * v.efficiency)
        if v.soc >= v.target or hours <= (end - now).total_seconds() / 3600 + EPS:
            state.boost_active, state.boost_original = True, v.target
        else:
            state.boost_suppressed = True
    return end if state.boost_active else None


def plan_site(
    vehicles: list[Vehicle],
    slots: list[PriceSlot],
    now: datetime,
    *,
    timezone: str,
    grid_kw: float,
    states: dict[str, RuleState] | None = None,
    tolerance: float = 0.005,
    margin_minutes: int = 15,
    boost_enabled: bool = True,
    boost_threshold: float = 0.5,
    boost_target: float = 80,
) -> dict[str, Forecast]:
    """Conservative equal shares mirror v1.2; idle shares are not redistributed.

    Reserve a share even for invalid connected vehicles, preventing optimistic forecasts
    for their peers. Actual active power, when supplied, caps that vehicle's estimate.
    """
    now = utc(now)
    cutoff = next_clock(now, timezone, 7)
    if not (
        isfinite(tolerance)
        and tolerance >= 0
        and isfinite(boost_threshold)
        and isfinite(boost_target)
        and 0 <= boost_target <= 100
        and 0 <= margin_minutes <= 240
    ):
        return {
            v.key: Forecast(
                reason="Invalid planner configuration", updated_at=now, forecast_cutoff=cutoff
            )
            for v in vehicles
        }
    states = states if states is not None else {}
    invalid_prices = None
    try:
        slots = validate_slots(slots)
    except ValueError as err:
        slots, invalid_prices = [], str(err)
    contenders = max(
        1,
        sum(
            v.connected
            and (not v.fresh or v.soc < max(v.target, boost_target if boost_enabled else v.target))
            for v in vehicles
        ),
    )
    result = {}
    for v in vehicles:
        f = Forecast(forecast_cutoff=cutoff, updated_at=now, effective_target=v.target)
        result[v.key] = f
        values = (v.soc, v.target, v.capacity_kwh, v.max_kw, v.efficiency, grid_kw)
        if not all(isfinite(x) for x in values) or not (
            0 <= v.soc <= 100
            and 0 <= v.target <= 100
            and v.capacity_kwh > 0
            and v.max_kw > 0
            and grid_kw > 0
            and 0 < v.efficiency <= 1
        ):
            f.reason = "Invalid vehicle or site limits"
            continue
        if not v.fresh or not v.connected:
            f.reason = (
                "Stale or missing vehicle data" if not v.fresh else "Vehicle disconnected or away"
            )
            continue
        power = min(v.max_kw, grid_kw / contenders)
        if v.charging:
            if v.actual_kw is None or not isfinite(v.actual_kw) or v.actual_kw <= 0:
                f.reason = "Active charging power unavailable"
                continue
            power = min(power, v.actual_kw)
        f.power_kw = power
        state = states.setdefault(v.key, RuleState())
        deadline = _anchor(v, now, timezone, state)
        usable = [s for s in slots if s.end > now]
        boost_end = _boost(
            v, usable, now, power, state, boost_enabled, boost_threshold, boost_target
        )
        effective = max(v.target, boost_target) if boost_end else v.target
        f.effective_target = effective
        if v.soc >= effective:
            f.valid, f.status, f.reason = (
                True,
                "no_charge_required",
                "Effective target already reached",
            )
            f.expected_soc_at_0700 = v.soc
            continue
        if not usable:
            f.reason = invalid_prices or "No usable future prices"
            continue
        # slot index -> AC energy. Each allocation starts at the beginning of its slot.
        allocation = [0.0] * len(usable)

        def start(i):
            return max(now, usable[i].start)

        def capacity(i, until):
            return max(0.0, (min(until, usable[i].end) - start(i)).total_seconds() / 3600 * power)

        def energy(pct):
            return max(0.0, min(effective, pct) - v.soc) * v.capacity_kwh / 100 / v.efficiency

        def selected_end():
            # Baseline anchors stages at price-slot ends, even for partially used slots.
            return max((s.end for i, s in enumerate(usable) if allocation[i] > EPS), default=now)

        def allocate(required, until, chronological, label):
            have = sum(min(allocation[i], capacity(i, until)) for i in range(len(usable)))
            deficit = max(0.0, required - have)
            order = (
                sorted(range(len(usable)), key=lambda i: start(i))
                if chronological
                else [usable.index(s) for s in ordered_prices(usable, tolerance)]
            )
            for i in order:
                take = min(max(0.0, capacity(i, until) - allocation[i]), deficit)
                allocation[i] += take
                deficit -= take
                if deficit < EPS:
                    break
            f.stages.append(
                {
                    "rule": label,
                    "deadline": until.isoformat(),
                    "complete": deficit < EPS,
                    "missing_ac_kwh": max(0, deficit),
                }
            )

        if v.charging:
            current_index = next(
                (i for i, slot in enumerate(usable) if slot.start <= now < slot.end), None
            )
            if current_index is None:
                f.reason = "Active charging has no current price interval"
                continue
            allocation[current_index] = min(
                energy(effective), capacity(current_index, usable[current_index].end)
            )

        if v.soc < 5:
            allocate(energy(min(5, v.target)), now + timedelta(hours=6), True, "immediate_to_5")
        if v.soc < 10 and v.target > 5:
            until = selected_end() + timedelta(hours=4) if v.soc < 5 else deadline
            allocate(energy(min(10, v.target)), until, False, "to_10_within_4h")
        reach50 = None
        if v.soc < 50 and v.target > 10:
            until = (
                min(cutoff, deadline - timedelta(minutes=margin_minutes))
                if v.target >= 85
                else cutoff
            )
            allocate(energy(min(50, v.target)), until, False, "to_50_by_morning")
            reach50 = selected_end()
        if v.target > 50:
            until = (
                deadline - timedelta(minutes=margin_minutes)
                if v.target >= 85
                else deadline
                if v.soc >= 50
                else (reach50 or selected_end()) + timedelta(hours=24)
            )
            allocate(energy(v.target), until, False, "final_target")
        if boost_end:
            # Continuous cheap charging has priority; normal plan is trimmed after target.
            for i in range(len(usable)):
                if start(i) < boost_end:
                    allocation[i] = max(allocation[i], capacity(i, boost_end))
        remaining = energy(effective)
        for i, slot in enumerate(usable):
            take = min(remaining, allocation[i])
            if take > EPS:
                end = start(i) + timedelta(hours=take / power)
                f.allocations.append(
                    Allocation(
                        start(i),
                        end,
                        power,
                        slot.price,
                        "cheap_boost" if boost_end and start(i) < boost_end else "scheduled",
                    )
                )
                remaining -= take
        complete = remaining < EPS and all(s["complete"] for s in f.stages)
        f.valid = complete
        f.provisional = not complete and bool(f.allocations)
        f.status = "scheduled" if complete else "provisional" if f.allocations else "unavailable"
        f.reason = (
            "Complete scheduled plan"
            if complete
            else "Insufficient known priced capacity or missed rule deadline"
        )
        if remaining < EPS and f.allocations:
            f.expected_finish = f.allocations[-1].end
        active = next((a for a in f.allocations if a.start <= now < a.end), None)
        if active and v.charging:
            f.status = "charging"
        else:
            f.expected_next_start = next((a.start for a in f.allocations if a.start >= now), None)
        # A conditional 07:00 projection is reliable only if full coverage exists up
        # to the cutoff or the effective target has already been delivered by then.
        before = sum(
            a.kw * max(0, (min(a.end, cutoff) - a.start).total_seconds()) / 3600
            for a in f.allocations
            if a.start < cutoff
        )
        cursor = now
        for slot in usable:
            if slot.start > cursor:
                break
            cursor = max(cursor, slot.end)
        if before >= energy(effective) - EPS or cursor >= cutoff:
            f.expected_soc_at_0700 = round(
                min(effective, v.soc + before * v.efficiency / v.capacity_kwh * 100), 3
            )
        else:
            f.reason += "; 07:00 forecast unknown: incomplete price coverage"
    return result
