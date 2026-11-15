"""Sol-by-sol simulation: building production, upkeep, life support, hazards.

This module must not import ``actions`` at module level, because ``actions``
imports this file. ``feed_crew`` is imported lazily inside ``advance_sol``.
"""

from typing import Any, Dict, List

import Resource_Class as resource_inventory
from Building_file import LogisticsBuilding, PowerPlant, ResourceBuilding

HOURS_PER_SOL = 24

# Units a fully effective building adds to its local storage per sol.
# Looked up by class name, walking up the inheritance chain (IceMinor -> WaterExtractor).
BUILDING_BASE_OUTPUTS: Dict[str, float] = {
    "WaterExtractor": 60.0,
    "OxygenGenerator": 25.0,
    "CarbonDioxideGenerator": 15.0,
    "NitrogenGenerator": 20.0,
    "HydrogenGenerator": 15.0,
    "FoodFactory": 22000.0,
    "PowerPlant": 220.0,
    "FuelRefinery": 40.0,
    "AluminumMine": 30.0,
    "SteelMill": 25.0,
    "SoilProcessor": 50.0,
    "PlasticFactory": 20.0,
    "GlassFactory": 20.0,
    "CarFactory": 0.25,
    "TruckFactory": 0.2,
    "RoverFactory": 0.2,
    "SatelliteFactory": 0.15,
    "RocketFactory": 0.1,
    "DroneFactory": 0.4,
    "Farm": 15.0,
}

CREW_OXYGEN_PER_SOL = 1.0
CREW_CO2_PER_SOL = 1.0
SUFFOCATION_DAMAGE = 8.0


class TimeEngine:
    """Tracks elapsed mission time."""

    def __init__(self) -> None:
        self.elapsed_hours: int = 0

    def advance(self, hours: int = HOURS_PER_SOL) -> None:
        self.elapsed_hours += hours


def base_output_for(facility: Any, default: float = 10.0) -> float:
    """Base output of a building, resolved through its class hierarchy."""
    for cls in type(facility).__mro__:
        if cls.__name__ in BUILDING_BASE_OUTPUTS:
            return BUILDING_BASE_OUTPUTS[cls.__name__]
    return default


def _active_crew(state: Any) -> List[Any]:
    return [
        w for w in state.workers
        if not getattr(w, "retired", False) and w.getHealth() > 0
    ]


def _staff_factor(bld: Any) -> float:
    """0.5-1.5x output from staffing level and staff health."""
    cap = max(1, type(bld).max_worker_capacity)
    staffing = 0.5 + 0.5 * (bld.number_of_workers / cap)
    if not bld.workers:
        return staffing
    health = sum(max(0.25, min(1.5, w.getHealth() / 100.0)) for w in bld.workers)
    return round(staffing * health / len(bld.workers), 3)


def _snapshot(state: Any) -> Dict[str, float]:
    return {name: res.getResources() for name, res in state.resources.items()}


def _build_report(state: Any, before: Dict[str, float]) -> None:
    report: Dict[str, Dict[str, float]] = {}
    for name, res in state.resources.items():
        net = round(res.getResources() - before.get(name, 0.0), 2)
        if abs(net) < 1e-9:
            continue
        report[name] = {
            "added": max(net, 0.0),
            "subtracted": max(-net, 0.0),
            "net": net,
        }
    state.daily_report = report


def _run_buildings(state: Any) -> None:
    """Pay every building's inputs and let paid producers fill local storage."""
    solar = float(state.space.get("solar_multiplier", 1.0))
    # Power plants first so their output can be hauled before other upkeep.
    ordered = sorted(state.buildings, key=lambda b: not isinstance(b, PowerPlant))
    for bld in ordered:
        was_operational = bld.is_operational()
        paid = bld.consume_turn_resources()
        if not paid:
            if was_operational:
                state.log.append(f"{bld.name} idle: not enough input resources.")
            continue
        if isinstance(bld, ResourceBuilding) and was_operational:
            amount = base_output_for(bld) * _staff_factor(bld)
            if isinstance(bld, PowerPlant):
                amount *= solar
            bld.produce(round(amount, 2))


def _run_logistics(state: Any) -> None:
    sources = [b for b in state.buildings if isinstance(b, ResourceBuilding)]
    for hub in state.buildings:
        if isinstance(hub, LogisticsBuilding) and hub.is_operational():
            hub.process_turn(sources)


def _environment_drain(state: Any) -> None:
    """Heating/shielding power draw and atmosphere leaks scale with active volume."""
    volume = sum(float(getattr(b, "volume", 100)) for b in state.buildings if b.is_on)
    blocks = volume / 100.0
    for res_name, key in (
        ("electricity", "power_per_100m3"),
        ("oxigen", "o2_leak_per_100m3"),
        ("Nitrogen", "n2_leak_per_100m3"),
    ):
        inventory = state.resources.get(res_name)
        if inventory is None:
            continue
        inventory.SubtractResources(min(inventory.getResources(), blocks * float(state.space.get(key, 0.0))))


def _life_support(state: Any) -> None:
    crew = _active_crew(state)
    if not crew:
        return
    oxygen = state.resources.get("oxigen")
    needed = len(crew) * CREW_OXYGEN_PER_SOL
    if oxygen is not None:
        have = oxygen.getResources()
        oxygen.SubtractResources(min(have, needed))
        if have < needed:
            state.log.append(f"Oxygen shortage! Crew took {SUFFOCATION_DAMAGE} damage.")
            for worker in crew:
                worker.takeDamage(SUFFOCATION_DAMAGE)
    co2 = state.resources.get("CO2")
    if co2 is not None:
        co2.addResources(len(crew) * CREW_CO2_PER_SOL)


def _recover_workers(state: Any) -> None:
    """Unassigned workers who worked, studied, or were treated are ready next sol."""
    for worker in _active_crew(state):
        if worker.assigned_building is None and not worker.Available:
            worker.SendToRest()


def advance_sol(state: Any) -> bool:
    """Simulate one full sol. Returns False if there is no crew left to simulate."""
    from actions import feed_crew  # lazy: actions imports this module

    if not _active_crew(state):
        state.log.append("No active crew; the colony is lost.")
        return False

    before = _snapshot(state)
    state.log.append(f"--- Sol {state.sol} complete ---")

    _run_buildings(state)
    _run_logistics(state)
    _environment_drain(state)
    _life_support(state)
    feed_crew(state)
    state.hazard_manager.process_turn(state)
    _recover_workers(state)

    state.time_engine.advance(HOURS_PER_SOL)
    state.sol += 1
    _build_report(state, before)
    return True


def advance_multiple_sols(state: Any, count: int) -> bool:
    """Advance up to ``count`` sols, stopping early if the crew is lost."""
    advanced = 0
    for _ in range(max(0, min(int(count), 365))):
        if not advance_sol(state):
            break
        advanced += 1
    return advanced > 0
