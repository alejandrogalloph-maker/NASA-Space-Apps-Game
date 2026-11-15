from typing import Any, Dict, List
from Building_file import (
    ResourceBuilding,
    PowerPlant,
    LogisticsBuilding,
    University,
    CommunicationsHub,
    SatelliteDish,
    MedicalBay,
    Hospital,
    Canteen,
    RecreationCenter,
    Habitation,
)


BUILDING_BASE_OUTPUTS: Dict[str, float] = {
    'PowerPlant': 95.0,
    'WaterExtractor': 28.0,
    'IceMinor': 34.0,
    'OxygenGenerator': 10.0,
    'CarbonDioxideGenerator': 12.0,
    'NitrogenGenerator': 8.0,
    'HydrogenGenerator': 10.0,
    'FoodFactory': 16000.0,
    'FuelRefinery': 24.0,
    'AluminumMine': 14.0,
    'SteelMill': 14.0,
    'SoilProcessor': 30.0,
    'PlasticFactory': 12.0,
    'GlassFactory': 12.0,
    'Farm': 8.0,
    'CarFactory': 1.0,
    'TruckFactory': 1.0,
    'RoverFactory': 1.0,
    'SatelliteFactory': 1.0,
    'RocketFactory': 1.0,
    'DroneFactory': 1.0,
}


def _get_res(state: Any, name: str) -> float:
    res = state.resources.get(name)
    if res is None:
        return 0.0
    return res.getResources()


def _spend_res(state: Any, name: str, amount: float) -> bool:
    res = state.resources.get(name)
    if res is None:
        return False
    return res.SubtractResources(amount)


def _add_res(state: Any, name: str, amount: float) -> bool:
    res = state.resources.get(name)
    if res is None:
        return False
    res.addResources(amount)
    return True


def _apply_worker_damage(worker: Any, amount: float) -> None:
    if not worker.takeDamage(amount):
        worker.health = 0.0
        worker.Available = False


class TimeEngine:
    def __init__(self, hours_per_sol: int = 24):
        self.hours_per_sol = hours_per_sol
        self.elapsed_sols = 0
        self.elapsed_hours = 0

    def step_sol(self, state: Any) -> Dict[str, Dict[str, float]]:
        state.sol += 1
        self.elapsed_sols += 1
        self.elapsed_hours += self.hours_per_sol

        env = state.space
        tracked = [
            'food', 'water', 'oxigen', 'CO2', 'Nitrogen',
            'electricity', 'steel', 'aluminum', 'plastic', 'dirt', 'fuel',
        ]
        gained = {k: 0.0 for k in tracked}
        spent = {k: 0.0 for k in tracked}

        active = [w for w in state.workers if not getattr(w, 'retired', False) and w.getHealth() > 0]
        people_count = len(active)
        total_volume = sum(
            float(getattr(b, 'volume', 100))
            for b in state.buildings
            if getattr(b, 'is_on', True)
        )
        space_units = max(1.0, total_volume / 100.0)

        ordered_buildings = sorted(
            state.buildings,
            key=lambda b: 0 if isinstance(b, PowerPlant) else 1,
        )

        resource_buildings: List[ResourceBuilding] = []
        logistics_buildings: List[LogisticsBuilding] = []

        for bld in ordered_buildings:
            if isinstance(bld, LogisticsBuilding):
                logistics_buildings.append(bld)
            if isinstance(bld, ResourceBuilding):
                resource_buildings.append(bld)

            recipe = (
                type(bld).operating_resource_costs
                if bld.is_operational()
                else type(bld).standby_resource_costs
            )
            if not bld.consume_turn_resources():
                state.log.append(f'{bld.name} offline today (insufficient upkeep inputs).')
                continue

            for res_name, amt in recipe.items():
                if res_name in spent:
                    spent[res_name] += amt

            if not bld.is_operational():
                continue

            safety = float(getattr(bld, 'safety_rating', 95))
            safety_factor = (safety / 100.0) if safety > 1.0 else safety
            max_cap = max(1, int(getattr(type(bld), 'max_worker_capacity', 1)))
            workers_assigned = int(getattr(bld, 'number_of_workers', 0))
            staff_factor = 0.6 + 0.4 * (workers_assigned / max_cap)

            if isinstance(bld, ResourceBuilding):
                cls_name = type(bld).__name__
                base_output = BUILDING_BASE_OUTPUTS.get(cls_name, 10.0)
                env_factor = env['solar_multiplier'] if isinstance(bld, PowerPlant) else 1.0
                produced_qty = round(base_output * max(0.3, safety_factor) * staff_factor * env_factor, 1)
                bld.produce(produced_qty)
            elif isinstance(bld, University):
                pts = bld.produce_research()
                if pts > 0:
                    state.science_points += pts * 15.0
            elif isinstance(bld, (CommunicationsHub, SatelliteDish)):
                bonus = 6.0 if isinstance(bld, CommunicationsHub) else 2.5
                state.science_points += round(bonus * staff_factor, 1)
            elif isinstance(bld, (MedicalBay, Hospital)):
                heal_amt = 8.0 if isinstance(bld, Hospital) else 4.0
                for w in active:
                    if w.getHealth() < 100.0:
                        w.health = min(100.0, w.getHealth() + heal_amt)

        operational_hubs = [h for h in logistics_buildings if h.is_operational()]
        if operational_hubs and resource_buildings:
            for hub in operational_hubs:
                transferred = hub.process_turn(resource_buildings)
                for res_name, amt in transferred.items():
                    if res_name in gained:
                        gained[res_name] += amt
        elif resource_buildings:
            pending = sum(
                store.getResources()
                for bld in resource_buildings
                for store in bld.storage.values()
            )
            if pending > 0:
                state.log.append('No operational LogisticsHub (needs On + 1 Pilot): produced resources remain in local storage.')

        if state.active_satellites > 0:
            sat_power = round(state.active_satellites * 20.0 * env['solar_multiplier'], 1)
            _add_res(state, 'electricity', sat_power)
            gained['electricity'] += sat_power

        space_power_cost = round(space_units * env['power_per_100m3'], 1)
        space_o2_cost = round(space_units * env['o2_leak_per_100m3'], 2)
        space_n2_cost = round(space_units * env['n2_leak_per_100m3'], 2)

        if _spend_res(state, 'electricity', space_power_cost):
            spent['electricity'] += space_power_cost
        else:
            actual = _get_res(state, 'electricity')
            _spend_res(state, 'electricity', actual)
            spent['electricity'] += actual
            for worker in active:
                _apply_worker_damage(worker, 6.0)
            state.log.append(f'Life-support power deficit across {total_volume:.0f} m^3 base volume!')

        o2_used = min(space_o2_cost, _get_res(state, 'oxigen'))
        _spend_res(state, 'oxigen', o2_used)
        spent['oxigen'] += o2_used

        n2_used = min(space_n2_cost, _get_res(state, 'Nitrogen'))
        _spend_res(state, 'Nitrogen', n2_used)
        spent['Nitrogen'] += n2_used

        has_canteen = any(isinstance(b, Canteen) and b.is_operational() for b in state.buildings)
        has_recreation = any(isinstance(b, RecreationCenter) and b.is_operational() for b in state.buildings)
        total_bed_cap = sum(
            int(getattr(b, 'resident_capacity', 0))
            for b in state.buildings
            if isinstance(b, Habitation) and b.is_operational()
        )

        if total_bed_cap > 0 and people_count > total_bed_cap:
            for worker in active:
                _apply_worker_damage(worker, 4.0)
            state.log.append(f'Overcrowding! {people_count} crew exceed {total_bed_cap} habitation beds (-4 HP).')

        daily_kcal_need = 1800.0 if has_canteen else 2000.0

        for worker in active:
            worker.age += 1

            if _spend_res(state, 'food', daily_kcal_need):
                spent['food'] += daily_kcal_need
            else:
                _apply_worker_damage(worker, 15.0)
                state.log.append(f'Food shortage (-{daily_kcal_need:.0f} kcal needed)! {worker.Name} took 15 damage.')

            if _spend_res(state, 'water', 2.5):
                spent['water'] += 2.5
            else:
                _apply_worker_damage(worker, 15.0)
                state.log.append(f'Water shortage (-2.5 L needed)! {worker.Name} took 15 damage.')

            if _spend_res(state, 'oxigen', 0.84):
                spent['oxigen'] += 0.84
            else:
                _apply_worker_damage(worker, 20.0)
                state.log.append(f'Oxigen shortage (-0.84 kg needed)! {worker.Name} took 20 damage.')

            if _spend_res(state, 'electricity', 4.0):
                spent['electricity'] += 4.0

            _add_res(state, 'CO2', 1.0)
            gained['CO2'] += 1.0

            if has_recreation:
                for i in range(len(worker.getDebuffs())):
                    worker.modDebuff(-1.5, i)

            if not worker.isAvailable() and getattr(worker, 'assigned_building', None) is None:
                worker.SendToRest()

        for bld in state.buildings:
            if hasattr(bld, 'safety_rating') and getattr(bld, 'is_on', True):
                if bld.safety_rating <= 1.0:
                    bld.safety_rating = max(0.5, round(bld.safety_rating - 0.01, 2))
                else:
                    bld.safety_rating = max(50, bld.safety_rating - 1)

        if hasattr(state, 'hazard_manager'):
            state.hazard_manager.process_turn(state)

        state.daily_report = {
            k: {
                'added': round(gained[k], 1),
                'subtracted': round(spent[k], 1),
                'net': round(gained[k] - spent[k], 1),
            }
            for k in tracked
            if gained[k] > 0 or spent[k] > 0
        }

        env_label = env['label']
        net_food = state.daily_report.get('food', {}).get('net', 0)
        net_o2 = state.daily_report.get('oxigen', {}).get('net', 0)
        net_water = state.daily_report.get('water', {}).get('net', 0)
        net_power = state.daily_report.get('electricity', {}).get('net', 0)
        state.log.append(
            f'Sol {state.sol} ({env_label} | Crew: {people_count} | Vol: {total_volume:.0f} m^3): '
            f'Food {net_food:+.0f} kcal, O2 {net_o2:+.1f}, Water {net_water:+.1f}, Power {net_power:+.1f}'
        )
        return state.daily_report


def advance_sol(state: Any) -> Dict[str, Dict[str, float]]:
    engine = getattr(state, 'time_engine', None)
    if engine is None:
        engine = TimeEngine()
        state.time_engine = engine
    return engine.step_sol(state)


def advance_multiple_sols(state: Any, days: int = 1) -> int:
    steps = max(1, min(365, int(days)))
    completed = 0
    for _ in range(steps):
        active = [w for w in state.workers if not getattr(w, 'retired', False) and w.getHealth() > 0]
        if not active:
            break
        advance_sol(state)
        completed += 1
    return completed
