"""Browser-based NASA Mission Control GUI for Living on Red.

Zero external dependencies (uses Python standard library http.server + json).
Run:
    python ui.py
    python ui.py --port 8080 --no-browser
"""

import argparse
import json
import math
import random
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import main as game
import Resource_Class as resource_inventory
from Building_file import (
    Farm,
    LogisticsBuilding,
    ResearchBuilding,
    ResourceBuilding,
    University,
    all_buildings,
)
from Worker_Class import Profession, Worker
from Worker_Class import RobotWorker
from actions import SPACE_ENVIRONMENTS, build_from_catalog
from actions import (
    DAILY_ACTION_LIMITS,
    ROCKET_CREW_WEIGHTS_KG,
    ROCKET_MAX_PAYLOAD_KG,
    ROCKET_VEHICLE_WEIGHTS_KG,
    daily_action_limit,
)

try:
    from cli import BUILD_TYPES
except ImportError:
    BUILD_TYPES = [
        "power", "water", "iceminer", "oxygen", "co2", "nitrogen", "hydrogen", "food", "fuel",
        "rtg",
        "aluminum", "steel", "soil", "plastic", "glass",
        "farm_lettuce", "farm_wheat", "farm_flax", "farm_sunflower",
        "car_factory", "truck_factory", "rover_factory", "satellite_factory", "rocket_factory", "drone_factory",
        "habitation", "recreation", "canteen", "logistics", "research", "university",
        "medical_bay", "hospital", "graveyard", "comms_hub", "satellite_dish",
    ]


NUM_SET_ACTIONS = 5
NUM_RANDOM_ACTIONS = 5
DAILY_ACTION_LIMITS["reroll_random_actions"] = 1


PHASE_CATALOG: Dict[str, int] = {
    "power": 1, "rtg": 1, "water": 1, "oxygen": 1, "food": 1,
    "habitation": 1, "canteen": 1, "recreation": 1, "logistics": 1,
    "farm_lettuce": 1, "farm_wheat": 1, "medical_bay": 1,
    "iceminer": 2, "aluminum": 2, "steel": 2, "soil": 2,
    "plastic": 2, "glass": 2, "co2": 2, "nitrogen": 2,
    "hydrogen": 2, "fuel": 2, "farm_flax": 2, "farm_sunflower": 2,
    "hospital": 2, "graveyard": 2,
    "research": 3, "university": 3, "comms_hub": 3, "satellite_dish": 3,
    "drone_factory": 4, "rover_factory": 4, "satellite_factory": 4,
    "rocket_factory": 4, "car_factory": 4, "truck_factory": 4,
}


ROLE_PROFILES: Dict[str, Dict[str, str]] = {
    "Doctor": {
        "title": "Chief Medical & Habitat Officer",
        "summary": "Keeps the Main Habitation Dome, Medical Bay, and Recreation Center operational. Required to seal Ammonia Coolant Leaks.",
        "buildings": "Habitation Dome, Medical Bay, Hospital, Recreation Center",
        "bonus": "Crisis Response: Seals Ammonia Leaks & stabilizes crew health",
    },
    "Engineer": {
        "title": "Systems & Power Engineer",
        "summary": "Operates Solar Power Plants, MOXIE Oxygen Generators, Steel Mills, and Fuel Refineries. Repairs Grid Overloads and Hull Breaches.",
        "buildings": "Power Plant, MOXIE, Steel Mill, Fuel Refinery, Research Lab",
        "bonus": "1.5x yield on MOXIE O2, Sabatier Fuel & Alloy Refining",
    },
    "Biologist": {
        "title": "Astrobiologist & Life-Support Specialist",
        "summary": "Runs Hydroponic Food Factories, Crop Farms, Canteens, and Research Labs to sustain daily crew calorie rations.",
        "buildings": "Food Factory, Crop Farms, Canteen, Research Lab",
        "bonus": "1.5x yield on Hydroponics & Food Refinery",
    },
    "Geologist": {
        "title": "Planetary Geologist & Extraction Lead",
        "summary": "Operates Subsurface Water Extractors, Ice Mines, and Aluminum Mines. Leads surface rover expeditions and patches hull breaches.",
        "buildings": "Water Extractor, Ice Mining Facility, Aluminum Mine",
        "bonus": "1.5x yield on Surface Mining & Rover Expeditions",
    },
    "Pilot": {
        "title": "Flight & Logistics Officer",
        "summary": "Commands the Central Logistics Hub to move local building production into global colony storage, and pilots drones, satellites, and rockets.",
        "buildings": "Logistics Hub, Communications Hub, Satellite Dish",
        "bonus": "1.5x Science on Drone Recon, Satellites & Rocket Missions",
    },
    "Unassigned": {
        "title": "Mission Specialist",
        "summary": "Supports general colony operations.",
        "buildings": "General Support",
        "bonus": "Standard shift efficiency",
    },
}


SET_ACTION_TEMPLATES: List[Dict[str, Any]] = [
    {
        "id": "set_atmosphere",
        "title": "Balance Habitat Atmosphere",
        "action": "balance_atmosphere",
        "arg_mode": "none",
        "param": None,
        "preferred_role": "",
        "cost": "10 Water, 20 Electricity",
        "effect": "+8 Oxygen, +2 H2, +2 N2, -5 CO2",
    },
    {
        "id": "set_maintain",
        "title": "Preventive Structural Maintenance",
        "action": "maintain_buildings",
        "arg_mode": "none",
        "param": None,
        "preferred_role": "",
        "cost": "Upkeep Power + 1 Al / Building",
        "effect": "+4% Safety Rating on all buildings",
    },
    {
        "id": "set_logistics",
        "title": "Run Colony Logistics Transfer",
        "action": "transfer_logistics",
        "arg_mode": "none",
        "param": None,
        "preferred_role": "Pilot",
        "cost": "Requires Operational Logistics Hub",
        "effect": "Moves local building buffers to global stock",
    },
    {
        "id": "set_rations",
        "title": "Distribute Supplemental Crew Rations",
        "action": "feed_crew",
        "arg_mode": "none",
        "param": None,
        "preferred_role": "",
        "cost": "2,000 kcal Food & 2.5 Water / Crew",
        "effect": "Restores +3 HP to injured active crew",
    },
    {
        "id": "set_crises",
        "title": "Emergency Crisis Containment",
        "action": "resolve_crises",
        "arg_mode": "none",
        "param": None,
        "preferred_role": "",
        "cost": "Incident Materials + Ready Specialists",
        "effect": "Resolves active colony hazards",
    },
]


RANDOM_ACTION_POOL: List[Dict[str, Any]] = [
    {
        "key": "rnd_moxie",
        "min_phase": 1,
        "title": "MOXIE High-Output O2 Cycle",
        "action": "run_moxie",
        "arg_mode": "worker",
        "param": None,
        "preferred_role": "Engineer",
        "cost": "25 Electricity, 4 CO2 + 1 Ready Worker",
        "effect": "+6.0x Oxygen (1.5x with Engineer)",
    },
    {
        "key": "rnd_hydro_lettuce",
        "min_phase": 1,
        "title": "Hydroponic Flush: Lettuce",
        "action": "hydroponics",
        "arg_mode": "worker_param",
        "param": "lettuce",
        "preferred_role": "Biologist",
        "cost": "2 Lettuce Seeds, 12 Water, 15 Power",
        "effect": "+4.0x Lettuce, +1.5x O2, +1 Seed",
    },
    {
        "key": "rnd_hydro_wheat",
        "min_phase": 1,
        "title": "Hydroponic Flush: Wheat",
        "action": "hydroponics",
        "arg_mode": "worker_param",
        "param": "wheat",
        "preferred_role": "Biologist",
        "cost": "2 Wheat Seeds, 12 Water, 15 Power",
        "effect": "+4.0x Wheat, +1.5x O2, +1 Seed",
    },
    {
        "key": "rnd_refine_wheat",
        "min_phase": 1,
        "title": "Caloric Ration Processing (Wheat)",
        "action": "food_refinery",
        "arg_mode": "worker_param",
        "param": "wheat",
        "preferred_role": "Biologist",
        "cost": "5 Wheat, 10 Electricity + 1 Ready Worker",
        "effect": "+16,000x Food kcal (1.5x with Biologist)",
    },
    {
        "key": "rnd_refine_lettuce",
        "min_phase": 1,
        "title": "Fresh Greens Processing (Lettuce)",
        "action": "food_refinery",
        "arg_mode": "worker_param",
        "param": "lettuce",
        "preferred_role": "Biologist",
        "cost": "5 Lettuce, 10 Electricity + 1 Ready Worker",
        "effect": "+9,000x Food kcal (1.5x with Biologist)",
    },
    {
        "key": "rnd_power_shift",
        "min_phase": 1,
        "title": "Manual Auxiliary Generator Shift",
        "action": "work",
        "arg_mode": "worker",
        "param": None,
        "preferred_role": "Engineer",
        "cost": "1 Ready Worker (-2 HP fatigue)",
        "effect": "+6.0x Emergency Electricity",
    },
    {
        "key": "rnd_study_drill",
        "min_phase": 1,
        "title": "Telemetry Simulation Training",
        "action": "study",
        "arg_mode": "worker",
        "param": None,
        "preferred_role": "",
        "cost": "5 Electricity + 1 Ready Worker",
        "effect": "+8 Role Skill & lowers debuffs",
    },
    {
        "key": "rnd_med_check",
        "min_phase": 1,
        "title": "Preventive Med-Bay Recovery",
        "action": "hospital",
        "arg_mode": "worker",
        "param": None,
        "preferred_role": "Doctor",
        "cost": "2 Water, 5 Electricity + 1 Ready Worker",
        "effect": "Restores HP & clears -5 debuffs",
    },
    {
        "key": "rnd_mine",
        "min_phase": 2,
        "title": "Core Drill Regolith & Ice Run",
        "action": "mine",
        "arg_mode": "worker",
        "param": None,
        "preferred_role": "Geologist",
        "cost": "15 Electricity, 10 Fuel + 1 Ready Worker",
        "effect": "+Dirt, Water, Aluminum, Steel & Science",
    },
    {
        "key": "rnd_fuel",
        "min_phase": 2,
        "title": "Sabatier Propellant Synthesis",
        "action": "produce_fuel",
        "arg_mode": "worker",
        "param": None,
        "preferred_role": "Engineer",
        "cost": "6 CO2, 8 H2, 20 Electricity + 1 Ready Worker",
        "effect": "+18.0x Fuel & +4.0x Water",
    },
    {
        "key": "rnd_refine_steel",
        "min_phase": 2,
        "title": "Smelt Structural Steel Batch",
        "action": "refine_materials",
        "arg_mode": "worker_param",
        "param": "steel",
        "preferred_role": "Engineer",
        "cost": "20 Dirt, 20 Electricity + 1 Ready Worker",
        "effect": "+10.0x Steel Alloy",
    },
    {
        "key": "rnd_rover_survey",
        "min_phase": 2,
        "title": "Jezero Rim Rover Traverse",
        "action": "deploy_rover",
        "arg_mode": "worker",
        "param": None,
        "preferred_role": "Geologist",
        "cost": "1 Rover, 12 Fuel, 10 Power + 1 Worker",
        "effect": "+25.0x Science Points & +12.0x Dirt",
    },
    {
        "key": "rnd_drone_recon",
        "min_phase": 2,
        "title": "Autonomous Aerial Drone Recon",
        "action": "fly_drone",
        "arg_mode": "worker",
        "param": None,
        "preferred_role": "Pilot",
        "cost": "1 Drone, 8 Fuel, 8 Power + 1 Worker",
        "effect": "+20.0x Science Points & +2 Crop Seeds",
    },
]


class MissionSession:
    """Thread-safe controller bridging the simulation engine and web console."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.router: Any = None
        self.target_sols: int = 30
        self.target_sci: float = 500.0
        self.aborted: bool = False
        self.unlock_all_override: bool = False
        self.announced_phases: set[int] = {1}
        self.num_set_actions: int = NUM_SET_ACTIONS
        self.num_random_actions: int = NUM_RANDOM_ACTIONS
        self.daily_set_actions: List[Dict[str, Any]] = []
        self.daily_random_actions: List[Dict[str, Any]] = []
        self.daily_usage: Dict[str, int] = {}
        role_cycle = [
            "Doctor", "Engineer", "Biologist", "Geologist", "Pilot",
            "Engineer", "Biologist", "Geologist", "Pilot", "Doctor",
        ]
        self.candidates = {
            "humans": [
                {
                    "id": f"human-{idx}",
                    "name": random.choice(Worker.NAMES),
                    "profession": role_cycle[idx % len(role_cycle)],
                }
                for idx in range(50)
            ],
            "robots": [
                {
                    "id": f"robot-{idx}",
                    "name": f"Rover-{idx + 1:03d}",
                    "profession": role_cycle[idx % len(role_cycle)],
                }
                for idx in range(100)
            ],
        }
        self.current_human_candidate_ids: List[str] = []
        self.current_robot_candidate_ids: List[str] = []
        self.current_starting_resources: Dict[str, float] = {
            key: default for key, (_, default) in game.STARTING_STOCK.items()
        }
        self.new_mission(
            "mars", 6, 30, 500.0, unlock_all=False,
            human_candidate_ids=[candidate["id"] for candidate in self.candidates["humans"][:6]],
            robot_candidate_ids=[],
        )

    def setup_options(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "candidates": self.candidates,
                "current_human_candidate_ids": list(self.current_human_candidate_ids),
                "current_robot_candidate_ids": list(self.current_robot_candidate_ids),
                "current_starting_resources": dict(self.current_starting_resources),
                "resources": [
                    {
                        "key": key,
                        "label": game.RESOURCE_LABELS[key],
                        "max": maximum,
                        "default": default,
                    }
                    for key, (maximum, default) in game.STARTING_STOCK.items()
                ],
            }

    def new_mission(
        self,
        space_key: str,
        crew_count: int,
        target_sols: int,
        target_sci: float,
        unlock_all: bool = False,
        human_candidate_ids: Optional[List[str]] = None,
        robot_candidate_ids: Optional[List[str]] = None,
        starting_resources: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        with self.lock:
            space = space_key if space_key in SPACE_ENVIRONMENTS else "mars"
            if starting_resources is not None:
                if not isinstance(starting_resources, dict):
                    raise ValueError("Starting resources must be an object of resource amounts.")
                unknown_resources = set(starting_resources) - set(game.STARTING_STOCK)
                if unknown_resources:
                    raise ValueError(
                        f"Unknown starting resources: {', '.join(sorted(unknown_resources))}"
                    )
                for key, amount in starting_resources.items():
                    try:
                        numeric_amount = float(amount)
                    except (TypeError, ValueError):
                        raise ValueError(f"Starting {key} must be a number.") from None
                    maximum = game.STARTING_STOCK[key][0]
                    if not math.isfinite(numeric_amount) or not 0 <= numeric_amount <= maximum:
                        raise ValueError(f"Starting {key} must be between 0 and {maximum:g}.")
            if human_candidate_ids is None and robot_candidate_ids is None:
                human_ids = [candidate["id"] for candidate in self.candidates["humans"][:max(0, min(50, int(crew_count)))]]
                robot_ids: List[str] = []
            else:
                human_ids = list(human_candidate_ids or [])
                robot_ids = list(robot_candidate_ids or [])
            if any(not isinstance(candidate_id, str) for candidate_id in human_ids + robot_ids):
                raise ValueError("Selected candidate IDs must be strings.")
            if len(human_ids) > 50 or len(robot_ids) > 100:
                raise ValueError("Mission crew limits are 50 humans and 100 robots.")
            if len(set(human_ids)) != len(human_ids) or len(set(robot_ids)) != len(robot_ids):
                raise ValueError("A crew candidate cannot be selected more than once.")
            candidate_by_id = {
                candidate["id"]: candidate
                for kind in ("humans", "robots")
                for candidate in self.candidates[kind]
            }
            if any(candidate_id not in candidate_by_id for candidate_id in human_ids + robot_ids):
                raise ValueError("One or more selected crew candidates are invalid.")
            if any(not candidate_id.startswith("human-") for candidate_id in human_ids):
                raise ValueError("Human manifest contains a non-human candidate.")
            if any(not candidate_id.startswith("robot-") for candidate_id in robot_ids):
                raise ValueError("Robot manifest contains a non-robot candidate.")
            self.current_human_candidate_ids = human_ids
            self.current_robot_candidate_ids = robot_ids
            self.current_starting_resources = {
                key: float((starting_resources or {}).get(key, default))
                for key, (_, default) in game.STARTING_STOCK.items()
            }
            self.target_sols = max(10, min(365, int(target_sols)))
            self.target_sci = float(max(50, min(10000, target_sci)))
            self.aborted = False
            self.unlock_all_override = bool(unlock_all)
            self.announced_phases = {1}
            self.daily_usage = {}

            all_buildings.clear()
            Worker.TotalCount = 0
            Worker.AvailableCount = 0
            for attr, inv in vars(resource_inventory).items():
                if isinstance(inv, resource_inventory.resources):
                    inv.current = 0
                    inv.max = 10000 if attr == "research" else 0

            selected_workers: List[Worker] = []
            for idx, candidate_id in enumerate(human_ids):
                candidate = candidate_by_id[candidate_id]
                worker = Worker(10000 + idx * 350)
                worker.Name = candidate["name"]
                worker.setType(Profession[candidate["profession"]].value)
                selected_workers.append(worker)
            for candidate_id in robot_ids:
                candidate = candidate_by_id[candidate_id]
                robot = RobotWorker(candidate["name"])
                robot.setType(Profession[candidate["profession"]].value)
                selected_workers.append(robot)

            self.router = game.setup_game(
                space_key=space,
                crew_count=len(human_ids),
                workers=selected_workers,
                starting_resources=starting_resources,
            )
            state = self.router.state

            self._evaluate_unlocks_locked(announce=False)
            self._roll_daily_actions_locked()
            return self._serialize_locked()

    def _roll_daily_actions_locked(self) -> None:
        unlocks = self._compute_unlocks_locked()
        max_phase = unlocks["max_phase"]

        self.daily_set_actions = [
            {**tpl, "category": "set", "used_today": False}
            for tpl in SET_ACTION_TEMPLATES[: self.num_set_actions]
        ]

        # Never offer directives from a phase that is still locked. It is fine
        # to show fewer cards early in the mission than the configured maximum.
        eligible = [item for item in RANDOM_ACTION_POOL if item["min_phase"] <= max_phase]
        picked = random.sample(eligible, k=min(self.num_random_actions, len(eligible)))
        self.daily_random_actions = [
            {
                "id": f"rnd_{self.router.state.sol}_{i}_{item['key']}",
                "category": "random",
                "title": item["title"],
                "action": item["action"],
                "arg_mode": item["arg_mode"],
                "param": item["param"],
                "preferred_role": item["preferred_role"],
                "cost": item["cost"],
                "effect": item["effect"],
                "used_today": False,
            }
            for i, item in enumerate(picked)
        ]

    def _mark_daily_card_used_locked(self, card_id: Optional[str], action_name: str) -> None:
        for group in (self.daily_set_actions, self.daily_random_actions):
            for card in group:
                if card_id and card["id"] == card_id:
                    card["used_today"] = True
                    return
        for group in (self.daily_set_actions, self.daily_random_actions):
            for card in group:
                if not card["used_today"] and card["action"] == action_name:
                    card["used_today"] = True
                    return

    def _daily_action_limit_locked(self, action: str) -> int:
        if action == "reroll_random_actions":
            return 1
        return daily_action_limit(self.router.state, action)

    def _staff_all_feasibility_locked(self) -> Dict[str, Any]:
        state = self.router.state
        available: Dict[str, int] = {}
        for worker in state.workers:
            if worker.isAvailable():
                profession = worker.getType().name
                available[profession] = available.get(profession, 0) + 1

        needed: Dict[str, int] = {}
        for bld in state.buildings:
            assigned = bld._profession_counts()
            for profession, (minimum, _) in type(bld).required_professions.items():
                needed[profession] = needed.get(profession, 0) + max(
                    0, minimum - assigned.get(profession, 0)
                )
        shortages = {
            profession: count - available.get(profession, 0)
            for profession, count in needed.items()
            if count > available.get(profession, 0)
        }
        return {
            "feasible": not shortages,
            "needed": needed,
            "available": available,
            "shortages": shortages,
        }

    def _compute_unlocks_locked(self) -> Dict[str, Any]:
        state = self.router.state
        sol = int(state.sol)
        sci = float(state.science_points)
        ov = self.unlock_all_override
        active_people = sum(
            not getattr(worker, "is_robot", False)
            and not getattr(worker, "retired", False)
            and worker.getHealth() > 0
            for worker in state.workers
        )
        resupply_unlocked = (
            ov or sci >= 100.0 or state.mined_units >= 500.0 or active_people >= 30
        )

        p2 = ov or sol >= 3 or sci >= 40.0
        p3 = ov or sol >= 6 or sci >= 120.0
        p4 = ov or sol >= 10 or sci >= 250.0

        max_phase = 4 if p4 else (3 if p3 else (2 if p2 else 1))
        return {
            "max_phase": max_phase,
            "override": ov,
            "rocket_resupply": {
                "unlocked": resupply_unlocked,
                "requirements": {
                    "science": {"current": round(sci, 1), "threshold": 100.0, "met": sci >= 100.0},
                    "mined_units": {
                        "current": round(state.mined_units, 1),
                        "threshold": 500.0,
                        "met": state.mined_units >= 500.0,
                    },
                    "active_people": {
                        "current": active_people,
                        "threshold": 30,
                        "met": active_people >= 30,
                    },
                },
            },
            "phases": {
                "1": {
                    "id": 1,
                    "name": "Phase I: Surface Survival & Habitat Ops",
                    "unlocked": True,
                    "requirement": "Active at Landing (Sol 1)",
                },
                "2": {
                    "id": 2,
                    "name": "Phase II: Regolith Extraction & Recon",
                    "unlocked": p2,
                    "requirement": "Sol 3 or 40 Science",
                },
                "3": {
                    "id": 3,
                    "name": "Phase III: Research Lab & Comms Array",
                    "unlocked": p3,
                    "requirement": "Sol 6 or 120 Science",
                },
                "4": {
                    "id": 4,
                    "name": "Phase IV: Heavy Fabrication & Orbital Flight",
                    "unlocked": p4,
                    "requirement": "Sol 10 or 250 Science",
                },
            },
            "systems": {
                "life_support": True,
                "buildings": True,
                "crew": True,
                "mining_refining": p2,
                "recon_expeditions": p2,
                "research_academy": p3,
                "manufacturing": p4,
                "orbital_launches": p4,
            },
        }

    def _evaluate_unlocks_locked(self, announce: bool = True) -> None:
        unlocks = self._compute_unlocks_locked()
        for pid_str, info in unlocks["phases"].items():
            pid = int(pid_str)
            if info["unlocked"] and pid not in self.announced_phases:
                self.announced_phases.add(pid)
                if announce:
                    self.router.state.log.append(f"CLEARANCE GRANTED: {info['name']} systems online.")

    def execute_action(self, action: str, args: List[Any], card_id: Optional[str] = None) -> Dict[str, Any]:
        with self.lock:
            state = self.router.state
            unlocks = self._compute_unlocks_locked()
            sys_locks = unlocks["systems"]

            if action in ("assign_job", "university_train"):
                return {
                    "ok": False,
                    "message": "Crew specialties are permanent for this mission and cannot be reassigned.",
                    "state": self._serialize_locked(),
                }

            if action == "abort_mission":
                self.aborted = True
                state.log.append("Mission aborted by Flight Director.")
                return {"ok": True, "message": "Mission aborted.", "state": self._serialize_locked()}

            if action == "reroll_random_actions":
                if self.daily_usage.get(action, 0) >= self._daily_action_limit_locked(action):
                    return {
                        "ok": False,
                        "message": "Random actions can only be refreshed once per Sol.",
                        "state": self._serialize_locked(),
                    }
                self._roll_daily_actions_locked()
                self.daily_usage[action] = self.daily_usage.get(action, 0) + 1
                msg = f"Refreshed {self.num_random_actions} random daily directives for Sol {state.sol}."
                state.log.append(msg)
                return {"ok": True, "message": msg, "state": self._serialize_locked()}

            if action == "reassign_building_worker":
                try:
                    target_b_idx = int(args[0])
                    w_idx = int(args[1])
                    if not (0 <= target_b_idx < len(state.buildings)) or not (0 <= w_idx < len(state.workers)):
                        return {"ok": False, "message": "Invalid building or worker index.", "state": self._serialize_locked()}
                    worker = state.workers[w_idx]
                    old_bld = getattr(worker, "assigned_building", None)
                    if old_bld is state.buildings[target_b_idx]:
                        return {
                            "ok": True,
                        "message": f"{worker.Name} is already assigned to {state.buildings[target_b_idx].name}.",
                            "state": self._serialize_locked(),
                        }

                    old_idx = state.buildings.index(old_bld) if old_bld in state.buildings else None
                    if old_idx is not None:
                        if not self.router.execute("unstaff_building", old_idx, w_idx):
                            last_msg = state.log[-1] if state.log else "Could not release worker."
                            return {"ok": False, "message": last_msg, "state": self._serialize_locked()}

                    ok = self.router.execute("staff_building", target_b_idx, w_idx)
                    if not ok and old_idx is not None:
                        # Roll back the move so a rejected destination never leaves
                        # the worker unexpectedly unassigned.
                        self.router.execute("staff_building", old_idx, w_idx)
                    last_msg = state.log[-1] if state.log else "Worker assignment unchanged."
                    return {"ok": bool(ok), "message": last_msg, "state": self._serialize_locked()}
                except Exception as err:
                    return {"ok": False, "message": f"{type(err).__name__}: {err}", "state": self._serialize_locked()}

            gated_actions = {
                "mine": ("mining_refining", "Phase II (Sol 3 or 40 Science)"),
                "produce_fuel": ("mining_refining", "Phase II (Sol 3 or 40 Science)"),
                "refine_materials": ("mining_refining", "Phase II (Sol 3 or 40 Science)"),
                "deploy_rover": ("recon_expeditions", "Phase II (Sol 3 or 40 Science)"),
                "fly_drone": ("recon_expeditions", "Phase II (Sol 3 or 40 Science)"),
                "run_research": ("research_academy", "Phase III (Sol 6 or 120 Science)"),
                "manufacture": ("manufacturing", "Phase IV (Sol 10 or 250 Science)"),
                "launch_satellite": ("orbital_launches", "Phase IV (Sol 10 or 250 Science)"),
            }
            if action in gated_actions:
                sys_key, req_label = gated_actions[action]
                if not sys_locks.get(sys_key, False):
                    return {
                        "ok": False,
                        "message": f"System locked. Unlocks at {req_label}.",
                        "state": self._serialize_locked(),
                    }

            if action == "launch_rocket" and not unlocks["rocket_resupply"]["unlocked"]:
                return {
                    "ok": False,
                    "message": "Resupply rockets unlock at 100 Science, 500 mined units, or 30 active people.",
                    "state": self._serialize_locked(),
                }

            daily_limit = self._daily_action_limit_locked(action)
            daily_used = (
                self.daily_usage.get(action, 0)
                if action == "reroll_random_actions"
                else state.daily_action_usage.get(action, 0)
            )
            if daily_limit and daily_used >= daily_limit:
                return {
                    "ok": False,
                    "message": f"{action.replace('_', ' ').capitalize()} daily limit reached ({daily_limit} per Sol).",
                    "state": self._serialize_locked(),
                }

            if action == "construct_building" and args:
                b_key = str(args[0]).lower()
                req_phase = PHASE_CATALOG.get(b_key, 1)
                if req_phase > unlocks["max_phase"]:
                    req_txt = unlocks["phases"][str(req_phase)]["requirement"]
                    return {
                        "ok": False,
                        "message": f"Blueprint '{b_key}' unlocks at {req_txt}.",
                        "state": self._serialize_locked(),
                    }

            if action == "configure_farm":
                try:
                    b_idx = int(args[0])
                    crop = str(args[1]).lower()
                    ptype = str(args[2]).lower()
                    if not (0 <= b_idx < len(state.buildings)):
                        return {"ok": False, "message": "Invalid building index.", "state": self._serialize_locked()}
                    farm = state.buildings[b_idx]
                    if not isinstance(farm, Farm):
                        return {"ok": False, "message": "Selected building is not a Farm.", "state": self._serialize_locked()}
                    farm.set_crop(crop)
                    farm.set_product_type(ptype)
                    state.daily_action_usage[action] = state.daily_action_usage.get(action, 0) + 1
                    msg = f"{farm.name} configured to {crop} ({ptype})."
                    state.log.append(msg)
                    return {"ok": True, "message": msg, "state": self._serialize_locked()}
                except Exception as err:
                    return {"ok": False, "message": f"{type(err).__name__}: {err}", "state": self._serialize_locked()}

            if action == "advance_sols":
                count = max(1, min(365, int(args[0]) if args else 5))
                crises_before = len(state.hazard_manager.active_incidents)
                phase_before = unlocks["max_phase"]
                ran = 0
                halt_reason = ""
                for _ in range(count):
                    res = self.router.execute("advance_sol")
                    if not res:
                        break
                    ran += 1
                    self.daily_usage = {}
                    self._evaluate_unlocks_locked(announce=True)
                    active_crew = [w for w in state.workers if not getattr(w, "retired", False) and w.getHealth() > 0]
                    if not res or (state.workers and not active_crew) or state.sol >= self.target_sols:
                        break
                    if len(state.hazard_manager.active_incidents) > crises_before:
                        halt_reason = " Halted for new crisis alert."
                        break
                    if self._compute_unlocks_locked()["max_phase"] > phase_before:
                        halt_reason = " Halted for new system clearance."
                        break
                self._roll_daily_actions_locked()
                return {
                    "ok": True,
                    "message": f"Advanced {ran} Sol(s).{halt_reason}",
                    "state": self._serialize_locked(),
                }

            before_len = len(state.log)
            try:
                result = self.router.execute(action, *args)
                new_entries = state.log[before_len:]
                msg = new_entries[-1] if new_entries else f"Executed {action}."
                self._evaluate_unlocks_locked(announce=True)
                if action == "advance_sol" and result:
                    self.daily_usage = {}
                    self._roll_daily_actions_locked()
                ok = True if result is None else bool(result)
                if ok:
                    self._mark_daily_card_used_locked(card_id, action)
                return {"ok": ok, "message": msg, "state": self._serialize_locked()}
            except Exception as err:
                return {"ok": False, "message": f"{type(err).__name__}: {err}", "state": self._serialize_locked()}

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return self._serialize_locked()

    def _serialize_locked(self) -> Dict[str, Any]:
        state = self.router.state
        unlocks = self._compute_unlocks_locked()
        staffing = self._staff_all_feasibility_locked()
        active_units = [
            w for w in state.workers
            if not getattr(w, "retired", False) and w.getHealth() > 0
        ]
        active_crew = [w for w in state.workers if not getattr(w, "is_robot", False) and w in active_units]
        active_robots = [w for w in state.workers if getattr(w, "is_robot", False) and w in active_units]
        total_volume = sum(
            float(getattr(b, "volume", 100))
            for b in state.buildings
            if getattr(b, "is_on", True)
        )

        resources_out: Dict[str, Dict[str, float]] = {}
        for name, inv in state.resources.items():
            cur = float(inv.getResources())
            cap = float(inv.getMaxResources())
            daily = state.daily_report.get(name, {"added": 0.0, "subtracted": 0.0, "net": 0.0})
            resources_out[name] = {
                "current": round(cur, 2),
                "max": round(cap, 2),
                "pct": round((cur / cap * 100.0) if cap > 0 else 0.0, 1),
                "net": round(float(daily.get("net", 0.0)), 2),
                "added": round(float(daily.get("added", 0.0)), 2),
                "subtracted": round(float(daily.get("subtracted", 0.0)), 2),
            }

        buildings_out: List[Dict[str, Any]] = []
        for idx, bld in enumerate(state.buildings):
            b_cls = type(bld)
            req_profs = {
                prof: [lo, hi]
                for prof, (lo, hi) in getattr(b_cls, "required_professions", {}).items()
            }
            assigned = []
            for w in bld.workers:
                w_idx = state.workers.index(w) if w in state.workers else -1
                assigned.append({
                    "index": w_idx,
                    "name": w.Name,
                    "profession": w.getType().name,
                    "health": round(float(w.getHealth()), 1),
                })

            local_storage = {}
            if isinstance(bld, ResourceBuilding):
                for r_name, store in bld.storage.items():
                    local_storage[r_name] = {
                        "current": round(float(store.getResources()), 1),
                        "max": round(float(store.getMaxResources()), 0),
                    }

            kind = "Building"
            if isinstance(bld, Farm):
                kind = "Farm"
            elif isinstance(bld, ResearchBuilding):
                kind = "Research"
            elif isinstance(bld, University):
                kind = "University"
            elif isinstance(bld, LogisticsBuilding):
                kind = "Logistics"
            elif isinstance(bld, ResourceBuilding):
                kind = "Producer"

            buildings_out.append({
                "index": idx,
                "name": bld.name,
                "type": b_cls.__name__,
                "kind": kind,
                "is_on": bool(getattr(bld, "is_on", True)),
                "is_operational": bool(bld.is_operational()),
                "volume": float(getattr(bld, "volume", 100)),
                "safety": round(float(getattr(bld, "safety_rating", 0)), 1),
                "workers_count": int(bld.number_of_workers),
                "max_workers": int(getattr(b_cls, "max_worker_capacity", 0)),
                "required_professions": req_profs,
                "operating_costs": dict(getattr(b_cls, "operating_resource_costs", {})),
                "standby_costs": dict(getattr(b_cls, "standby_resource_costs", {})),
                "assigned_workers": assigned,
                "local_storage": local_storage,
                "farm_crop": getattr(bld, "crop", None),
                "farm_product": getattr(bld, "product_type", None),
            })

        prof_index = {
            "Unassigned": 0, "Doctor": 1, "Engineer": 2,
            "Biologist": 3, "Geologist": 4, "Pilot": 5,
        }
        workers_out: List[Dict[str, Any]] = []
        for idx, w in enumerate(state.workers):
            job_name = w.getType().name
            p_idx = prof_index.get(job_name, 0)
            skills = w.getSkills()
            debuffs = w.getDebuffs()
            profile = ROLE_PROFILES.get(job_name, ROLE_PROFILES["Unassigned"])
            assigned_bld = getattr(w, "assigned_building", None)
            assigned_bld_idx = state.buildings.index(assigned_bld) if (assigned_bld and assigned_bld in state.buildings) else -1
            if getattr(w, "retired", False):
                status = "Retired"
            elif w.getHealth() <= 0:
                status = "Deceased"
            elif getattr(w, "is_robot", False) and not getattr(w, "powered_on", True):
                status = "Powered Off"
            elif assigned_bld is not None:
                status = f"Staffed @ {assigned_bld.name}"
            elif w.isAvailable():
                status = "Ready"
            else:
                status = "Busy"

            workers_out.append({
                "index": idx,
                "name": w.Name,
                "age_years": int(w.age // 365),
                "is_robot": bool(getattr(w, "is_robot", False)),
                "powered_on": bool(getattr(w, "powered_on", True)),
                "health": round(float(w.getHealth()), 1),
                "profession": job_name,
                "role_title": profile["title"],
                "role_summary": profile["summary"],
                "role_buildings": profile["buildings"],
                "role_bonus": profile["bonus"],
                "available": bool(w.isAvailable()),
                "retired": bool(getattr(w, "retired", False)),
                "assigned_building": assigned_bld.name if assigned_bld else None,
                "assigned_building_index": assigned_bld_idx,
                "status": status,
                "role_skill": round(float(skills[p_idx]), 1),
                "role_debuff": round(float(debuffs[p_idx]), 1),
            })

        crises_out = [
            {
                "name": inc.name,
                "description": inc.description,
                "severity": int(inc.severity),
                "turns_active": int(getattr(inc, "turns_active", 0)),
            }
            for inc in state.hazard_manager.active_incidents
        ]
        risk_profiles = []
        for incident_type in state.hazard_manager.incident_pool:
            incident = incident_type()
            risk_profiles.append({
                "name": incident.name,
                "definition": incident.definition,
                "response": incident.description,
                "severity": int(incident.severity),
                "probability_per_sol": state.hazard_manager.DAILY_CHANCE_PER_HAZARD,
            })

        catalog_out = []
        for key in BUILD_TYPES:
            sample = build_from_catalog(key)
            if sample is None:
                continue
            s_cls = type(sample)
            req_phase = PHASE_CATALOG.get(key, 1)
            catalog_out.append({
                "key": key,
                "name": sample.name,
                "type": s_cls.__name__,
                "phase": req_phase,
                "unlocked": req_phase <= unlocks["max_phase"],
                "unlock_req": unlocks["phases"][str(req_phase)]["requirement"],
                "power_cost": round(float(getattr(sample, "production_cost", 500)) * 0.05, 1),
                "steel_cost": 20,
                "aluminum_cost": 20,
                "volume": float(getattr(sample, "volume", 100)),
                "max_workers": int(getattr(s_cls, "max_worker_capacity", 0)),
                "required_professions": {
                    p: [lo, hi] for p, (lo, hi) in getattr(s_cls, "required_professions", {}).items()
                },
                "operating_costs": dict(getattr(s_cls, "operating_resource_costs", {})),
            })

        payload_items = []
        for key in state.resources:
            if key == "research":
                continue
            payload_items.append({
                "key": key,
                "label": game.RESOURCE_LABELS.get(key, key.replace("_", " ").title()),
                "weight_kg": ROCKET_VEHICLE_WEIGHTS_KG.get(key, 1.0),
            })
        payload_items.extend(
            {"key": key, "label": label, "weight_kg": ROCKET_CREW_WEIGHTS_KG[key]}
            for key, label in (("people", "Human crew"), ("robots", "Robots"))
        )

        mission_over = False
        mission_status = "ACTIVE"
        mission_reason = ""
        if state.workers and not active_units:
            mission_over = True
            mission_status = "FAILED"
            mission_reason = "All humans and robots are inactive. Life support reserves depleted or crises overwhelmed the colony."
        elif self.aborted:
            mission_over = True
            mission_status = "ABORTED"
            mission_reason = "Mission terminated early by Flight Director."
        elif state.sol >= self.target_sols:
            mission_over = True
            if state.science_points >= self.target_sci:
                mission_status = "SUCCESS"
                mission_reason = f"Survived {self.target_sols} Sols and achieved {state.science_points:.1f} Science."
            else:
                mission_status = "FAILED"
                mission_reason = f"Survived {self.target_sols} Sols, but reached {state.science_points:.1f}/{self.target_sci:.0f} Science."

        avg_safety = (
            sum(float(b.safety_rating) for b in state.buildings) / len(state.buildings)
            if state.buildings else 0.0
        )

        return {
            "sol": int(state.sol),
            "target_sols": self.target_sols,
            "elapsed_hours": int(getattr(state.time_engine, "elapsed_hours", (state.sol - 1) * 24)),
            "space_key": state.space_key,
            "space_label": state.space["label"],
            "environments": SPACE_ENVIRONMENTS,
            "science_points": round(float(state.science_points), 1),
            "target_sci": self.target_sci,
            "active_satellites": int(state.active_satellites),
            "active_crew_count": len(active_crew),
            "total_crew_count": sum(not getattr(w, "is_robot", False) for w in state.workers),
            "active_robot_count": len(active_robots),
            "total_robot_count": sum(getattr(w, "is_robot", False) for w in state.workers),
            "powered_robot_count": sum(
                getattr(w, "is_robot", False)
                and getattr(w, "powered_on", False)
                and w.getHealth() > 0
                and not getattr(w, "retired", False)
                for w in state.workers
            ),
            "active_volume": round(total_volume, 1),
            "crisis_risk_pct": int(round(state.hazard_manager.last_risk_score * 100)),
            "avg_safety": round(avg_safety, 1),
            "unlocks": unlocks,
            "rocket_resupply": unlocks["rocket_resupply"],
            "mined_units": round(float(state.mined_units), 1),
            "rocket_max_payload_kg": ROCKET_MAX_PAYLOAD_KG,
            "rocket_payload_items": payload_items,
            "staff_all_feasibility": staffing,
            "daily_action_usage": {
                action: {
                    "used": (
                        self.daily_usage.get(action, 0)
                        if action == "reroll_random_actions"
                        else state.daily_action_usage.get(action, 0)
                    ),
                    "limit": self._daily_action_limit_locked(action),
                }
                for action in set(DAILY_ACTION_LIMITS) | {
                    "reroll_random_actions", "run_research", "transfer_logistics",
                    "operate_factory", "configure_farm", "toggle_building"
                }
            },
            "daily_actions": {
                "num_set_actions": self.num_set_actions,
                "num_random_actions": self.num_random_actions,
                "set": self.daily_set_actions,
                "random": self.daily_random_actions,
            },
            "mission_over": mission_over,
            "mission_status": mission_status,
            "mission_reason": mission_reason,
            "resources": resources_out,
            "resource_labels": game.RESOURCE_LABELS,
            "buildings": buildings_out,
            "workers": workers_out,
            "crises": crises_out,
            "risk_profiles": risk_profiles,
            "combined_daily_hazard_pct": round(
                (1.0 - (1.0 - state.hazard_manager.DAILY_CHANCE_PER_HAZARD) ** len(risk_profiles)) * 100,
                2,
            ),
            "catalog": catalog_out,
            "log": state.log[-50:],
        }


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>LIVING ON RED — NASA Space Apps Challenge 2026 | Daedalus Team</title>
<style>
  :root {
    --bg: #080b11;
    --surface: #0e131d;
    --surface-2: #141b29;
    --surface-3: #1b2436;
    --border: #232e42;
    --border-strong: #344461;
    --text: #e6ebf4;
    --muted: #8f9cb3;
    --accent: #3b82f6;
    --mars: #d95326;
    --mars-hi: #f06a3b;
    --ok: #16a34a;
    --ok-hi: #4ade80;
    --warn: #d97706;
    --warn-hi: #fbbf24;
    --danger: #dc2626;
    --danger-hi: #f87171;
    --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    --sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  }

  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: var(--sans);
    font-size: 13px;
    line-height: 1.45;
    font-variant-numeric: tabular-nums;
  }

  /* ==================== SIMPLE CINEMA MOVIE TITLE INTRO ==================== */
  .movie-intro {
    position: fixed;
    inset: 0;
    z-index: 400;
    background: #030408;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    padding: 32px;
    overflow: hidden;
    transition: opacity 0.8s ease, visibility 0.8s ease;
  }
  .movie-intro.hidden {
    opacity: 0;
    visibility: hidden;
    pointer-events: none;
  }
  .movie-horizon {
    position: absolute;
    left: -15%;
    right: -15%;
    bottom: -42vh;
    height: 62vh;
    border-radius: 50% 50% 0 0;
    background: radial-gradient(ellipse at 50% 10%, rgba(217, 83, 38, 0.36) 0%, rgba(120, 36, 14, 0.16) 45%, transparent 75%);
    border-top: 1px solid rgba(240, 106, 59, 0.35);
    pointer-events: none;
    animation: horizonPulse 7s ease-in-out infinite alternate;
  }
  @keyframes horizonPulse {
    from { transform: translateY(0) scale(1); opacity: 0.85; }
    to { transform: translateY(-8px) scale(1.02); opacity: 1; }
  }
  .movie-card {
    position: relative;
    z-index: 2;
    max-width: 820px;
  }
  .movie-credit-top {
    font-family: var(--mono);
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 5px;
    text-transform: uppercase;
    color: #94a3b8;
    opacity: 0;
    animation: titleFadeIn 1.1s ease 0.2s forwards;
  }
  .movie-credit-team {
    margin-top: 18px;
    font-family: var(--mono);
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 4px;
    text-transform: uppercase;
    color: #fdba74;
    opacity: 0;
    animation: titleFadeIn 1.1s ease 0.85s forwards;
  }
  .movie-main-title {
    margin: 26px 0 14px 0;
    font-size: clamp(44px, 8vw, 92px);
    font-weight: 800;
    letter-spacing: 16px;
    text-transform: uppercase;
    line-height: 1.05;
    color: #ffffff;
    text-shadow: 0 0 50px rgba(217, 83, 38, 0.45);
    opacity: 0;
    transform: scale(0.97);
    animation: titleScaleIn 1.35s cubic-bezier(0.16, 1, 0.3, 1) 1.45s forwards;
  }
  .movie-tagline {
    font-size: 14px;
    letter-spacing: 2.5px;
    text-transform: uppercase;
    color: #94a3b8;
    margin-bottom: 38px;
    opacity: 0;
    animation: titleFadeIn 1s ease 2.1s forwards;
  }
  .movie-actions {
    display: flex;
    gap: 12px;
    justify-content: center;
    flex-wrap: wrap;
    opacity: 0;
    animation: titleFadeIn 1s ease 2.45s forwards;
  }
  .keyboard-hint {
    margin-top: 16px;
    color: #94a3b8;
    font-size: 11px;
  }
  kbd {
    background: var(--surface-2);
    border: 1px solid var(--border-strong);
    border-radius: 3px;
    color: var(--text);
    padding: 1px 5px;
    font-family: var(--mono);
  }
  @keyframes titleFadeIn { to { opacity: 1; } }
  @keyframes titleScaleIn { to { opacity: 1; transform: scale(1); } }

  /* ==================== TUTORIAL SPOTLIGHT & BANNER ==================== */
  .tutorial-spotlight {
    position: relative;
    z-index: 45;
    outline: 2px solid #38bdf8 !important;
    outline-offset: 3px;
    box-shadow: 0 0 0 6px rgba(56, 189, 248, 0.22), 0 0 24px rgba(56, 189, 248, 0.45) !important;
    animation: spotPulse 1.5s ease-in-out infinite;
  }
  @keyframes spotPulse {
    0%, 100% { box-shadow: 0 0 0 4px rgba(56, 189, 248, 0.25), 0 0 18px rgba(56, 189, 248, 0.4); }
    50% { box-shadow: 0 0 0 8px rgba(56, 189, 248, 0.4), 0 0 28px rgba(56, 189, 248, 0.65); }
  }

  .guided-banner {
    display: none;
    background: linear-gradient(90deg, #0c1e3a, #102a4e);
    border-bottom: 2px solid #38bdf8;
    padding: 12px 18px;
    align-items: center;
    justify-content: space-between;
    gap: 14px;
    flex-wrap: wrap;
  }
  .guided-banner.visible { display: flex; }
  .step-counter {
    font-family: var(--mono);
    font-size: 11px;
    font-weight: 800;
    background: #0284c7;
    color: #fff;
    padding: 3px 8px;
    border-radius: 4px;
    letter-spacing: 0.8px;
  }
  .guided-title { font-size: 14px; font-weight: 700; color: #fff; margin-left: 8px; }
  .guided-body { font-size: 12.5px; color: #bae6fd; margin-top: 4px; }

  /* ==================== CONSISTENT FLIGHT CONSOLE UI ==================== */
  .topbar {
    position: sticky;
    top: 0;
    z-index: 30;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 8px 16px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    flex-wrap: wrap;
  }
  .mission-id { display: flex; align-items: center; gap: 10px; }
  .mission-tag {
    background: var(--mars);
    color: #fff;
    font-family: var(--mono);
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 4px 8px;
    border-radius: 4px;
  }
  .mission-name { font-weight: 700; font-size: 14px; letter-spacing: 0.4px; }
  .mission-sub { font-size: 11px; color: var(--muted); font-family: var(--mono); }

  .kpi-strip { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .kpi {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 5px;
    padding: 4px 9px;
    font-family: var(--mono);
    font-size: 11px;
    color: var(--muted);
  }
  .kpi strong { color: var(--text); font-size: 12px; }

  .btn-group { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }

  button {
    background: var(--surface-2);
    color: var(--text);
    border: 1px solid var(--border-strong);
    border-radius: 5px;
    padding: 6px 12px;
    font-family: var(--sans);
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.12s, border-color 0.12s;
  }
  button:hover:not(:disabled) { background: var(--surface-3); border-color: #5b739e; }
  button:disabled { opacity: 0.38; cursor: not-allowed; }
  button:focus-visible {
    outline: 2px solid #38bdf8;
    outline-offset: 3px;
  }
  button.btn-primary { background: #1d4ed8; border-color: #3b82f6; color: #fff; }
  button.btn-primary:hover:not(:disabled) { background: #2563eb; }
  button.btn-mars { background: var(--mars); border-color: var(--mars-hi); color: #fff; }
  button.btn-mars:hover:not(:disabled) { background: #e05a2b; }
  button.btn-ok { background: #15803d; border-color: #22c55e; color: #fff; }
  button.btn-warn { background: #b45309; border-color: #f59e0b; color: #fff; }
  button.btn-danger { background: #991b1b; border-color: #ef4444; color: #fff; }

  .alert-bar {
    display: none;
    background: #450a0a;
    border-bottom: 1px solid var(--danger);
    padding: 8px 16px;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    flex-wrap: wrap;
    font-size: 12px;
  }
  .alert-bar.visible { display: flex; }

  .workspace {
    display: grid;
    grid-template-columns: 1fr 330px;
    gap: 10px;
    padding: 10px 16px 20px 16px;
    max-width: 1600px;
    margin: 0 auto;
    align-items: start;
  }
  @media (max-width: 1080px) {
    .workspace { grid-template-columns: 1fr; }
  }

  .nav-tabs {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    margin-bottom: 10px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 5px;
  }
  .nav-tab {
    background: transparent;
    border: 1px solid transparent;
    color: var(--muted);
    padding: 6px 12px;
    border-radius: 4px;
    font-size: 12px;
  }
  .nav-tab.active {
    background: var(--surface-3);
    border-color: var(--border-strong);
    color: #fff;
  }
  .nav-tab .lock-tag {
    font-family: var(--mono);
    font-size: 10px;
    color: var(--warn-hi);
    margin-left: 4px;
  }

  .view-pane { display: none; }
  .view-pane.active { display: block; }

  .grid-vitals {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 8px;
  }
  @media (max-width: 900px) {
    .grid-vitals { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }
  .grid-2col {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
    align-items: stretch;
  }
  @media (max-width: 820px) {
    .grid-2col { grid-template-columns: 1fr; }
  }

  .panel {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 10px 12px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
  }
  .panel-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
  }
  .panel-title { font-weight: 700; font-size: 13px; color: #f1f5f9; }
  .label-mono { font-family: var(--mono); font-size: 11px; color: var(--muted); }
  .val-lg { font-family: var(--mono); font-size: 16px; font-weight: 700; margin: 2px 0 6px 0; }
  .meter { height: 5px; background: var(--bg); border-radius: 2px; overflow: hidden; }
  .meter-fill { height: 100%; background: var(--accent); transition: width 0.2s; }
  .meter-fill.low { background: var(--danger-hi); }
  .meter-fill.mid { background: var(--warn-hi); }
  .meter-fill.ok { background: var(--ok-hi); }

  .delta-pos { color: var(--ok-hi); font-family: var(--mono); font-size: 11px; font-weight: 700; }
  .delta-neg { color: var(--danger-hi); font-family: var(--mono); font-size: 11px; font-weight: 700; }

  .status-pill {
    font-family: var(--mono);
    font-size: 10px;
    font-weight: 700;
    padding: 2px 6px;
    border-radius: 3px;
    text-transform: uppercase;
  }
  .status-pill.op { background: rgba(22, 163, 74, 0.2); color: var(--ok-hi); border: 1px solid rgba(22, 163, 74, 0.45); }
  .status-pill.idle { background: rgba(217, 119, 6, 0.2); color: var(--warn-hi); border: 1px solid rgba(217, 119, 6, 0.45); }
  .status-pill.off { background: rgba(220, 38, 38, 0.2); color: var(--danger-hi); border: 1px solid rgba(220, 38, 38, 0.45); }
  .status-pill.role { background: rgba(59, 130, 246, 0.18); color: #93c5fd; border: 1px solid rgba(59, 130, 246, 0.45); }

  .ctrl-row { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin-top: 8px; }
  select, input[type="number"], input[type="text"] {
    background: var(--bg);
    color: var(--text);
    border: 1px solid var(--border-strong);
    border-radius: 4px;
    padding: 5px 8px;
    font-size: 12px;
    font-family: var(--sans);
  }

  .notice-strip {
    background: var(--surface-2);
    border: 1px solid var(--border-strong);
    border-left: 3px solid var(--accent);
    padding: 8px 11px;
    border-radius: 4px;
    font-size: 12px;
    color: #dbeafe;
    margin-bottom: 8px;
  }

  .lock-overlay-card {
    background: var(--surface);
    border: 1px dashed var(--border-strong);
    border-radius: 6px;
    padding: 16px;
    text-align: center;
    color: var(--muted);
  }
  .lock-overlay-card strong { color: var(--warn-hi); display: block; margin-bottom: 4px; font-family: var(--mono); }

  .stock-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(175px, 1fr));
    gap: 6px;
  }
  .stock-cell {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 6px 8px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-family: var(--mono);
    font-size: 11.5px;
  }

  .log-sidebar {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 10px;
    position: sticky;
    top: 56px;
    height: calc(100vh - 70px);
    display: flex;
    flex-direction: column;
  }
  .log-feed {
    flex: 1;
    overflow-y: auto;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 8px;
    font-family: var(--mono);
    font-size: 11px;
    line-height: 1.48;
  }
  .log-entry { padding: 3px 0; border-bottom: 1px solid #121824; }
  .log-entry.crit { color: var(--danger-hi); font-weight: 700; }
  .log-entry.sol { color: #60a5fa; font-weight: 700; }
  .log-entry.unlock { color: var(--ok-hi); font-weight: 700; }

  .toast-msg {
    position: fixed;
    bottom: 16px;
    right: 16px;
    z-index: 90;
    background: var(--surface-2);
    border: 1px solid var(--accent);
    border-left: 4px solid var(--accent);
    padding: 9px 14px;
    border-radius: 5px;
    font-size: 12.5px;
    max-width: 420px;
    box-shadow: 0 10px 28px rgba(0, 0, 0, 0.65);
    display: none;
  }
  .toast-msg.err { border-color: var(--danger); border-left-color: var(--danger); color: #fecaca; }

  /* Modals */
  .modal-wrap {
    position: fixed;
    inset: 0;
    z-index: 450;
    background: rgba(4, 6, 10, 0.88);
    display: none;
    align-items: center;
    justify-content: center;
    padding: 16px;
  }
  .modal-wrap.open { display: flex; }
  .modal-box {
    background: var(--surface);
    border: 1px solid var(--border-strong);
    border-radius: 8px;
    padding: 18px 20px;
    max-width: 780px;
    width: 100%;
    max-height: 90vh;
    overflow-y: auto;
    box-shadow: 0 24px 64px rgba(0, 0, 0, 0.85);
  }
  .setup-modal-box { max-width: 1040px; }
  .setup-section {
    margin-top: 12px;
    padding: 10px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface);
  }
  .candidate-columns {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
    margin-top: 8px;
  }
  .candidate-list {
    max-height: 220px;
    overflow-y: auto;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--bg);
    padding: 5px;
  }
  .candidate-row {
    display: flex;
    align-items: flex-start;
    gap: 7px;
    padding: 5px;
    border-bottom: 1px solid var(--border);
    cursor: pointer;
  }
  .candidate-row:last-child { border-bottom: 0; }
  .resource-slider-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
    gap: 8px 14px;
    margin-top: 8px;
  }
  .resource-slider-row { min-width: 0; }
  .resource-slider-row input { width: 100%; }
  .modal-box h2 { margin: 0 0 6px 0; font-size: 17px; }
  .env-options {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    margin: 10px 0;
  }
  .env-opt {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 5px;
    padding: 9px 11px;
    cursor: pointer;
  }
  .env-opt.active {
    border-color: var(--mars-hi);
    background: rgba(217, 83, 38, 0.14);
  }
  .manual-section {
    border-top: 1px solid var(--border);
    padding-top: 10px;
    margin-top: 10px;
  }
  .manual-section h3 {
    margin: 0 0 4px 0;
    font-size: 13px;
    color: #93c5fd;
    font-family: var(--mono);
  }
  .manual-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
    margin-top: 6px;
  }
  .manual-table th, .manual-table td {
    border: 1px solid var(--border);
    padding: 5px 8px;
    text-align: left;
  }
  .manual-table th { background: var(--bg); color: var(--muted); font-family: var(--mono); font-size: 11px; }
</style>
</head>
<body>

<!-- ==================== SIMPLE MOVIE TITLE INTRO ==================== -->
<section class="movie-intro" id="movieIntro">
  <div class="movie-horizon"></div>
  <div class="movie-card">
    <div class="movie-credit-top">NASA SPACE APPS CHALLENGE 2026</div>
    <div class="movie-credit-team">DAEDALUS TEAM &nbsp;&bull;&nbsp; BOGOT&Aacute;, COLOMBIA</div>
    <h1 class="movie-main-title">LIVING ON RED</h1>
    <div class="movie-tagline">Surface Habitat Command &amp; Closed-Loop Survival</div>
    <div class="movie-actions">
      <button class="btn-mars" style="padding:11px 24px;font-size:13px;letter-spacing:1px;" onclick="beginMissionFlow()">BEGIN MISSION &amp; MEET CREW</button>
      <button style="padding:11px 18px;font-size:13px;" onclick="openSetupModal()">MISSION SETTINGS</button>
      <button style="padding:11px 18px;font-size:13px;" onclick="openManual()">OPERATIONS MANUAL</button>
    </div>
    <div class="keyboard-hint"><kbd>↑</kbd> <kbd>↓</kbd> <kbd>←</kbd> <kbd>→</kbd> move between controls &nbsp; <kbd>Enter</kbd> activate</div>
  </div>
</section>

<!-- ==================== CREW INTRODUCTION MODAL ==================== -->
<div class="modal-wrap" id="crewIntroModal">
  <div class="modal-box" style="max-width:820px;">
    <div class="panel-header">
      <div>
        <h2>CREW MANIFEST &amp; SPECIALIST BRIEFING</h2>
        <div class="label-mono">Each crew member holds a permanent NASA mission specialty that cannot be changed.</div>
      </div>
      <span class="status-pill role" id="crewIntroEnv">MARS SURFACE</span>
    </div>

    <div class="ctrl-row" style="margin-top:8px;justify-content:flex-end;">
      <button onclick="closeCrewIntro(false)">Enter Console Without Tutorial</button>
      <button class="btn-mars" style="padding:8px 16px;" onclick="closeCrewIntro(true)">Start Interactive Tutorial &rarr;</button>
    </div>

    <div class="notice-strip" style="margin-top:8px;">
      <strong>How Staffing Works:</strong> Your specialists start assigned to core life-support buildings so your base runs automatically. To use a specialist for a daily action or field shift, open <strong>2. Buildings &amp; Staffing</strong> and click <strong>See Workers &amp; Put to Work</strong>.
    </div>

    <div class="grid-2col" id="crewIntroCards" style="margin-top:10px;"></div>

    <div class="ctrl-row" style="margin-top:14px;justify-content:flex-end;">
      <button onclick="openManual()">Read Full Manual</button>
    </div>
  </div>
</div>

<!-- ==================== BUILDING WORKERS & ASSIGNMENT MODAL ==================== -->
<div class="modal-wrap" id="bldWorkersModal">
  <div class="modal-box" style="max-width:740px;">
    <div class="panel-header">
      <div>
        <h2 id="bwmTitle">BUILDING WORKFORCE &amp; STAFFING</h2>
        <div class="label-mono" id="bwmSubtitle"></div>
      </div>
      <button onclick="closeBuildingWorkersModal()">Close [ESC]</button>
    </div>

    <div class="notice-strip" style="margin-top:8px;">
      <strong>Put Workers to Work:</strong> Only specialists matching this building's required professions can be assigned here. Reassigning a worker automatically unstaffs them from their previous post.
    </div>

    <div style="margin-top:10px;">
      <div class="label-mono" style="font-weight:700;color:#e2e8f0;margin-bottom:6px;">CURRENTLY ASSIGNED TO THIS BUILDING</div>
      <div id="bwmAssignedList"></div>
    </div>

    <div style="margin-top:14px;">
      <div class="label-mono" style="font-weight:700;color:#e2e8f0;margin-bottom:6px;">ELIGIBLE SPECIALISTS (MATCHING PROFESSION)</div>
      <div class="grid-2col" id="bwmAllWorkersList"></div>
    </div>
  </div>
</div>

<!-- ==================== FLIGHT DIRECTOR TOP BAR ==================== -->
<header class="topbar">
  <div class="mission-id">
    <span class="mission-tag">DAEDALUS // 2026</span>
    <div>
      <div class="mission-name">LIVING ON RED</div>
      <div class="mission-sub" id="envSubLabel">Mars Jezero Crater Base</div>
    </div>
  </div>

  <div class="kpi-strip">
    <div class="kpi">SOL <strong id="kpiSol">1/30</strong> (<span id="kpiHrs">0h</span>)</div>
    <div class="kpi">HUMANS <strong id="kpiCrew">6/6</strong></div>
    <div class="kpi">ROBOTS <strong id="kpiRobots">0/0</strong></div>
    <div class="kpi">VOL <strong id="kpiVol">1300m&sup3;</strong></div>
    <div class="kpi">SCIENCE <strong id="kpiSci">0/500</strong></div>
    <div class="kpi">RESEARCH <strong id="kpiRes">0</strong></div>
    <div class="kpi">CLEARANCE <strong id="kpiPhase">PHASE I</strong></div>
    <div class="kpi">RISK <strong id="kpiRisk">19%</strong></div>
  </div>

  <div class="btn-group">
    <button class="btn-mars" id="btnAdvance1" onclick="sendAction('advance_sol', [])">Advance 1 Sol</button>
    <button onclick="sendAction('advance_sols', [5])">+5 Sols</button>
    <button onclick="openCrewIntro()">Meet Crew</button>
    <button class="btn-primary" onclick="startTutorial()">Tutorial</button>
    <button onclick="openManual()">Manual</button>
    <button onclick="openSetupModal()">New Mission</button>
    <button class="btn-danger" onclick="sendAction('abort_mission', [])">Abort</button>
  </div>
</header>

<!-- ==================== ACTIVE CRISIS BANNER ==================== -->
<div class="alert-bar" id="crisisBar">
  <div id="crisisSummary"></div>
  <button class="btn-warn" onclick="sendAction('resolve_crises', [])">Deploy Specialists &amp; Resolve</button>
</div>

<!-- ==================== INTERACTIVE STEP-BY-STEP TUTORIAL ==================== -->
<div class="guided-banner" id="guidedBanner">
  <div>
    <div>
      <span class="step-counter" id="tutStepTag">STEP 1 OF 7</span>
      <span class="guided-title" id="tutStepTitle">Review Life Support Vitals</span>
    </div>
    <div class="guided-body" id="tutStepDesc"></div>
  </div>
  <div class="btn-group">
    <button class="btn-primary" id="tutActionBtn" onclick="nextTutorialStep()">Next Step &rarr;</button>
    <button onclick="stopTutorial()">End Tutorial</button>
  </div>
</div>

<!-- ==================== MAIN WORKSPACE ==================== -->
<div class="workspace">
  <div>
    <nav class="nav-tabs" id="navTabs">
      <button class="nav-tab active" data-pane="ops" onclick="selectPane('ops', this)">1. Life Support &amp; Stockpile</button>
      <button class="nav-tab" data-pane="buildings" onclick="selectPane('buildings', this)">2. Buildings &amp; Staffing</button>
      <button class="nav-tab" data-pane="actions" onclick="selectPane('actions', this)">3. Actions</button>
      <button class="nav-tab" data-pane="crew" onclick="selectPane('crew', this)">4. Crew Roster</button>
      <button class="nav-tab" data-pane="construct" onclick="selectPane('construct', this)">5. Construct Facilities</button>
      <button class="nav-tab" data-pane="field" onclick="selectPane('field', this)">6. Field Ops &amp; Launches <span class="lock-tag" id="fieldLockTag">[PHASE II]</span></button>
      <button class="nav-tab" data-pane="risks" onclick="selectPane('risks', this)">7. Possible Risks</button>
    </nav>

    <!-- PANE 1: LIFE SUPPORT & STOCKPILE -->
    <section class="view-pane active" id="pane-ops">
      <div class="grid-vitals" id="vitalsGrid"></div>

      <div class="panel" id="panelDirectOps" style="margin-top:8px;">
        <div class="panel-header">
          <span class="panel-title">Direct Life-Support &amp; Colony Maintenance</span>
          <span class="label-mono" id="readyCountLabel">0 Ready Crew</span>
        </div>
        <div id="opsWorkerNotice"></div>
        <div class="ctrl-row">
          <button onclick="sendAction('balance_atmosphere', [])">Balance Atmosphere (10 Water, 20 Power)</button>
          <button onclick="sendAction('feed_crew', [])">Issue Extra Ration</button>
          <button onclick="sendAction('maintain_buildings', [])">Maintain All Buildings (+4% Safety)</button>
          <button onclick="sendAction('transfer_logistics', [])">Run Logistics Transfer</button>
        </div>
        <div class="ctrl-row">
          <select id="selOpsWorker"></select>
          <button id="btnMoxie" onclick="runWithWorker('run_moxie', 'selOpsWorker')">Run MOXIE (+O2)</button>
          <select id="selCrop">
            <option value="lettuce">Lettuce</option>
            <option value="wheat">Wheat</option>
            <option value="flax">Flax</option>
            <option value="sunflower">Sunflower</option>
          </select>
          <button id="btnHydro" onclick="runWithWorkerCrop('hydroponics')">Grow Hydroponics</button>
          <button id="btnRefineCrop" onclick="runWithWorkerCrop('food_refinery')">Refine Harvest</button>
        </div>
      </div>

      <div class="panel" style="margin-top:8px;">
        <div class="panel-header">
          <span class="panel-title">Colony Inventory &amp; Last Sol Net Deltas</span>
          <span class="label-mono" id="solBalanceSummary">Awaiting Sol 1 completion</span>
        </div>
        <div class="stock-grid" id="stockGrid"></div>
      </div>
    </section>

    <!-- PANE 2: BUILDINGS & STAFFING -->
    <section class="view-pane" id="pane-buildings">
      <div class="notice-strip">
        <strong>Buildings Menu:</strong> Click <strong>See Workers &amp; Put to Work</strong> on any building to inspect its staff and assign eligible specialists. Auto-staff fills each building's minimum profession requirements.
      </div>
      <div class="panel" style="margin-bottom:8px;">
        <div class="panel-header">
          <span class="panel-title">Staff All Buildings</span>
          <button class="btn-primary" id="btnStaffAll" onclick="sendAction('staff_all_buildings', [])">Auto-Staff Minimum Roles</button>
        </div>
        <div class="label-mono" id="staffAllStatus"></div>
      </div>
      <div class="grid-2col" id="buildingsGrid"></div>
    </section>

    <!-- PANE 3: ACTIONS MENU (5 SET + 5 RANDOM DAILY ACTIONS) -->
    <section class="view-pane" id="pane-actions">
      <div class="panel" style="margin-bottom:8px;">
        <div class="panel-header">
          <span class="panel-title" id="actionsHeaderTitle">DAILY COLONY ACTIONS &mdash; SOL 1</span>
          <div class="btn-group">
            <span class="status-pill op" id="setActionsCounter">5 SET ACTIONS</span>
            <span class="status-pill role" id="rndActionsCounter">5 RANDOM ACTIONS</span>
          </div>
        </div>
        <div class="label-mono">Choose an available Set Action or Random Daily Directive. Most actions are limited to once per Sol; actions tied to a building scale with the number of matching buildings. Action limits reset each Sol.</div>
        <div id="actionsWorkerNotice" style="margin-top:8px;"></div>
        <div class="ctrl-row">
          <label class="label-mono">Active Specialist for Worker Actions:</label>
          <select id="selDailyActionWorker"></select>
          <button id="btnRerollActions" onclick="sendAction('reroll_random_actions', [])">Refresh Random Actions</button>
        </div>
      </div>

      <div class="panel" style="margin-bottom:8px;">
        <div class="panel-header">
          <span class="panel-title">STANDARD DAILY SET ACTIONS (5)</span>
          <span class="label-mono">Available Every Sol</span>
        </div>
        <div class="grid-2col" id="setActionsGrid"></div>
      </div>

      <div class="panel">
        <div class="panel-header">
          <span class="panel-title">RANDOM DAILY DIRECTIVES (5)</span>
          <span class="label-mono">Rolled Specifically for Today</span>
        </div>
        <div class="grid-2col" id="randomActionsGrid"></div>
      </div>
    </section>

    <!-- PANE 4: CREW ROSTER -->
    <section class="view-pane" id="pane-crew">
      <div class="notice-strip">
        <strong>Permanent Crew Specialties:</strong> Each astronaut is locked to their trained mission role (Doctor, Engineer, Biologist, Geologist, or Pilot). Unstaffed crew can rest to heal, study to boost role skill, or visit the hospital.
      </div>
      <div class="grid-2col" id="crewGrid"></div>
    </section>

    <!-- PANE 5: CONSTRUCT FACILITIES -->
    <section class="view-pane" id="pane-construct">
      <div class="panel" style="margin-bottom:8px;">
        <div class="panel-header">
          <span class="panel-title">Colony Engineering Blueprints</span>
          <span class="label-mono" id="phaseScheduleLabel"></span>
        </div>
        <div class="ctrl-row" style="margin-top:4px;">
          <input type="text" id="filterInput" placeholder="Search blueprint (e.g. food, power, lab, rover, farm)..." oninput="renderCatalog()" style="min-width:280px;" />
          <label class="label-mono" style="display:flex;align-items:center;gap:5px;cursor:pointer;">
            <input type="checkbox" id="showLockedChk" checked onchange="renderCatalog()" /> Show upcoming phase blueprints
          </label>
        </div>
      </div>
      <div class="grid-2col" id="catalogGrid"></div>
    </section>

    <!-- PANE 6: FIELD OPS & LAUNCHES -->
    <section class="view-pane" id="pane-field">
      <div id="fieldLockedBanner"></div>
      <div id="fieldWorkerNotice"></div>
      <div id="rocketOpsPanel" style="margin-bottom:8px;"></div>
      <div class="grid-2col" id="fieldGrid"></div>
    </section>

    <!-- PANE 7: POSSIBLE RISKS -->
    <section class="view-pane" id="pane-risks">
      <div class="notice-strip">
        Each listed hazard is rolled independently once per Sol. Multiple distinct hazards can occur on the same Sol; active hazard types do not re-trigger until resolved.
      </div>
      <div class="grid-2col" id="risksGrid"></div>
    </section>
  </div>

  <!-- RIGHT TELEMETRY LOG -->
  <aside class="log-sidebar">
    <div class="panel-header">
      <span class="panel-title">MISSION TELEMETRY LOG</span>
      <span class="label-mono">LIVE</span>
    </div>
    <div class="log-feed" id="logFeed"></div>
  </aside>
</div>

<div class="toast-msg" id="toastBox"></div>

<!-- ==================== MISSION CONFIGURATION MODAL ==================== -->
<div class="modal-wrap" id="setupModal">
  <div class="modal-box setup-modal-box">
    <h2>Mission Configuration &mdash; Daedalus Team</h2>
    <div class="label-mono">Select the destination, crew manifest, starting stockpiles, and mission parameters.</div>
    <div class="env-options" id="envOptionsGrid"></div>
    <section class="setup-section">
      <div class="panel-header">
        <div>
          <div class="panel-title">Meet Your Possible Crew</div>
          <div class="label-mono">Select candidates manually, then randomly fill any remaining slots.</div>
        </div>
      </div>
      <div class="ctrl-row">
        <label class="label-mono">Humans (0-50): <input type="number" id="inCrew" min="0" max="50" value="6" oninput="updateManifestSummary()" style="width:72px;" /></label>
        <label class="label-mono">Robots (0-100): <input type="number" id="inRobots" min="0" max="100" value="0" oninput="updateManifestSummary()" style="width:76px;" /></label>
        <button type="button" onclick="generateRemainingCrew()">Generate Remaining Crew Randomly</button>
      </div>
      <div class="label-mono" id="manifestSummary" aria-live="polite"></div>
      <div class="candidate-columns">
        <div>
          <div class="label-mono" style="margin-bottom:5px;">HUMAN CANDIDATES</div>
          <div class="candidate-list" id="humanCandidates"></div>
        </div>
        <div>
          <div class="label-mono" style="margin-bottom:5px;">ROBOT CANDIDATES</div>
          <div class="candidate-list" id="robotCandidates"></div>
        </div>
      </div>
    </section>
    <section class="setup-section">
      <div class="panel-title">Starting Resources</div>
      <div class="label-mono">Set the amount of each stockpile brought on the mission (0 to its storage capacity).</div>
      <div class="resource-slider-grid" id="startingResources"></div>
    </section>
    <div class="ctrl-row" style="margin-top:10px;">
      <label class="label-mono">Target Sols: <input type="number" id="inSols" min="10" max="365" value="30" style="width:72px;" /></label>
      <label class="label-mono">Target Science: <input type="number" id="inSci" min="50" max="10000" step="50" value="500" style="width:82px;" /></label>
    </div>
    <div class="ctrl-row" style="margin-top:10px;">
      <label class="label-mono" style="display:flex;align-items:center;gap:6px;cursor:pointer;">
        <input type="checkbox" id="inUnlockAll" /> Sandbox Override: Unlock all Phase I-IV controls immediately
      </label>
    </div>
    <div class="ctrl-row" style="margin-top:14px;justify-content:flex-end;">
      <button onclick="closeSetupModal()">Cancel</button>
      <button class="btn-mars" onclick="launchConfiguredMission()">Authorize &amp; Meet Crew</button>
    </div>
  </div>
</div>

<!-- ==================== FIELD MANUAL MODAL ==================== -->
<div class="modal-wrap" id="manualModal">
  <div class="modal-box">
    <div class="panel-header">
      <h2>LIVING ON RED &mdash; FLIGHT OPERATIONS MANUAL</h2>
      <button onclick="closeManual()">Close [ESC]</button>
    </div>
    <div class="label-mono">NASA Space Apps Challenge 2026 | Daedalus Team (Bogot&aacute;, Colombia)</div>

    <div class="manual-section">
      <h3>1. MISSION OBJECTIVE &amp; VICTORY RULES</h3>
      <p style="margin:4px 0;">Survive the target mission duration (default <strong>30 Sols</strong>) and accumulate the target <strong>Science Points</strong> (default <strong>500</strong>). If all active crew members reach 0 HP, the mission ends immediately.</p>
    </div>

    <div class="manual-section">
      <h3>2. DAILY ACTIONS MENU</h3>
      <p style="margin:4px 0;">Each Sol provides core Set Actions and random daily directives tailored to your clearance phase. Most actions can be used once per Sol; building-based actions are limited by the number of matching buildings. Random directives can be refreshed once per Sol.</p>
    </div>

    <div class="manual-section">
      <h3>3. PERMANENT CREW SPECIALTIES</h3>
      <table class="manual-table">
        <tr><th>Role</th><th>Assigned Buildings</th><th>Field Bonus &amp; Crisis Duty</th></tr>
        <tr><td><strong>Doctor</strong></td><td>Habitation Dome, Medical Bay, Hospital, Recreation</td><td>Seals Ammonia Coolant Leaks &amp; restores crew health.</td></tr>
        <tr><td><strong>Engineer</strong></td><td>Power Plant, MOXIE, Steel Mill, Fuel Refinery, Lab</td><td>1.5x yield on MOXIE, Fuel Synthesis &amp; Refining; fixes Grid Overloads.</td></tr>
        <tr><td><strong>Biologist</strong></td><td>Food Factory, Crop Farms, Canteen, Research Lab</td><td>1.5x yield on Hydroponics &amp; Food Refinery.</td></tr>
        <tr><td><strong>Geologist</strong></td><td>Water Extractor, Ice Mine, Aluminum Mine</td><td>1.5x yield on Surface Mining &amp; Rover Expeditions; patches Hull Breaches.</td></tr>
        <tr><td><strong>Pilot</strong></td><td>Logistics Hub, Comms Hub, Satellite Dish</td><td>Transfers local building buffers to colony stock; 1.5x Science on Launches.</td></tr>
      </table>
    </div>

    <div class="manual-section">
      <h3>4. PROGRESSIVE CLEARANCE UNLOCKS</h3>
      <table class="manual-table">
        <tr><th>Phase</th><th>Unlock Condition</th><th>Capabilities Unlocked</th></tr>
        <tr><td>Phase I</td><td>Sol 1 (Landing)</td><td>Life Support (MOXIE, Hydroponics, Atmosphere), Building Staffing, Daily Actions, Crew Roster, Basic Construction.</td></tr>
        <tr><td>Phase II</td><td>Sol 3 or 40 Science</td><td>Regolith &amp; Ice Mining, Sabatier Fuel Synthesis, Material Refining, Rover &amp; Drone Recon.</td></tr>
        <tr><td>Phase III</td><td>Sol 6 or 120 Science</td><td>Research Lab Point Synthesis, Communications Hub &amp; Satellite Dish.</td></tr>
        <tr><td>Phase IV</td><td>Sol 10 or 250 Science</td><td>Spacecraft &amp; Vehicle Manufacturing and Orbital Satellite / Rocket Launches.</td></tr>
      </table>
    </div>
  </div>
</div>

<!-- ==================== POST-MISSION ANALYSIS MODAL ==================== -->
<div class="modal-wrap" id="reportModal">
  <div class="modal-box">
    <h2 id="repTitle">POST-MISSION ANALYSIS</h2>
    <p id="repReason" style="margin:6px 0 12px 0;"></p>
    <div class="panel" id="repMetrics" style="margin-bottom:12px;"></div>
    <div class="ctrl-row" style="justify-content:flex-end;">
      <button class="btn-mars" onclick="closeReportModal(); openSetupModal();">Configure Next Mission</button>
    </div>
  </div>
</div>

<script>
let STATE = null;
let chosenEnv = 'mars';
let reportShownSol = null;
let tutorialIdx = -1;
let activeBuildingModalIdx = null;
let SETUP_OPTIONS = null;
let rocketPayload = { water: 200, food: 50000 };
let selectedHumanIds = new Set();
let selectedRobotIds = new Set();
let manualHumanIds = new Set();
let manualRobotIds = new Set();

const TUTORIAL_FLOW = [
  {
    title: 'Step 1: Monitor Your 4 Core Life-Support Vitals',
    desc: 'Look at Food, Water, Power, and Oxygen at the top. Every Sol your crew consumes rations and your base draws Power. Click "Next Step" to inspect Buildings.',
    pane: 'ops',
    spotId: 'vitalsGrid'
  },
  {
    title: 'Step 2: Open 2. Buildings & Staffing',
    desc: 'Click the highlighted "2. Buildings & Staffing" tab to manage which specialists are working inside each colony building.',
    pane: 'ops',
    spotSelector: '.nav-tab[data-pane="buildings"]'
  },
  {
    title: 'Step 3: Open "See Workers & Put to Work" on a Building',
    desc: 'Click "See Workers & Put to Work" on [6] Colony Steel Mill (or any building) to view all workers and assign or unstaff specialists.',
    pane: 'buildings',
    spotSelector: '#buildingsGrid .panel:last-child .btn-primary'
  },
  {
    title: 'Step 4: Open the New "3. Actions" Menu',
    desc: 'Click the highlighted "3. Actions" tab to view the Set Actions and Random Daily Directives available this Sol.',
    pane: 'buildings',
    spotSelector: '.nav-tab[data-pane="actions"]'
  },
  {
    title: 'Step 5: Activate Any Daily Action',
    desc: 'Click "Activate Action" on any Set Action (such as Balance Habitat Atmosphere) or Random Daily Directive to execute it immediately.',
    pane: 'actions',
    spotId: 'setActionsGrid'
  },
  {
    title: 'Step 6: Advance 1 Sol (Simulate 24 Hours)',
    desc: 'Click "Advance 1 Sol" in the top bar. Automated buildings will produce resources, daily actions will refresh, and you will see your Net Balance per Sol.',
    pane: 'actions',
    spotId: 'btnAdvance1'
  },
  {
    title: 'Step 7: Expand & Unlock New Phases',
    desc: 'Open "5. Construct Facilities" to build another Food Factory or Power Plant, and reach Sol 3 to unlock Phase II Mining & Rovers!',
    pane: 'ops',
    spotSelector: '.nav-tab[data-pane="construct"]'
  }
];

function beginMissionFlow() {
  document.getElementById('movieIntro').classList.add('hidden');
  openCrewIntro();
}

function openCrewIntro() {
  renderCrewIntro();
  document.getElementById('crewIntroModal').classList.add('open');
}

function closeCrewIntro(withTutorial) {
  document.getElementById('crewIntroModal').classList.remove('open');
  if (withTutorial) startTutorial();
}

function renderCrewIntro() {
  if (!STATE) return;
  document.getElementById('crewIntroEnv').textContent = STATE.space_label.toUpperCase();
  document.getElementById('crewIntroCards').innerHTML = STATE.workers.map(w => `
    <div class="panel">
      <div>
        <div class="panel-header">
          <span class="panel-title">[${w.index}] ${w.name}</span>
          <span class="status-pill role">${w.is_robot ? 'ROBOT' : 'HUMAN'} — ${w.profession}</span>
        </div>
        <div class="label-mono" style="color:#cbd5e1;margin-bottom:4px;">${w.role_title}</div>
        <div style="font-size:12px;color:#94a3b8;">${w.role_summary}</div>
      </div>
      <div style="margin-top:8px;padding-top:6px;border-top:1px solid var(--border);">
        <div class="label-mono"><strong>Specialty Bonus:</strong> ${w.role_bonus}</div>
        <div class="label-mono"><strong>Starting Post:</strong> ${w.assigned_building || 'Ready on Standby'} | Skill: ${w.role_skill}</div>
      </div>
    </div>
  `).join('');
}

function openBuildingWorkersModal(bIdx) {
  activeBuildingModalIdx = bIdx;
  renderBuildingWorkersModal();
  document.getElementById('bldWorkersModal').classList.add('open');
  onTutorialEvent('OPEN_BLD_WORKERS');
}

function closeBuildingWorkersModal() {
  activeBuildingModalIdx = null;
  document.getElementById('bldWorkersModal').classList.remove('open');
}

function renderBuildingWorkersModal() {
  if (activeBuildingModalIdx === null || !STATE) return;
  const b = STATE.buildings[activeBuildingModalIdx];
  if (!b) return closeBuildingWorkersModal();

  const reqEntries = Object.entries(b.required_professions);
  const reqText = reqEntries.map(([p, [lo, hi]]) => `${p} (min ${lo}, max ${hi})`).join(', ') || 'None';
  const allowedProfs = Object.keys(b.required_professions);

  document.getElementById('bwmTitle').textContent = `${b.name} — Workers & Staffing`;
  document.getElementById('bwmSubtitle').textContent =
    `${b.type} | Status: ${b.is_on ? (b.is_operational ? 'OPERATIONAL' : 'IDLE') : 'OFF'} | Staff: ${b.workers_count}/${b.max_workers} | Required: ${reqText}`;

  const assignedEl = document.getElementById('bwmAssignedList');
  if (!b.assigned_workers.length) {
    assignedEl.innerHTML = `<div class="notice-strip">No workers are currently working in ${b.name}. Select an eligible specialist below to put them to work.</div>`;
  } else {
    assignedEl.innerHTML = `<div class="grid-2col">` + b.assigned_workers.map(w => `
      <div class="panel">
        <div class="panel-header">
          <span class="panel-title">[${w.index}] ${w.name}</span>
          <span class="status-pill op">${w.profession} &bull; HP ${w.health}%</span>
        </div>
        <div class="ctrl-row">
          <button class="btn-warn" onclick="sendAction('unstaff_building', [${b.index}, ${w.index}])">Unstaff Worker</button>
        </div>
      </div>
    `).join('') + `</div>`;
  }

  const eligibleWorkers = STATE.workers.filter(w =>
    allowedProfs.includes(w.profession) &&
    !w.retired &&
    w.health > 0 &&
    w.powered_on &&
    (w.available || w.assigned_building) &&
    !b.assigned_workers.some(aw => aw.index === w.index)
  );
  document.getElementById('bwmAllWorkersList').innerHTML = eligibleWorkers.length
    ? eligibleWorkers.map(w => {
    const alreadyHere = b.assigned_workers.some(aw => aw.index === w.index);
    const isFull = b.workers_count >= b.max_workers;

    let actionBtn = '';
    if (alreadyHere) {
      actionBtn = `<span class="status-pill op">WORKING HERE</span>`;
    } else if (isFull) {
      actionBtn = `<span class="label-mono">Building Full</span>`;
    } else if (w.available) {
      actionBtn = `<button class="btn-ok" onclick="sendAction('staff_building', [${b.index}, ${w.index}])">Put to Work</button>`;
    } else if (w.assigned_building) {
      actionBtn = `<button class="btn-primary" onclick="sendAction('reassign_building_worker', [${b.index}, ${w.index}])">Reassign &amp; Put to Work</button>`;
    } else {
      actionBtn = `<span class="status-pill idle">${w.status}</span>`;
    }

    return `
      <div class="panel">
        <div>
          <div class="panel-header">
            <span class="panel-title">[${w.index}] ${w.name}</span>
            <span class="status-pill role">${w.profession}</span>
          </div>
          <div class="label-mono">HP: ${w.health}% | Skill: ${w.role_skill} | ${w.status}</div>
        </div>
        <div class="ctrl-row">${actionBtn}</div>
      </div>
    `;
  }).join('')
    : `<div class="notice-strip">No active specialists with a required profession are eligible to staff this building.</div>`;
}

function clearSpotlights() {
  document.querySelectorAll('.tutorial-spotlight').forEach(el => el.classList.remove('tutorial-spotlight'));
}

function applySpotlight(step) {
  clearSpotlights();
  if (!step) return;
  let target = step.spotId ? document.getElementById(step.spotId) : null;
  if (!target && step.spotSelector) target = document.querySelector(step.spotSelector);
  if (target) {
    target.classList.add('tutorial-spotlight');
    target.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
}

function startTutorial() {
  tutorialIdx = 0;
  const tabBtn = document.querySelector('.nav-tab[data-pane="ops"]');
  if (tabBtn) selectPane('ops', tabBtn, true);
  renderTutorial();
}

function stopTutorial() {
  tutorialIdx = -1;
  clearSpotlights();
  document.getElementById('guidedBanner').classList.remove('visible');
}

function nextTutorialStep() {
  if (tutorialIdx < TUTORIAL_FLOW.length - 1) {
    tutorialIdx++;
    const step = TUTORIAL_FLOW[tutorialIdx];
    const tabBtn = document.querySelector(`.nav-tab[data-pane="${step.pane}"]`);
    if (tabBtn) selectPane(step.pane, tabBtn, true);
    renderTutorial();
  } else {
    stopTutorial();
    toast('Guided walkthrough complete. You are in full command!');
  }
}

function onTutorialEvent(evt) {
  if (tutorialIdx < 0) return;
  if (tutorialIdx === 1 && evt === 'OPEN_BUILDINGS') {
    tutorialIdx = 2;
    renderTutorial();
  } else if (tutorialIdx === 2 && (evt === 'OPEN_BLD_WORKERS' || evt === 'staff_building' || evt === 'reassign_building_worker')) {
    tutorialIdx = 3;
    renderTutorial();
  } else if (tutorialIdx === 3 && evt === 'OPEN_ACTIONS') {
    tutorialIdx = 4;
    renderTutorial();
  } else if (tutorialIdx === 4 && evt === 'DAILY_ACTION_ACTIVATED') {
    tutorialIdx = 5;
    renderTutorial();
  } else if (tutorialIdx === 5 && ['advance_sol', 'advance_sols'].includes(evt)) {
    tutorialIdx = 6;
    renderTutorial();
  }
}

function renderTutorial() {
  const banner = document.getElementById('guidedBanner');
  if (tutorialIdx < 0 || tutorialIdx >= TUTORIAL_FLOW.length) {
    banner.classList.remove('visible');
    clearSpotlights();
    return;
  }
  const step = TUTORIAL_FLOW[tutorialIdx];
  banner.classList.add('visible');
  document.getElementById('tutStepTag').textContent = `STEP ${tutorialIdx + 1} OF ${TUTORIAL_FLOW.length}`;
  document.getElementById('tutStepTitle').textContent = step.title;
  document.getElementById('tutStepDesc').textContent = step.desc;
  document.getElementById('tutActionBtn').textContent = tutorialIdx === TUTORIAL_FLOW.length - 1 ? 'Finish Tutorial' : 'Next Step \u2192';
  setTimeout(() => applySpotlight(step), 60);
}

function toast(msg, isErr = false) {
  const el = document.getElementById('toastBox');
  el.textContent = msg;
  el.className = isErr ? 'toast-msg err' : 'toast-msg';
  el.style.display = 'block';
  clearTimeout(window._tTimer);
  window._tTimer = setTimeout(() => { el.style.display = 'none'; }, 4000);
}

async function loadState() {
  const res = await fetch('/api/state');
  STATE = await res.json();
  renderConsole();
}

async function sendAction(action, args = [], cardId = null) {
  const res = await fetch('/api/action', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, args, card_id: cardId })
  });
  const data = await res.json();
  STATE = data.state;
  toast(data.message, !data.ok);
  renderConsole();
  if (activeBuildingModalIdx !== null) renderBuildingWorkersModal();
  if (data.ok) {
    if (cardId) onTutorialEvent('DAILY_ACTION_ACTIVATED');
    onTutorialEvent(action);
  }
}

function activateDailyCard(category, idx) {
  if (!STATE || !STATE.daily_actions) return;
  const list = category === 'set' ? STATE.daily_actions.set : STATE.daily_actions.random;
  const card = list[idx];
  if (!card) return;

  if (card.arg_mode === 'none') {
    sendAction(card.action, [], card.id);
    return;
  }

  const readyCrew = STATE.workers.filter(w => w.available);
  const selEl = document.getElementById('selDailyActionWorker');
  let chosenWorkerIdx = selEl ? parseInt(selEl.value, 10) : NaN;

  if (card.preferred_role) {
    const match = readyCrew.find(w => w.profession === card.preferred_role);
    if (match) chosenWorkerIdx = match.index;
  }
  if (isNaN(chosenWorkerIdx) && readyCrew.length > 0) {
    chosenWorkerIdx = readyCrew[0].index;
  }
  if (isNaN(chosenWorkerIdx)) {
    return toast('No Ready specialist available. Click "Unstaff 1 Specialist Now" first.', true);
  }

  if (card.arg_mode === 'worker') {
    sendAction(card.action, [chosenWorkerIdx], card.id);
  } else if (card.arg_mode === 'worker_param') {
    sendAction(card.action, [chosenWorkerIdx, card.param], card.id);
  }
}

function quickUnstaffFirst() {
  if (!STATE) return;
  const staffedBld = STATE.buildings.find(b => b.assigned_workers && b.assigned_workers.length > 0);
  if (!staffedBld) return toast('No staffed workers found.', true);
  const w = staffedBld.assigned_workers[0];
  sendAction('unstaff_building', [staffedBld.index, w.index]);
}

function runWithWorker(action, selectId) {
  const idx = parseInt(document.getElementById(selectId).value, 10);
  if (isNaN(idx)) return toast('No Ready specialist available. Unstaff 1 specialist first.', true);
  sendAction(action, [idx]);
}

function runWithWorkerCrop(action) {
  const idx = parseInt(document.getElementById('selOpsWorker').value, 10);
  const crop = document.getElementById('selCrop').value;
  if (isNaN(idx)) return toast('No Ready specialist available. Unstaff 1 specialist first.', true);
  sendAction(action, [idx, crop]);
}

function runWithWorkerVal(action, wSelId, vSelId) {
  const idx = parseInt(document.getElementById(wSelId).value, 10);
  const val = document.getElementById(vSelId).value;
  if (isNaN(idx)) return toast('No Ready specialist available. Unstaff 1 specialist first.', true);
  sendAction(action, [idx, val]);
}

function selectPane(name, btn, skipTutorialHook = false) {
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.view-pane').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('pane-' + name).classList.add('active');
  if (!skipTutorialHook) {
    if (name === 'buildings') onTutorialEvent('OPEN_BUILDINGS');
    if (name === 'actions') onTutorialEvent('OPEN_ACTIONS');
  }
  if (tutorialIdx >= 0) setTimeout(() => applySpotlight(TUTORIAL_FLOW[tutorialIdx]), 60);
}

async function openSetupModal() {
  chosenEnv = STATE ? STATE.space_key : 'mars';
  renderEnvGrid();
  document.getElementById('setupModal').classList.add('open');
  try {
    const res = await fetch('/api/setup_options');
    if (!res.ok) throw new Error(`Setup options request failed (${res.status}).`);
    SETUP_OPTIONS = await res.json();
    renderEnvGrid();
    document.getElementById('inCrew').value = SETUP_OPTIONS.current_human_candidate_ids.length;
    document.getElementById('inRobots').value = SETUP_OPTIONS.current_robot_candidate_ids.length;
    document.getElementById('inSols').value = STATE ? STATE.target_sols : 30;
    document.getElementById('inSci').value = STATE ? STATE.target_sci : 500;
    selectedHumanIds = new Set(SETUP_OPTIONS.current_human_candidate_ids);
    selectedRobotIds = new Set(SETUP_OPTIONS.current_robot_candidate_ids);
    manualHumanIds = new Set(selectedHumanIds);
    manualRobotIds = new Set(selectedRobotIds);
    generatedHumanIds = new Set();
    generatedRobotIds = new Set();
    renderSetupOptions();
  } catch (error) {
    toast(`Could not load mission setup options: ${error.message}`, true);
  }
}
function closeSetupModal() { document.getElementById('setupModal').classList.remove('open'); }
function openManual() { document.getElementById('manualModal').classList.add('open'); }
function closeManual() { document.getElementById('manualModal').classList.remove('open'); }
function closeReportModal() { document.getElementById('reportModal').classList.remove('open'); }

window.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    closeManual();
    closeSetupModal();
    closeBuildingWorkersModal();
  }

  if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
  const target = e.target;
  if (target instanceof HTMLElement &&
      (target.isContentEditable || target.matches('input, textarea, select, [contenteditable="true"]'))) return;

  const openModal = [...document.querySelectorAll('.modal-wrap.open')].pop();
  const intro = document.getElementById('movieIntro');
  const activeContainer = openModal ||
    (intro && !intro.classList.contains('hidden') ? intro : document);
  const buttons = [...activeContainer.querySelectorAll('button:not(:disabled)')]
    .filter(button => button.getClientRects().length > 0 &&
      getComputedStyle(button).visibility === 'visible');
  if (!buttons.length) return;

  if (e.key === 'Enter') {
    const focusedButton = document.activeElement;
    const button = buttons.includes(focusedButton) ? focusedButton : buttons[0];
    e.preventDefault();
    button.focus();
    button.click();
    return;
  }

  const direction = {
    ArrowRight: 'right',
    ArrowDown: 'down',
    ArrowLeft: 'left',
    ArrowUp: 'up'
  }[e.key];
  if (!direction) return;

  e.preventDefault();
  const focusedButton = document.activeElement;
  if (!buttons.includes(focusedButton)) {
    buttons[0].focus();
    return;
  }

  const currentRect = focusedButton.getBoundingClientRect();
  const currentX = currentRect.left + currentRect.width / 2;
  const currentY = currentRect.top + currentRect.height / 2;
  const candidates = buttons
    .filter(button => button !== focusedButton)
    .map(button => {
      const rect = button.getBoundingClientRect();
      const dx = rect.left + rect.width / 2 - currentX;
      const dy = rect.top + rect.height / 2 - currentY;
      const primary = direction === 'right' ? dx :
        direction === 'left' ? -dx :
        direction === 'down' ? dy : -dy;
      const secondary = direction === 'right' || direction === 'left' ? Math.abs(dy) : Math.abs(dx);
      return { button, rect, primary, secondary };
    });
  let next = candidates
    .filter(candidate => candidate.primary > 0)
    .sort((a, b) => a.primary + a.secondary * 2 - (b.primary + b.secondary * 2))[0];

  if (!next) {
    next = candidates.sort((a, b) => {
      const aEdge = direction === 'right' ? a.rect.left :
        direction === 'left' ? -a.rect.right :
        direction === 'down' ? a.rect.top : -a.rect.bottom;
      const bEdge = direction === 'right' ? b.rect.left :
        direction === 'left' ? -b.rect.right :
        direction === 'down' ? b.rect.top : -b.rect.bottom;
      return aEdge - bEdge || a.secondary - b.secondary;
    })[0];
  }
  if (next) next.button.focus();
});

function renderEnvGrid() {
  if (!STATE) return;
  document.getElementById('envOptionsGrid').innerHTML = Object.entries(STATE.environments).map(([k, info]) => `
    <div class="env-opt ${chosenEnv === k ? 'active' : ''}" onclick="chosenEnv='${k}'; renderEnvGrid();">
      <strong>${info.label}</strong>
      <div class="label-mono" style="margin-top:3px;">Solar x${info.solar_multiplier} | Power/100m&sup3;: -${info.power_per_100m3} | Hazard: ${Math.round(info.hazard_chance * 100)}% per hazard/Sol</div>
    </div>
  `).join('');
}

function renderSetupOptions() {
  if (!SETUP_OPTIONS) return;
  for (const [kind, listId, selected] of [
    ['humans', 'humanCandidates', selectedHumanIds],
    ['robots', 'robotCandidates', selectedRobotIds]
  ]) {
    document.getElementById(listId).innerHTML = SETUP_OPTIONS.candidates[kind].map(candidate => `
      <label class="candidate-row">
        <input type="checkbox" data-candidate-id="${candidate.id}"
          ${selected.has(candidate.id) ? 'checked' : ''}
          onchange="toggleCandidate('${kind}', '${candidate.id}', this.checked)" />
        <span><strong>${candidate.name}</strong><br />
          <span class="label-mono">${candidate.profession} specialist</span></span>
      </label>
    `).join('');
  }
  document.getElementById('startingResources').innerHTML = SETUP_OPTIONS.resources.map(resource => {
    const amount = SETUP_OPTIONS.current_starting_resources[resource.key] ?? resource.default;
    const step = Math.max(1, Math.ceil(resource.max / 1000));
    return `
      <label class="resource-slider-row label-mono" for="startRes_${resource.key}">
        <span>${resource.label}: <strong id="startResVal_${resource.key}">${amount}</strong> / ${resource.max}</span>
        <input type="range" id="startRes_${resource.key}" min="0" max="${resource.max}"
          step="${step}" value="${amount}"
          oninput="document.getElementById('startResVal_${resource.key}').textContent=this.value" />
      </label>
    `;
  }).join('');
  updateManifestSummary();
}

function toggleCandidate(kind, candidateId, checked) {
  const selected = kind === 'humans' ? selectedHumanIds : selectedRobotIds;
  const manual = kind === 'humans' ? manualHumanIds : manualRobotIds;
  const generated = kind === 'humans' ? generatedHumanIds : generatedRobotIds;
  if (checked) {
    selected.add(candidateId);
    manual.add(candidateId);
    generated.delete(candidateId);
  } else {
    selected.delete(candidateId);
    manual.delete(candidateId);
    generated.delete(candidateId);
  }
  updateManifestSummary();
}

let generatedHumanIds = new Set();
let generatedRobotIds = new Set();

function updateManifestSummary() {
  const humanTarget = Number(document.getElementById('inCrew').value);
  const robotTarget = Number(document.getElementById('inRobots').value);
  const humanText = Number.isInteger(humanTarget) && humanTarget >= 0 && humanTarget <= 50
    ? `${selectedHumanIds.size}/${humanTarget} humans`
    : 'invalid human target';
  const robotText = Number.isInteger(robotTarget) && robotTarget >= 0 && robotTarget <= 100
    ? `${selectedRobotIds.size}/${robotTarget} robots`
    : 'invalid robot target';
  document.getElementById('manifestSummary').textContent = `Selected manifest: ${humanText}, ${robotText}.`;
}

function generateRemainingCrew() {
  if (!SETUP_OPTIONS) return;
  const humanTarget = Number(document.getElementById('inCrew').value);
  const robotTarget = Number(document.getElementById('inRobots').value);
  if (!Number.isInteger(humanTarget) || humanTarget < 0 || humanTarget > 50 ||
      !Number.isInteger(robotTarget) || robotTarget < 0 || robotTarget > 100) {
    toast('Human count must be 0-50 and robot count 0-100.', true);
    return;
  }
  if (manualHumanIds.size > humanTarget || manualRobotIds.size > robotTarget) {
    toast('The manually selected candidates exceed one or more requested crew counts.', true);
    return;
  }
  const chooseRandom = (candidates, excluded, count) => {
    const available = candidates.filter(candidate => !excluded.has(candidate.id));
    for (let i = available.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [available[i], available[j]] = [available[j], available[i]];
    }
    return available.slice(0, count).map(candidate => candidate.id);
  };
  generatedHumanIds = new Set(chooseRandom(
    SETUP_OPTIONS.candidates.humans, manualHumanIds, humanTarget - manualHumanIds.size
  ));
  generatedRobotIds = new Set(chooseRandom(
    SETUP_OPTIONS.candidates.robots, manualRobotIds, robotTarget - manualRobotIds.size
  ));
  selectedHumanIds = new Set([...manualHumanIds, ...generatedHumanIds]);
  selectedRobotIds = new Set([...manualRobotIds, ...generatedRobotIds]);
  for (const [listId, selected] of [
    ['humanCandidates', selectedHumanIds], ['robotCandidates', selectedRobotIds]
  ]) {
    document.querySelectorAll(`#${listId} input[data-candidate-id]`).forEach(input => {
      input.checked = selected.has(input.dataset.candidateId);
    });
  }
  updateManifestSummary();
}

async function launchConfiguredMission() {
  if (!SETUP_OPTIONS) {
    toast('Mission setup options are still loading. Please try again.', true);
    return;
  }
  const crew_count = Number(document.getElementById('inCrew').value);
  const robot_count = Number(document.getElementById('inRobots').value);
  if (!Number.isInteger(crew_count) || crew_count < 0 || crew_count > 50 ||
      !Number.isInteger(robot_count) || robot_count < 0 || robot_count > 100) {
    toast('Human count must be 0-50 and robot count 0-100.', true);
    return;
  }
  if (selectedHumanIds.size !== crew_count || selectedRobotIds.size !== robot_count) {
    toast('Select candidates manually or use Generate Remaining Crew Randomly to complete the manifest.', true);
    return;
  }
  const target_sols = parseInt(document.getElementById('inSols').value, 10) || 30;
  const target_sci = parseFloat(document.getElementById('inSci').value) || 500;
  const unlock_all = document.getElementById('inUnlockAll').checked;
  const starting_resources = Object.fromEntries(SETUP_OPTIONS.resources.map(resource => [
    resource.key,
    Number(document.getElementById(`startRes_${resource.key}`).value)
  ]));
  const res = await fetch('/api/new_game', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      space_key: chosenEnv,
      crew_count,
      target_sols,
      target_sci,
      unlock_all,
      human_candidate_ids: [...selectedHumanIds],
      robot_candidate_ids: [...selectedRobotIds],
      starting_resources
    })
  });
  const response = await res.json();
  if (!res.ok) {
    toast(response.message || `Mission setup failed (${res.status}).`, true);
    return;
  }
  STATE = response;
  reportShownSol = null;
  closeSetupModal();
  document.getElementById('movieIntro').classList.add('hidden');
  renderConsole();
  openCrewIntro();
}

function fmtCosts(obj) {
  const pairs = Object.entries(obj || {});
  return pairs.length ? pairs.map(([k, v]) => `${v} ${k}`).join(', ') : 'none';
}

function renderConsole() {
  if (!STATE) return;
  const u = STATE.unlocks;

  document.getElementById('envSubLabel').textContent = `${STATE.space_label} // Daedalus Team (Bogot\u00e1)`;
  document.getElementById('kpiSol').textContent = `${STATE.sol}/${STATE.target_sols}`;
  document.getElementById('kpiHrs').textContent = `${STATE.elapsed_hours}h`;
  document.getElementById('kpiCrew').textContent = `${STATE.active_crew_count}/${STATE.total_crew_count}`;
  document.getElementById('kpiRobots').textContent = `${STATE.powered_robot_count}/${STATE.total_robot_count}`;
  document.getElementById('kpiVol').textContent = `${STATE.active_volume}m\u00b3`;
  document.getElementById('kpiSci').textContent = `${STATE.science_points}/${STATE.target_sci}`;
  document.getElementById('kpiRes').textContent = STATE.resources.research ? STATE.resources.research.current : 0;
  document.getElementById('kpiPhase').textContent = `PHASE ${['I','II','III','IV'][u.max_phase - 1]}`;
  document.getElementById('kpiRisk').textContent = `${STATE.crisis_risk_pct}%`;

  const fieldLock = document.getElementById('fieldLockTag');
  fieldLock.textContent = u.max_phase >= 2 ? '' : '[PHASE II]';

  const cBar = document.getElementById('crisisBar');
  if (STATE.crises.length > 0) {
    cBar.classList.add('visible');
    document.getElementById('crisisSummary').innerHTML = STATE.crises.map(c =>
      `<div><strong>[CRISIS SEV ${c.severity}] ${c.name}:</strong> ${c.description}</div>`
    ).join('');
  } else {
    cBar.classList.remove('visible');
  }

  const vitals = [
    ['food', 'FOOD (KCAL)'], ['water', 'WATER (L)'], ['oxigen', 'OXYGEN (KG)'],
    ['electricity', 'POWER (KWH)'], ['fuel', 'FUEL (L)'], ['CO2', 'CO2 (KG)'],
    ['Nitrogen', 'NITROGEN (KG)'], ['Hydrogen', 'HYDROGEN (KG)']
  ];
  document.getElementById('vitalsGrid').innerHTML = vitals.map(([k, lbl]) => {
    const r = STATE.resources[k] || { current: 0, max: 0, pct: 0, net: 0 };
    const cls = r.pct < 20 ? 'low' : (r.pct < 45 ? 'mid' : 'ok');
    const netTag = r.net !== 0
      ? `<span class="${r.net > 0 ? 'delta-pos' : 'delta-neg'}">${r.net > 0 ? '+' : ''}${r.net}/sol</span>`
      : `<span class="label-mono">0/sol</span>`;
    return `
      <div class="panel">
        <div class="panel-header"><span class="label-mono">${lbl}</span>${netTag}</div>
        <div class="val-lg">${r.current} <span class="label-mono">/ ${r.max}</span></div>
        <div class="meter"><div class="meter-fill ${cls}" style="width:${Math.min(100, r.pct)}%"></div></div>
      </div>`;
  }).join('');

  const readyCrew = STATE.workers.filter(w => w.available);
  document.getElementById('readyCountLabel').textContent = `${readyCrew.length} Ready Crew`;
  const workerNotice = readyCrew.length === 0
    ? `<div class="notice-strip" style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
         <span>All active specialists are currently staffed inside buildings. Free a specialist to run worker actions.</span>
         <button class="btn-primary" onclick="quickUnstaffFirst()">Unstaff 1 Specialist Now</button>
       </div>`
    : '';
  document.getElementById('opsWorkerNotice').innerHTML = workerNotice;
  document.getElementById('actionsWorkerNotice').innerHTML = workerNotice;
  document.getElementById('fieldWorkerNotice').innerHTML = workerNotice;

  const wOptions = readyCrew.length
    ? readyCrew.map(w => `<option value="${w.index}">[${w.index}] ${w.name} (${w.profession}, HP ${w.health})</option>`).join('')
    : '<option value="">No Ready Specialists (Unstaff 1 first)</option>';
  document.getElementById('selOpsWorker').innerHTML = wOptions;
  document.getElementById('selDailyActionWorker').innerHTML = wOptions;

  const deltas = Object.entries(STATE.resources)
    .filter(([, r]) => r.net !== 0)
    .map(([k, r]) => `<span class="${r.net > 0 ? 'delta-pos' : 'delta-neg'}">${k} ${r.net > 0 ? '+' : ''}${r.net}</span>`);
  document.getElementById('solBalanceSummary').innerHTML = deltas.length ? deltas.join(' | ') : 'Awaiting Sol 1 completion';

  document.getElementById('stockGrid').innerHTML = Object.entries(STATE.resources)
    .filter(([, r]) => r.max > 0 || r.current > 0)
    .map(([k, r]) => {
      const d = r.net !== 0 ? ` <span class="${r.net > 0 ? 'delta-pos' : 'delta-neg'}">(${r.net > 0 ? '+' : ''}${r.net})</span>` : '';
      return `<div class="stock-cell"><span>${STATE.resource_labels[k] || k}${d}</span><strong>${r.current}/${r.max}</strong></div>`;
    }).join('');

  // Buildings Menu with "See Workers & Put to Work" button on every building
  document.getElementById('buildingsGrid').innerHTML = STATE.buildings.map(b => {
    const pillCls = !b.is_on ? 'off' : (b.is_operational ? 'op' : 'idle');
    const pillTxt = !b.is_on ? 'OFF' : (b.is_operational ? 'OP' : 'IDLE');
    const reqs = Object.entries(b.required_professions).map(([p, [lo, hi]]) => `${p} ${lo}-${hi}`).join(', ') || 'none';
    const local = Object.entries(b.local_storage).map(([k, v]) => `${k}: ${v.current}/${v.max}`).join(' | ');
    const badges = b.assigned_workers.map(w =>
      `<span class="status-pill role">[${w.index}] ${w.name} (${w.profession})</span>`
    ).join(' ');

    let extraHtml = '';
    if (b.kind === 'Farm') {
      const crops = ['lettuce', 'wheat', 'flax', 'sunflower'];
      const farmUsage = STATE.daily_action_usage.configure_farm;
      const farmAtLimit = farmUsage.used >= farmUsage.limit;
      extraHtml += `
        <div class="ctrl-row">
          <select id="fCrop_${b.index}">${crops.map(c => `<option value="${c}" ${b.farm_crop === c ? 'selected' : ''}>${c}</option>`).join('')}</select>
          <select id="fType_${b.index}">
            <option value="crop" ${b.farm_product === 'crop' ? 'selected' : ''}>Crop</option>
            <option value="seed" ${b.farm_product === 'seed' ? 'selected' : ''}>Seeds</option>
          </select>
          <button class="btn-primary" onclick="setFarm(${b.index})" ${farmAtLimit ? 'disabled' : ''}>${farmAtLimit ? 'Daily Limit Reached' : 'Set Output'}</button>
        </div>`;
    }
    if (b.kind === 'Research') {
      const lockedRes = !u.systems.research_academy;
      extraHtml += `
        <div class="ctrl-row">
          <select id="rPts_${b.index}" ${lockedRes ? 'disabled' : ''}>
            <option value="1">1 Research Pt (+15 Sci)</option>
            <option value="3">3 Research Pts (+45 Sci)</option>
          </select>
          <button class="btn-primary" ${lockedRes ? 'disabled' : ''} onclick="runLab(${b.index})">${lockedRes ? 'Locked (Phase III)' : 'Synthesize Research'}</button>
        </div>`;
    }

    return `
      <div class="panel">
        <div>
          <div class="panel-header">
            <span class="panel-title">[${b.index}] ${b.name}</span>
            <span class="status-pill ${pillCls}">${pillTxt}</span>
          </div>
          <div class="label-mono">${b.type} | Vol ${b.volume}m&sup3; | Safety ${b.safety}% | Staff ${b.workers_count}/${b.max_workers} (${reqs})</div>
          <div class="label-mono">Upkeep: ${fmtCosts(b.operating_costs)} (Standby: ${fmtCosts(b.standby_costs)})</div>
          ${local ? `<div class="label-mono" style="color:#60a5fa;margin-top:3px;">Local Storage: ${local}</div>` : ''}
        </div>
        <div>
          <div class="ctrl-row">${badges || '<span class="label-mono">No workers assigned</span>'}</div>
          <div class="ctrl-row">
            <button class="btn-primary" onclick="openBuildingWorkersModal(${b.index})">See Workers &amp; Put to Work (${b.workers_count}/${b.max_workers})</button>
            <button onclick="sendAction('toggle_building', [${b.index}])" ${STATE.daily_action_usage.toggle_building.used >= STATE.daily_action_usage.toggle_building.limit ? 'disabled' : ''}>${b.is_on ? 'Turn Off' : 'Turn On'}</button>
          </div>
          ${extraHtml}
        </div>
      </div>`;
  }).join('');

  const staffing = STATE.staff_all_feasibility;
  const staffAllButton = document.getElementById('btnStaffAll');
  const staffAllStatus = document.getElementById('staffAllStatus');
  const staffingDeficit = Object.values(staffing.needed)
    .reduce((total, count) => total + count, 0);
  staffAllButton.disabled = !staffing.feasible || staffingDeficit === 0;
  if (staffingDeficit === 0) {
    staffAllStatus.textContent = 'All buildings already meet their minimum profession staffing.';
  } else if (staffing.feasible) {
    staffAllStatus.textContent = `Enough available specialists to fill all minimum roles (${staffingDeficit} assignments needed).`;
  } else {
    staffAllStatus.textContent = `Insufficient available specialists: ${Object.entries(staffing.shortages).map(([role, count]) => `${role} short ${count}`).join(', ')}.`;
  }

  // Actions Menu (5 Set Actions + 5 Random Actions)
  renderDailyActions();

  // Crew Roster (Stable Permanent Roles — no role changing)
  document.getElementById('crewGrid').innerHTML = STATE.workers.map(w => `
    <div class="panel">
      <div>
        <div class="panel-header">
          <span class="panel-title">[${w.index}] ${w.name}</span>
          <div class="btn-group">
            <span class="status-pill role">${w.is_robot ? 'ROBOT' : 'HUMAN'} — ${w.profession}</span>
            <span class="status-pill ${w.available ? 'op' : 'idle'}">${w.status}</span>
          </div>
        </div>
        <div class="label-mono" style="color:#cbd5e1;">${w.role_title}</div>
        <div class="label-mono">HP ${w.health}% | Specialty Skill ${w.role_skill} | Debuff ${w.role_debuff} | ${w.is_robot ? (w.powered_on ? 'Powered' : 'Auto-resuming when power returns') : `Age ${w.age_years}y`}</div>
        <div style="font-size:11.5px;color:var(--muted);margin-top:4px;">${w.role_bonus}</div>
      </div>
      <div>
        <div class="ctrl-row">
          <button onclick="sendAction('work', [${w.index}])" ${!w.available ? 'disabled' : ''}>General Shift (+Power)</button>
          <button onclick="sendAction('rest', [${w.index}])" ${w.assigned_building || w.retired || w.health <= 0 ? 'disabled' : ''}>Rest (+HP)</button>
          <button onclick="sendAction('hospital', [${w.index}])" ${!w.available ? 'disabled' : ''}>Hospital</button>
          <button onclick="sendAction('study', [${w.index}])" ${!w.available ? 'disabled' : ''}>Study (+Skill)</button>
          ${w.is_robot ? `
            <button onclick="sendAction('maintain_robot', [${w.index}, 'steel'])" ${w.health <= 0 || w.retired || w.health >= 100 || STATE.resources.steel.current < 1 ? 'disabled' : ''}>Repair +10% (1 Steel)</button>
            <button onclick="sendAction('maintain_robot', [${w.index}, 'aluminum'])" ${w.health <= 0 || w.retired || w.health >= 100 || STATE.resources.aluminum.current < 1 ? 'disabled' : ''}>Repair +10% (1 Aluminum)</button>
          ` : ''}
          <button class="btn-danger" onclick="sendAction('retire', [${w.index}])" ${w.retired || w.health <= 0 ? 'disabled' : ''}>Retire</button>
        </div>
      </div>
    </div>
  `).join('');

  document.getElementById('phaseScheduleLabel').textContent =
    `Current Clearance: Phase ${u.max_phase} | Next unlocks at Sol 3 / Sol 6 / Sol 10`;
  renderCatalog();
  renderFieldOps(wOptions, u);
  renderRiskPane();

  document.getElementById('logFeed').innerHTML = STATE.log.slice().reverse().map(line => {
    const cls = line.includes('CRISIS') || line.includes('INCIDENT') || line.includes('shortage')
      ? 'log-entry crit'
      : (line.includes('CLEARANCE GRANTED') ? 'log-entry unlock' : (line.includes('Sol ') ? 'log-entry sol' : 'log-entry'));
    return `<div class="${cls}">${line}</div>`;
  }).join('');

  if (STATE.mission_over && reportShownSol !== STATE.sol) {
    reportShownSol = STATE.sol;
    document.getElementById('repTitle').textContent = `POST-MISSION ANALYSIS // ${STATE.mission_status}`;
    document.getElementById('repReason').textContent = STATE.mission_reason;
    document.getElementById('repMetrics').innerHTML = `
      <div class="label-mono">Duration: <strong>${STATE.sol} / ${STATE.target_sols} Sols (${STATE.elapsed_hours}h)</strong></div>
      <div class="label-mono">Science Achieved: <strong>${STATE.science_points} / ${STATE.target_sci}</strong></div>
      <div class="label-mono">Human Survival: <strong>${STATE.active_crew_count} / ${STATE.total_crew_count}</strong></div>
      <div class="label-mono">Robot Survival: <strong>${STATE.active_robot_count} / ${STATE.total_robot_count}</strong></div>
      <div class="label-mono">Average Colony Safety: <strong>${STATE.avg_safety}%</strong></div>
    `;
    document.getElementById('reportModal').classList.add('open');
  }

  if (tutorialIdx >= 0) setTimeout(() => applySpotlight(TUTORIAL_FLOW[tutorialIdx]), 40);
}

function renderDailyActions() {
  if (!STATE || !STATE.daily_actions) return;
  const da = STATE.daily_actions;
  document.getElementById('actionsHeaderTitle').textContent = `DAILY COLONY ACTIONS — SOL ${STATE.sol}`;
  document.getElementById('setActionsCounter').textContent = `${da.num_set_actions} SET ACTIONS`;
  document.getElementById('rndActionsCounter').textContent = `${da.num_random_actions} RANDOM ACTIONS`;
  const rerollUsage = STATE.daily_action_usage.reroll_random_actions;
  const rerollButton = document.getElementById('btnRerollActions');
  rerollButton.disabled = rerollUsage.used >= rerollUsage.limit;
  rerollButton.textContent = rerollButton.disabled ? 'Daily Refresh Used' : 'Refresh Random Actions';

  const renderCard = (card, idx, category) => {
    const roleTag = card.preferred_role ? ` | Specialist: ${card.preferred_role}` : '';
    const usage = STATE.daily_action_usage[card.action];
    const atLimit = usage && usage.limit > 0 && usage.used >= usage.limit;
    const noBuildings = usage && usage.limit === 0;
    const statusBadge = atLimit
      ? `<span class="status-pill op">ACTIVATED TODAY</span>`
      : (noBuildings
        ? `<span class="status-pill off">NO REQUIRED BUILDING</span>`
        : `<span class="status-pill role">${category === 'set' ? 'SET ACTION' : 'DAILY RANDOM'}</span>`);
    const btnClass = category === 'set' ? 'btn-primary' : 'btn-mars';
    return `
      <div class="panel">
        <div>
          <div class="panel-header">
            <span class="panel-title">${idx + 1}. ${card.title}</span>
            ${statusBadge}
          </div>
          <div class="label-mono">Cost: ${card.cost}${roleTag}</div>
          ${usage ? `<div class="label-mono">Uses today: ${usage.used}/${usage.limit}${usage.limit > 0 ? ` (${usage.limit - usage.used} remaining)` : ''}</div>` : ''}
          <div style="font-size:12px;color:#cbd5e1;margin-top:4px;">${card.effect}</div>
        </div>
        <div class="ctrl-row">
          <button class="${btnClass}" onclick="activateDailyCard('${category}', ${idx})" ${atLimit || noBuildings ? 'disabled' : ''}>${atLimit ? 'Daily Limit Reached' : 'Activate Action'}</button>
        </div>
      </div>
    `;
  };

  document.getElementById('setActionsGrid').innerHTML = da.set.map((c, i) => renderCard(c, i, 'set')).join('');
  document.getElementById('randomActionsGrid').innerHTML = da.random.map((c, i) => renderCard(c, i, 'random')).join('');
}

function renderRiskPane() {
  if (!STATE) return;
  const profiles = STATE.risk_profiles || [];
  document.getElementById('risksGrid').innerHTML = `
    <div class="notice-strip" style="grid-column:1 / -1;">
      Combined chance of at least one hazard this Sol: <strong>${STATE.combined_daily_hazard_pct}%</strong>
    </div>
    ${profiles.map(risk => `
      <div class="panel">
        <div class="panel-header">
          <span class="panel-title">${risk.name}</span>
          <span class="status-pill idle">SEVERITY ${risk.severity}</span>
        </div>
        <div class="label-mono">${risk.definition}</div>
        <div class="label-mono" style="margin-top:5px;">Response: ${risk.response}</div>
        <div class="label-mono" style="margin-top:8px;">Expected probability each Sol: <strong>${(risk.probability_per_sol * 100).toFixed(0)}%</strong></div>
      </div>
    `).join('')}`;
}

function rocketPayloadWeight() {
  return Object.entries(rocketPayload).reduce((total, [key, quantity]) => {
    const item = STATE.rocket_payload_items.find(candidate => candidate.key === key);
    return total + (item ? item.weight_kg * quantity : 0);
  }, 0);
}

function updateRocketPayloadSummary() {
  const summary = document.getElementById('rocketPayloadSummary');
  if (!summary || !STATE) return;
  const weight = rocketPayloadWeight();
  const lines = Object.entries(rocketPayload)
    .filter(([, quantity]) => quantity > 0)
    .map(([key, quantity]) => {
      const item = STATE.rocket_payload_items.find(candidate => candidate.key === key);
      return `<div class="ctrl-row"><span class="label-mono">${item.label}: ${quantity} × ${item.weight_kg} kg = ${quantity * item.weight_kg} kg</span><button onclick="removeRocketPayload('${key}')">Remove</button></div>`;
    });
  summary.innerHTML = `${lines.join('') || '<span class="label-mono">No cargo selected.</span>'}
    <div class="label-mono" style="margin-top:6px;color:${weight > STATE.rocket_max_payload_kg ? 'var(--danger-hi)' : 'var(--ok-hi)'};">
      Payload: ${weight.toLocaleString()} / ${STATE.rocket_max_payload_kg.toLocaleString()} kg (${(weight / 1000).toFixed(1)} / 100 tonnes)
    </div>`;
  const launch = document.getElementById('btnLaunchRocket');
  if (launch) {
    const usage = STATE.daily_action_usage.launch_rocket;
    launch.disabled = !STATE.rocket_resupply.unlocked ||
      usage.used >= usage.limit ||
      weight > STATE.rocket_max_payload_kg ||
      !STATE.workers.some(worker => worker.available);
  }
}

function addRocketPayload() {
  const key = document.getElementById('rocketPayloadItem').value;
  const quantity = Number(document.getElementById('rocketPayloadAmount').value);
  if (!Number.isFinite(quantity) || quantity <= 0) return toast('Enter a positive payload quantity.', true);
  rocketPayload[key] = (rocketPayload[key] || 0) + quantity;
  updateRocketPayloadSummary();
}

function removeRocketPayload(key) {
  delete rocketPayload[key];
  updateRocketPayloadSummary();
}

function launchResupplyRocket() {
  const workerIndex = Number(document.getElementById('selRocketWorker').value);
  if (!Number.isInteger(workerIndex)) return toast('Select an available specialist to launch the rocket.', true);
  sendAction('launch_rocket', [workerIndex, rocketPayload]);
}

function renderFieldOps(wOptions, u) {
  const banner = document.getElementById('fieldLockedBanner');
  const grid = document.getElementById('fieldGrid');
  renderRocketOps(wOptions);

  if (!u.systems.mining_refining) {
    banner.innerHTML = `
      <div class="lock-overlay-card">
        <strong>PHASE II CLEARANCE REQUIRED</strong>
        Surface Mining, Fuel Synthesis, Material Refining, and Rover/Drone Recon unlock automatically at <strong>Sol 3</strong> or <strong>40 Science Points</strong>.
      </div>`;
    grid.innerHTML = '';
    return;
  }

  banner.innerHTML = '';
  const p4Locked = !u.systems.manufacturing;

  grid.innerHTML = `
    <div class="panel">
      <div>
        <div class="panel-header">
          <span class="panel-title">Regolith Mining &amp; Sabatier Fuel</span>
          <span class="status-pill op">PHASE II</span>
        </div>
        <div class="label-mono">Geologists gain 1.5x mining yield (+1.5x with a Rover). Engineers gain 1.5x on fuel &amp; refining.</div>
      </div>
      <div>
        <div class="ctrl-row">
          <select id="selIndWorker">${wOptions}</select>
          <button onclick="runWithWorker('mine', 'selIndWorker')">Mine (15 Power, 10 Fuel)</button>
          <button onclick="runWithWorker('produce_fuel', 'selIndWorker')">Synthesize Fuel (6 CO2, 8 H2, 20 Power)</button>
        </div>
        <div class="ctrl-row">
          <select id="selMat">
            <option value="steel">Steel (20 Dirt, 20 Power)</option>
            <option value="aluminum">Aluminum (20 Dirt, 20 Power)</option>
            <option value="glass">Glass (15 Dirt, 15 Power)</option>
            <option value="plastic">Plastic (5 CO2, 5 H2, 15 Power)</option>
          </select>
          <button onclick="runWithWorkerVal('refine_materials', 'selIndWorker', 'selMat')">Refine Material</button>
        </div>
      </div>
    </div>

    <div class="panel">
      <div>
        <div class="panel-header">
          <span class="panel-title">Surface Recon Expeditions</span>
          <span class="status-pill op">PHASE II</span>
        </div>
        <div class="label-mono">Deploy Rovers (Geologist bonus) or Drones (Pilot bonus) for Science Points, Dirt, and Crop Seeds.</div>
      </div>
      <div>
        <div class="ctrl-row">
          <select id="selExpWorker">${wOptions}</select>
          <button onclick="runWithWorker('deploy_rover', 'selExpWorker')">Deploy Rover (12 Fuel, 10 Power)</button>
          <button onclick="runWithWorker('fly_drone', 'selExpWorker')">Fly Drone (8 Fuel, 8 Power)</button>
        </div>
      </div>
    </div>

    ${p4Locked ? `
      <div class="lock-overlay-card" style="grid-column: 1 / -1;">
        <strong>PHASE IV CLEARANCE REQUIRED FOR HEAVY FABRICATION &amp; SATELLITE DEPLOYMENT</strong>
        Spacecraft Manufacturing and Satellite Deployment unlock at <strong>Sol 10</strong> or <strong>250 Science Points</strong>. Resupply rockets use the separate thresholds above.
      </div>
    ` : `
      <div class="panel">
        <div>
          <div class="panel-header">
            <span class="panel-title">Vehicle &amp; Spacecraft Fabrication</span>
            <span class="status-pill op">PHASE IV</span>
          </div>
          <div class="label-mono">Assemble drones, rovers, orbital satellites, and heavy rockets from refined alloys.</div>
        </div>
        <div>
          <div class="ctrl-row">
            <select id="selMfgWorker">${wOptions}</select>
            <select id="selItem">
              <option value="drones">Drone (15 Al, 10 Plastic, 5 Glass, 20 Power)</option>
              <option value="rovers">Rover (40 Al, 30 Steel, 15 Plastic, 10 Glass, 40 Power)</option>
              <option value="satellites">Satellite (25 Al, 15 Plastic, 20 Glass, 45 Power)</option>
              <option value="rockets">Rocket (120 Al, 100 Steel, 40 Plastic, 25 Glass, 100 Power)</option>
              <option value="cars">Car (35 Al, 35 Steel, 20 Plastic, 15 Glass, 35 Power)</option>
              <option value="trucks">Truck (50 Al, 60 Steel, 20 Plastic, 15 Glass, 50 Power)</option>
            </select>
            <button class="btn-primary" onclick="runWithWorkerVal('manufacture', 'selMfgWorker', 'selItem')">Manufacture</button>
          </div>
        </div>
      </div>

      <div class="panel">
        <div>
          <div class="panel-header">
            <span class="panel-title">Orbital Launch Complex</span>
            <span class="status-pill op">PHASE IV</span>
          </div>
          <div class="label-mono">Satellites permanently boost daily solar power (+20 kWh).</div>
        </div>
        <div class="ctrl-row">
          <select id="selOrbWorker">${wOptions}</select>
          <button class="btn-primary" onclick="runWithWorker('launch_satellite', 'selOrbWorker')">Launch Satellite (1 Sat, 1 Rocket, 80 Fuel)</button>
        </div>
      </div>
    `}
  `;
}

function renderRocketOps(wOptions) {
  const unlocked = STATE.rocket_resupply.unlocked;
  const requirements = STATE.rocket_resupply.requirements;
  const rocketUsage = STATE.daily_action_usage.launch_rocket;
  const statusText = unlocked
    ? 'Resupply launch threshold met.'
    : 'Unlock when any one threshold is met.';
  document.getElementById('rocketOpsPanel').innerHTML = `
    <div class="panel">
      <div>
        <div class="panel-header">
          <span class="panel-title">Orbital Resupply Rocket</span>
          <span class="status-pill ${unlocked ? 'op' : 'idle'}">${unlocked ? 'UNLOCKED' : 'LOCKED'}</span>
        </div>
        <div class="label-mono">${statusText} Thresholds: 100 Science (${requirements.science.current}/100), 500 mined units (${requirements.mined_units.current}/500), or 30 living, non-retired people (${requirements.active_people.current}/30).</div>
        <div class="label-mono" style="margin-top:5px;">Payload limit: 100 tonnes. Resource units count as 1 kg; human 80 kg; robot 500 kg; car 1,500 kg; truck 5,000 kg; rover 1,000 kg; satellite 600 kg; rocket 25,000 kg; drone 20 kg.</div>
      </div>
      <div class="ctrl-row">
        <select id="selRocketWorker">${wOptions}</select>
        <select id="rocketPayloadItem">
          ${STATE.rocket_payload_items.map(item => `<option value="${item.key}">${item.label} (${item.weight_kg} kg/unit)</option>`).join('')}
        </select>
        <input type="number" id="rocketPayloadAmount" min="0.1" step="1" value="1" style="width:82px;" aria-label="Payload quantity" />
        <button onclick="addRocketPayload()">Add to Payload</button>
      </div>
      <div id="rocketPayloadSummary"></div>
      <div class="ctrl-row">
        <button class="btn-ok" id="btnLaunchRocket" onclick="launchResupplyRocket()" ${unlocked && rocketUsage.used < rocketUsage.limit ? '' : 'disabled'}>Launch Resupply (1 Rocket, 120 Fuel, 60 Power)</button>
        <span class="label-mono">Launches today: ${rocketUsage.used}/${rocketUsage.limit}</span>
        <span class="label-mono">Launch yields science and delivers the selected cargo.</span>
      </div>
    </div>`;
  const itemSelect = document.getElementById('rocketPayloadItem');
  const quantityInput = document.getElementById('rocketPayloadAmount');
  itemSelect.addEventListener('change', () => {
    const item = STATE.rocket_payload_items.find(candidate => candidate.key === itemSelect.value);
    const wholeUnits = ['people', 'robots', 'cars', 'trucks', 'rovers', 'satellites', 'rockets', 'drones'].includes(item.key);
    quantityInput.step = wholeUnits ? '1' : '0.1';
    quantityInput.min = wholeUnits ? '1' : '0.1';
    quantityInput.value = wholeUnits ? '1' : '0.1';
  });
  updateRocketPayloadSummary();
}

function setFarm(bIdx) {
  sendAction('configure_farm', [
    bIdx,
    document.getElementById('fCrop_' + bIdx).value,
    document.getElementById('fType_' + bIdx).value
  ]);
}
function runLab(bIdx) {
  sendAction('run_research', [bIdx, parseInt(document.getElementById('rPts_' + bIdx).value, 10) || 1]);
}

function renderCatalog() {
  if (!STATE) return;
  const q = (document.getElementById('filterInput').value || '').toLowerCase();
  const showLocked = document.getElementById('showLockedChk').checked;
  const buildUsage = STATE.daily_action_usage.construct_building;
  const items = STATE.catalog.filter(c => {
    if (!showLocked && !c.unlocked) return false;
    return c.key.includes(q) || c.name.toLowerCase().includes(q) || c.type.toLowerCase().includes(q);
  });
  document.getElementById('catalogGrid').innerHTML = items.map(c => {
    const reqs = Object.entries(c.required_professions).map(([p, [lo, hi]]) => `${p} ${lo}-${hi}`).join(', ') || 'none';
    const actionBtn = c.unlocked && buildUsage.used < buildUsage.limit
      ? `<button class="btn-primary" onclick="sendAction('construct_building', ['${c.key}'])">Construct</button>`
      : (c.unlocked
        ? `<button class="btn-primary" disabled>Daily Build Limit Reached</button>`
        : `<span class="status-pill idle">LOCKED (${c.unlock_req})</span>`);
    return `
      <div class="panel" style="${c.unlocked ? '' : 'opacity:0.62;'}">
        <div class="panel-header">
          <span class="panel-title">${c.name} <span class="label-mono">[${c.key}]</span></span>
          ${actionBtn}
        </div>
        <div class="label-mono">Cost: ${c.power_cost} Power, ${c.steel_cost} Steel, ${c.aluminum_cost} Al | Vol: ${c.volume}m&sup3;</div>
        <div class="label-mono">Staff (${c.max_workers} max): ${reqs} | Upkeep: ${fmtCosts(c.operating_costs)}</div>
      </div>`;
  }).join('');
}

loadState();
</script>
</body>
</html>
"""


def make_handler(session: MissionSession):
    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                body = HTML_PAGE.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path == "/api/state":
                self._send_json(session.snapshot())
            elif path == "/api/setup_options":
                self._send_json(session.setup_options())
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                self._send_json({"ok": False, "message": "Invalid JSON"}, HTTPStatus.BAD_REQUEST)
                return

            if path == "/api/action":
                action = str(data.get("action", ""))
                args = list(data.get("args", []))
                card_id = data.get("card_id")
                self._send_json(session.execute_action(action, args, card_id=card_id))
            elif path == "/api/new_game":
                try:
                    state = session.new_mission(
                        space_key=str(data.get("space_key", "mars")),
                        crew_count=int(data.get("crew_count", 6)),
                        target_sols=int(data.get("target_sols", 30)),
                        target_sci=float(data.get("target_sci", 500.0)),
                        unlock_all=bool(data.get("unlock_all", False)),
                        human_candidate_ids=data.get("human_candidate_ids"),
                        robot_candidate_ids=data.get("robot_candidate_ids"),
                        starting_resources=data.get("starting_resources"),
                    )
                except (TypeError, ValueError) as err:
                    self._send_json({"ok": False, "message": str(err)}, HTTPStatus.BAD_REQUEST)
                    return
                self._send_json(state)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Living on Red — Daedalus Team Mission Control UI")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port number (default 8000)")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open browser")
    args = parser.parse_args()

    session = MissionSession()
    handler = make_handler(session)

    # Prefer the requested port, but let Windows choose an available ephemeral
    # port if the preferred one is already occupied or cannot be bound.
    try:
        server = ThreadingHTTPServer((args.host, args.port), handler)
    except OSError as bind_error:
        if args.port == 0:
            raise
        print(
            f"Could not use port {args.port} on {args.host} ({bind_error}). "
            "Selecting an available port instead."
        )
        server = ThreadingHTTPServer((args.host, 0), handler)

    bound_host, bound_port = server.server_address[:2]
    # Wildcard addresses are valid bind targets, but not browser destinations.
    browser_host = str(bound_host)
    if browser_host in ("0.0.0.0", ""):
        browser_host = "127.0.0.1"
    elif browser_host == "::":
        browser_host = "::1"
    if ":" in browser_host and not browser_host.startswith("["):
        browser_host = f"[{browser_host}]"

    url = f"http://{browser_host}:{bound_port}"
    print(f"Living on Red — Mission Control running at {url}")
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
        print("Shutting down Mission Control.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
