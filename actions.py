import random
from typing import Any, Callable, Dict, List


SPACE_ENVIRONMENTS = {
    'orbit': {
        'label': 'Low Earth Orbit Station',
        'solar_multiplier': 1.35,
        'power_per_space': 4.0,
        'o2_leak_per_space': 0.25,
        'n2_leak_per_space': 0.20,
        'hazard_chance': 0.20,
    },
    'moon': {
        'label': 'Lunar South Pole Base',
        'solar_multiplier': 1.15,
        'power_per_space': 6.0,
        'o2_leak_per_space': 0.30,
        'n2_leak_per_space': 0.25,
        'hazard_chance': 0.25,
    },
    'mars': {
        'label': 'Mars Jezero Crater Base',
        'solar_multiplier': 0.85,
        'power_per_space': 5.0,
        'o2_leak_per_space': 0.20,
        'n2_leak_per_space': 0.15,
        'hazard_chance': 0.25,
    },
    'deep_space': {
        'label': 'Deep Space Transit Habitat',
        'solar_multiplier': 0.45,
        'power_per_space': 8.0,
        'o2_leak_per_space': 0.35,
        'n2_leak_per_space': 0.30,
        'hazard_chance': 0.30,
    },
}


class GameState:
    def __init__(
        self,
        resource_pool: Dict[str, Any],
        workers: List[Any],
        buildings: List[Any],
        space_key: str = 'mars',
    ):
        self.resources = resource_pool
        self.workers = workers
        self.buildings = buildings
        self.space_key = space_key if space_key in SPACE_ENVIRONMENTS else 'mars'
        self.space = SPACE_ENVIRONMENTS[self.space_key]
        self.sol = 1
        self.science_points = 0.0
        self.active_satellites = 0
        self.daily_report: Dict[str, Dict[str, float]] = {}
        self.log: List[str] = []


'Resource management'

def get_resource(state: GameState, name: str) -> float:
    res = state.resources.get(name)
    if res is None:
        return 0.0
    return res.getResources()


def has_resource(state: GameState, name: str, amount: float) -> bool:
    return get_resource(state, name) >= amount


def spend_resource(state: GameState, name: str, amount: float) -> bool:
    res = state.resources.get(name)
    if res is None:
        return False
    return res.SubtractResources(amount)


def add_resource(state: GameState, name: str, amount: float) -> bool:
    res = state.resources.get(name)
    if res is None:
        return False
    res.addResources(amount)
    return True


def expand_resource_max(state: GameState, name: str, amount: float) -> bool:
    res = state.resources.get(name)
    if res is None:
        return False
    res.AddMax(amount)
    return True


def _spend_bundle(state: GameState, costs: Dict[str, float]) -> bool:
    for name, amount in costs.items():
        if not has_resource(state, name, amount):
            return False
    for name, amount in costs.items():
        spend_resource(state, name, amount)
    return True


def _get_worker(state: GameState, worker_index: int) -> Any:
    if not (0 <= worker_index < len(state.workers)):
        state.log.append('Invalid worker index.')
        return None
    worker = state.workers[worker_index]
    if getattr(worker, 'retired', False) or worker.getHealth() <= 0:
        state.log.append(f'{worker.Name} is inactive.')
        return None
    return worker


def _get_available_worker(state: GameState, worker_index: int) -> Any:
    worker = _get_worker(state, worker_index)
    if worker is None:
        return None
    if not worker.isAvailable():
        state.log.append(f'{worker.Name} is busy right now.')
        return None
    return worker


def _worker_efficiency(worker: Any, preferred_job: str = '') -> float:
    role_index = {
        'Unassigned': 0,
        'Doctor': 1,
        'Engineer': 2,
        'Biologist': 3,
        'Geologist': 4,
        'Pilot': 5,
    }
    job_name = worker.getType().name
    idx = role_index.get(job_name, 0)
    skills = worker.getSkills()
    debuffs = worker.getDebuffs()
    net_skill = max(10.0, skills[idx] - 0.5 * debuffs[idx])
    hp_factor = max(0.25, min(1.5, worker.getHealth() / 100.0))
    role_bonus = 1.5 if preferred_job and job_name == preferred_job else 1.0
    return round((net_skill / 50.0) * hp_factor * role_bonus, 2)


def _damage_worker(worker: Any, amount: float) -> None:
    if not worker.takeDamage(amount):
        worker.health = 0.0
        worker.Available = False


'Worker actions'

def assign_worker_job(state: GameState, worker_index: int, profession_code: int) -> bool:
    worker = _get_worker(state, worker_index)
    if worker is None:
        return False
    worker.setType(profession_code)
    state.log.append(f'{worker.Name} assigned to {worker.getType().name}.')
    return True


def send_worker_to_work(state: GameState, worker_index: int) -> bool:
    worker = _get_available_worker(state, worker_index)
    if worker is None:
        return False
    eff = _worker_efficiency(worker)
    worker.SendToWork()
    _damage_worker(worker, 2.0)
    power_gain = round(6.0 * eff, 1)
    add_resource(state, 'electricity', power_gain)
    state.log.append(f'{worker.Name} completed general shift (+{power_gain} electricity).')
    return True


def send_worker_to_rest(state: GameState, worker_index: int) -> bool:
    worker = _get_worker(state, worker_index)
    if worker is None:
        return False
    worker.SendToRest()
    for i in range(len(worker.getDebuffs())):
        worker.modDebuff(-2.0, i)
    state.log.append(f'{worker.Name} rested (HP: {worker.getHealth():.1f}).')
    return True


def send_worker_to_hospital(state: GameState, worker_index: int) -> bool:
    worker = _get_worker(state, worker_index)
    if worker is None:
        return False
    if not _spend_bundle(state, {'water': 2.0, 'electricity': 5.0}):
        state.log.append('Not enough water or electricity for hospital care.')
        return False
    worker.SendToHospital()
    for i in range(len(worker.getDebuffs())):
        worker.modDebuff(-5.0, i)
    state.log.append(f'{worker.Name} treated in hospital (HP: {worker.getHealth():.1f}).')
    return True


def send_worker_to_study(state: GameState, worker_index: int) -> bool:
    worker = _get_worker(state, worker_index)
    if worker is None:
        return False
    if not spend_resource(state, 'electricity', 5.0):
        state.log.append('Need 5 electricity to run training terminal.')
        return False
    worker.SendToStudy()
    role_index = {
        'Unassigned': 0,
        'Doctor': 1,
        'Engineer': 2,
        'Biologist': 3,
        'Geologist': 4,
        'Pilot': 5,
    }
    idx = role_index.get(worker.getType().name, 0)
    worker.modSkill(8.0, idx)
    state.log.append(f'{worker.Name} studied {worker.getType().name} skills.')
    return True


def retire_worker(state: GameState, worker_index: int) -> bool:
    worker = _get_worker(state, worker_index)
    if worker is None:
        return False
    worker.Retire()
    worker.retired = True
    state.log.append(f'{worker.Name} retired from active duty.')
    return True


'Life support and farming actions'

def run_moxie(state: GameState, worker_index: int) -> bool:
    worker = _get_available_worker(state, worker_index)
    if worker is None:
        return False
    if not _spend_bundle(state, {'electricity': 25.0, 'CO2': 4.0}):
        state.log.append('MOXIE requires 25 electricity and 4 CO2.')
        return False
    eff = _worker_efficiency(worker, 'Engineer')
    worker.SendToWork()
    _damage_worker(worker, 2.0)
    o2_gain = round(6.0 * eff, 1)
    add_resource(state, 'oxigen', o2_gain)
    state.log.append(f'{worker.Name} ran MOXIE: +{o2_gain} oxigen.')
    return True


def balance_atmosphere(state: GameState) -> bool:
    if not _spend_bundle(state, {'water': 10.0, 'electricity': 20.0}):
        state.log.append('Atmosphere processor needs 10 water and 20 electricity.')
        return False
    spend_resource(state, 'CO2', min(5.0, get_resource(state, 'CO2')))
    add_resource(state, 'oxigen', 8.0)
    add_resource(state, 'Hydrogen', 2.0)
    add_resource(state, 'Nitrogen', 2.0)
    state.log.append('Atmosphere balanced: +8 oxigen, +2 Hydrogen, +2 Nitrogen, -5 CO2.')
    return True


def run_hydroponics(state: GameState, worker_index: int, crop_name: str) -> bool:
    crop_map = {
        'lettuce': ('seed_Lettuce', 'lettuce'),
        'wheat': ('seed_Wheat', 'wheat'),
        'flax': ('seed_Flax', 'flax'),
        'sunflower': ('seed_sunflower', 'sunflower'),
    }
    key = crop_name.strip().lower()
    if key not in crop_map:
        state.log.append(f'Unknown crop: {crop_name}.')
        return False
    worker = _get_available_worker(state, worker_index)
    if worker is None:
        return False
    seed_key, harvest_key = crop_map[key]
    if not _spend_bundle(state, {seed_key: 2, 'water': 12.0, 'electricity': 15.0}):
        state.log.append(f'Hydroponics needs 2 {seed_key}, 12 water, and 15 electricity.')
        return False
    spend_resource(state, 'CO2', min(2.0, get_resource(state, 'CO2')))
    eff = _worker_efficiency(worker, 'Biologist')
    worker.SendToWork()
    _damage_worker(worker, 2.0)
    harvest = round(4.0 * eff, 1)
    o2_gain = round(1.5 * eff, 1)
    add_resource(state, harvest_key, harvest)
    add_resource(state, 'oxigen', o2_gain)
    add_resource(state, seed_key, 1)
    state.log.append(f'{worker.Name} harvested +{harvest} {harvest_key} and +{o2_gain} oxigen.')
    return True


def run_food_refinery(state: GameState, worker_index: int, crop_name: str) -> bool:
    key = crop_name.strip().lower()
    if key not in {'lettuce', 'wheat', 'sunflower', 'flax'}:
        state.log.append(f'Cannot refine {crop_name}.')
        return False
    worker = _get_available_worker(state, worker_index)
    if worker is None:
        return False
    if not _spend_bundle(state, {key: 5.0, 'electricity': 10.0}):
        state.log.append(f'Refinery needs 5 {key} and 10 electricity.')
        return False
    eff = _worker_efficiency(worker, 'Biologist')
    worker.SendToWork()
    _damage_worker(worker, 1.5)
    if key == 'flax':
        plastic_gain = round(6.0 * eff, 1)
        add_resource(state, 'plastic', plastic_gain)
        state.log.append(f'{worker.Name} refined flax into +{plastic_gain} plastic.')
    else:
        kcal_rates = {'lettuce': 9000.0, 'wheat': 16000.0, 'sunflower': 14000.0}
        food_gain = round(kcal_rates[key] * eff, 0)
        add_resource(state, 'food', food_gain)
        if key == 'sunflower':
            add_resource(state, 'fuel', round(2.0 * eff, 1))
        state.log.append(f'{worker.Name} refined {key} into +{food_gain} food Kcals.')
    return True


def feed_crew(state: GameState) -> bool:
    active = [w for w in state.workers if not getattr(w, 'retired', False) and w.getHealth() > 0]
    if not active:
        return False
    all_fed = True
    for worker in active:
        fed_food = spend_resource(state, 'food', 2000.0)
        fed_water = spend_resource(state, 'water', 2.5)
        if fed_food and fed_water:
            if worker.getHealth() < 100.0:
                worker.health = min(100.0, worker.getHealth() + 3.0)
        else:
            all_fed = False
            _damage_worker(worker, 12.0)
            state.log.append(f'Ration shortage! {worker.Name} took 12 damage.')
    if all_fed:
        state.log.append(f'Fed {len(active)} crew members.')
    return all_fed


'Mining and manufacturing actions'

def mine_resources(state: GameState, worker_index: int) -> bool:
    worker = _get_available_worker(state, worker_index)
    if worker is None:
        return False
    if not _spend_bundle(state, {'electricity': 15.0, 'fuel': 10.0}):
        state.log.append('Mining needs 15 electricity and 10 fuel.')
        return False
    rover_bonus = 1.5 if get_resource(state, 'rovers') >= 1 else 1.0
    eff = _worker_efficiency(worker, 'Geologist') * rover_bonus
    worker.SendToWork()
    _damage_worker(worker, 3.0)
    dirt_gain = round(35.0 * eff, 1)
    water_gain = round(15.0 * eff, 1)
    al_gain = round(6.0 * eff, 1)
    steel_gain = round(5.0 * eff, 1)
    sci_gain = round(8.0 * eff, 1)
    add_resource(state, 'dirt', dirt_gain)
    add_resource(state, 'water', water_gain)
    add_resource(state, 'aluminum', al_gain)
    add_resource(state, 'steel', steel_gain)
    state.science_points += sci_gain
    state.log.append(f'{worker.Name} mined +{dirt_gain} dirt, +{water_gain} water, +{al_gain} aluminum, +{steel_gain} steel.')
    return True


def refine_materials(state: GameState, worker_index: int, material_name: str) -> bool:
    key = material_name.strip().lower()
    recipes = {
        'glass': ({'dirt': 15.0, 'electricity': 15.0}, 'glass', 8.0),
        'aluminum': ({'dirt': 20.0, 'electricity': 20.0}, 'aluminum', 10.0),
        'steel': ({'dirt': 20.0, 'electricity': 20.0}, 'steel', 10.0),
        'plastic': ({'CO2': 5.0, 'Hydrogen': 5.0, 'electricity': 15.0}, 'plastic', 8.0),
    }
    if key not in recipes:
        state.log.append(f'Unknown material: {material_name}.')
        return False
    worker = _get_available_worker(state, worker_index)
    if worker is None:
        return False
    costs, output_key, base_yield = recipes[key]
    if not _spend_bundle(state, costs):
        state.log.append(f'Insufficient inputs to refine {key}.')
        return False
    eff = _worker_efficiency(worker, 'Engineer')
    worker.SendToWork()
    _damage_worker(worker, 2.0)
    amount = round(base_yield * eff, 1)
    add_resource(state, output_key, amount)
    state.log.append(f'{worker.Name} refined +{amount} {output_key}.')
    return True


def produce_fuel(state: GameState, worker_index: int) -> bool:
    worker = _get_available_worker(state, worker_index)
    if worker is None:
        return False
    if not _spend_bundle(state, {'CO2': 6.0, 'Hydrogen': 8.0, 'electricity': 20.0}):
        state.log.append('Fuel synthesis needs 6 CO2, 8 Hydrogen, and 20 electricity.')
        return False
    eff = _worker_efficiency(worker, 'Engineer')
    worker.SendToWork()
    _damage_worker(worker, 2.0)
    fuel_gain = round(18.0 * eff, 1)
    water_gain = round(4.0 * eff, 1)
    add_resource(state, 'fuel', fuel_gain)
    add_resource(state, 'water', water_gain)
    state.log.append(f'{worker.Name} synthesized +{fuel_gain} fuel and +{water_gain} water.')
    return True


def manufacture_item(state: GameState, worker_index: int, item_name: str) -> bool:
    key = item_name.strip().lower()
    blueprints = {
        'drones': {'aluminum': 15.0, 'plastic': 10.0, 'glass': 5.0, 'electricity': 20.0},
        'rovers': {'aluminum': 40.0, 'steel': 30.0, 'plastic': 15.0, 'glass': 10.0, 'electricity': 40.0},
        'cars': {'aluminum': 35.0, 'steel': 35.0, 'plastic': 20.0, 'glass': 15.0, 'electricity': 35.0},
        'trucks': {'aluminum': 50.0, 'steel': 60.0, 'plastic': 20.0, 'glass': 15.0, 'electricity': 50.0},
        'satellites': {'aluminum': 25.0, 'plastic': 15.0, 'glass': 20.0, 'electricity': 45.0},
        'rockets': {'aluminum': 120.0, 'steel': 100.0, 'plastic': 40.0, 'glass': 25.0, 'electricity': 100.0},
    }
    if key not in blueprints:
        state.log.append(f'Unknown item blueprint: {item_name}.')
        return False
    worker = _get_available_worker(state, worker_index)
    if worker is None:
        return False
    if not _spend_bundle(state, blueprints[key]):
        state.log.append(f'Insufficient materials to build {key}.')
        return False
    worker.SendToWork()
    _damage_worker(worker, 2.5)
    add_resource(state, key, 1)
    state.log.append(f'{worker.Name} manufactured 1 {key}.')
    return True


'Building and factory actions'

def construct_building(state: GameState, new_building: Any) -> bool:
    power_cost = float(getattr(new_building, 'production_cost', 50))
    costs = {'electricity': power_cost, 'steel': 20.0, 'aluminum': 20.0}
    if not _spend_bundle(state, costs):
        state.log.append(f'Need {power_cost} electricity, 20 steel, and 20 aluminum to build {new_building.name}.')
        return False
    state.buildings.append(new_building)
    for storage_key in ('water', 'oxigen', 'electricity', 'food'):
        expand_resource_max(state, storage_key, 250.0)
    state.log.append(f'Constructed {new_building.name} (+250 storage caps).')
    return True


def operate_factory(state: GameState, factory_index: int, worker_indices: List[int]) -> bool:
    if not (0 <= factory_index < len(state.buildings)):
        state.log.append('Invalid building index.')
        return False
    facility = state.buildings[factory_index]
    needed_workers = int(getattr(facility, 'number_of_workers', 1))
    unique_indices = list(dict.fromkeys(worker_indices))
    if len(unique_indices) < needed_workers:
        state.log.append(f'{facility.name} requires {needed_workers} workers.')
        return False
    crew_assigned = []
    for idx in unique_indices[:needed_workers]:
        worker = _get_available_worker(state, idx)
        if worker is None:
            return False
        crew_assigned.append(worker)
    power_cost = round(float(getattr(facility, 'production_cost', 40)) * 0.25, 1)
    if not _spend_bundle(state, {'electricity': power_cost, 'dirt': 15.0}):
        state.log.append(f'{facility.name} needs {power_cost} electricity and 15 dirt.')
        return False
    avg_eff = sum(_worker_efficiency(w, 'Engineer') for w in crew_assigned) / len(crew_assigned)
    safety = float(getattr(facility, 'safety_rating', 0.95))
    for worker in crew_assigned:
        worker.SendToWork()
        damage = 8.0 if random.random() > safety else 2.0
        _damage_worker(worker, damage)
    output = round(10.0 * avg_eff, 1)
    add_resource(state, 'steel', output)
    add_resource(state, 'aluminum', output)
    add_resource(state, 'plastic', round(output * 0.5, 1))
    state.log.append(f'{facility.name} produced +{output} steel, +{output} aluminum.')
    return True


def maintain_buildings(state: GameState) -> bool:
    if not state.buildings:
        state.log.append('No buildings to maintain.')
        return False
    total_maint = sum(float(getattr(b, 'maintenance_cost', 10)) for b in state.buildings)
    power_needed = round(total_maint * 0.2, 1)
    al_needed = float(len(state.buildings))
    if not _spend_bundle(state, {'electricity': power_needed, 'aluminum': al_needed}):
        state.log.append(f'Maintenance needs {power_needed} electricity and {al_needed} aluminum.')
        return False
    for bld in state.buildings:
        if hasattr(bld, 'safety_rating'):
            bld.safety_rating = min(1.0, round(bld.safety_rating + 0.02, 2))
    state.log.append(f'Maintained {len(state.buildings)} buildings.')
    return True


'Vehicle and mission actions'

def deploy_rover(state: GameState, worker_index: int) -> bool:
    if not has_resource(state, 'rovers', 1):
        state.log.append('No rovers available.')
        return False
    worker = _get_available_worker(state, worker_index)
    if worker is None:
        return False
    if not _spend_bundle(state, {'fuel': 12.0, 'electricity': 10.0}):
        state.log.append('Rover expedition needs 12 fuel and 10 electricity.')
        return False
    eff = _worker_efficiency(worker, 'Geologist')
    worker.SendToWork()
    _damage_worker(worker, 2.0)
    sci = round(25.0 * eff, 1)
    dirt_gain = round(12.0 * eff, 1)
    state.science_points += sci
    add_resource(state, 'dirt', dirt_gain)
    state.log.append(f'{worker.Name} drove rover expedition: +{sci} science, +{dirt_gain} dirt.')
    return True


def fly_drone(state: GameState, worker_index: int) -> bool:
    if not has_resource(state, 'drones', 1):
        state.log.append('No drones available.')
        return False
    worker = _get_available_worker(state, worker_index)
    if worker is None:
        return False
    if not _spend_bundle(state, {'fuel': 8.0, 'electricity': 8.0}):
        state.log.append('Drone flight needs 8 fuel and 8 electricity.')
        return False
    eff = _worker_efficiency(worker, 'Pilot')
    worker.SendToWork()
    _damage_worker(worker, 1.5)
    sci = round(20.0 * eff, 1)
    state.science_points += sci
    add_resource(state, 'seed_Lettuce', 1)
    add_resource(state, 'seed_Wheat', 1)
    state.log.append(f'{worker.Name} flew drone recon: +{sci} science, +2 seeds.')
    return True


def launch_satellite(state: GameState, worker_index: int) -> bool:
    worker = _get_available_worker(state, worker_index)
    if worker is None:
        return False
    if not _spend_bundle(state, {'satellites': 1, 'rockets': 1, 'fuel': 80.0, 'electricity': 50.0}):
        state.log.append('Satellite launch needs 1 satellite, 1 rocket, 80 fuel, and 50 electricity.')
        return False
    eff = _worker_efficiency(worker, 'Pilot')
    worker.SendToWork()
    _damage_worker(worker, 3.0)
    sci = round(150.0 * eff, 1)
    state.science_points += sci
    state.active_satellites += 1
    state.log.append(f'{worker.Name} launched satellite into orbit: +{sci} science.')
    return True


def launch_rocket(state: GameState, worker_index: int) -> bool:
    worker = _get_available_worker(state, worker_index)
    if worker is None:
        return False
    if not _spend_bundle(state, {'rockets': 1, 'fuel': 120.0, 'electricity': 60.0}):
        state.log.append('Rocket launch needs 1 rocket, 120 fuel, and 60 electricity.')
        return False
    eff = _worker_efficiency(worker, 'Pilot')
    worker.SendToWork()
    _damage_worker(worker, 4.0)
    sci = round(300.0 * eff, 1)
    state.science_points += sci
    add_resource(state, 'water', 200.0)
    add_resource(state, 'food', 50000.0)
    state.log.append(f'{worker.Name} completed rocket mission: +{sci} science and orbital resupply.')
    return True


'Turn progression'

def advance_sol(state: GameState) -> None:
    state.sol += 1
    env = state.space
    tracked = ['food', 'water', 'oxigen', 'CO2', 'Nitrogen', 'electricity', 'steel', 'aluminum', 'plastic', 'dirt']
    gained = {k: 0.0 for k in tracked}
    spent = {k: 0.0 for k in tracked}

    active = [w for w in state.workers if not getattr(w, 'retired', False) and w.getHealth() > 0]
    people_count = len(active)
    total_space = max(1, sum(int(getattr(b, 'space_size', 1)) for b in state.buildings))

    ordered_buildings = sorted(
        state.buildings,
        key=lambda b: 0 if getattr(b, 'type_of_building', '') == 'Power' else 1,
    )

    for bld in ordered_buildings:
        inputs = dict(getattr(bld, 'daily_inputs', {}))
        outputs = dict(getattr(bld, 'daily_outputs', {}))
        safety = float(getattr(bld, 'safety_rating', 1.0))

        if inputs and not _spend_bundle(state, inputs):
            state.log.append(f'{bld.name} offline today (missing inputs).')
            continue

        for res_name, amt in inputs.items():
            if res_name in spent:
                spent[res_name] += amt

        for res_name, amt in outputs.items():
            scale = env['solar_multiplier'] if res_name == 'electricity' else 1.0
            produced = round(amt * safety * scale, 1)
            add_resource(state, res_name, produced)
            if res_name in gained:
                gained[res_name] += produced

    if state.active_satellites > 0:
        sat_power = round(state.active_satellites * 20.0 * env['solar_multiplier'], 1)
        add_resource(state, 'electricity', sat_power)
        gained['electricity'] += sat_power

    space_power_cost = round(total_space * env['power_per_space'], 1)
    space_o2_cost = round(total_space * env['o2_leak_per_space'], 2)
    space_n2_cost = round(total_space * env['n2_leak_per_space'], 2)

    if spend_resource(state, 'electricity', space_power_cost):
        spent['electricity'] += space_power_cost
    else:
        actual = get_resource(state, 'electricity')
        spend_resource(state, 'electricity', actual)
        spent['electricity'] += actual
        for worker in active:
            _damage_worker(worker, 6.0)
        state.log.append(f'Life-support power deficit across {total_space} space units!')

    o2_used = min(space_o2_cost, get_resource(state, 'oxigen'))
    spend_resource(state, 'oxigen', o2_used)
    spent['oxigen'] += o2_used

    n2_used = min(space_n2_cost, get_resource(state, 'Nitrogen'))
    spend_resource(state, 'Nitrogen', n2_used)
    spent['Nitrogen'] += n2_used

    for worker in active:
        worker.age += 1

        if spend_resource(state, 'food', 2000.0):
            spent['food'] += 2000.0
        else:
            _damage_worker(worker, 15.0)
            state.log.append(f'Food shortage (-2000 kcal needed)! {worker.Name} took 15 damage.')

        if spend_resource(state, 'water', 2.5):
            spent['water'] += 2.5
        else:
            _damage_worker(worker, 15.0)
            state.log.append(f'Water shortage (-2.5 L needed)! {worker.Name} took 15 damage.')

        if spend_resource(state, 'oxigen', 0.84):
            spent['oxigen'] += 0.84
        else:
            _damage_worker(worker, 20.0)
            state.log.append(f'Oxigen shortage (-0.84 kg needed)! {worker.Name} took 20 damage.')

        if spend_resource(state, 'electricity', 4.0):
            spent['electricity'] += 4.0

        add_resource(state, 'CO2', 1.0)
        gained['CO2'] += 1.0

        if not worker.isAvailable():
            worker.SendToRest()

    for bld in state.buildings:
        if hasattr(bld, 'safety_rating'):
            bld.safety_rating = max(0.5, round(bld.safety_rating - 0.01, 2))

    if random.random() < env['hazard_chance'] and active:
        event = random.choice(['dust_storm', 'micrometeorite', 'solar_flare'])
        target = random.choice(active)
        if event == 'dust_storm':
            loss = min(25.0, get_resource(state, 'electricity'))
            spend_resource(state, 'electricity', loss)
            spent['electricity'] += loss
            env_label = env['label']
            state.log.append(f'Space Event ({env_label}): Dust storm drained {loss:.1f} electricity.')
        elif event == 'micrometeorite':
            loss = min(6.0, get_resource(state, 'oxigen'))
            spend_resource(state, 'oxigen', loss)
            spent['oxigen'] += loss
            _damage_worker(target, 10.0)
            state.log.append(f'Space Event: Hull micrometeorite (-{loss:.1f} oxigen). {target.Name} took 10 damage.')
        elif event == 'solar_flare':
            target.modDebuff(8.0, 0)
            state.log.append(f'Space Event: Solar flare radiation hit {target.Name}.')

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
        f'Sol {state.sol} ({env_label} | Crew: {people_count} | Space: {total_space}): '
        f'Food {net_food:+.0f} kcal, O2 {net_o2:+.1f}, Water {net_water:+.1f}, Power {net_power:+.1f}'
    )


'Action router'

class ActionRouter:
    def __init__(self, state: GameState):
        self.state = state
        self.routes: Dict[str, Callable[..., Any]] = {
            'assign_job': assign_worker_job,
            'work': send_worker_to_work,
            'rest': send_worker_to_rest,
            'hospital': send_worker_to_hospital,
            'study': send_worker_to_study,
            'retire': retire_worker,
            'run_moxie': run_moxie,
            'balance_atmosphere': balance_atmosphere,
            'hydroponics': run_hydroponics,
            'food_refinery': run_food_refinery,
            'feed_crew': feed_crew,
            'mine': mine_resources,
            'refine_materials': refine_materials,
            'produce_fuel': produce_fuel,
            'manufacture': manufacture_item,
            'construct_building': construct_building,
            'operate_factory': operate_factory,
            'maintain_buildings': maintain_buildings,
            'deploy_rover': deploy_rover,
            'fly_drone': fly_drone,
            'launch_satellite': launch_satellite,
            'launch_rocket': launch_rocket,
            'advance_sol': advance_sol,
        }

    def available_actions(self) -> List[str]:
        return list(self.routes.keys())

    def execute(self, action_name: str, *args: Any, **kwargs: Any) -> Any:
        action = self.routes.get(action_name)
        if action is None:
            raise ValueError(f'Unknown action: {action_name}')
        return action(self.state, *args, **kwargs)
