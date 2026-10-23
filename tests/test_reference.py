"""Execute the committed JavaScript planner, rather than copying expected outputs."""

import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from .test_planner import NOW, V, plan, slots


@pytest.mark.parametrize(
    "soc,target,prices",
    [
        (60, 61, [2, 1, 3]),
        (60, 64, [1.004, 1, 1.008, 1]),
        (4, 10, [9, 9, 1, 1, 1, 1]),
        (40, 50, [1] * 8),
        (60, 85, [1] * 12),
    ],
)
def test_node_red_parity(soc, target, prices):
    if not shutil.which("node"):
        pytest.skip("Node.js required for original-flow parity")
    flow = Path(__file__).parents[1] / "node-red/EV-Charge-Optimizer-v1.2.json"
    function = next(n["func"] for n in json.loads(flow.read_text()) if n["id"] == "calc")
    # Run the original function body with injected deterministic clock and HA snapshot.
    original = slots(prices)
    payload = {
        "input_boolean.ev_charge_optimizer_config_initialized": {"state": "on"},
        "input_number.ev_site_anemonevej_grid_limit_amps": {"state": str(10000 / 690)},
        "input_number.blue_flux_optimizer_battery_capacity_kwh": {"state": "100"},
        "input_number.blue_flux_optimizer_max_ac_kw": {"state": "10"},
        "sensor.blue_flux_broker_battery_level": {"state": str(soc)},
        "sensor.blue_flux_broker_charge_limit_actual": {"state": str(target)},
        "sensor.blue_flux_broker_location": {"state": "home"},
        "binary_sensor.blue_flux_broker_charge_cable_connected": {"state": "on"},
    }
    script = """const fs=require('fs'); const x=JSON.parse(fs.readFileSync(0,'utf8'));
const NativeDate=Date; global.Date=class extends NativeDate {constructor(...args){super(...(args.length?args:[x.now]));} static now(){return new NativeDate(x.now).getTime();}};
const cache={evopt_price_sources:{real_energy:{slots:x.slots}}};
const flow={get:k=>cache[k],set:(k,v)=>cache[k]=v};
const fn=new Function('msg','flow',x.fn); fn({payload:x.payload},flow);
console.log(JSON.stringify(cache.evopt_latest_summary.cars.blue_flux));"""
    result = subprocess.run(
        ["node", "-e", script],
        input=json.dumps(
            {
                "fn": function,
                "now": NOW.isoformat(),
                "payload": payload,
                "slots": [
                    {"start": s.start.isoformat(), "end": s.end.isoformat(), "price": s.price}
                    for s in original
                ],
            }
        ),
        text=True,
        capture_output=True,
        check=True,
        env={**__import__("os").environ, "TZ": "Europe/Copenhagen"},
    )
    reference = json.loads(result.stdout)
    native = plan(replace(V, soc=soc, target=target), original)
    assert native.valid == reference["planValid"]
    assert [a.start.isoformat().replace("+00:00", ".000Z") for a in native.allocations] == [
        s["start"] for s in reference["selectedSlots"]
    ]
    assert [round(a.kwh, 2) for a in native.allocations] == [
        s["kwh"] for s in reference["selectedSlots"]
    ]
