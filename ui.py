"""Browser-based NASA Mission Control GUI for Living on Red.

Zero external dependencies (uses Python standard library http.server + json).
Run:
    python ui.py
    python ui.py --port 8080 --no-browser
"""

import argparse
import json
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List
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
from actions import SPACE_ENVIRONMENTS, build_from_catalog

try:
    from cli import BUILD_TYPES
except ImportError:
    BUILD_TYPES = [
        "power", "water", "iceminer", "oxygen", "co2", "nitrogen", "hydrogen", "food", "fuel",
        "aluminum", "steel", "soil", "plastic", "glass",
        "farm_lettuce", "farm_wheat", "farm_flax", "farm_sunflower",
        "car_factory", "truck_factory", "rover_factory", "satellite_factory", "rocket_factory", "drone_factory",
        "habitation", "recreation", "canteen", "logistics", "research", "university",
        "medical_bay", "hospital", "graveyard", "comms_hub", "satellite_dish",
    ]


PHASE_CATALOG: Dict[str, int] = {
    "power": 1, "water": 1, "oxygen": 1, "food": 1,
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
        self.new_mission("mars", 6, 30, 500.0, unlock_all=False)

    def new_mission(
        self,
        space_key: str,
        crew_count: int,
        target_sols: int,
        target_sci: float,
        unlock_all: bool = False,
    ) -> Dict[str, Any]:
        with self.lock:
            space = space_key if space_key in SPACE_ENVIRONMENTS else "mars"
            crew = max(2, min(10, int(crew_count)))
            self.target_sols = max(5, min(365, int(target_sols)))
            self.target_sci = float(max(50, min(10000, target_sci)))
            self.aborted = False
            self.unlock_all_override = bool(unlock_all)
            self.announced_phases = {1}

            all_buildings.clear()
            Worker.TotalCount = 0
            Worker.AvailableCount = 0
            for attr, inv in vars(resource_inventory).items():
                if isinstance(inv, resource_inventory.resources):
                    inv.current = 0
                    inv.max = 10000 if attr == "research" else 0

            self.router = game.setup_game(space_key=space, crew_count=crew)
            state = self.router.state

            # Ensure every crew member has a stable, non-Unassigned specialist role
            role_cycle = [1, 2, 3, 4, 5, 2, 3, 4, 5, 1]
            for idx, w in enumerate(state.workers):
                if w.getType() == Profession.Unassigned:
                    w.setType(role_cycle[idx % len(role_cycle)])

            self._evaluate_unlocks_locked(announce=False)
            return self._serialize_locked()

    def _compute_unlocks_locked(self) -> Dict[str, Any]:
        state = self.router.state
        sol = int(state.sol)
        sci = float(state.science_points)
        ov = self.unlock_all_override

        p2 = ov or sol >= 3 or sci >= 40.0
        p3 = ov or sol >= 6 or sci >= 120.0
        p4 = ov or sol >= 10 or sci >= 250.0

        max_phase = 4 if p4 else (3 if p3 else (2 if p2 else 1))
        return {
            "max_phase": max_phase,
            "override": ov,
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

    def execute_action(self, action: str, args: List[Any]) -> Dict[str, Any]:
        with self.lock:
            state = self.router.state
            unlocks = self._compute_unlocks_locked()
            sys_locks = unlocks["systems"]

            # Enforce permanent, stable crew roles
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

            gated_actions = {
                "mine": ("mining_refining", "Phase II (Sol 3 or 40 Science)"),
                "produce_fuel": ("mining_refining", "Phase II (Sol 3 or 40 Science)"),
                "refine_materials": ("mining_refining", "Phase II (Sol 3 or 40 Science)"),
                "deploy_rover": ("recon_expeditions", "Phase II (Sol 3 or 40 Science)"),
                "fly_drone": ("recon_expeditions", "Phase II (Sol 3 or 40 Science)"),
                "run_research": ("research_academy", "Phase III (Sol 6 or 120 Science)"),
                "manufacture": ("manufacturing", "Phase IV (Sol 10 or 250 Science)"),
                "launch_satellite": ("orbital_launches", "Phase IV (Sol 10 or 250 Science)"),
                "launch_rocket": ("orbital_launches", "Phase IV (Sol 10 or 250 Science)"),
            }
            if action in gated_actions:
                sys_key, req_label = gated_actions[action]
                if not sys_locks.get(sys_key, False):
                    return {
                        "ok": False,
                        "message": f"System locked. Unlocks at {req_label}.",
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
                    ran += 1
                    self._evaluate_unlocks_locked(announce=True)
                    active_crew = [w for w in state.workers if not getattr(w, "retired", False) and w.getHealth() > 0]
                    if not res or not active_crew or state.sol >= self.target_sols:
                        break
                    if len(state.hazard_manager.active_incidents) > crises_before:
                        halt_reason = " Halted for new crisis alert."
                        break
                    if self._compute_unlocks_locked()["max_phase"] > phase_before:
                        halt_reason = " Halted for new system clearance."
                        break
                return {
                    "ok": True,
                    "message": f"Advanced {ran} Sol(s).{halt_reason}",
                    "state": self._serialize_locked(),
                }

            before_len = len(state.log)
            try:
                result = self.router.execute(action, *args)
                self._evaluate_unlocks_locked(announce=True)
                new_entries = state.log[before_len:]
                msg = new_entries[-1] if new_entries else f"Executed {action}."
                ok = True if result is None else bool(result)
                return {"ok": ok, "message": msg, "state": self._serialize_locked()}
            except Exception as err:
                return {"ok": False, "message": f"{type(err).__name__}: {err}", "state": self._serialize_locked()}

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return self._serialize_locked()

    def _serialize_locked(self) -> Dict[str, Any]:
        state = self.router.state
        unlocks = self._compute_unlocks_locked()
        active_crew = [
            w for w in state.workers
            if not getattr(w, "retired", False) and w.getHealth() > 0
        ]
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
            if getattr(w, "retired", False):
                status = "Retired"
            elif w.getHealth() <= 0:
                status = "Deceased"
            elif getattr(w, "assigned_building", None) is not None:
                status = f"Staffed @ {w.assigned_building.name}"
            elif w.isAvailable():
                status = "Ready"
            else:
                status = "Busy"

            workers_out.append({
                "index": idx,
                "name": w.Name,
                "age_years": int(w.age // 365),
                "health": round(float(w.getHealth()), 1),
                "profession": job_name,
                "role_title": profile["title"],
                "role_summary": profile["summary"],
                "role_buildings": profile["buildings"],
                "role_bonus": profile["bonus"],
                "available": bool(w.isAvailable()),
                "retired": bool(getattr(w, "retired", False)),
                "assigned_building": w.assigned_building.name if getattr(w, "assigned_building", None) else None,
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

        mission_over = False
        mission_status = "ACTIVE"
        mission_reason = ""
        if not active_crew:
            mission_over = True
            mission_status = "FAILED"
            mission_reason = "Total loss of crew. Life support reserves depleted or crises overwhelmed the colony."
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
            "total_crew_count": len(state.workers),
            "active_volume": round(total_volume, 1),
            "crisis_risk_pct": int(round(state.hazard_manager.last_risk_score * 100)),
            "avg_safety": round(avg_safety, 1),
            "unlocks": unlocks,
            "mission_over": mission_over,
            "mission_status": mission_status,
            "mission_reason": mission_reason,
            "resources": resources_out,
            "buildings": buildings_out,
            "workers": workers_out,
            "crises": crises_out,
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
  @keyframes titleFadeIn {
    to { opacity: 1; }
  }
  @keyframes titleScaleIn {
    to { opacity: 1; transform: scale(1); }
  }

  /* ==================== CREW BRIEFING & TUTORIAL SPOTLIGHTS ==================== */
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
  .guided-title {
    font-size: 14px;
    font-weight: 700;
    color: #fff;
    margin-left: 8px;
  }
  .guided-body {
    font-size: 12.5px;
    color: #bae6fd;
    margin-top: 4px;
  }

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
    z-index: 350;
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
    max-width: 760px;
    width: 100%;
    max-height: 90vh;
    overflow-y: auto;
    box-shadow: 0 24px 64px rgba(0, 0, 0, 0.85);
  }
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

    <div class="notice-strip" style="margin-top:8px;">
      <strong>How Staffing Works:</strong> Your specialists start assigned to core life-support buildings so your base runs automatically. To use a specialist for a manual shift or field expedition, click their badge in <strong>2. Buildings &amp; Staffing</strong> to unstaff them first.
    </div>

    <div class="grid-2col" id="crewIntroCards" style="margin-top:10px;"></div>

    <div class="ctrl-row" style="margin-top:14px;justify-content:space-between;">
      <button onclick="openManual()">Read Full Manual</button>
      <div class="btn-group">
        <button onclick="closeCrewIntro(false)">Enter Console Without Tutorial</button>
        <button class="btn-mars" style="padding:8px 16px;" onclick="closeCrewIntro(true)">Start Interactive Tutorial &rarr;</button>
      </div>
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
    <div class="kpi">CREW <strong id="kpiCrew">6/6</strong></div>
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
      <span class="step-counter" id="tutStepTag">STEP 1 OF 6</span>
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
      <button class="nav-tab" data-pane="crew" onclick="selectPane('crew', this)">3. Crew Roster</button>
      <button class="nav-tab" data-pane="construct" onclick="selectPane('construct', this)">4. Construct Facilities</button>
      <button class="nav-tab" data-pane="field" onclick="selectPane('field', this)">5. Field Ops &amp; Launches <span class="lock-tag" id="fieldLockTag">[PHASE II]</span></button>
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
        <strong>Step-by-Step Staffing:</strong> Buildings marked <strong>OP</strong> are staffed and producing every Sol. Click any specialist button (e.g. <code>[5] Name (Engineer) &times;</code>) to free them for manual shifts, or select a Ready matching specialist to staff an <strong>IDLE</strong> building.
      </div>
      <div class="grid-2col" id="buildingsGrid"></div>
    </section>

    <!-- PANE 3: CREW ROSTER -->
    <section class="view-pane" id="pane-crew">
      <div class="notice-strip">
        <strong>Permanent Crew Specialties:</strong> Each astronaut is locked to their trained mission role (Doctor, Engineer, Biologist, Geologist, or Pilot). Unstaffed crew can rest to heal, study to boost role skill, or visit the hospital.
      </div>
      <div class="grid-2col" id="crewGrid"></div>
    </section>

    <!-- PANE 4: CONSTRUCT FACILITIES -->
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

    <!-- PANE 5: FIELD OPS & LAUNCHES -->
    <section class="view-pane" id="pane-field">
      <div id="fieldLockedBanner"></div>
      <div id="fieldWorkerNotice"></div>
      <div class="grid-2col" id="fieldGrid"></div>
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
  <div class="modal-box">
    <h2>Mission Configuration &mdash; Daedalus Team</h2>
    <div class="label-mono">Select destination environment, crew complement, and mission parameters.</div>
    <div class="env-options" id="envOptionsGrid"></div>
    <div class="ctrl-row" style="margin-top:10px;">
      <label class="label-mono">Crew (2-10): <input type="number" id="inCrew" min="2" max="10" value="6" style="width:64px;" /></label>
      <label class="label-mono">Target Sols: <input type="number" id="inSols" min="5" max="365" value="30" style="width:72px;" /></label>
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
      <h3>2. PERMANENT CREW SPECIALTIES</h3>
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
      <h3>3. PROGRESSIVE CLEARANCE UNLOCKS</h3>
      <table class="manual-table">
        <tr><th>Phase</th><th>Unlock Condition</th><th>Capabilities Unlocked</th></tr>
        <tr><td>Phase I</td><td>Sol 1 (Landing)</td><td>Life Support (MOXIE, Hydroponics, Atmosphere), Building Staffing, Crew Roster, Basic Habitat &amp; Utility Construction.</td></tr>
        <tr><td>Phase II</td><td>Sol 3 or 40 Science</td><td>Regolith &amp; Ice Mining, Sabatier Fuel Synthesis, Material Refining, Rover &amp; Drone Recon.</td></tr>
        <tr><td>Phase III</td><td>Sol 6 or 120 Science</td><td>Research Lab Point Synthesis, Communications Hub &amp; Satellite Dish.</td></tr>
        <tr><td>Phase IV</td><td>Sol 10 or 250 Science</td><td>Spacecraft &amp; Vehicle Manufacturing and Orbital Satellite / Rocket Launches.</td></tr>
      </table>
    </div>

    <div class="manual-section">
      <h3>4. EMERGENCY CRISIS RESOLUTION</h3>
      <table class="manual-table">
        <tr><th>Crisis</th><th>Effect</th><th>Required Resources &amp; Ready Crew</th></tr>
        <tr><td>Grid Overload</td><td>Drains 35% stored power &amp; trips PowerPlants off.</td><td>50 Aluminum + 2 ready Engineers</td></tr>
        <tr><td>Ammonia Coolant Leak</td><td>10 initial toxic damage + escalating damage/Sol.</td><td>10 Plastic + 15 Water + 1 ready Doctor</td></tr>
        <tr><td>Micrometeorite Breach</td><td>Reduces building safety (-35%) &amp; vents Oxygen.</td><td>80 Steel + 80 Dirt + 1 Geologist + 1 Engineer</td></tr>
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

const TUTORIAL_FLOW = [
  {
    title: 'Step 1: Monitor Your 4 Core Life-Support Vitals',
    desc: 'Look at Food, Water, Power, and Oxygen at the top. Every Sol your crew consumes rations and your base draws Power. Click "Next Step" to inspect your buildings.',
    pane: 'ops',
    spotId: 'vitalsGrid'
  },
  {
    title: 'Step 2: Open Buildings & Staffing',
    desc: 'Click the highlighted "2. Buildings & Staffing" tab to see which facilities are Operational (OP) and which specialists are staffed inside them.',
    pane: 'ops',
    spotSelector: '.nav-tab[data-pane="buildings"]'
  },
  {
    title: 'Step 3: Free a Specialist for Field Shifts',
    desc: 'All 6 crew members start staffed inside buildings. Click the unstaff button on [2] MOXIE Oxygen Generator (or any staffed badge) so that Engineer becomes READY.',
    pane: 'buildings',
    spotSelector: '#buildingsGrid .panel:nth-child(3) .ctrl-row button'
  },
  {
    title: 'Step 4: Run a Manual Life-Support Shift',
    desc: 'Now that you have a Ready Engineer, click "Run MOXIE (+O2)" below to convert CO2 and Electricity into emergency Oxygen.',
    pane: 'ops',
    spotId: 'btnMoxie'
  },
  {
    title: 'Step 5: Advance 1 Sol (Simulate 24 Hours)',
    desc: 'Click "Advance 1 Sol" in the top bar. Automated buildings will produce resources, Logistics will transfer them, and you will see your Net Balance per Sol.',
    pane: 'ops',
    spotId: 'btnAdvance1'
  },
  {
    title: 'Step 6: Expand & Unlock New Phases',
    desc: 'Notice your daily Food/Power net balance. Open "4. Construct Facilities" to build another Food Factory or Power Plant, and reach Sol 3 to unlock Phase II Mining!',
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
          <span class="status-pill role">${w.profession} (PERMANENT)</span>
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
  } else if (tutorialIdx === 2 && evt === 'unstaff_building') {
    tutorialIdx = 3;
    const tabBtn = document.querySelector('.nav-tab[data-pane="ops"]');
    if (tabBtn) selectPane('ops', tabBtn, true);
    renderTutorial();
  } else if (tutorialIdx === 3 && ['run_moxie', 'hydroponics', 'food_refinery'].includes(evt)) {
    tutorialIdx = 4;
    renderTutorial();
  } else if (tutorialIdx === 4 && ['advance_sol', 'advance_sols'].includes(evt)) {
    tutorialIdx = 5;
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

async function sendAction(action, args = []) {
  const res = await fetch('/api/action', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, args })
  });
  const data = await res.json();
  STATE = data.state;
  toast(data.message, !data.ok);
  renderConsole();
  if (data.ok) onTutorialEvent(action);
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
  if (isNaN(idx)) return toast('No Ready specialist available. Click "Unstaff 1 Specialist" first.', true);
  sendAction(action, [idx]);
}

function runWithWorkerCrop(action) {
  const idx = parseInt(document.getElementById('selOpsWorker').value, 10);
  const crop = document.getElementById('selCrop').value;
  if (isNaN(idx)) return toast('No Ready specialist available. Click "Unstaff 1 Specialist" first.', true);
  sendAction(action, [idx, crop]);
}

function runWithWorkerVal(action, wSelId, vSelId) {
  const idx = parseInt(document.getElementById(wSelId).value, 10);
  const val = document.getElementById(vSelId).value;
  if (isNaN(idx)) return toast('No Ready specialist available. Click "Unstaff 1 Specialist" first.', true);
  sendAction(action, [idx, val]);
}

function selectPane(name, btn, skipTutorialHook = false) {
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.view-pane').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('pane-' + name).classList.add('active');
  if (!skipTutorialHook && name === 'buildings') onTutorialEvent('OPEN_BUILDINGS');
  if (tutorialIdx >= 0) setTimeout(() => applySpotlight(TUTORIAL_FLOW[tutorialIdx]), 60);
}

function openSetupModal() {
  chosenEnv = STATE ? STATE.space_key : 'mars';
  renderEnvGrid();
  document.getElementById('setupModal').classList.add('open');
}
function closeSetupModal() { document.getElementById('setupModal').classList.remove('open'); }
function openManual() { document.getElementById('manualModal').classList.add('open'); }
function closeManual() { document.getElementById('manualModal').classList.remove('open'); }
function closeReportModal() { document.getElementById('reportModal').classList.remove('open'); }

window.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    closeManual();
    closeSetupModal();
  }
});

function renderEnvGrid() {
  if (!STATE) return;
  document.getElementById('envOptionsGrid').innerHTML = Object.entries(STATE.environments).map(([k, info]) => `
    <div class="env-opt ${chosenEnv === k ? 'active' : ''}" onclick="chosenEnv='${k}'; renderEnvGrid();">
      <strong>${info.label}</strong>
      <div class="label-mono" style="margin-top:3px;">Solar x${info.solar_multiplier} | Power/100m&sup3;: -${info.power_per_100m3} | Hazard: ${Math.round(info.hazard_chance * 100)}%</div>
    </div>
  `).join('');
}

async function launchConfiguredMission() {
  const crew_count = parseInt(document.getElementById('inCrew').value, 10) || 6;
  const target_sols = parseInt(document.getElementById('inSols').value, 10) || 30;
  const target_sci = parseFloat(document.getElementById('inSci').value) || 500;
  const unlock_all = document.getElementById('inUnlockAll').checked;
  const res = await fetch('/api/new_game', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ space_key: chosenEnv, crew_count, target_sols, target_sci, unlock_all })
  });
  STATE = await res.json();
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
         <span>All active specialists are staffed inside buildings. Free a specialist to run manual shifts or expeditions.</span>
         <button class="btn-primary" onclick="quickUnstaffFirst()">Unstaff 1 Specialist Now</button>
       </div>`
    : '';
  document.getElementById('opsWorkerNotice').innerHTML = workerNotice;
  document.getElementById('fieldWorkerNotice').innerHTML = workerNotice;

  const wOptions = readyCrew.length
    ? readyCrew.map(w => `<option value="${w.index}">[${w.index}] ${w.name} (${w.profession}, HP ${w.health})</option>`).join('')
    : '<option value="">No Ready Specialists (Unstaff 1 first)</option>';
  document.getElementById('selOpsWorker').innerHTML = wOptions;

  const deltas = Object.entries(STATE.resources)
    .filter(([, r]) => r.net !== 0)
    .map(([k, r]) => `<span class="${r.net > 0 ? 'delta-pos' : 'delta-neg'}">${k} ${r.net > 0 ? '+' : ''}${r.net}</span>`);
  document.getElementById('solBalanceSummary').innerHTML = deltas.length ? deltas.join(' | ') : 'Awaiting Sol 1 completion';

  document.getElementById('stockGrid').innerHTML = Object.entries(STATE.resources)
    .filter(([, r]) => r.max > 0 || r.current > 0)
    .map(([k, r]) => {
      const d = r.net !== 0 ? ` <span class="${r.net > 0 ? 'delta-pos' : 'delta-neg'}">(${r.net > 0 ? '+' : ''}${r.net})</span>` : '';
      return `<div class="stock-cell"><span>${k}${d}</span><strong>${r.current}/${r.max}</strong></div>`;
    }).join('');

  document.getElementById('buildingsGrid').innerHTML = STATE.buildings.map(b => {
    const pillCls = !b.is_on ? 'off' : (b.is_operational ? 'op' : 'idle');
    const pillTxt = !b.is_on ? 'OFF' : (b.is_operational ? 'OP' : 'IDLE');
    const reqs = Object.entries(b.required_professions).map(([p, [lo, hi]]) => `${p} ${lo}-${hi}`).join(', ') || 'none';
    const local = Object.entries(b.local_storage).map(([k, v]) => `${k}: ${v.current}/${v.max}`).join(' | ');
    const allowed = Object.keys(b.required_professions);
    const eligible = readyCrew.filter(w => allowed.includes(w.profession));

    const staffHtml = eligible.length
      ? `<select id="stSel_${b.index}">${eligible.map(w => `<option value="${w.index}">[${w.index}] ${w.name} (${w.profession})</option>`).join('')}</select>
         <button class="btn-ok" onclick="assignStaff(${b.index})">Assign Staff</button>`
      : `<span class="label-mono">Needs Ready ${allowed.join('/')}</span>`;

    const badges = b.assigned_workers.map(w =>
      `<button onclick="sendAction('unstaff_building', [${b.index}, ${w.index}])" title="Click to unstaff">[${w.index}] ${w.name} (${w.profession}) &times;</button>`
    ).join(' ');

    let extraHtml = '';
    if ((b.kind === 'Producer' || b.kind === 'Farm') && readyCrew.length) {
      extraHtml += `
        <div class="ctrl-row">
          <select id="shSel_${b.index}">${readyCrew.map(w => `<option value="${w.index}">[${w.index}] ${w.name}</option>`).join('')}</select>
          <button onclick="manualShift(${b.index})">Manual Shift (15 Power)</button>
        </div>`;
    }
    if (b.kind === 'Farm') {
      const crops = ['lettuce', 'wheat', 'flax', 'sunflower'];
      extraHtml += `
        <div class="ctrl-row">
          <select id="fCrop_${b.index}">${crops.map(c => `<option value="${c}" ${b.farm_crop === c ? 'selected' : ''}>${c}</option>`).join('')}</select>
          <select id="fType_${b.index}">
            <option value="crop" ${b.farm_product === 'crop' ? 'selected' : ''}>Crop</option>
            <option value="seed" ${b.farm_product === 'seed' ? 'selected' : ''}>Seeds</option>
          </select>
          <button class="btn-primary" onclick="setFarm(${b.index})">Set Output</button>
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
            ${staffHtml}
            <button onclick="sendAction('toggle_building', [${b.index}])">${b.is_on ? 'Turn Off' : 'Turn On'}</button>
          </div>
          ${extraHtml}
        </div>
      </div>`;
  }).join('');

  // Crew Roster (Stable Permanent Roles — no role changing)
  document.getElementById('crewGrid').innerHTML = STATE.workers.map(w => `
    <div class="panel">
      <div>
        <div class="panel-header">
          <span class="panel-title">[${w.index}] ${w.name}</span>
          <div class="btn-group">
            <span class="status-pill role">${w.profession} (FIXED)</span>
            <span class="status-pill ${w.available ? 'op' : 'idle'}">${w.status}</span>
          </div>
        </div>
        <div class="label-mono" style="color:#cbd5e1;">${w.role_title}</div>
        <div class="label-mono">HP ${w.health}% | Specialty Skill ${w.role_skill} | Debuff ${w.role_debuff} | Age ${w.age_years}y</div>
        <div style="font-size:11.5px;color:var(--muted);margin-top:4px;">${w.role_bonus}</div>
      </div>
      <div>
        <div class="ctrl-row">
          <button onclick="sendAction('work', [${w.index}])" ${!w.available ? 'disabled' : ''}>General Shift (+Power)</button>
          <button onclick="sendAction('rest', [${w.index}])" ${w.assigned_building || w.retired || w.health <= 0 ? 'disabled' : ''}>Rest (+HP)</button>
          <button onclick="sendAction('hospital', [${w.index}])" ${!w.available ? 'disabled' : ''}>Hospital</button>
          <button onclick="sendAction('study', [${w.index}])" ${!w.available ? 'disabled' : ''}>Study (+Skill)</button>
          <button class="btn-danger" onclick="sendAction('retire', [${w.index}])" ${w.retired || w.health <= 0 ? 'disabled' : ''}>Retire</button>
        </div>
      </div>
    </div>
  `).join('');

  document.getElementById('phaseScheduleLabel').textContent =
    `Current Clearance: Phase ${u.max_phase} | Next unlocks at Sol 3 / Sol 6 / Sol 10`;
  renderCatalog();
  renderFieldOps(wOptions, u);

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
      <div class="label-mono">Crew Survival: <strong>${STATE.active_crew_count} / ${STATE.total_crew_count}</strong></div>
      <div class="label-mono">Average Colony Safety: <strong>${STATE.avg_safety}%</strong></div>
    `;
    document.getElementById('reportModal').classList.add('open');
  }

  if (tutorialIdx >= 0) setTimeout(() => applySpotlight(TUTORIAL_FLOW[tutorialIdx]), 40);
}

function renderFieldOps(wOptions, u) {
  const banner = document.getElementById('fieldLockedBanner');
  const grid = document.getElementById('fieldGrid');

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
        <strong>PHASE IV CLEARANCE REQUIRED FOR HEAVY FABRICATION &amp; ORBITAL LAUNCHES</strong>
        Spacecraft Manufacturing, Satellite Deployment, and Orbital Resupply Rockets unlock at <strong>Sol 10</strong> or <strong>250 Science Points</strong>.
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
          <div class="label-mono">Satellites permanently boost daily solar power (+20 kWh). Rockets deliver +300 Science and resupply crates.</div>
        </div>
        <div>
          <div class="ctrl-row">
            <select id="selOrbWorker">${wOptions}</select>
            <button class="btn-primary" onclick="runWithWorker('launch_satellite', 'selOrbWorker')">Launch Satellite (1 Sat, 1 Rocket, 80 Fuel)</button>
            <button class="btn-ok" onclick="runWithWorker('launch_rocket', 'selOrbWorker')">Launch Rocket (1 Rocket, 120 Fuel)</button>
          </div>
        </div>
      </div>
    `}
  `;
}

function assignStaff(bIdx) {
  const sel = document.getElementById('stSel_' + bIdx);
  if (sel) sendAction('staff_building', [bIdx, parseInt(sel.value, 10)]);
}
function manualShift(bIdx) {
  const sel = document.getElementById('shSel_' + bIdx);
  if (sel) sendAction('operate_factory', [bIdx, [parseInt(sel.value, 10)]]);
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
  const items = STATE.catalog.filter(c => {
    if (!showLocked && !c.unlocked) return false;
    return c.key.includes(q) || c.name.toLowerCase().includes(q) || c.type.toLowerCase().includes(q);
  });
  document.getElementById('catalogGrid').innerHTML = items.map(c => {
    const reqs = Object.entries(c.required_professions).map(([p, [lo, hi]]) => `${p} ${lo}-${hi}`).join(', ') || 'none';
    const actionBtn = c.unlocked
      ? `<button class="btn-primary" onclick="sendAction('construct_building', ['${c.key}'])">Construct</button>`
      : `<span class="status-pill idle">LOCKED (${c.unlock_req})</span>`;
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
                self._send_json(session.execute_action(action, args))
            elif path == "/api/new_game":
                state = session.new_mission(
                    space_key=str(data.get("space_key", "mars")),
                    crew_count=int(data.get("crew_count", 6)),
                    target_sols=int(data.get("target_sols", 30)),
                    target_sci=float(data.get("target_sci", 500.0)),
                    unlock_all=bool(data.get("unlock_all", False)),
                )
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
    server = ThreadingHTTPServer((args.host, args.port), make_handler(session))
    url = f"http://{args.host}:{args.port}"
    print(f"Living on Red — Mission Control running at {url}")
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
        print("Shutting down Mission Control.")
        server.server_close()


if __name__ == "__main__":
    main()
