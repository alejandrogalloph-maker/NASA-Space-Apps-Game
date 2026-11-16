import math
import random
from typing import Any, Callable, Dict, List
import Resource_Class as resource_inventory
from Building_file import (
    all_buildings,
    ResourceBuilding,
    RobotFactory,
    ServiceBuilding,
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
from Worker_Class import Profession, RobotWorker


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
    "mine": 1,
    "refine_materials": 1,
    "produce_fuel": 1,
    "manufacture": 1,
    "deploy_rover": 1,
    "fly_drone": 1,
    "launch_satellite": 1,
    "launch_rocket": 1,
    "fabricate_robot": 1,
    "work": 1,
    "rest": 1,
    "hospital": 1,
    "study": 1,
    "maintain_robot": 1,
    "construct_building": 1,
    "process_harvest": 1,
    "hydroponics_rotation": 1,
    "manage_eva_suits": 2,
    "team_exploration": 1,
}
DIFFICULTY_PROFILES: Dict[str, Dict[str, Any]] = {
    "easy": {
        "label": "Easy",
        "cost_multiplier": 0.65,
        "action_multiplier": 2.0,
    },
    "normal": {
        "label": "Normal",
        "cost_multiplier": 1.0,
        "action_multiplier": 1.0,
    },
    "hard": {
        "label": "Hard",
        "cost_multiplier": 1.5,
        "action_multiplier": 0.75,
    },
}


def difficulty_profile(difficulty: str) -> Dict[str, Any]:
    """Resolve a difficulty name to its economy and action settings."""
    normalized = str(difficulty).strip().lower()
    if normalized not in DIFFICULTY_PROFILES:
        raise ValueError(f"Unknown difficulty: {difficulty}")
    return DIFFICULTY_PROFILES[normalized]
def daily_action_limit(state: Any, action: str) -> int:
    if ":" in action:
        action, _ = action.split(":", 1)
    if action == "run_research":
        base_limit = sum(isinstance(bld, ResearchBuilding) for bld in state.buildings)
    elif action == "transfer_logistics":
        base_limit = sum(isinstance(bld, LogisticsBuilding) for bld in state.buildings)
    elif action == "operate_factory":
        base_limit = sum(isinstance(bld, ResourceBuilding) for bld in state.buildings)
    elif action == "configure_farm":
        base_limit = sum(isinstance(bld, Farm) for bld in state.buildings)
    elif action == "toggle_building":
        base_limit = len(state.buildings)
    elif action == "boost_production":
        return 1
    else:
        base_limit = DAILY_ACTION_LIMITS.get(action, 0)
    if not base_limit:
        return 0
    profile = DIFFICULTY_PROFILES.get(getattr(state, "difficulty", "easy"), DIFFICULTY_PROFILES["easy"])
    return max(1, math.ceil(base_limit * profile["action_multiplier"]))


def daily_action_usage_key(action: str, args: tuple[Any, ...]) -> str:
    if action == "hydroponics" and len(args) > 1:
        return f"{action}:{str(args[1]).strip().lower()}"
    if action == "boost_production" and args:
        return f"{action}:{int(args[0])}"
    return action


def rocket_transit_sols(destination: str, launch_sol: int) -> int:
    """Approximate game-scaled travel time as the target moves around Earth."""
    cycles = {"moon": (29.53, 18.0, 8.0), "mars": (780.0, 75.0, 30.0)}
    cycle, base_sols, variation = cycles[destination]
    phase = 2.0 * math.pi * ((launch_sol - 1) % cycle) / cycle
    return max(1, round(base_sols + variation * (1.0 - math.cos(phase)) / 2.0))


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
        difficulty: str = "easy",
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
        serviceable = [
            building for building in self.buildings
            if not isinstance(building, ServiceBuilding)
        ]
        for building in self.buildings:
            if isinstance(building, ServiceBuilding) and not building.maintenance_targets:
                building.maintenance_targets = serviceable[:building.max_serviceable_buildings]
        self.space_key = space_key if space_key in SPACE_ENVIRONMENTS else 'mars'
        self.space = SPACE_ENVIRONMENTS[self.space_key]
        self.difficulty = str(difficulty).strip().lower()
        profile = difficulty_profile(self.difficulty)
        for inventory in self.resources.values():
            if isinstance(inventory, resource_inventory.resources):
                inventory.cost_multiplier = float(profile["cost_multiplier"])
        self.sol = 1
        self.science_points = 0.0
        self.mined_units = 0.0
        self.daily_action_usage: Dict[str, int] = {}
        self.active_satellites = 0
        self.pending_rockets: List[Dict[str, Any]] = []
        self.next_rocket_id = 1
        self.daily_report: Dict[str, Dict[str, float]] = {}
        self.time_engine = TimeEngine()
        self.hazard_manager = HazardManager()
        self.hazard_manager.compute_risk_probability(self)
        self.crisis_events: List[Dict[str, Any]] = []
        self.resource_depletion_events: List[Dict[str, Any]] = []
        self.log: List[str] = []
        self.hydroponics_rotation_index = 0
        self.eva_suits = 0
        self.damaged_eva_suits = 0
        self.exploration_wear = {"car": 0.0, "drone": 0.0}


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
    return res.consumeResources(amount)


def add_resource(state: GameState, name: str, amount: float) -> bool:
    res = state.resources.get(name)
    if res is None:
        return False
    res.addResources(amount)
    return True


def process_harvest(state: GameState, worker_index: int) -> bool:
    """Process available full five-unit crop batches in one worker action."""
    worker = _get_available_worker(state, worker_index)
    if worker is None:
        return False

    crops = ("lettuce", "wheat", "flax", "sunflower")
    batches = {
        crop: int(get_resource(state, crop) // 5)
        for crop in crops
    }
    if not any(batches.values()):
        state.log.append("Process Plants needs at least 5 units of a harvested crop.")
        return False

    selected: List[str] = [
        crop for crop in crops for _ in range(batches[crop])
    ]
    while selected:
        costs: Dict[str, float] = {
            "electricity": 10.0 * len(selected),
        }
        for crop in selected:
            costs[crop] = costs.get(crop, 0.0) + 5.0
        if all(
            name in state.resources
            and state.resources[name].getResources()
            >= state.resources[name].required_amount(amount)
            for name, amount in costs.items()
        ):
            break
        selected.pop()
    if not selected:
        state.log.append("Process Plants needs 10 electricity and 5 units of a crop.")
        return False

    costs = {"electricity": 10.0 * len(selected)}
    for crop in selected:
        costs[crop] = costs.get(crop, 0.0) + 5.0
    if not _spend_bundle(state, costs):
        state.log.append("Process Plants could not pay its crop and electricity costs.")
        return False

    efficiency = _worker_efficiency(worker, "Biologist")
    worker.SendToWork()
    _damage_worker(worker, 1.5)
    food_gains: Dict[str, float] = {"lettuce": 9000.0, "wheat": 16000.0, "sunflower": 14000.0}
    processed: Dict[str, int] = {}
    for crop in selected:
        processed[crop] = processed.get(crop, 0) + 1
    for crop, count in processed.items():
        if crop == "flax":
            add_resource(state, "plastic", round(6.0 * efficiency * count, 1))
        else:
            add_resource(state, "food", round(food_gains[crop] * efficiency * count, 0))
            if crop == "sunflower":
                add_resource(state, "fuel", round(2.0 * efficiency * count, 1))

    detail = ", ".join(f"{count} {crop}" for crop, count in processed.items())
    state.log.append(
        f"{worker.Name} processed plants ({detail}) in one pass into food, plastic, and fuel."
    )
    return True


def staff_building_to_capacity(state: GameState, building_index: int) -> bool:
    """Fill one building's remaining slots with eligible available specialists."""
    if not (0 <= building_index < len(state.buildings)):
        state.log.append("Invalid building index.")
        return False
    facility = state.buildings[building_index]
    if facility.max_worker_capacity <= facility.number_of_workers:
        state.log.append(f"{facility.name} has no open worker slots.")
        return False
    assignments = 0
    while facility.number_of_workers < facility.max_worker_capacity:
        assigned = False
        counts = facility._profession_counts()
        for profession, (_, maximum) in type(facility).required_professions.items():
            if counts.get(profession, 0) >= maximum:
                continue
            worker = next(
                (
                    candidate for candidate in state.workers
                    if candidate.isAvailable()
                    and not getattr(candidate, "is_robot", False)
                    and candidate.getType().name == profession
                ),
                None,
            )
            if worker is None:
                worker = next(
                    (
                        candidate for candidate in state.workers
                        if candidate.isAvailable()
                        and getattr(candidate, "is_robot", False)
                    ),
                    None,
                )
            if worker is None:
                continue
            facility.assign_worker(worker)
            worker.assigned_building = facility
            assignments += 1
            assigned = True
            break
        if not assigned:
            break
    if assignments == 0:
        state.log.append(
            f"No eligible available specialists can fill more slots at {facility.name}."
        )
        return False
    state.log.append(
        f"Filled {assignments} worker slot(s) at {facility.name} "
        f"({facility.number_of_workers}/{facility.max_worker_capacity})."
    )
    return True


def expand_resource_max(state: GameState, name: str, amount: float) -> bool:
    res = state.resources.get(name)
    if res is None:
        return False
    res.AddMax(amount)
    return True


def _spend_bundle(state: GameState, costs: Dict[str, float]) -> bool:
    for name, amount in costs.items():
        inventory = state.resources.get(name)
        if inventory is None or inventory.getResources() < inventory.required_amount(amount):
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
        'Robot': 0,
    }
    job_name = worker.getType().name
    idx = role_index.get(job_name, 0)
    skills = worker.getSkills()
    debuffs = worker.getDebuffs()
    net_skill = max(10.0, skills[idx] - 0.5 * debuffs[idx])
    hp_factor = max(0.25, min(1.5, worker.getHealth() / 100.0))
    role_bonus = (
        1.5
        if preferred_job and (job_name == preferred_job or getattr(worker, "is_robot", False))
        else 1.0
    )
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
    if getattr(worker, "is_robot", False):
        state.log.append(f'{worker.Name} is a universal Robot and does not change profession.')
        return False
    if not getattr(worker, "is_robot", False) and worker.job.value == profession_code:
        state.log.append(f'{worker.Name} already has that profession.')
        return False
    assigned_bld = getattr(worker, 'assigned_building', None)
    if assigned_bld is not None:
        worker.assigned_building = None
        try:
            assigned_bld.remove_worker(worker)
        except ValueError:
            pass
        state.log.append(f'{worker.Name} removed from {assigned_bld.name} before job change.')
    elif worker.isAvailable():
        worker.SendToWork()
    worker.available_after_sol = state.sol + 1
    worker.setType(profession_code)
    state.log.append(
        f'{worker.Name} assigned to {worker.getType().name}; available after '
        f'Sol {state.sol + 1}.'
    )
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
    if state.sol < getattr(worker, "available_after_sol", 0):
        state.log.append(
            f'{worker.Name} is in reassignment cooldown until Sol '
            f'{worker.available_after_sol}.'
        )
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


def run_hydroponics_rotation(state: GameState, worker_index: int) -> bool:
    """Attempt the next crop in sequence and advance the rotation each time."""
    crops = ("lettuce", "wheat", "flax", "sunflower")
    crop = crops[state.hydroponics_rotation_index % len(crops)]
    state.hydroponics_rotation_index = (state.hydroponics_rotation_index + 1) % len(crops)
    usage_key = f"hydroponics:{crop}"
    crop_limit = daily_action_limit(state, usage_key)
    if state.daily_action_usage.get(usage_key, 0) >= crop_limit:
        state.log.append(f"Hydroponics rotation reached today's {crop} production limit.")
        return False
    if not run_hydroponics(state, worker_index, crop):
        return False
    state.daily_action_usage[usage_key] = state.daily_action_usage.get(usage_key, 0) + 1
    return True


def manage_eva_suits(state: GameState, operation: str) -> bool:
    """Create one EVA suit or repair one damaged suit from colony materials."""
    normalized = str(operation).strip().lower()
    if normalized == "create":
        costs = {
            "aluminum": 8.0,
            "plastic": 6.0,
            "glass": 3.0,
            "flax": 4.0,
            "electricity": 12.0,
        }
        if not _spend_bundle(state, costs):
            state.log.append(
                "Creating an EVA suit needs 8 aluminum, 6 plastic, 3 glass, "
                "4 flax, and 12 electricity."
            )
            return False
        state.eva_suits += 1
        state.log.append(f"Created an EVA suit. Ready suits: {state.eva_suits}.")
        return True
    if normalized == "repair":
        if state.damaged_eva_suits <= 0:
            state.log.append("There are no damaged EVA suits to repair.")
            return False
        costs = {"steel": 2.0, "plastic": 2.0, "electricity": 5.0}
        if not _spend_bundle(state, costs):
            state.log.append("Repairing an EVA suit needs 2 steel, 2 plastic, and 5 electricity.")
            return False
        state.damaged_eva_suits -= 1
        state.eva_suits += 1
        state.log.append(f"Repaired an EVA suit. Ready suits: {state.eva_suits}.")
        return True
    state.log.append("EVA suit operation must be 'create' or 'repair'.")
    return False


def team_exploration(state: GameState) -> bool:
    """Run a randomized surface expedition using a drone, car, and four EVA suits."""
    cars = state.resources["cars"]
    drones = state.resources["drones"]
    if cars.getResources() < 1 or drones.getResources() < 1:
        state.log.append("Team exploration requires one available car and one drone.")
        return False
    if state.exploration_wear["car"] >= 100 or state.exploration_wear["drone"] >= 100:
        state.log.append("A worn-out car or drone must be replaced before another expedition.")
        return False
    if state.eva_suits < 4:
        state.log.append("Team exploration requires four ready EVA suits.")
        return False
    if not _spend_bundle(state, {"fuel": 12.0, "electricity": 15.0}):
        state.log.append("Team exploration requires 12 fuel and 15 electricity.")
        return False

    outcome = random.choice(("sample_cache", "mineral_vein", "storm_detour"))
    suit_damage = random.randint(1, 3)
    state.eva_suits -= 4
    state.damaged_eva_suits += suit_damage
    state.eva_suits += 4 - suit_damage
    state.exploration_wear["car"] += random.uniform(12.0, 28.0)
    state.exploration_wear["drone"] += random.uniform(15.0, 35.0)
    worn_out = []
    for equipment, inventory in (("car", cars), ("drone", drones)):
        if state.exploration_wear[equipment] >= 100:
            inventory.SubtractResources(1)
            state.exploration_wear[equipment] = 0.0
            worn_out.append(equipment)

    if outcome == "sample_cache":
        science = round(random.uniform(25.0, 60.0), 1)
        water = round(random.uniform(10.0, 35.0), 1)
        state.science_points += science
        add_resource(state, "water", water)
        result = f"recovered +{water:g} water and +{science:g} science"
    elif outcome == "mineral_vein":
        science = round(random.uniform(15.0, 45.0), 1)
        aluminum = round(random.uniform(8.0, 25.0), 1)
        state.science_points += science
        add_resource(state, "aluminum", aluminum)
        state.mined_units += aluminum
        result = f"mapped a vein: +{aluminum:g} aluminum and +{science:g} science"
    else:
        science = round(random.uniform(5.0, 20.0), 1)
        state.science_points += science
        crew = [
            worker for worker in state.workers
            if not getattr(worker, "is_robot", False)
            and not getattr(worker, "retired", False)
            and worker.getHealth() > 0
        ]
        if crew:
            injured = random.choice(crew)
            _damage_worker(injured, random.uniform(4.0, 12.0))
            result = f"a storm forced a detour; {injured.Name} was injured and the team gained +{science:g} science"
        else:
            result = f"a storm forced a detour; the team gained +{science:g} science"
    state.log.append(
        f"Exploration team returned: {result}. Suit wear: {suit_damage}/4 suits "
        f"damaged; car wear {state.exploration_wear['car']:.0f}%, "
        f"drone wear {state.exploration_wear['drone']:.0f}%."
        + (f" Worn-out equipment scrapped: {', '.join(worn_out)}." if worn_out else "")
    )
    return True


def boost_building_production(state: GameState, building_index: int) -> bool:
    """Trade structural condition for a one-sol production boost."""
    if not 0 <= building_index < len(state.buildings):
        state.log.append("Invalid building index.")
        return False
    facility = state.buildings[building_index]
    if not isinstance(facility, ResourceBuilding):
        state.log.append(f"{facility.name} cannot boost resource production.")
        return False
    if not facility.is_operational():
        state.log.append(f"{facility.name} must be operational to boost production.")
        return False
    if facility.health < 15:
        state.log.append(f"{facility.name} is too damaged to safely boost production.")
        return False
    facility.health = max(0.0, facility.health - 10.0)
    facility.production_boost = max(facility.production_boost, 1.5)
    state.log.append(
        f"{facility.name} is overdriven for +50% production next Sol; "
        "structural health decreased by 10%."
    )
    return True


def set_maintenance_targets(
    state: GameState, service_index: int, target_indices: List[int]
) -> bool:
    if not 0 <= service_index < len(state.buildings):
        state.log.append("Invalid Service Building index.")
        return False
    service = state.buildings[service_index]
    if not isinstance(service, ServiceBuilding):
        state.log.append("Selected facility is not a Service Building.")
        return False
    if len(target_indices) > service.max_serviceable_buildings:
        state.log.append(
            f"{service.name} can maintain at most "
            f"{service.max_serviceable_buildings} buildings."
        )
        return False
    if len(set(target_indices)) != len(target_indices):
        state.log.append("A building cannot be assigned twice to the same Service Building.")
        return False
    targets = []
    for index in target_indices:
        if not 0 <= index < len(state.buildings):
            state.log.append("Invalid maintenance target index.")
            return False
        target = state.buildings[index]
        if isinstance(target, ServiceBuilding) or target is service:
            state.log.append("Service Buildings cannot maintain themselves or one another.")
            return False
        targets.append(target)
    service.maintenance_targets = targets
    state.log.append(
        f"{service.name} assigned to maintain {len(targets)} building(s): "
        f"{', '.join(target.name for target in targets) or 'none'}."
    )
    return True


def scrap_robot(state: GameState, worker_index: int) -> bool:
    if not 0 <= worker_index < len(state.workers):
        state.log.append("Invalid robot index.")
        return False
    robot = state.workers[worker_index]
    if not getattr(robot, "is_robot", False):
        state.log.append(f"{robot.Name} is not a robot and cannot be scrapped.")
        return False
    if getattr(robot, "assigned_building", None) is not None:
        assigned_building = robot.assigned_building
        assigned_building.remove_worker(robot)
        robot.assigned_building = None
    robot.Retire()
    robot.retired = True
    robot.powered_on = False
    state.log.append(
        f"{robot.Name} was scrapped. Future robot water and electricity upkeep is reduced."
    )
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
    available_robots: List[Any] = []
    for worker in state.workers:
        if worker.isAvailable():
            if getattr(worker, "is_robot", False):
                available_robots.append(worker)
            else:
                available_by_profession.setdefault(worker.getType().name, []).append(worker)

    assignments: List[tuple[Any, Any]] = []
    for facility in state.buildings:
        robot_slots = facility._profession_counts().get("Robot", 0)
        for profession, (minimum, _) in type(facility).required_professions.items():
            current = facility._profession_counts().get(profession, 0)
            missing = max(0, minimum - current)
            covered_by_robots = min(missing, robot_slots)
            robot_slots -= covered_by_robots
            for _ in range(missing - covered_by_robots):
                candidates = available_by_profession.get(profession, [])
                worker = candidates.pop(0) if candidates else (
                    available_robots.pop(0) if available_robots else None
                )
                if worker is None:
                    state.log.append(
                        f"Cannot staff every building: not enough available {profession} specialists."
                    )
                    return False
                assignments.append((facility, worker))

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


def fabricate_robot(state: GameState, worker_index: int) -> bool:
    factories = [
        building for building in state.buildings
        if isinstance(building, RobotFactory) and building.is_operational()
    ]
    if not factories:
        state.log.append("No operational Robot Factory is available.")
        return False
    active_robots = sum(
        getattr(worker, "is_robot", False)
        and not getattr(worker, "retired", False)
        and worker.getHealth() > 0
        for worker in state.workers
    )
    if active_robots >= 100:
        state.log.append("The colony has reached its limit of 100 active robots.")
        return False
    worker = _get_available_worker(state, worker_index)
    if worker is None:
        return False
    if not _spend_bundle(
        state, {"aluminum": 30.0, "steel": 20.0, "electricity": 40.0}
    ):
        state.log.append(
            "Robot fabrication needs 30 aluminum, 20 steel, and 40 electricity."
        )
        return False
    worker.SendToWork()
    _damage_worker(worker, 2.0)
    robot = RobotWorker(f"Colony-Robot-{len(state.workers) + 1:03d}")
    state.workers.append(robot)
    state.log.append(f"{worker.Name} fabricated {robot.Name} at the Robot Factory.")
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
        'farm_lettuce': lambda: Farm('Hydroponics Bay', crop='lettuce', product_type='crop', safety_rating=96),
        'farm_wheat': lambda: Farm('Hydroponics Bay', crop='wheat', product_type='crop', safety_rating=96),
        'farm_flax': lambda: Farm('Hydroponics Bay', crop='flax', product_type='crop', safety_rating=96),
        'farm_sunflower': lambda: Farm('Hydroponics Bay', crop='sunflower', product_type='crop', safety_rating=96),
        'car_factory': lambda: CarFactory('Car Factory', safety_rating=90),
        'truck_factory': lambda: TruckFactory('Truck Factory', safety_rating=90),
        'rover_factory': lambda: RoverFactory('Rover Factory', safety_rating=92),
        'satellite_factory': lambda: SatelliteFactory('Satellite Factory', safety_rating=94),
        'rocket_factory': lambda: RocketFactory('Rocket Factory', safety_rating=90),
        'drone_factory': lambda: DroneFactory('Drone Factory', safety_rating=93),
        'robot_factory': lambda: RobotFactory('Robot Factory', safety_rating=95),
        'service': lambda: ServiceBuilding('Maintenance Service Building', safety_rating=96),
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


def construct_building(state: GameState, worker_index: int, building_key: str) -> bool:
    worker = _get_available_worker(state, worker_index)
    if worker is None:
        return False
    new_building: Any = building_key
    if isinstance(building_key, str):
        resolved = build_from_catalog(building_key)
        if resolved is None:
            state.log.append(f'Unknown building type: {building_key}.')
            return False
        new_building = resolved
    power_cost = round(float(getattr(new_building, 'production_cost', 500)) * 0.05, 1)
    costs = {'electricity': power_cost, 'steel': 20.0, 'aluminum': 20.0}
    if not _spend_bundle(state, costs):
        state.log.append(f'Need {power_cost} electricity, 20 steel, and 20 aluminum to build {new_building.name}.')
        return False
    worker.SendToWork()
    _damage_worker(worker, 2.0)
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
    worker.available_after_sol = state.sol + 1
    state.log.append(
        f'{worker.Name} unassigned from {bld.name}; available after '
        f'Sol {state.sol + 1}.'
    )
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
    service_buildings = [
        building for building in state.buildings
        if isinstance(building, ServiceBuilding) and building.is_operational()
    ]
    if not service_buildings:
        state.log.append('No operational Service Building is available.')
        return False
    eligible = [building for building in state.buildings if not isinstance(building, ServiceBuilding)]
    targets = list(dict.fromkeys(
        target
        for service in service_buildings
        for target in service.maintenance_targets
        if target in eligible
    ))
    if not targets:
        state.log.append('Assign buildings to an operational Service Building before maintenance.')
        return False
    total_maint = sum(float(getattr(b, 'maintenance_cost', 10)) for b in targets)
    power_needed = round(total_maint * 0.2, 1)
    al_needed = float(len(targets))
    if not _spend_bundle(state, {'electricity': power_needed, 'aluminum': al_needed}):
        state.log.append(f'Maintenance needs {power_needed} electricity and {al_needed} aluminum for {len(targets)} serviced buildings.')
        return False
    for bld in targets:
        if hasattr(bld, 'safety_rating'):
            bld.safety_rating = min(100, bld.safety_rating + 4)
        bld.health = min(100.0, bld.health + 20.0)
        if bld.number_of_workers > 0:
            bld.production_boost = max(bld.production_boost, 1.25)
    state.log.append(
        f'Service Building maintained {len(targets)} assigned building(s); '
        'staffed producers receive +25% production next Sol.'
    )
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
        state.log.append(
            'Logistics hubs found no transferable stock '
            '(daily limit may be exhausted).'
        )
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
    state.log.append(
        f'{worker.Name} launched a satellite from {state.space["label"]}: '
        f'+{sci} science; it will generate passive research each Sol.'
    )
    return True


def launch_rocket(
    state: GameState,
    worker_index: int,
    payload: Dict[str, Any] | None = None,
    destination: str = "mars",
) -> bool:
    worker = _get_available_worker(state, worker_index)
    if worker is None:
        return False
    cargo = {"water": 200.0, "food": 50000.0} if payload is None else payload
    if not isinstance(cargo, dict):
        state.log.append("Rocket payload must be an object of item quantities.")
        return False
    destination = str(destination).strip().lower()
    if destination not in {"mars", "moon"}:
        state.log.append("Rocket destination must be Mars or the Moon.")
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

    pending_resources: Dict[str, float] = {}
    pending_people = 0
    pending_robots = 0
    for shipment in state.pending_rockets:
        pending_people += int(shipment["payload"].get("people", 0))
        pending_robots += int(shipment["payload"].get("robots", 0))
        for name, quantity in shipment["payload"].items():
            if name in state.resources:
                pending_resources[name] = pending_resources.get(name, 0.0) + float(quantity)
    for name, quantity in normalized_cargo.items():
        if name in state.resources:
            inventory = state.resources[name]
            free_capacity = (
                inventory.getMaxResources()
                - inventory.getResources()
                - pending_resources.get(name, 0.0)
            )
            if quantity > free_capacity:
                state.log.append(f"Not enough reserved storage capacity for rocket payload: {name}.")
                return False
    if (
        total_people + pending_people + people_count > 50
        or total_robots + pending_robots + robot_count > 100
    ):
        state.log.append("Rocket payload exceeds the colony limits of 50 people or 100 robots.")
        return False

    eff = _worker_efficiency(worker, 'Pilot')
    worker.SendToWork()
    _damage_worker(worker, 4.0)
    sci = round(300.0 * eff, 1)
    state.science_points += sci
    transit_sols = rocket_transit_sols(destination, state.sol)
    rocket_id = state.next_rocket_id
    state.next_rocket_id += 1
    state.pending_rockets.append({
        "id": rocket_id,
        "destination": destination,
        "launched_sol": state.sol,
        "arrival_sol": state.sol + transit_sols,
        "transit_sols": transit_sols,
        "payload": normalized_cargo,
        "payload_weight_kg": round(payload_weight, 1),
    })
    payload_summary = ", ".join(
        f"{quantity:g} {name}" for name, quantity in normalized_cargo.items()
    ) or "no cargo"
    state.log.append(
        f"{worker.Name} launched Earth resupply rocket #{rocket_id} to "
        f"{destination.title()} ({transit_sols} Sols): {payload_weight:,.1f} kg "
        f"payload at no resource cost; +{sci} science. Cargo in transit: {payload_summary}."
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
            'process_harvest': process_harvest,
            'feed_crew': feed_crew,
            'mine': mine_resources,
            'refine_materials': refine_materials,
            'produce_fuel': produce_fuel,
            'manufacture': manufacture_item,
            'fabricate_robot': fabricate_robot,
            'construct_building': construct_building,
            'toggle_building': toggle_building,
            'staff_building': assign_building_worker,
            'staff_building_slots': staff_building_to_capacity,
            'staff_all_buildings': staff_all_buildings,
            'unstaff_building': unassign_building_worker,
            'operate_factory': operate_factory,
            'maintain_buildings': maintain_buildings,
            'maintain_robot': maintain_robot,
            'manage_eva_suits': manage_eva_suits,
            'team_exploration': team_exploration,
            'boost_production': boost_building_production,
            'set_maintenance_targets': set_maintenance_targets,
            'scrap_robot': scrap_robot,
            'hydroponics_rotation': run_hydroponics_rotation,
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
        usage_key = daily_action_usage_key(action_name, args)
        used = self.state.daily_action_usage.get(usage_key, 0)
        if limit and used >= limit:
            self.state.log.append(
                f"{action_name.replace('_', ' ').capitalize()} daily limit reached ({limit} per Sol)."
            )
            return False
        result = action(self.state, *args, **kwargs)
        if result and limit:
            self.state.daily_action_usage[usage_key] = used + 1
        return result
