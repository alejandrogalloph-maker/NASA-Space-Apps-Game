import math
import random
from typing import Any, Callable, Dict, List
import Resource_Class as resource_inventory
from Building_file import (
    all_buildings,
    ResourceBuilding,
    WaterExtractor,
    OxygenGenerator,
    CarbonDioxideGenerator,
    NitrogenGenerator,
    HydrogenGenerator,
    FoodFactory,
    PowerPlant,
    RadioisotopeThermoelectricGenerator,
    FuelRefinery,
    AluminumMine,
    SteelMill,
    SoilProcessor,
    PlasticFactory,
    GlassFactory,
    CarFactory,
    TruckFactory,
    RoverFactory,
    SatelliteFactory,
    RocketFactory,
    DroneFactory,
    Farm,
    IceMinor,
    Habitation,
    RecreationCenter,
    Canteen,
    LogisticsBuilding,
    ResearchBuilding,
    University,
    MedicalBay,
    Hospital,
    Graveyard,
    CommunicationsHub,
    SatelliteDish,
)
from hazards import HazardManager
from time_system import base_output_for, TimeEngine, advance_sol, advance_multiple_sols
from Worker_Class import Profession, RobotWorker, Worker


ROCKET_MAX_PAYLOAD_KG = 100_000.0
ROCKET_VEHICLE_WEIGHTS_KG = {
    "cars": 1500.0,
    "trucks": 5000.0,
    "rovers": 1000.0,
    "satellites": 600.0,
    "rockets": 25_000.0,
    "drones": 20.0,
}
ROCKET_CREW_WEIGHTS_KG = {"people": 80.0, "robots": 500.0}
DAILY_ACTION_LIMITS: Dict[str, int] = {
    "balance_atmosphere": 1,
    "maintain_buildings": 1,
    "feed_crew": 1,
    "resolve_crises": 1,
    "run_moxie": 1,
    "hydroponics": 1,
    "food_refinery": 1,
    "mine": 1,
    "refine_materials": 1,
    "produce_fuel": 1,
    "manufacture": 1,
    "deploy_rover": 1,
    "fly_drone": 1,
    "launch_satellite": 1,
    "launch_rocket": 1,
    "work": 1,
    "rest": 1,
    "hospital": 1,
    "study": 1,
    "maintain_robot": 1,
    "construct_building": 1,
}
RESUPPLY_PROFESSIONS = [
    Profession.Doctor,
    Profession.Engineer,
    Profession.Biologist,
    Profession.Geologist,
    Profession.Pilot,
]


def daily_action_limit(state: Any, action: str) -> int:
    if action == "run_research":
        return sum(isinstance(bld, ResearchBuilding) for bld in state.buildings)
    if action == "transfer_logistics":
        return sum(isinstance(bld, LogisticsBuilding) for bld in state.buildings)
    if action == "operate_factory":
        return sum(isinstance(bld, ResourceBuilding) for bld in state.buildings)
    if action == "configure_farm":
        return sum(isinstance(bld, Farm) for bld in state.buildings)
    if action == "toggle_building":
        return len(state.buildings)
    return DAILY_ACTION_LIMITS.get(action, 0)


SPACE_ENVIRONMENTS = {
    'orbit': {
        'label': 'Low Earth Orbit Station',
        'solar_multiplier': 1.35,
        'power_per_100m3': 3.5,
        'o2_leak_per_100m3': 0.25,
        'n2_leak_per_100m3': 0.20,
        'hazard_chance': 0.01,
    },
    'moon': {
        'label': 'Lunar South Pole Base',
        'solar_multiplier': 1.15,
        'power_per_100m3': 5.5,
        'o2_leak_per_100m3': 0.30,
        'n2_leak_per_100m3': 0.25,
        'hazard_chance': 0.01,
    },
    'mars': {
        'label': 'Mars Jezero Crater Base',
        'solar_multiplier': 0.85,
        'power_per_100m3': 4.5,
        'o2_leak_per_100m3': 0.20,
        'n2_leak_per_100m3': 0.15,
        'hazard_chance': 0.01,
    },
    'deep_space': {
        'label': 'Deep Space Transit Habitat',
        'solar_multiplier': 0.45,
        'power_per_100m3': 7.5,
        'o2_leak_per_100m3': 0.35,
        'n2_leak_per_100m3': 0.30,
        'hazard_chance': 0.01,
    },
}


FoodFactory.storage_capacity = 50000


class GameState:
    def __init__(
        self,
        resource_pool: Dict[str, Any],
        workers: List[Any],
        buildings: List[Any],
        space_key: str = 'mars',
    ):
        # The pool must share the module-level inventories that buildings use.
        for name, inventory in vars(resource_inventory).items():
            if isinstance(inventory, resource_inventory.resources):
                existing = resource_pool.setdefault(name, inventory)
                if existing is not inventory:
                    raise ValueError(
                        f"resource_pool['{name}'] is not the shared inventory in "
                        "Resource_Class; buildings and actions would disagree"
                    )

        self.resources = resource_pool
        for b in buildings:
            if b not in all_buildings:
                all_buildings.append(b)
        self.workers = workers
        self.buildings = buildings
        self.space_key = space_key if space_key in SPACE_ENVIRONMENTS else 'mars'
        self.space = SPACE_ENVIRONMENTS[self.space_key]
        self.sol = 1
        self.science_points = 0.0
        self.mined_units = 0.0
        self.daily_action_usage: Dict[str, int] = {}
        self.active_satellites = 0
        self.daily_report: Dict[str, Dict[str, float]] = {}
        self.time_engine = TimeEngine()
        self.hazard_manager = HazardManager()
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
        if getattr(worker, 'assigned_building', None) is not None:
            bld_name = worker.assigned_building.name
            state.log.append(f'{worker.Name} is staffed at {bld_name}. Unstaff first.')
        else:
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
    morale_factor = (
        max(0.8, min(1.2, 0.8 + float(getattr(worker, "morale", 50.0)) / 250.0))
        if not getattr(worker, "is_robot", False)
        else 1.0
    )
    return round((net_skill / 50.0) * hp_factor * role_bonus * morale_factor, 2)


def _damage_worker(worker: Any, amount: float) -> None:
    if not worker.takeDamage(amount):
        worker.health = 0.0
        worker.Available = False


'Worker actions'

def assign_worker_job(state: GameState, worker_index: int, profession_code: int) -> bool:
    worker = _get_worker(state, worker_index)
    if worker is None:
        return False
    assigned_bld = getattr(worker, 'assigned_building', None)
    if assigned_bld is not None:
        worker.assigned_building = None
        try:
            assigned_bld.remove_worker(worker)
        except ValueError:
            pass
        state.log.append(f'{worker.Name} removed from {assigned_bld.name} before job change.')
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
    if getattr(worker, 'assigned_building', None) is not None:
        state.log.append(f'{worker.Name} is staffed at {worker.assigned_building.name}. Unstaff first to rest.')
        return False
    worker.SendToRest()
    for i in range(len(worker.getDebuffs())):
        worker.modDebuff(-2.0, i)
    state.log.append(f'{worker.Name} rested (HP: {worker.getHealth():.1f}).')
    return True


def send_worker_to_hospital(state: GameState, worker_index: int) -> bool:
    worker = _get_available_worker(state, worker_index)
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
    worker = _get_available_worker(state, worker_index)
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


def train_worker_university(state: GameState, building_index: int, worker_index: int, profession_name: str) -> bool:
    if not (0 <= building_index < len(state.buildings)):
        state.log.append('Invalid building index.')
        return False
    uni = state.buildings[building_index]
    if not isinstance(uni, University):
        state.log.append(f'{uni.name} is not a University.')
        return False
    worker = _get_available_worker(state, worker_index)
    if worker is None:
        return False
    formatted = profession_name.strip().capitalize()
    try:
        ok = uni.train_worker(worker, formatted)
    except ValueError as err:
        state.log.append(str(err))
        return False
    if not ok:
        state.log.append(f'{uni.name} could not train {worker.Name} (check staffing, 5 research, 20 electricity, 5 food).')
        return False
    state.log.append(f'{uni.name} trained {worker.Name} as {formatted}.')
    return True


def retire_worker(state: GameState, worker_index: int) -> bool:
    worker = _get_worker(state, worker_index)
    if worker is None:
        return False
    assigned_bld = getattr(worker, 'assigned_building', None)
    if assigned_bld is not None:
        worker.assigned_building = None
        try:
            assigned_bld.remove_worker(worker)
        except ValueError:
            pass
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
    active = [
        w for w in state.workers
        if not getattr(w, 'is_robot', False)
        and not getattr(w, 'retired', False)
        and w.getHealth() > 0
    ]
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
    state.mined_units += dirt_gain + water_gain + al_gain + steel_gain
    state.log.append(f'{worker.Name} mined +{dirt_gain} dirt, +{water_gain} water, +{al_gain} aluminum, +{steel_gain} steel.')
    return True


def staff_all_buildings(state: GameState) -> bool:
    """Assign available specialists to every building's minimum profession needs."""
    available_by_profession: Dict[str, List[Any]] = {}
    for worker in state.workers:
        if worker.isAvailable():
            available_by_profession.setdefault(worker.getType().name, []).append(worker)

    assignments: List[tuple[Any, Any]] = []
    for facility in state.buildings:
        for profession, (minimum, _) in type(facility).required_professions.items():
            current = facility._profession_counts().get(profession, 0)
            for _ in range(max(0, minimum - current)):
                candidates = available_by_profession.get(profession, [])
                if not candidates:
                    state.log.append(
                        f"Cannot staff every building: not enough available {profession} specialists."
                    )
                    return False
                assignments.append((facility, candidates.pop(0)))

    for facility, worker in assignments:
        facility.assign_worker(worker)
        worker.assigned_building = facility
        state.log.append(f"{worker.Name} ({worker.getType().name}) staffed at {facility.name}.")

    state.log.append(
        f"Staffed all buildings to their minimum profession requirements ({len(assignments)} new assignments)."
    )
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

def build_from_catalog(building_key: str) -> Any:
    key = building_key.strip().lower()
    catalog = {
        'power': lambda: PowerPlant('Solar Power Plant', safety_rating=95),
        'rtg': lambda: RadioisotopeThermoelectricGenerator(
            'Radioisotope Thermoelectric Generator', safety_rating=99
        ),
        'water': lambda: WaterExtractor('Water Extractor', safety_rating=92),
        'iceminer': lambda: IceMinor('Ice Mining Facility', safety_rating=90),
        'oxygen': lambda: OxygenGenerator('Oxygen Generator', safety_rating=95),
        'co2': lambda: CarbonDioxideGenerator('CO2 Scrubber', safety_rating=94),
        'nitrogen': lambda: NitrogenGenerator('Nitrogen Generator', safety_rating=94),
        'hydrogen': lambda: HydrogenGenerator('Hydrogen Generator', safety_rating=92),
        'food': lambda: FoodFactory('Food Factory', safety_rating=96),
        'fuel': lambda: FuelRefinery('Fuel Refinery', safety_rating=91),
        'aluminum': lambda: AluminumMine('Aluminum Mine', safety_rating=90),
        'steel': lambda: SteelMill('Steel Mill', safety_rating=89),
        'soil': lambda: SoilProcessor('Soil Processor', safety_rating=93),
        'plastic': lambda: PlasticFactory('Plastic Factory', safety_rating=92),
        'glass': lambda: GlassFactory('Glass Factory', safety_rating=93),
        'farm_lettuce': lambda: Farm('Lettuce Farm', crop='lettuce', product_type='crop', safety_rating=96),
        'farm_wheat': lambda: Farm('Wheat Farm', crop='wheat', product_type='crop', safety_rating=96),
        'farm_flax': lambda: Farm('Flax Farm', crop='flax', product_type='crop', safety_rating=96),
        'farm_sunflower': lambda: Farm('Sunflower Farm', crop='sunflower', product_type='crop', safety_rating=96),
        'car_factory': lambda: CarFactory('Car Factory', safety_rating=90),
        'truck_factory': lambda: TruckFactory('Truck Factory', safety_rating=90),
        'rover_factory': lambda: RoverFactory('Rover Factory', safety_rating=92),
        'satellite_factory': lambda: SatelliteFactory('Satellite Factory', safety_rating=94),
        'rocket_factory': lambda: RocketFactory('Rocket Factory', safety_rating=90),
        'drone_factory': lambda: DroneFactory('Drone Factory', safety_rating=93),
        'habitation': lambda: Habitation('Habitation Dome', safety_rating=98),
        'recreation': lambda: RecreationCenter('Recreation Center', safety_rating=98),
        'canteen': lambda: Canteen('Colony Canteen', safety_rating=97),
        'logistics': lambda: LogisticsBuilding('Logistics Hub', safety_rating=96, transfer_amount=25000),
        'research': lambda: ResearchBuilding('Research Lab', safety_rating=96),
        'university': lambda: University('Colony University', safety_rating=97),
        'medical_bay': lambda: MedicalBay('Medical Bay', safety_rating=97),
        'hospital': lambda: Hospital('Colony Hospital', safety_rating=98),
        'graveyard': lambda: Graveyard('Memorial Grounds', safety_rating=100),
        'comms_hub': lambda: CommunicationsHub('Communications Hub', safety_rating=96),
        'satellite_dish': lambda: SatelliteDish('Satellite Dish', safety_rating=95),
    }
    factory_fn = catalog.get(key)
    if factory_fn is None:
        return None
    return factory_fn()


def construct_building(state: GameState, new_building: Any) -> bool:
    if isinstance(new_building, str):
        resolved = build_from_catalog(new_building)
        if resolved is None:
            state.log.append(f'Unknown building type: {new_building}.')
            return False
        new_building = resolved
    power_cost = round(float(getattr(new_building, 'production_cost', 500)) * 0.05, 1)
    costs = {'electricity': power_cost, 'steel': 20.0, 'aluminum': 20.0}
    if not _spend_bundle(state, costs):
        state.log.append(f'Need {power_cost} electricity, 20 steel, and 20 aluminum to build {new_building.name}.')
        return False
    state.buildings.append(new_building)
    if new_building not in all_buildings:
        all_buildings.append(new_building)
    for storage_key in ('water', 'oxigen', 'electricity', 'food'):
        expand_resource_max(state, storage_key, 250.0)
    state.log.append(f'Constructed {new_building.name} (+250 storage caps). Assign required workers with staff_building.')
    return True


def toggle_building(state: GameState, building_index: int) -> bool:
    if not (0 <= building_index < len(state.buildings)):
        state.log.append('Invalid building index.')
        return False
    bld = state.buildings[building_index]
    if bld.is_on:
        bld.turn_off()
        state.log.append(f'{bld.name} turned Off.')
    else:
        bld.turn_on()
        state.log.append(f'{bld.name} turned On.')
    return True


def assign_building_worker(state: GameState, building_index: int, worker_index: int) -> bool:
    if not (0 <= building_index < len(state.buildings)):
        state.log.append('Invalid building index.')
        return False
    worker = _get_available_worker(state, worker_index)
    if worker is None:
        return False
    bld = state.buildings[building_index]
    try:
        bld.assign_worker(worker)
        worker.assigned_building = bld
        state.log.append(f'{worker.Name} ({worker.getType().name}) staffed at {bld.name}.')
        return True
    except ValueError as err:
        state.log.append(str(err))
        return False


def unassign_building_worker(state: GameState, building_index: int, worker_index: int) -> bool:
    if not (0 <= building_index < len(state.buildings)):
        state.log.append('Invalid building index.')
        return False
    if not (0 <= worker_index < len(state.workers)):
        state.log.append('Invalid worker index.')
        return False
    bld = state.buildings[building_index]
    worker = state.workers[worker_index]
    if worker not in bld.workers:
        state.log.append(f'{worker.Name} is not assigned to {bld.name}.')
        return False
    worker.assigned_building = None
    bld.remove_worker(worker)
    state.log.append(f'{worker.Name} unassigned from {bld.name} and now Ready.')
    return True


def operate_factory(state: GameState, factory_index: int, worker_indices: List[int]) -> bool:
    if not (0 <= factory_index < len(state.buildings)):
        state.log.append('Invalid building index.')
        return False
    facility = state.buildings[factory_index]
    if not isinstance(facility, ResourceBuilding):
        state.log.append(f'{facility.name} is not a production building.')
        return False
    if not facility.is_on:
        state.log.append(f'{facility.name} is turned Off.')
        return False
    unique_indices = list(dict.fromkeys(worker_indices))
    if not unique_indices:
        state.log.append(f'Provide at least 1 worker index for {facility.name}.')
        return False
    crew_assigned = []
    for idx in unique_indices:
        worker = _get_available_worker(state, idx)
        if worker is None:
            return False
        crew_assigned.append(worker)
    if not spend_resource(state, 'electricity', 15.0):
        state.log.append(f'{facility.name} needs 15 electricity to run manual shift.')
        return False
    avg_eff = sum(_worker_efficiency(w, 'Engineer') for w in crew_assigned) / len(crew_assigned)
    safety = float(getattr(facility, 'safety_rating', 90))
    safety_ratio = safety / 100.0 if safety > 1.0 else safety
    for worker in crew_assigned:
        worker.SendToWork()
        damage = 8.0 if random.random() > safety_ratio else 2.0
        _damage_worker(worker, damage)
    base_out = base_output_for(facility)
    storage = facility._get_storage(facility.resource_attribute)
    prev = storage.getResources()
    storage.addResources(round(base_out * avg_eff, 1))
    produced = round(storage.getResources() - prev, 1)
    state.log.append(f'{facility.name} stored +{produced} {facility.resource_attribute} locally.')
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
            bld.safety_rating = min(100, bld.safety_rating + 4)
    state.log.append(f'Maintained {len(state.buildings)} buildings.')
    return True


def maintain_robot(state: GameState, worker_index: int, material: str) -> bool:
    if not (0 <= worker_index < len(state.workers)):
        state.log.append('Invalid robot index.')
        return False
    robot = state.workers[worker_index]
    if not getattr(robot, 'is_robot', False):
        state.log.append(f'{robot.Name} is not a robot.')
        return False
    if getattr(robot, 'retired', False) or robot.getHealth() <= 0:
        state.log.append(f'{robot.Name} cannot be maintained while inactive.')
        return False
    material_name = str(material).lower()
    if material_name not in ('steel', 'aluminum'):
        state.log.append('Robot maintenance requires steel or aluminum.')
        return False
    if robot.getHealth() >= 100.0:
        state.log.append(f'{robot.Name} is already at full health.')
        return False
    if not spend_resource(state, material_name, 1.0):
        state.log.append(f'Not enough {material_name} to maintain {robot.Name}.')
        return False
    robot.health = min(100.0, robot.getHealth() + 10.0)
    state.log.append(
        f'Maintained {robot.Name} using 1 {material_name} (+10% health; now {robot.getHealth():.0f}%).'
    )
    return True


def run_research_lab(state: GameState, building_index: int, points: int = 1) -> bool:
    if not (0 <= building_index < len(state.buildings)):
        state.log.append('Invalid building index.')
        return False
    lab = state.buildings[building_index]
    if not isinstance(lab, ResearchBuilding):
        state.log.append(f'{lab.name} is not a ResearchBuilding.')
        return False
    if not lab.is_operational():
        state.log.append(f'{lab.name} is not operational (requires On + 1 Engineer + 1 Biologist).')
        return False
    gained = lab.produce_research(max(1, int(points)))
    if gained <= 0:
        state.log.append(f'{lab.name} lacked inputs to produce research.')
        return False
    state.science_points += gained * 15.0
    state.log.append(f'{lab.name} generated +{gained} research points (+{gained * 15.0:.1f} science).')
    return True


def transfer_logistics(state: GameState) -> bool:
    resource_buildings = [b for b in state.buildings if isinstance(b, ResourceBuilding)]
    hubs = [b for b in state.buildings if isinstance(b, LogisticsBuilding) and b.is_operational()]
    if not hubs:
        state.log.append('No operational LogisticsBuilding (requires On + 1 Pilot).')
        return False
    total_moved: Dict[str, float] = {}
    for hub in hubs:
        moved = hub.process_turn(resource_buildings)
        for k, v in moved.items():
            total_moved[k] = total_moved.get(k, 0.0) + v
    if not total_moved:
        state.log.append('Logistics hubs found no local stockpiles to transfer.')
        return False
    summary = ', '.join(f'+{v:.1f} {k}' for k, v in total_moved.items())
    state.log.append(f'Logistics transfer complete: {summary}.')
    return True


'Vehicle, mission, and crisis actions'

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


def launch_rocket(
    state: GameState,
    worker_index: int,
    payload: Dict[str, Any] | None = None,
) -> bool:
    worker = _get_available_worker(state, worker_index)
    if worker is None:
        return False
    cargo = {"water": 200.0, "food": 50000.0} if payload is None else payload
    if not isinstance(cargo, dict):
        state.log.append("Rocket payload must be an object of item quantities.")
        return False

    payload_weight = 0.0
    normalized_cargo: Dict[str, float] = {}
    for name, amount in cargo.items():
        try:
            quantity = float(amount)
        except (TypeError, ValueError):
            state.log.append(f"Invalid rocket payload quantity for {name}.")
            return False
        if not math.isfinite(quantity) or quantity < 0:
            state.log.append(f"Invalid rocket payload quantity for {name}.")
            return False
        if name in ROCKET_CREW_WEIGHTS_KG:
            weight = ROCKET_CREW_WEIGHTS_KG[name]
            if not quantity.is_integer():
                state.log.append(f"Rocket payload quantity for {name} must be a whole number.")
                return False
        elif name in ROCKET_VEHICLE_WEIGHTS_KG:
            weight = ROCKET_VEHICLE_WEIGHTS_KG[name]
            if not quantity.is_integer():
                state.log.append(f"Rocket payload quantity for {name} must be a whole number.")
                return False
        elif name in state.resources and name != "research":
            weight = 1.0
        else:
            state.log.append(f"Unsupported rocket payload item: {name}.")
            return False
        if quantity:
            normalized_cargo[name] = quantity
            payload_weight += quantity * weight

    if payload_weight > ROCKET_MAX_PAYLOAD_KG:
        state.log.append(
            f"Rocket cannot launch: payload is {payload_weight:,.1f} kg; "
            f"maximum is {ROCKET_MAX_PAYLOAD_KG:,.0f} kg (100 tonnes)."
        )
        return False

    people_count = int(normalized_cargo.get("people", 0))
    robot_count = int(normalized_cargo.get("robots", 0))
    total_people = sum(not getattr(unit, "is_robot", False) for unit in state.workers)
    total_robots = sum(getattr(unit, "is_robot", False) for unit in state.workers)
    if total_people + people_count > 50 or total_robots + robot_count > 100:
        state.log.append("Rocket payload exceeds the colony limits of 50 people or 100 robots.")
        return False

    for name, quantity in normalized_cargo.items():
        if name in state.resources and quantity > state.resources[name].getMaxResources() - state.resources[name].getResources():
            state.log.append(f"Not enough storage capacity for rocket payload: {name}.")
            return False

    if not _spend_bundle(state, {'rockets': 1, 'fuel': 120.0, 'electricity': 60.0}):
        state.log.append('Rocket launch needs 1 rocket, 120 fuel, and 60 electricity.')
        return False
    eff = _worker_efficiency(worker, 'Pilot')
    worker.SendToWork()
    _damage_worker(worker, 4.0)
    sci = round(300.0 * eff, 1)
    state.science_points += sci
    for name, quantity in normalized_cargo.items():
        if name in state.resources:
            add_resource(state, name, quantity)
    for _ in range(people_count):
        person = Worker(30 * 365)
        person.setType(random.choice(RESUPPLY_PROFESSIONS).value)
        state.workers.append(person)
    for index in range(robot_count):
        robot = RobotWorker(f"Resupply-Robot-{len(state.workers) + index + 1:03d}")
        robot.setType(random.choice(RESUPPLY_PROFESSIONS).value)
        state.workers.append(robot)
    payload_summary = ", ".join(
        f"{quantity:g} {name}" for name, quantity in normalized_cargo.items()
    ) or "no cargo"
    state.log.append(
        f"{worker.Name} launched a {payload_weight:,.1f} kg resupply rocket: "
        f"+{sci} science; delivered {payload_summary}."
    )
    return True


def resolve_crises(state: GameState) -> bool:
    if not state.hazard_manager.active_incidents:
        state.log.append('No active crises to resolve.')
        return False
    resolved_any = False
    for inc in list(state.hazard_manager.active_incidents):
        if inc.check_resolution(state):
            state.hazard_manager.active_incidents.remove(inc)
            resolved_any = True
    if not resolved_any:
        state.log.append('Missing required resources or ready specialists to resolve crisis.')
    return resolved_any


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
            'university_train': train_worker_university,
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
            'toggle_building': toggle_building,
            'staff_building': assign_building_worker,
            'staff_all_buildings': staff_all_buildings,
            'unstaff_building': unassign_building_worker,
            'operate_factory': operate_factory,
            'maintain_buildings': maintain_buildings,
            'maintain_robot': maintain_robot,
            'run_research': run_research_lab,
            'transfer_logistics': transfer_logistics,
            'deploy_rover': deploy_rover,
            'fly_drone': fly_drone,
            'launch_satellite': launch_satellite,
            'launch_rocket': launch_rocket,
            'resolve_crises': resolve_crises,
            'advance_sol': advance_sol,
            'advance_sols': advance_multiple_sols,
        }

    def available_actions(self) -> List[str]:
        return list(self.routes.keys())

    def execute(self, action_name: str, *args: Any, **kwargs: Any) -> Any:
        action = self.routes.get(action_name)
        if action is None:
            raise ValueError(f'Unknown action: {action_name}')
        limit = daily_action_limit(self.state, action_name)
        used = self.state.daily_action_usage.get(action_name, 0)
        if limit and used >= limit:
            self.state.log.append(
                f"{action_name.replace('_', ' ').capitalize()} daily limit reached ({limit} per Sol)."
            )
            return False
        result = action(self.state, *args, **kwargs)
        if result and limit:
            self.state.daily_action_usage[action_name] = used + 1
        return result
