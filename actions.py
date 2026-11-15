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
from time_system import BUILDING_BASE_OUTPUTS, TimeEngine, advance_sol, advance_multiple_sols


# Environment tuning is shared by colony instances; values affect the time simulation.
SPACE_ENVIRONMENTS = {
    'orbit': {
        'label': 'Low Earth Orbit Station',
        'solar_multiplier': 1.35,
        'power_per_100m3': 3.5,
        'o2_leak_per_100m3': 0.25,
        'n2_leak_per_100m3': 0.20,
        'hazard_chance': 0.20,
    },
    'moon': {
        'label': 'Lunar South Pole Base',
        'solar_multiplier': 1.15,
        'power_per_100m3': 5.5,
        'o2_leak_per_100m3': 0.30,
        'n2_leak_per_100m3': 0.25,
        'hazard_chance': 0.25,
    },
    'mars': {
        'label': 'Mars Jezero Crater Base',
        'solar_multiplier': 0.85,
        'power_per_100m3': 4.5,
        'o2_leak_per_100m3': 0.20,
        'n2_leak_per_100m3': 0.15,
        'hazard_chance': 0.25,
    },
    'deep_space': {
        'label': 'Deep Space Transit Habitat',
        'solar_multiplier': 0.45,
        'power_per_100m3': 7.5,
        'o2_leak_per_100m3': 0.35,
        'n2_leak_per_100m3': 0.30,
        'hazard_chance': 0.30,
    },
}


FoodFactory.storage_capacity = 50000


class GameState:
    """Keep the live colony simulation state and its supporting systems together."""

    def __init__(
        self,
        resource_pool: Dict[str, Any],
        workers: List[Any],
        buildings: List[Any],
        space_key: str = 'mars',
    ):
        """Initialize resources, people, buildings, location, time, hazards, and logs."""
        # Ensure research exists in both the resource module and this state's pool.
        if not hasattr(resource_inventory, 'research'):
            resource_inventory.research = resource_inventory.resources(0, 10000)
        if 'research' not in resource_pool:
            resource_pool['research'] = resource_inventory.research

        self.resources = resource_pool
        self.workers = workers
        self.buildings = buildings
        self.space_key = space_key if space_key in SPACE_ENVIRONMENTS else 'mars'
        self.space = SPACE_ENVIRONMENTS[self.space_key]
        self.sol = 1
        self.science_points = 0.0
        self.active_satellites = 0
        self.daily_report: Dict[str, Dict[str, float]] = {}
        self.time_engine = TimeEngine()
        self.hazard_manager = HazardManager()
        self.log: List[str] = []


'Resource management'

def get_resource(state: GameState, name: str) -> float:
    """Read a resource amount, returning zero when the colony lacks that resource."""
    res = state.resources.get(name)
    if res is None:
        return 0.0
    return res.getResources()


def has_resource(state: GameState, name: str, amount: float) -> bool:
    """Check whether the colony currently holds at least the requested amount."""
    return get_resource(state, name) >= amount


def spend_resource(state: GameState, name: str, amount: float) -> bool:
    """Subtract a resource amount when that resource exists and has enough stock."""
    res = state.resources.get(name)
    if res is None:
        return False
    return res.SubtractResources(amount)


def add_resource(state: GameState, name: str, amount: float) -> bool:
    """Add to a known resource inventory and report whether it was found."""
    res = state.resources.get(name)
    if res is None:
        return False
    res.addResources(amount)
    return True


def expand_resource_max(state: GameState, name: str, amount: float) -> bool:
    """Increase a known resource inventory's storage capacity."""
    res = state.resources.get(name)
    if res is None:
        return False
    res.AddMax(amount)
    return True


def _spend_bundle(state: GameState, costs: Dict[str, float]) -> bool:
    """Check every input first, then deduct the full recipe without partial spending."""
    for name, amount in costs.items():
        if not has_resource(state, name, amount):
            return False
    for name, amount in costs.items():
        spend_resource(state, name, amount)
    return True


def _get_worker(state: GameState, worker_index: int) -> Any:
    """Return a living, non-retired worker by index or record why lookup failed."""
    if not (0 <= worker_index < len(state.workers)):
        state.log.append('Invalid worker index.')
        return None
    worker = state.workers[worker_index]
    if getattr(worker, 'retired', False) or worker.getHealth() <= 0:
        state.log.append(f'{worker.Name} is inactive.')
        return None
    return worker


def _get_available_worker(state: GameState, worker_index: int) -> Any:
    """Return an active worker only if they are currently available for an action."""
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
    """Combine role skill, debuffs, health, and a matching-profession bonus."""
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
    """Apply damage and explicitly mark a defeated worker unavailable."""
    if not worker.takeDamage(amount):
        worker.health = 0.0
        worker.Available = False


'Worker actions'

def assign_worker_job(state: GameState, worker_index: int, profession_code: int) -> bool:
    """Change a worker's profession, unstaffing them first if necessary."""
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
    """Run a general shift that converts worker efficiency into electricity."""
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
    """Rest an unstaffed worker and reduce each of their debuffs."""
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
    """Spend water and electricity to heal a worker and reduce their debuffs."""
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
    """Spend electricity to study and improve the worker's profession skill."""
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
    """Validate indices and delegate profession training to a University."""
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
    """Unstaff and permanently retire a selected worker."""
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
    """Consume electricity and carbon dioxide to produce oxygen with a worker."""
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
    """Spend water and electricity to adjust the colony's atmospheric resources."""
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
    """Spend seeds, water, and electricity to grow a crop and produce oxygen."""
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
    """Convert harvested crops to food, or flax to plastic, using a worker."""
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
    """Consume food and water per active worker; ration shortages cause damage."""
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
    """Use a geologist's shift and supplies to gather raw materials and science."""
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
    """Apply a material recipe and convert inputs into refined building materials."""
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
    """Synthesize fuel and water from carbon dioxide, hydrogen, and electricity."""
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
    """Check a blueprint, consume its materials, and add one manufactured item."""
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
    """Create the building associated with a catalog key, or return None if unknown."""
    key = building_key.strip().lower()
    catalog = {
        'power': lambda: PowerPlant('Solar Power Plant', safety_rating=95),
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
    """Pay construction inputs, add the building, and expand selected colony storage."""
    if isinstance(new_building, str):
        resolved = build_from_catalog(new_building)
        if resolved is None:
            state.log.append(f'Unknown building type: {new_building}.')
            return False
        new_building = resolved
    power_cost = round(float(getattr(new_building, 'production_cost', 500)) * 0.05, 1)
    costs = {'electricity': power_cost, 'steel': 20.0, 'aluminum': 20.0}
    if not _spend_bundle(state, costs):
        if new_building in all_buildings:
            all_buildings.remove(new_building)
        state.log.append(f'Need {power_cost} electricity, 20 steel, and 20 aluminum to build {new_building.name}.')
        return False
    state.buildings.append(new_building)
    for storage_key in ('water', 'oxigen', 'electricity', 'food'):
        expand_resource_max(state, storage_key, 250.0)
    state.log.append(f'Constructed {new_building.name} (+250 storage caps). Assign required workers with staff_building.')
    return True


def toggle_building(state: GameState, building_index: int) -> bool:
    """Switch a colony building between its on and off states."""
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
    """Assign a compatible available worker to a building and record the assignment."""
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
    """Remove a worker from a building and return them to the available workforce."""
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
    """Run a staffed production building with a manual crew and safety-based risk."""
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
    cls_name = type(facility).__name__
    base_out = BUILDING_BASE_OUTPUTS.get(cls_name, 10.0)
    storage = facility._get_storage(facility.resource_attribute)
    prev = storage.getResources()
    storage.addResources(round(base_out * avg_eff, 1))
    produced = round(storage.getResources() - prev, 1)
    state.log.append(f'{facility.name} stored +{produced} {facility.resource_attribute} locally.')
    return True


def maintain_buildings(state: GameState) -> bool:
    """Spend maintenance supplies and improve each building's safety rating."""
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
            if bld.safety_rating <= 1.0:
                bld.safety_rating = min(1.0, round(bld.safety_rating + 0.04, 2))
            else:
                bld.safety_rating = min(100, bld.safety_rating + 4)
    state.log.append(f'Maintained {len(state.buildings)} buildings.')
    return True


def run_research_lab(state: GameState, building_index: int, points: int = 1) -> bool:
    """Run an operational research lab and convert its output to science points."""
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
    """Use operational logistics hubs to move local producer stock to colony stores."""
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
    """Spend rover mission supplies to gain science and collected dirt."""
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
    """Spend drone mission supplies to gain science and discover crop seeds."""
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
    """Consume a satellite, rocket, fuel, and power to launch and gain science."""
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
    """Spend launch supplies and reward the colony with research and resupply."""
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


def resolve_crises(state: GameState) -> bool:
    """Ask each active incident whether current resources and specialists resolve it."""
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
    """Map external action names to their functions and execute them for a state."""

    def __init__(self, state: GameState):
        """Register the supported worker, building, mission, and time actions."""
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
            'unstaff_building': unassign_building_worker,
            'operate_factory': operate_factory,
            'maintain_buildings': maintain_buildings,
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
        """List the action names accepted by this router."""
        return list(self.routes.keys())

    def execute(self, action_name: str, *args: Any, **kwargs: Any) -> Any:
        """Run a named action with the router's game state as its first argument."""
        action = self.routes.get(action_name)
        if action is None:
            raise ValueError(f'Unknown action: {action_name}')
        return action(self.state, *args, **kwargs)
