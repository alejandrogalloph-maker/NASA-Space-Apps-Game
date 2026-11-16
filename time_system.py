"""Sol-by-sol simulation: building production, upkeep, life support, hazards.

This module must not import ``actions`` at module level, because ``actions``
imports this file. ``feed_crew`` is imported lazily inside ``advance_sol``.
"""

from typing import Any, Dict, List

import Resource_Class as resource_inventory
from Building_file import (
    LogisticsBuilding,
    PowerPlant,
    RadioisotopeThermoelectricGenerator,
    ResourceBuilding,
)
from Worker_Class import Profession, RobotWorker, Worker
import random

HOURS_PER_SOL = 24

# Units a fully effective building adds to its local storage per sol.
# Looked up by class name, walking up the inheritance chain (IceMinor -> WaterExtractor).
BUILDING_BASE_OUTPUTS: Dict[str, float] = {
    "WaterExtractor": 120.0,
    "OxygenGenerator": 50.0,
    "CarbonDioxideGenerator": 30.0,
    "NitrogenGenerator": 40.0,
    "HydrogenGenerator": 30.0,
    "FoodFactory": 36000.0,
    "PowerPlant": 440.0,
    "FuelRefinery": 80.0,
    "AluminumMine": 60.0,
    "SteelMill": 50.0,
    "SoilProcessor": 100.0,
    "PlasticFactory": 40.0,
    "GlassFactory": 40.0,
    "CarFactory": 0.5,
    "TruckFactory": 0.4,
    "RoverFactory": 0.4,
    "SatelliteFactory": 0.3,
    "RocketFactory": 0.2,
    "DroneFactory": 0.8,
    "Farm": 30.0,
    "RadioisotopeThermoelectricGenerator": 500.0,
}

CREW_OXYGEN_PER_SOL = 1.0
CREW_CO2_PER_SOL = 1.0
SUFFOCATION_DAMAGE = 8.0
ROBOT_WATER_PER_SOL = 2.5
ROBOT_POWER_KWH_PER_SOL = 2.64
ROBOT_UPKEEP_DAMAGE = 12.0


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
        if (
            not getattr(w, "is_robot", False)
            and not getattr(w, "retired", False)
            and w.getHealth() > 0
        )
    ]


def _active_units(state: Any) -> List[Any]:
    return [
        worker for worker in state.workers
        if not getattr(worker, "retired", False)
        and worker.getHealth() > 0
        and (
            not getattr(worker, "is_robot", False)
            or getattr(worker, "powered_on", True)
        )
    ]


def _staff_factor(bld: Any) -> float:
    """0.5-1.5x output from staffing level and staff health."""
    if not type(bld).required_professions:
        return 1.0
    cap = max(1, type(bld).max_worker_capacity)
    staffing = 0.5 + 0.5 * (bld.number_of_workers / cap)
    if not bld.workers:
        return staffing
    role_index = {
        "Unassigned": 0,
        "Doctor": 1,
        "Engineer": 2,
        "Biologist": 3,
        "Geologist": 4,
        "Pilot": 5,
    }
    worker_factors = []
    for worker in bld.workers:
        index = role_index.get(worker.getType().name, 0)
        skills = worker.getSkills()
        debuffs = worker.getDebuffs()
        net_skill = max(0.0, skills[index] - 0.5 * debuffs[index])
        skill_factor = max(0.5, min(1.5, 0.5 + net_skill / 100.0))
        health_factor = max(0.25, min(1.5, worker.getHealth() / 100.0))
        morale_factor = (
            max(0.8, min(1.2, 0.8 + float(getattr(worker, "morale", 50.0)) / 250.0))
            if not getattr(worker, "is_robot", False)
            else 1.0
        )
        worker_factors.append(skill_factor * health_factor * morale_factor)
    return round(staffing * sum(worker_factors) / len(worker_factors), 3)


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
            amount *= float(getattr(bld, "production_boost", 1.0))
            if isinstance(bld, PowerPlant):
                amount *= solar
            produced = bld.produce(round(amount, 2))
            if produced > 0:
                bld.production_boost = 1.0
            if isinstance(bld, RadioisotopeThermoelectricGenerator) and produced > 0:
                local_power = bld._get_storage("electricity")
                local_power.SubtractResources(produced)
                state.resources["electricity"].addResources(produced)


def _building_condition(state: Any) -> None:
    """Wear down structures and occasionally injure staff in unsafe buildings."""
    for building in state.buildings:
        wear = 0.45 if building.is_operational() else 0.15
        building.health = max(0.0, float(building.health) - wear)
        if building.health <= 0:
            building.turn_off()
            state.log.append(f"{building.name} failed from structural wear and was shut down.")
            continue
        if building.health >= 40:
            continue
        injury_chance = min(0.4, (40.0 - building.health) / 100.0)
        workers = [
            worker for worker in building.workers
            if not getattr(worker, "retired", False) and worker.getHealth() > 0
        ]
        if workers and random.random() < injury_chance:
            worker = random.choice(workers)
            damage = round(random.uniform(4.0, 10.0), 1)
            worker.takeDamage(damage)
            state.log.append(
                f"BUILDING DANGER: {building.name} (health {building.health:.0f}%, "
                f"danger rating {max(1, int((100 - building.health) // 20))}) "
                f"injured {worker.Name} for {damage:g} HP."
            )


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
        inventory.consumeResources(
            min(
                inventory.getResources() / max(inventory.cost_multiplier, 1e-9),
                blocks * float(state.space.get(key, 0.0)),
            )
        )


def _life_support(state: Any) -> None:
    crew = _active_crew(state)
    if not crew:
        return
    oxygen = state.resources.get("oxigen")
    needed = len(crew) * CREW_OXYGEN_PER_SOL
    if oxygen is not None:
        have = oxygen.getResources()
        oxygen.consumeResources(
            min(have / max(oxygen.cost_multiplier, 1e-9), needed)
        )
        if have < oxygen.required_amount(needed):
            state.log.append(f"Oxygen shortage! Crew took {SUFFOCATION_DAMAGE} damage.")
            for worker in crew:
                worker.takeDamage(SUFFOCATION_DAMAGE)
    co2 = state.resources.get("CO2")
    if co2 is not None:
        co2.addResources(len(crew) * CREW_CO2_PER_SOL)


def _robot_upkeep(state: Any) -> None:
    """Power robots automatically, then consume water as their daily service supply."""
    water = state.resources.get("water")
    electricity = state.resources.get("electricity")
    if water is None or electricity is None:
        return

    robots = [
        robot for robot in state.workers
        if (
            getattr(robot, "is_robot", False)
            and not getattr(robot, "retired", False)
            and robot.getHealth() > 0
        )
    ]
    power_per_robot = electricity.required_amount(ROBOT_POWER_KWH_PER_SOL)
    powered_capacity = (
        min(len(robots), int((electricity.getResources() + 1e-9) / power_per_robot))
        if power_per_robot > 0 else len(robots)
    )
    priority = sorted(
        robots,
        key=lambda robot: not getattr(robot, "powered_on", True),
    )
    active = set(id(robot) for robot in priority[:powered_capacity])
    for robot in robots:
        should_power = id(robot) in active
        if robot.powered_on and not should_power:
            robot.powered_on = False
            state.log.append(f"{robot.Name} shut down: insufficient electricity for the colony's power budget.")
        elif not robot.powered_on and should_power:
            robot.powered_on = True
            state.log.append(f"{robot.Name} automatically powered back on.")
    for robot in priority[:powered_capacity]:
        if not electricity.consumeResources(ROBOT_POWER_KWH_PER_SOL):
            robot.powered_on = False
            state.log.append(f"{robot.Name} shut down: insufficient electricity.")
            continue
        if not water.consumeResources(ROBOT_WATER_PER_SOL):
            robot.takeDamage(ROBOT_UPKEEP_DAMAGE)
            state.log.append(
                f"{robot.Name} missed water maintenance and took "
                f"{ROBOT_UPKEEP_DAMAGE:.0f} damage."
            )


def _recover_workers(state: Any) -> None:
    """Make every active, unassigned worker ready when the Sol ends."""
    for worker in _active_units(state):
        if (
            worker.assigned_building is None
            and not worker.Available
            and getattr(worker, "powered_on", True)
        ):
            worker.SendToRest()


def _award_satellite_research(state: Any) -> None:
    if state.active_satellites <= 0:
        return
    gained = float(state.active_satellites * 5)
    research = state.resources.get("research")
    if research is not None:
        research.addResources(gained)
    state.science_points += gained
    state.log.append(
        f"Orbital satellites generated +{gained:g} passive research and science."
    )


def _deliver_pending_rockets(state: Any) -> None:
    due = [
        shipment for shipment in state.pending_rockets
        if state.sol >= shipment["arrival_sol"]
    ]
    for shipment in due:
        payload = shipment["payload"]
        delivered: list[str] = []
        for name, quantity in payload.items():
            if name in state.resources:
                inventory = state.resources[name]
                before = inventory.getResources()
                inventory.addResources(quantity)
                accepted = inventory.getResources() - before
                delivered.append(f"{accepted:g} {name}")
        for _ in range(int(payload.get("people", 0))):
            person = Worker(30 * 365)
            person.setType(random.choice([
                Profession.Doctor,
                Profession.Engineer,
                Profession.Biologist,
                Profession.Geologist,
                Profession.Pilot,
            ]).value)
            state.workers.append(person)
        for index in range(int(payload.get("robots", 0))):
            robot = RobotWorker(
                f"Resupply-Robot-{len(state.workers) + index + 1:03d}"
            )
            state.workers.append(robot)
        cargo = ", ".join(delivered) or "no cargo"
        state.log.append(
            f"Earth resupply rocket #{shipment['id']} arrived at "
            f"{shipment['destination'].title()}: {cargo}."
        )
        state.pending_rockets.remove(shipment)


def _update_human_morale(state: Any) -> None:
    """Adjust hidden morale from health, life support, and active incidents."""
    humans = _active_crew(state)
    if not humans:
        return
    oxygen = state.resources.get("oxigen")
    water = state.resources.get("water")
    food = state.resources.get("food")
    oxygen_short = oxygen is not None and oxygen.getResources() < len(humans)
    water_short = water is not None and water.getResources() < len(humans) * 2.5
    food_short = food is not None and food.getResources() < len(humans) * 2000
    active_incidents = len(state.hazard_manager.active_incidents)

    for worker in humans:
        change = 1.0
        if worker.getHealth() < 75:
            change -= 2.0
        if worker.getHealth() < 50:
            change -= 3.0
        if oxygen_short or water_short or food_short:
            change -= 4.0
        if active_incidents:
            change -= min(8.0, 3.0 * active_incidents)
        worker.morale = max(0.0, min(100.0, worker.morale + change))


def advance_sol(state: Any) -> bool:
    """Simulate one full sol. Returns False if there is no crew left to simulate."""
    from actions import feed_crew  # lazy: actions imports this module

    if state.workers and not _active_units(state):
        state.log.append("No active crew or robots; the colony is lost.")
        return False
    if not state.workers:
        state.log.append("No crew or robots aboard; advancing unmanned colony systems.")

    before = _snapshot(state)
    previous_sol = state.sol
    state.log.append(f"--- Sol {state.sol} complete ---")

    _run_buildings(state)
    _run_logistics(state)
    _building_condition(state)
    _environment_drain(state)
    _robot_upkeep(state)
    _life_support(state)
    feed_crew(state)
    _award_satellite_research(state)
    state.hazard_manager.process_turn(state)
    _update_human_morale(state)
    _recover_workers(state)

    state.time_engine.advance(HOURS_PER_SOL)
    state.sol += 1
    for building in state.buildings:
        if isinstance(building, LogisticsBuilding):
            building.transferred_today = 0
    _deliver_pending_rockets(state)
    state.daily_action_usage.clear()
    _build_report(state, before)
    for name, inventory in state.resources.items():
        if before.get(name, 0.0) > 0 and inventory.getResources() <= 0:
            event = {
                "resource": name,
                "sol": previous_sol,
                "crises": [
                    incident.name
                    for incident in state.hazard_manager.active_incidents
                ],
            }
            state.resource_depletion_events.append(event)
            state.log.append(
                f"EMERGENCY: {name} was fully depleted during Sol {previous_sol}."
            )
    state.log.append(_houston_daily_update(state, previous_sol))
    return True


def _houston_daily_update(state: Any, completed_sol: int) -> str:
    """Provide an in-world Earth bulletin and a concise colony status report."""
    communication_blockers = [
        incident.name
        for incident in state.hazard_manager.active_incidents
        if getattr(incident, "blocks_communications", False)
    ]
    if communication_blockers:
        problem = " and ".join(communication_blockers)
        return (
            f"... [No message received due to {problem}], "
            "with the current crisis there."
        )
    bulletins = (
        "Earth bulletin: global launch teams are tracking the next favorable transfer window.",
        "Earth bulletin: mission specialists have confirmed the resupply network remains available.",
        "Earth bulletin: observatories report routine conditions; the science teams are reviewing your telemetry.",
        "Earth bulletin: ground control is coordinating additional life-support research.",
        "Earth bulletin: the communications network is monitoring solar activity.",
    )
    active_crises = ", ".join(
        incident.name for incident in state.hazard_manager.active_incidents
    ) or "none"
    power = state.resources.get("electricity")
    water = state.resources.get("water")
    power_text = f"{power.getResources():.0f} kWh" if power else "unavailable"
    water_text = f"{water.getResources():.0f} L" if water else "unavailable"
    bulletin = bulletins[(completed_sol - 1) % len(bulletins)]
    return (
        f"HOUSTON MISSION CONTROL: Sol {completed_sol} report — {bulletin} "
        f"Colony telemetry: power {power_text}, water {water_text}; "
        f"active incidents: {active_crises}."
    )


def advance_multiple_sols(state: Any, count: int) -> bool:
    """Advance up to ``count`` sols, stopping early if the crew is lost."""
    advanced = 0
    for _ in range(max(0, min(int(count), 365))):
        if not advance_sol(state):
            break
        advanced += 1
    return advanced > 0
