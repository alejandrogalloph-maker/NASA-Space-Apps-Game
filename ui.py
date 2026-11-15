"""Browser-based NASA Mission Control GUI for Colony Command.

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


class MissionSession:
    """Thread-safe wrapper around the live ActionRouter and mission targets."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.router: Any = None
        self.target_sols: int = 30
        self.target_sci: float = 500.0
        self.aborted: bool = False
        self.new_mission("mars", 6, 30, 500.0)

    def new_mission(self, space_key: str, crew_count: int, target_sols: int, target_sci: float) -> Dict[str, Any]:
        with self.lock:
            space = space_key if space_key in SPACE_ENVIRONMENTS else "mars"
            crew = max(2, min(10, int(crew_count)))
            self.target_sols = max(5, min(365, int(target_sols)))
            self.target_sci = float(max(50, min(10000, target_sci)))
            self.aborted = False

            all_buildings.clear()
            Worker.TotalCount = 0
            Worker.AvailableCount = 0
            for attr, inv in vars(resource_inventory).items():
                if isinstance(inv, resource_inventory.resources):
                    inv.current = 0
                    inv.max = 10000 if attr == "research" else 0

            self.router = game.setup_game(space_key=space, crew_count=crew)
            return self._serialize_locked()

    def execute_action(self, action: str, args: List[Any]) -> Dict[str, Any]:
        with self.lock:
            state = self.router.state
            if action == "abort_mission":
                self.aborted = True
                state.log.append("Mission aborted by Flight Director.")
                return {"ok": True, "message": "Mission aborted.", "state": self._serialize_locked()}

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
                    msg = f"{farm.name} reconfigured to produce {crop} ({ptype})."
                    state.log.append(msg)
                    return {"ok": True, "message": msg, "state": self._serialize_locked()}
                except Exception as err:
                    return {"ok": False, "message": f"{type(err).__name__}: {err}", "state": self._serialize_locked()}

            if action == "advance_sols":
                count = max(1, min(365, int(args[0]) if args else 5))
                crises_before = len(state.hazard_manager.active_incidents)
                ran = 0
                stopped_for_crisis = False
                for _ in range(count):
                    res = self.router.execute("advance_sol")
                    ran += 1
                    active_crew = [w for w in state.workers if not getattr(w, "retired", False) and w.getHealth() > 0]
                    if not res or not active_crew or state.sol >= self.target_sols:
                        break
                    if len(state.hazard_manager.active_incidents) > crises_before:
                        stopped_for_crisis = True
                        break
                msg = f"Advanced {ran} Sol(s)."
                if stopped_for_crisis:
                    msg += " Halted early due to new crisis alert!"
                return {"ok": True, "message": msg, "state": self._serialize_locked()}

            before_len = len(state.log)
            try:
                result = self.router.execute(action, *args)
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
        role_names_by_idx = ["Unassigned", "Doctor", "Engineer", "Biologist", "Geologist", "Pilot"]
        workers_out: List[Dict[str, Any]] = []
        for idx, w in enumerate(state.workers):
            job_name = w.getType().name
            p_idx = prof_index.get(job_name, 0)
            skills = w.getSkills()
            debuffs = w.getDebuffs()
            net_scores = [round(max(0.0, float(skills[i]) - 0.5 * float(debuffs[i])), 1) for i in range(6)]
            best_idx = max(range(1, 6), key=lambda i: net_scores[i])
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
                "age_days": int(w.age),
                "health": round(float(w.getHealth()), 1),
                "profession": job_name,
                "profession_code": prof_index.get(job_name, 0),
                "available": bool(w.isAvailable()),
                "retired": bool(getattr(w, "retired", False)),
                "assigned_building": w.assigned_building.name if getattr(w, "assigned_building", None) else None,
                "status": status,
                "role_skill": round(float(skills[p_idx]), 1),
                "role_debuff": round(float(debuffs[p_idx]), 1),
                "best_role": role_names_by_idx[best_idx],
                "best_score": net_scores[best_idx],
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
            catalog_out.append({
                "key": key,
                "name": sample.name,
                "type": s_cls.__name__,
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
                mission_reason = f"Survived {self.target_sols} Sols and achieved {state.science_points:.1f} Science!"
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
            "mission_over": mission_over,
            "mission_status": mission_status,
            "mission_reason": mission_reason,
            "resources": resources_out,
            "buildings": buildings_out,
            "workers": workers_out,
            "crises": crises_out,
            "catalog": catalog_out,
            "professions": [{"name": p.name, "code": p.value} for p in Profession],
            "log": state.log[-45:],
        }


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>NASA Space Apps 2026 — Daedalus Team | Living on Red</title>
<style>
  :root {
    --bg: #060913;
    --bg-elev: #0c1222;
    --panel: #10182c;
    --panel-alt: #16213b;
    --border: #233354;
    --border-hi: #364f80;
    --text: #e6edf7;
    --muted: #93a4c3;
    --accent: #38bdf8;
    --mars: #ea580c;
    --mars-glow: #fb923c;
    --ok: #22c55e;
    --warn: #f59e0b;
    --danger: #ef4444;
    --radius-lg: 12px;
    --radius-md: 8px;
    --radius-sm: 6px;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: 'Segoe UI', system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
    background:
      radial-gradient(ellipse at 85% 0%, rgba(234, 88, 12, 0.14) 0%, transparent 48%),
      radial-gradient(ellipse at 12% 8%, rgba(56, 189, 248, 0.10) 0%, transparent 45%),
      var(--bg);
    color: var(--text);
    min-height: 100vh;
    font-variant-numeric: tabular-nums;
  }

  /* ================= CINEMATIC INTRO SPLASH ================= */
  .intro-overlay {
    position: fixed;
    inset: 0;
    z-index: 200;
    background: #04060d;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    overflow: hidden;
    transition: opacity 0.85s cubic-bezier(0.22, 1, 0.36, 1), visibility 0.85s;
  }
  .intro-overlay.hidden {
    opacity: 0;
    visibility: hidden;
    pointer-events: none;
  }
  #marsCanvas {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    display: block;
  }
  .intro-vignette {
    position: absolute;
    inset: 0;
    background:
      radial-gradient(circle at 50% 42%, transparent 25%, rgba(4, 6, 13, 0.72) 100%),
      linear-gradient(180deg, rgba(4, 6, 13, 0.78) 0%, transparent 32%, transparent 68%, rgba(4, 6, 13, 0.92) 100%);
    pointer-events: none;
  }
  .intro-top-bar {
    position: relative;
    z-index: 2;
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 20px 28px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 11px;
    letter-spacing: 1.6px;
    color: var(--muted);
  }
  .intro-center {
    position: relative;
    z-index: 2;
    text-align: center;
    padding: 0 24px;
    margin-top: -4vh;
    pointer-events: none;
  }
  .intro-kicker {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 4px;
    color: var(--accent);
    text-transform: uppercase;
    opacity: 0;
    transform: translateY(14px);
    animation: riseFade 0.85s cubic-bezier(0.22, 1, 0.36, 1) 0.25s forwards;
  }
  .intro-team-row {
    display: inline-flex;
    align-items: center;
    gap: 14px;
    margin-top: 14px;
    padding: 7px 18px;
    border-radius: 999px;
    background: rgba(16, 24, 44, 0.72);
    border: 1px solid rgba(251, 146, 60, 0.38);
    backdrop-filter: blur(8px);
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 2.6px;
    color: #fed7aa;
    opacity: 0;
    transform: translateY(14px);
    animation: riseFade 0.85s cubic-bezier(0.22, 1, 0.36, 1) 0.75s forwards;
  }
  .intro-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--mars-glow);
    box-shadow: 0 0 10px var(--mars-glow);
  }
  .intro-title {
    margin: 18px 0 8px 0;
    font-size: clamp(38px, 6.8vw, 78px);
    font-weight: 900;
    letter-spacing: 10px;
    text-transform: uppercase;
    line-height: 1.05;
    background: linear-gradient(180deg, #ffffff 15%, #fed7aa 65%, #fb923c 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    filter: drop-shadow(0 8px 28px rgba(234, 88, 12, 0.35));
    opacity: 0;
    transform: translateY(18px) scale(0.98);
    animation: riseFade 1s cubic-bezier(0.22, 1, 0.36, 1) 1.25s forwards;
  }
  .intro-sub {
    font-size: 14px;
    letter-spacing: 2px;
    color: #cbd5e1;
    max-width: 620px;
    margin: 0 auto;
    opacity: 0;
    transform: translateY(12px);
    animation: riseFade 0.85s cubic-bezier(0.22, 1, 0.36, 1) 1.75s forwards;
  }
  .intro-cta-bar {
    position: relative;
    z-index: 3;
    display: flex;
    justify-content: center;
    gap: 14px;
    flex-wrap: wrap;
    padding: 0 20px 36px 20px;
    opacity: 0;
    transform: translateY(12px);
    animation: riseFade 0.85s cubic-bezier(0.22, 1, 0.36, 1) 2.15s forwards;
  }
  .btn-hero {
    padding: 12px 24px;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    border-radius: 8px;
    background: linear-gradient(135deg, #ea580c, #c2410c);
    border: 1px solid #fdba74;
    color: #fff;
    box-shadow: 0 8px 26px rgba(234, 88, 12, 0.42);
    cursor: pointer;
    transition: transform 0.18s ease, box-shadow 0.18s ease;
  }
  .btn-hero:hover {
    transform: translateY(-2px);
    box-shadow: 0 12px 32px rgba(234, 88, 12, 0.6);
  }
  .btn-hero-alt {
    padding: 12px 22px;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 1.3px;
    text-transform: uppercase;
    border-radius: 8px;
    background: rgba(16, 24, 44, 0.85);
    border: 1px solid var(--accent);
    color: #e0f2fe;
    backdrop-filter: blur(8px);
    cursor: pointer;
    transition: transform 0.18s ease, background 0.18s ease;
  }
  .btn-hero-alt:hover {
    transform: translateY(-2px);
    background: rgba(30, 58, 138, 0.65);
  }
  @keyframes riseFade {
    to { opacity: 1; transform: translateY(0) scale(1); }
  }

  /* ================= UNIFIED MISSION CONTROL SHELL ================= */
  header {
    background: rgba(12, 18, 34, 0.92);
    border-bottom: 1px solid var(--border);
    padding: 12px 22px;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    position: sticky;
    top: 0;
    z-index: 20;
    backdrop-filter: blur(10px);
  }
  .brand { display: flex; align-items: center; gap: 12px; }
  .badge-nasa {
    background: linear-gradient(135deg, #c2410c, #ea580c);
    border: 1px solid #fdba74;
    color: #fff;
    font-weight: 800;
    letter-spacing: 1.1px;
    padding: 6px 10px;
    border-radius: var(--radius-sm);
    font-size: 11px;
    text-transform: uppercase;
  }
  .title-block h1 { margin: 0; font-size: 16px; letter-spacing: 0.6px; }
  .title-block .sub { font-size: 12px; color: var(--accent); }
  .telemetry { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .stat-pill {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    padding: 6px 11px;
    font-size: 12px;
    color: var(--muted);
  }
  .stat-pill strong { color: #fff; font-size: 13px; }
  .header-actions { display: flex; gap: 8px; flex-wrap: wrap; }

  button {
    background: var(--panel-alt);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 7px 12px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: border-color 0.15s ease, background 0.15s ease, transform 0.1s ease;
  }
  button:hover:not(:disabled) { border-color: var(--accent); background: #1d2c4e; }
  button:active:not(:disabled) { transform: translateY(1px); }
  button:disabled { opacity: 0.42; cursor: not-allowed; }
  button.primary {
    background: linear-gradient(135deg, #0284c7, #2563eb);
    border-color: #38bdf8;
    color: #fff;
  }
  button.primary:hover:not(:disabled) { filter: brightness(1.1); }
  button.mars {
    background: linear-gradient(135deg, #c2410c, #ea580c);
    border-color: #fb923c;
    color: #fff;
  }
  button.warn { background: #78350f; border-color: var(--warn); color: #fef3c7; }
  button.danger { background: #7f1d1d; border-color: var(--danger); color: #fee2e2; }
  button.ok { background: #14532d; border-color: var(--ok); color: #dcfce7; }

  .toast {
    position: fixed;
    bottom: 20px;
    right: 20px;
    background: var(--panel);
    border: 1px solid var(--accent);
    padding: 11px 16px;
    border-radius: var(--radius-md);
    font-size: 13px;
    z-index: 60;
    max-width: 440px;
    box-shadow: 0 12px 30px rgba(0, 0, 0, 0.55);
    display: none;
  }
  .toast.err { border-color: var(--danger); color: #fecaca; }

  .crisis-banner {
    background: linear-gradient(90deg, rgba(127, 29, 29, 0.94), rgba(153, 27, 27, 0.88));
    border-bottom: 1px solid var(--danger);
    padding: 10px 22px;
    display: none;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
    font-size: 13px;
  }
  .crisis-banner.show { display: flex; }

  .layout {
    display: grid;
    grid-template-columns: 1fr 340px;
    gap: 16px;
    padding: 16px 22px;
    max-width: 1580px;
    margin: 0 auto;
  }
  @media (max-width: 1100px) {
    .layout { grid-template-columns: 1fr; }
  }

  .tabs {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    margin-bottom: 14px;
    border-bottom: 1px solid var(--border);
    padding-bottom: 10px;
  }
  .tab {
    padding: 8px 14px;
    border-radius: var(--radius-md);
    background: var(--panel);
    border: 1px solid var(--border);
    color: var(--muted);
  }
  .tab.active {
    background: #172554;
    border-color: var(--accent);
    color: #fff;
  }

  .section { display: none; }
  .section.active { display: block; }

  .grid-4 { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
  .grid-2 { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 12px; }

  .card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-top-color: var(--border-hi);
    border-radius: var(--radius-lg);
    padding: 14px;
  }
  .card h3 { margin: 0 0 8px 0; font-size: 14px; color: #f8fafc; }
  .res-head { display: flex; justify-content: space-between; align-items: center; font-size: 12px; margin-bottom: 5px; }
  .bar-bg {
    height: 7px;
    background: #070b14;
    border-radius: 99px;
    overflow: hidden;
    border: 1px solid #1e293b;
  }
  .bar-fill { height: 100%; background: var(--accent); transition: width 0.25s ease; }
  .bar-fill.low { background: var(--danger); }
  .bar-fill.mid { background: var(--warn); }
  .bar-fill.good { background: var(--ok); }
  .meta { font-size: 11.5px; color: var(--muted); margin-top: 6px; line-height: 1.45; }
  .net-pos { color: var(--ok); font-weight: 700; }
  .net-neg { color: #f87171; font-weight: 700; }

  .tag {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 99px;
    font-size: 10.5px;
    font-weight: 700;
    letter-spacing: 0.4px;
  }
  .tag.op { background: rgba(34, 197, 94, 0.16); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.4); }
  .tag.idle { background: rgba(245, 158, 11, 0.16); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.4); }
  .tag.off { background: rgba(239, 68, 68, 0.16); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.4); }

  .hint-box {
    background: rgba(56, 189, 248, 0.08);
    border: 1px solid rgba(56, 189, 248, 0.3);
    border-radius: var(--radius-md);
    padding: 8px 12px;
    font-size: 12px;
    color: #bae6fd;
    margin-top: 8px;
  }

  .row { display: flex; gap: 7px; flex-wrap: wrap; align-items: center; margin-top: 9px; }
  select, input[type="number"], input[type="text"] {
    background: #080d19;
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 6px 9px;
    font-size: 12px;
  }
  select:focus, input:focus { outline: none; border-color: var(--accent); }

  .log-panel {
    background: var(--panel);
    border: 1px solid var(--border);
    border-top-color: var(--border-hi);
    border-radius: var(--radius-lg);
    padding: 14px;
    height: calc(100vh - 102px);
    position: sticky;
    top: 76px;
    display: flex;
    flex-direction: column;
  }
  .log-list {
    flex: 1;
    overflow-y: auto;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 11.5px;
    line-height: 1.52;
    background: #060911;
    border: 1px solid #1e293b;
    border-radius: var(--radius-md);
    padding: 10px;
  }
  .log-item { padding: 4px 0; border-bottom: 1px dashed #141d30; }
  .log-item.crit { color: #fca5a5; font-weight: 600; }
  .log-item.sol { color: #38bdf8; font-weight: 600; }

  .modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(3, 7, 18, 0.85);
    display: none;
    align-items: center;
    justify-content: center;
    z-index: 120;
    padding: 16px;
    backdrop-filter: blur(6px);
  }
  .modal-backdrop.show { display: flex; }
  .modal {
    background: var(--panel);
    border: 1px solid var(--border-hi);
    border-radius: var(--radius-lg);
    padding: 22px;
    max-width: 640px;
    width: 100%;
    box-shadow: 0 24px 60px rgba(0, 0, 0, 0.75);
  }
  .modal h2 { margin-top: 0; font-size: 18px; }
  .env-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 12px 0; }
  .env-card {
    border: 1px solid var(--border);
    background: var(--panel-alt);
    border-radius: var(--radius-md);
    padding: 11px;
    cursor: pointer;
    transition: 0.15s ease;
  }
  .env-card:hover { border-color: var(--border-hi); }
  .env-card.selected { border-color: var(--mars-glow); background: rgba(234, 88, 12, 0.16); }
</style>
</head>
<body>

<!-- ==================== CINEMATIC INTRO SPLASH ==================== -->
<div class="intro-overlay" id="introOverlay">
  <canvas id="marsCanvas"></canvas>
  <div class="intro-vignette"></div>

  <div class="intro-top-bar">
    <span>TELEMETRY LINK // JEZERO CRATER SURFACE OPS</span>
    <button class="btn-hero-alt" style="padding:5px 12px;font-size:11px;" onclick="dismissIntro(false)">Skip Intro [ESC]</button>
  </div>

  <div class="intro-center">
    <div class="intro-kicker">NASA SPACE APPS CHALLENGE 2026</div>
    <div class="intro-team-row">
      <span>DAEDALUS TEAM</span>
      <span class="intro-dot"></span>
      <span>BOGOTA COLOMBIA</span>
    </div>
    <h1 class="intro-title">LIVING ON RED</h1>
    <p class="intro-sub">Autonomous Surface Habitat Architecture, Closed-Loop Life Support &amp; Multi-Sol Colony Command</p>
  </div>

  <div class="intro-cta-bar">
    <button class="btn-hero" onclick="dismissIntro(true)">Configure &amp; Launch Mission</button>
    <button class="btn-hero-alt" onclick="dismissIntro(false)">Enter Command Center (Mars)</button>
  </div>
</div>

<!-- ==================== MAIN COMMAND HEADER ==================== -->
<header>
  <div class="brand">
    <span class="badge-nasa">DAEDALUS // 2026</span>
    <div class="title-block">
      <h1>LIVING ON RED — MISSION CONTROL</h1>
      <div class="sub" id="envLabel">Loading telemetry...</div>
    </div>
  </div>
  <div class="telemetry">
    <div class="stat-pill">Sol <strong id="solVal">1/30</strong> (<span id="hrsVal">0h</span>)</div>
    <div class="stat-pill">Crew <strong id="crewVal">6/6</strong></div>
    <div class="stat-pill">Volume <strong id="volVal">1300 m³</strong></div>
    <div class="stat-pill">Science <strong id="sciVal">0 / 500</strong></div>
    <div class="stat-pill">Research <strong id="resPtsVal">0</strong></div>
    <div class="stat-pill">Sats <strong id="satVal">0</strong></div>
    <div class="stat-pill">Crisis Risk <strong id="riskVal">19%</strong></div>
  </div>
  <div class="header-actions">
    <button class="mars" onclick="act('advance_sol', [])">Advance 1 Sol</button>
    <button onclick="act('advance_sols', [5])">+5 Sols</button>
    <button onclick="openSetupModal()">New Mission</button>
    <button onclick="replayIntro()">Replay Intro</button>
    <button class="danger" onclick="act('abort_mission', [])">Abort</button>
  </div>
</header>

<div class="crisis-banner" id="crisisBanner">
  <div id="crisisText"></div>
  <button class="warn" onclick="act('resolve_crises', [])">Deploy Specialists &amp; Resolve Crises</button>
</div>

<div class="layout">
  <main>
    <div class="tabs">
      <button class="tab active" data-tab="overview" onclick="switchTab('overview', this)">1. Life Support &amp; Stockpile</button>
      <button class="tab" data-tab="buildings" onclick="switchTab('buildings', this)">2. Buildings &amp; Staffing</button>
      <button class="tab" data-tab="construct" onclick="switchTab('construct', this)">3. Construct Facilities</button>
      <button class="tab" data-tab="crew" onclick="switchTab('crew', this)">4. Crew Roster</button>
      <button class="tab" data-tab="industry" onclick="switchTab('industry', this)">5. Industry &amp; Expeditions</button>
    </div>

    <section id="tab-overview" class="section active">
      <div class="grid-4" id="vitalCards"></div>

      <div class="card" style="margin-top:14px;">
        <h3>Direct Life-Support &amp; Colony Operations</h3>
        <div id="readyWorkerHint"></div>
        <div class="row">
          <button onclick="act('balance_atmosphere', [])">Balance Atmosphere (10 Water, 20 Power)</button>
          <button onclick="act('feed_crew', [])">Emergency Extra Ration</button>
          <button onclick="act('maintain_buildings', [])">Maintain All Buildings (+4% Safety)</button>
          <button onclick="act('transfer_logistics', [])">Run Logistics Transfer</button>
        </div>
        <div class="row" style="margin-top:10px;">
          <select id="lsWorker"></select>
          <button onclick="actWorker('run_moxie', 'lsWorker')">Run MOXIE (+O2)</button>
          <select id="cropSelect">
            <option value="lettuce">Lettuce</option>
            <option value="wheat">Wheat</option>
            <option value="flax">Flax</option>
            <option value="sunflower">Sunflower</option>
          </select>
          <button onclick="actWorkerCrop('hydroponics')">Grow Hydroponics</button>
          <button onclick="actWorkerCrop('food_refinery')">Refine Harvest</button>
        </div>
      </div>

      <div class="card" style="margin-top:14px;">
        <h3>Last Sol Balance &amp; Full Colony Stockpile</h3>
        <div id="dailySummaryStrip" class="meta" style="margin-bottom:10px;"></div>
        <div class="grid-4" id="allResourceCards"></div>
      </div>
    </section>

    <section id="tab-buildings" class="section">
      <div class="row" style="margin-bottom:12px;">
        <button onclick="act('maintain_buildings', [])">Maintain All Buildings</button>
        <button onclick="act('transfer_logistics', [])">Transfer Local Storage via Logistics</button>
      </div>
      <div class="grid-2" id="buildingCards"></div>
    </section>

    <section id="tab-construct" class="section">
      <div class="row" style="margin-bottom:12px;">
        <input type="text" id="catalogFilter" placeholder="Filter buildings (e.g. food, power, lab, farm, rover)..." oninput="renderCatalog()" style="min-width:300px;" />
      </div>
      <div class="grid-2" id="catalogCards"></div>
    </section>

    <section id="tab-crew" class="section">
      <div class="grid-2" id="crewCards"></div>
    </section>

    <section id="tab-industry" class="section">
      <div id="industryWorkerHint" style="margin-bottom:12px;"></div>
      <div class="grid-2">
        <div class="card">
          <h3>Surface Mining &amp; Fuel Synthesis</h3>
          <p class="meta">Geologists get 1.5x bonus on mining (plus 1.5x with a Rover). Engineers get 1.5x bonus on fuel &amp; refining.</p>
          <div class="row">
            <select id="indWorker"></select>
            <button onclick="actWorker('mine', 'indWorker')">Mine Regolith &amp; Ice (15 Power, 10 Fuel)</button>
            <button onclick="actWorker('produce_fuel', 'indWorker')">Synthesize Fuel (6 CO2, 8 H2, 20 Power)</button>
          </div>
          <div class="row">
            <select id="matSelect">
              <option value="steel">Steel (20 Dirt, 20 Power)</option>
              <option value="aluminum">Aluminum (20 Dirt, 20 Power)</option>
              <option value="glass">Glass (15 Dirt, 15 Power)</option>
              <option value="plastic">Plastic (5 CO2, 5 H2, 15 Power)</option>
            </select>
            <button onclick="actWorkerSelect('refine_materials', 'indWorker', 'matSelect')">Refine Material</button>
          </div>
        </div>

        <div class="card">
          <h3>Vehicle &amp; Spacecraft Manufacturing</h3>
          <p class="meta">Requires ready worker + refined Aluminum, Steel, Plastic, Glass, and Electricity.</p>
          <div class="row">
            <select id="mfgWorker"></select>
            <select id="itemSelect">
              <option value="drones">Drone (15 Al, 10 Plastic, 5 Glass, 20 Power)</option>
              <option value="rovers">Rover (40 Al, 30 Steel, 15 Plastic, 10 Glass, 40 Power)</option>
              <option value="satellites">Satellite (25 Al, 15 Plastic, 20 Glass, 45 Power)</option>
              <option value="rockets">Rocket (120 Al, 100 Steel, 40 Plastic, 25 Glass, 100 Power)</option>
              <option value="cars">Car (35 Al, 35 Steel, 20 Plastic, 15 Glass, 35 Power)</option>
              <option value="trucks">Truck (50 Al, 60 Steel, 20 Plastic, 15 Glass, 50 Power)</option>
            </select>
            <button class="primary" onclick="actWorkerSelect('manufacture', 'mfgWorker', 'itemSelect')">Manufacture</button>
          </div>
        </div>

        <div class="card">
          <h3>Science Expeditions &amp; Orbital Launches</h3>
          <p class="meta">Deploy Rovers (Geologist bonus) or Drones, Satellites, and Rockets (Pilot bonus) to earn Science Points.</p>
          <div class="row">
            <select id="expWorker"></select>
            <button onclick="actWorker('deploy_rover', 'expWorker')">Deploy Rover (+Science, Dirt)</button>
            <button onclick="actWorker('fly_drone', 'expWorker')">Fly Drone (+Science, Seeds)</button>
          </div>
          <div class="row">
            <button class="primary" onclick="actWorker('launch_satellite', 'expWorker')">Launch Satellite (1 Sat + 1 Rocket)</button>
            <button class="ok" onclick="actWorker('launch_rocket', 'expWorker')">Launch Resupply Rocket (1 Rocket)</button>
          </div>
        </div>
      </div>
    </section>
  </main>

  <aside class="log-panel">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
      <strong style="font-size:13px;">MISSION TELEMETRY LOG</strong>
      <span class="meta" style="margin:0;">Bogota // Jezero Link</span>
    </div>
    <div class="log-list" id="logList"></div>
  </aside>
</div>

<div class="toast" id="toast"></div>

<div class="modal-backdrop" id="setupModal">
  <div class="modal">
    <h2>Configure Space Mission — Daedalus Team</h2>
    <p class="meta">Select destination environment, crew complement, and mission victory targets.</p>
    <div class="env-grid" id="envGrid"></div>
    <div class="row" style="margin-top:12px;">
      <label class="meta">Crew (2–10): <input type="number" id="cfgCrew" min="2" max="10" value="6" style="width:65px;"></label>
      <label class="meta">Target Sols: <input type="number" id="cfgSols" min="5" max="365" value="30" style="width:75px;"></label>
      <label class="meta">Target Science: <input type="number" id="cfgSci" min="50" max="10000" step="50" value="500" style="width:85px;"></label>
    </div>
    <div class="row" style="margin-top:16px;justify-content:flex-end;">
      <button onclick="closeSetupModal()">Cancel</button>
      <button class="mars" onclick="startNewMission()">Launch Mission</button>
    </div>
  </div>
</div>

<div class="modal-backdrop" id="endModal">
  <div class="modal">
    <h2 id="endTitle">POST-MISSION ANALYSIS</h2>
    <p id="endReason" style="font-size:14px;"></p>
    <div class="card" id="endStats" style="margin:12px 0;"></div>
    <div class="row" style="justify-content:flex-end;">
      <button class="mars" onclick="closeEndModal(); openSetupModal();">Configure New Mission</button>
    </div>
  </div>
</div>

<script>
/* ==================== MARTIAN ROVER OPENING ANIMATION ==================== */
(function initMarsAnimation() {
  const canvas = document.getElementById('marsCanvas');
  const ctx = canvas.getContext('2d');
  let W = 0, H = 0, animId = null, running = true;

  const stars = Array.from({ length: 150 }, () => ({
    x: Math.random(),
    y: Math.random() * 0.62,
    r: Math.random() * 1.6 + 0.3,
    phase: Math.random() * Math.PI * 2,
    speed: Math.random() * 1.8 + 0.5
  }));

  const dust = Array.from({ length: 65 }, () => ({
    x: Math.random(),
    y: 0.45 + Math.random() * 0.52,
    vx: 0.015 + Math.random() * 0.035,
    r: Math.random() * 2.2 + 0.6,
    alpha: Math.random() * 0.35 + 0.08
  }));

  const wheelDust = [];

  function resize() {
    W = canvas.width = window.innerWidth;
    H = canvas.height = window.innerHeight;
  }
  window.addEventListener('resize', resize);
  resize();

  function terrainY(x, baseRatio, amp1, amp2, scroll) {
    const nx = (x + scroll) * 0.0022;
    return H * baseRatio
      + Math.sin(nx) * amp1
      + Math.sin(nx * 2.7 + 1.3) * amp2
      + Math.cos(nx * 0.6 - 0.8) * (amp1 * 0.6);
  }

  function drawRover(x, scale, wheelAngle, t, isLead) {
    const scroll = t * (isLead ? 38 : 26);
    const yL = terrainY(x - 36 * scale, 0.81, 22, 9, scroll);
    const yR = terrainY(x + 36 * scale, 0.81, 22, 9, scroll);
    const yCenter = (yL + yR) * 0.5 - 18 * scale;
    const slope = Math.atan2(yR - yL, 72 * scale);

    ctx.save();
    ctx.translate(x, yCenter);
    ctx.rotate(slope);
    ctx.scale(scale, scale);

    // Soft ground shadow
    ctx.fillStyle = 'rgba(10, 4, 2, 0.55)';
    ctx.beginPath();
    ctx.ellipse(0, 22, 54, 7, 0, 0, Math.PI * 2);
    ctx.fill();

    // Rocker-bogie suspension struts
    ctx.strokeStyle = '#94a3b8';
    ctx.lineWidth = 3.2;
    ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.moveTo(-34, 15);
    ctx.lineTo(-14, -2);
    ctx.lineTo(14, -2);
    ctx.lineTo(34, 15);
    ctx.moveTo(0, 15);
    ctx.lineTo(0, -2);
    ctx.stroke();

    // Rear RTG nuclear power fin
    ctx.save();
    ctx.translate(-34, -10);
    ctx.rotate(-0.35);
    ctx.fillStyle = '#334155';
    ctx.fillRect(-14, -6, 18, 12);
    ctx.fillStyle = '#fb923c';
    ctx.fillRect(-12, -2, 12, 4);
    ctx.restore();

    // Main rover chassis
    ctx.fillStyle = '#e2e8f0';
    ctx.strokeStyle = '#475569';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.roundRect(-28, -15, 56, 15, 4);
    ctx.fill();
    ctx.stroke();

    // Copper accent stripe
    ctx.fillStyle = '#ea580c';
    ctx.fillRect(-24, -10, 48, 4);

    // High-gain parabolic dish
    ctx.save();
    ctx.translate(-14, -16);
    ctx.rotate(Math.sin(t * 1.1) * 0.25 - 0.3);
    ctx.strokeStyle = '#cbd5e1';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(0, -6, 9, 0.2 * Math.PI, 0.8 * Math.PI);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.lineTo(0, -7);
    ctx.stroke();
    ctx.restore();

    // Remote Sensing Mast
    ctx.fillStyle = '#cbd5e1';
    ctx.fillRect(14, -36, 4.5, 21);
    ctx.fillStyle = '#f8fafc';
    ctx.strokeStyle = '#334155';
    ctx.beginPath();
    ctx.roundRect(9, -44, 16, 10, 3);
    ctx.fill();
    ctx.stroke();

    // Glowing cyan optical lens + LiDAR scan beam
    ctx.fillStyle = '#38bdf8';
    ctx.beginPath();
    ctx.arc(21, -39, 2.5, 0, Math.PI * 2);
    ctx.fill();

    if (isLead) {
      const scanPulse = 0.5 + 0.5 * Math.sin(t * 2.4);
      const grad = ctx.createLinearGradient(22, -39, 135, 22);
      grad.addColorStop(0, `rgba(56, 189, 248, ${0.32 * scanPulse})`);
      grad.addColorStop(1, 'rgba(56, 189, 248, 0)');
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.moveTo(22, -39);
      ctx.lineTo(145, 20);
      ctx.lineTo(105, 24);
      ctx.closePath();
      ctx.fill();
    }

    // 3 cleated wheels with rotating spokes
    [-34, 0, 34].forEach(wx => {
      ctx.save();
      ctx.translate(wx, 15);
      ctx.rotate(wheelAngle);
      ctx.fillStyle = '#1e293b';
      ctx.strokeStyle = '#94a3b8';
      ctx.lineWidth = 2.2;
      ctx.beginPath();
      ctx.arc(0, 0, 10.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();

      ctx.strokeStyle = '#fb923c';
      ctx.lineWidth = 1.6;
      for (let s = 0; s < 3; s++) {
        const a = (s * Math.PI) / 3;
        ctx.beginPath();
        ctx.moveTo(Math.cos(a) * -9, Math.sin(a) * -9);
        ctx.lineTo(Math.cos(a) * 9, Math.sin(a) * 9);
        ctx.stroke();
      }
      ctx.fillStyle = '#e2e8f0';
      ctx.beginPath();
      ctx.arc(0, 0, 3, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    });

    ctx.restore();

    if (Math.random() < 0.45) {
      wheelDust.push({
        x: x - 36 * scale,
        y: yL + 6 * scale,
        vx: -25 - Math.random() * 35,
        vy: -8 - Math.random() * 14,
        r: (2 + Math.random() * 4) * scale,
        life: 1.0
      });
    }
  }

  function drawDrone(x, y, t) {
    ctx.save();
    ctx.translate(x, y + Math.sin(t * 3.2) * 7);

    const bladeW = 28 * Math.abs(Math.cos(t * 28));
    ctx.strokeStyle = 'rgba(226, 232, 240, 0.65)';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(-bladeW, -12);
    ctx.lineTo(bladeW, -12);
    ctx.moveTo(-bladeW * 0.85, -8);
    ctx.lineTo(bladeW * 0.85, -8);
    ctx.stroke();

    ctx.fillStyle = '#38bdf8';
    ctx.fillRect(-10, -15, 20, 2.5);
    ctx.fillStyle = '#cbd5e1';
    ctx.fillRect(-1.5, -14, 3, 14);

    ctx.fillStyle = '#f8fafc';
    ctx.fillRect(-6, -2, 12, 9);
    ctx.strokeStyle = '#94a3b8';
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.moveTo(-5, 7); ctx.lineTo(-11, 15);
    ctx.moveTo(5, 7); ctx.lineTo(11, 15);
    ctx.stroke();

    if (Math.sin(t * 8) > 0) {
      ctx.fillStyle = '#fb923c';
      ctx.beginPath();
      ctx.arc(0, 2, 2.2, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  }

  let lastTime = performance.now();
  function frame(now) {
    if (!running) return;
    const dt = Math.min(0.05, (now - lastTime) / 1000);
    lastTime = now;
    const t = now * 0.001;

    const sky = ctx.createLinearGradient(0, 0, 0, H * 0.84);
    sky.addColorStop(0, '#040711');
    sky.addColorStop(0.42, '#0d1428');
    sky.addColorStop(0.74, '#3b1814');
    sky.addColorStop(1, '#9a3412');
    ctx.fillStyle = sky;
    ctx.fillRect(0, 0, W, H);

    stars.forEach(s => {
      const alpha = 0.25 + 0.75 * (0.5 + 0.5 * Math.sin(t * s.speed + s.phase));
      ctx.fillStyle = `rgba(226, 232, 240, ${alpha})`;
      ctx.beginPath();
      ctx.arc(s.x * W, s.y * H, s.r, 0, Math.PI * 2);
      ctx.fill();
    });

    const sunX = W * 0.76, sunY = H * 0.56;
    const halo = ctx.createRadialGradient(sunX, sunY, 6, sunX, sunY, 170);
    halo.addColorStop(0, 'rgba(254, 243, 199, 0.85)');
    halo.addColorStop(0.25, 'rgba(251, 146, 60, 0.35)');
    halo.addColorStop(1, 'rgba(234, 88, 12, 0)');
    ctx.fillStyle = halo;
    ctx.beginPath();
    ctx.arc(sunX, sunY, 170, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = '#29110e';
    ctx.beginPath();
    ctx.moveTo(0, H);
    for (let x = 0; x <= W + 20; x += 20) {
      ctx.lineTo(x, terrainY(x, 0.64, 34, 14, t * 8));
    }
    ctx.lineTo(W, H);
    ctx.closePath();
    ctx.fill();

    ctx.fillStyle = '#431912';
    ctx.beginPath();
    ctx.moveTo(0, H);
    for (let x = 0; x <= W + 16; x += 16) {
      ctx.lineTo(x, terrainY(x, 0.73, 26, 11, t * 18));
    }
    ctx.lineTo(W, H);
    ctx.closePath();
    ctx.fill();

    const droneX = ((t * 58 + W * 0.62) % (W + 240)) - 120;
    drawDrone(droneX, H * 0.63, t);

    const fgGrad = ctx.createLinearGradient(0, H * 0.76, 0, H);
    fgGrad.addColorStop(0, '#7c2d12');
    fgGrad.addColorStop(0.35, '#5a1e0c');
    fgGrad.addColorStop(1, '#1c0a06');
    ctx.fillStyle = fgGrad;
    ctx.beginPath();
    ctx.moveTo(0, H);
    for (let x = 0; x <= W + 10; x += 10) {
      ctx.lineTo(x, terrainY(x, 0.81, 22, 9, t * 38));
    }
    ctx.lineTo(W, H);
    ctx.closePath();
    ctx.fill();

    const leadX = ((t * 46 + W * 0.45) % (W + 320)) - 160;
    const trailX = ((t * 34 + W * 0.16) % (W + 320)) - 160;
    drawRover(trailX, 0.72, t * 3.1, t, false);
    drawRover(leadX, 1.05, t * 4.2, t, true);

    for (let i = wheelDust.length - 1; i >= 0; i--) {
      const p = wheelDust[i];
      p.x += p.vx * dt;
      p.y += p.vy * dt;
      p.r += 8 * dt;
      p.life -= 0.9 * dt;
      if (p.life <= 0) {
        wheelDust.splice(i, 1);
        continue;
      }
      ctx.fillStyle = `rgba(251, 146, 60, ${p.life * 0.25})`;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fill();
    }

    dust.forEach(d => {
      d.x = (d.x + d.vx * dt) % 1;
      ctx.fillStyle = `rgba(253, 186, 116, ${d.alpha})`;
      ctx.beginPath();
      ctx.arc(d.x * W, d.y * H, d.r, 0, Math.PI * 2);
      ctx.fill();
    });

    animId = requestAnimationFrame(frame);
  }

  animId = requestAnimationFrame(frame);

  window.dismissIntro = function(openConfig) {
    const el = document.getElementById('introOverlay');
    el.classList.add('hidden');
    running = false;
    if (animId) cancelAnimationFrame(animId);
    if (openConfig) openSetupModal();
  };

  window.replayIntro = function() {
    const el = document.getElementById('introOverlay');
    el.classList.remove('hidden');
    if (!running) {
      running = true;
      lastTime = performance.now();
      animId = requestAnimationFrame(frame);
    }
  };

  window.addEventListener('keydown', e => {
    if (e.key === 'Escape' && !document.getElementById('introOverlay').classList.contains('hidden')) {
      window.dismissIntro(false);
    }
  });
})();

/* ==================== MISSION CONTROL STATE & RENDERING ==================== */
let STATE = null;
let selectedEnv = 'mars';
let endShownForSol = null;

function showToast(msg, isErr=false) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = isErr ? 'toast err' : 'toast';
  el.style.display = 'block';
  clearTimeout(window._toastTimer);
  window._toastTimer = setTimeout(() => { el.style.display = 'none'; }, 4000);
}

async function fetchState() {
  const res = await fetch('/api/state');
  STATE = await res.json();
  renderAll();
}

async function act(action, args=[]) {
  const res = await fetch('/api/action', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, args })
  });
  const data = await res.json();
  STATE = data.state;
  showToast(data.message, !data.ok);
  renderAll();
}

function actWorker(action, selectId) {
  const idx = parseInt(document.getElementById(selectId).value, 10);
  if (isNaN(idx)) return showToast('No ready worker available. Unstaff a worker in Buildings first.', true);
  act(action, [idx]);
}

function actWorkerCrop(action) {
  const idx = parseInt(document.getElementById('lsWorker').value, 10);
  const crop = document.getElementById('cropSelect').value;
  if (isNaN(idx)) return showToast('No ready worker available. Unstaff a worker in Buildings first.', true);
  act(action, [idx, crop]);
}

function actWorkerSelect(action, workerSelId, valSelId) {
  const idx = parseInt(document.getElementById(workerSelId).value, 10);
  const val = document.getElementById(valSelId).value;
  if (isNaN(idx)) return showToast('No ready worker available. Unstaff a worker in Buildings first.', true);
  act(action, [idx, val]);
}

function switchTab(name, btn) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('tab-' + name).classList.add('active');
}

function openSetupModal() {
  selectedEnv = STATE ? STATE.space_key : 'mars';
  renderEnvChoices();
  document.getElementById('setupModal').classList.add('show');
}
function closeSetupModal() { document.getElementById('setupModal').classList.remove('show'); }
function closeEndModal() { document.getElementById('endModal').classList.remove('show'); }

function renderEnvChoices() {
  const grid = document.getElementById('envGrid');
  if (!STATE) return;
  grid.innerHTML = Object.entries(STATE.environments).map(([k, info]) => `
    <div class="env-card ${selectedEnv === k ? 'selected' : ''}" onclick="selectedEnv='${k}'; renderEnvChoices();">
      <strong>${info.label}</strong>
      <div class="meta">Solar x${info.solar_multiplier} | Power/100m³: -${info.power_per_100m3} | O2 Leak: -${info.o2_leak_per_100m3} | Hazard: ${Math.round(info.hazard_chance*100)}%</div>
    </div>
  `).join('');
}

async function startNewMission() {
  const crew = parseInt(document.getElementById('cfgCrew').value, 10) || 6;
  const target_sols = parseInt(document.getElementById('cfgSols').value, 10) || 30;
  const target_sci = parseFloat(document.getElementById('cfgSci').value) || 500;
  const res = await fetch('/api/new_game', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ space_key: selectedEnv, crew_count: crew, target_sols, target_sci })
  });
  STATE = await res.json();
  endShownForSol = null;
  closeSetupModal();
  showToast(`Mission launched: ${STATE.space_label}`);
  renderAll();
}

function formatCosts(costsObj) {
  const entries = Object.entries(costsObj || {});
  if (!entries.length) return 'none';
  return entries.map(([k, v]) => `${v} ${k}`).join(', ');
}

function renderAll() {
  if (!STATE) return;
  document.getElementById('envLabel').textContent = `${STATE.space_label} // Daedalus Team (Bogota, Colombia)`;
  document.getElementById('solVal').textContent = `${STATE.sol}/${STATE.target_sols}`;
  document.getElementById('hrsVal').textContent = `${STATE.elapsed_hours}h`;
  document.getElementById('crewVal').textContent = `${STATE.active_crew_count}/${STATE.total_crew_count}`;
  document.getElementById('volVal').textContent = `${STATE.active_volume} m³`;
  document.getElementById('sciVal').textContent = `${STATE.science_points} / ${STATE.target_sci}`;
  document.getElementById('resPtsVal').textContent = STATE.resources.research ? STATE.resources.research.current : 0;
  document.getElementById('satVal').textContent = STATE.active_satellites;
  document.getElementById('riskVal').textContent = `${STATE.crisis_risk_pct}%`;

  const banner = document.getElementById('crisisBanner');
  if (STATE.crises.length > 0) {
    banner.classList.add('show');
    document.getElementById('crisisText').innerHTML = STATE.crises.map(c =>
      `<div><strong>[CRISIS SEV ${c.severity}] ${c.name}:</strong> ${c.description}</div>`
    ).join('');
  } else {
    banner.classList.remove('show');
  }

  const vitals = [
    ['food', 'Food (kcal)'], ['water', 'Water (L)'], ['oxigen', 'Oxygen (kg)'],
    ['electricity', 'Electricity (kWh)'], ['fuel', 'Fuel (L)'], ['CO2', 'CO2 (kg)'],
    ['Nitrogen', 'Nitrogen (kg)'], ['Hydrogen', 'Hydrogen (kg)']
  ];
  document.getElementById('vitalCards').innerHTML = vitals.map(([k, label]) => {
    const r = STATE.resources[k] || { current: 0, max: 0, pct: 0, net: 0 };
    const cls = r.pct < 20 ? 'low' : (r.pct < 45 ? 'mid' : 'good');
    const netHtml = r.net !== 0
      ? `<span class="${r.net > 0 ? 'net-pos' : 'net-neg'}">${r.net > 0 ? '+' : ''}${r.net}/sol</span>`
      : `<span class="meta" style="margin:0;">0/sol</span>`;
    return `
      <div class="card">
        <div class="res-head"><span>${label}</span>${netHtml}</div>
        <div style="font-size:17px;font-weight:700;margin-bottom:6px;">${r.current} <span class="meta">/ ${r.max}</span></div>
        <div class="bar-bg"><div class="bar-fill ${cls}" style="width:${Math.min(100, r.pct)}%"></div></div>
      </div>`;
  }).join('');

  const deltas = Object.entries(STATE.resources)
    .filter(([, r]) => r.net !== 0)
    .map(([k, r]) => `<span class="${r.net > 0 ? 'net-pos' : 'net-neg'}">${k}: ${r.net > 0 ? '+' : ''}${r.net}</span>`);
  document.getElementById('dailySummaryStrip').innerHTML = deltas.length
    ? `<strong>Last Sol Net Balance:</strong> ` + deltas.join(' &nbsp;|&nbsp; ')
    : `<strong>Last Sol Net Balance:</strong> Advance 1 Sol to view daily production vs. life-support consumption.`;

  document.getElementById('allResourceCards').innerHTML = Object.entries(STATE.resources)
    .filter(([, r]) => r.max > 0 || r.current > 0)
    .map(([k, r]) => {
      const badge = r.net !== 0
        ? ` <span class="${r.net > 0 ? 'net-pos' : 'net-neg'}">(${r.net > 0 ? '+' : ''}${r.net})</span>`
        : '';
      return `
        <div class="card" style="padding:10px;">
          <div class="res-head"><strong>${k}${badge}</strong><span>${r.current} / ${r.max}</span></div>
        </div>`;
    }).join('');

  const readyWorkers = STATE.workers.filter(w => w.available);
  const hintHtml = readyWorkers.length === 0
    ? `<div class="hint-box">All ${STATE.active_crew_count} active crew members are currently staffed inside buildings. To run manual shifts, mining, or expeditions, unstaff a worker in <strong>2. Buildings &amp; Staffing</strong>.</div>`
    : '';
  document.getElementById('readyWorkerHint').innerHTML = hintHtml;
  document.getElementById('industryWorkerHint').innerHTML = hintHtml;

  const workerOpts = readyWorkers.length
    ? readyWorkers.map(w => `<option value="${w.index}">[${w.index}] ${w.name} (${w.profession}, HP ${w.health})</option>`).join('')
    : '<option value="">No ready workers (unstaff in Buildings)</option>';
  ['lsWorker', 'indWorker', 'mfgWorker', 'expWorker'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = workerOpts;
  });

  document.getElementById('buildingCards').innerHTML = STATE.buildings.map(b => {
    const tagCls = !b.is_on ? 'off' : (b.is_operational ? 'op' : 'idle');
    const tagTxt = !b.is_on ? 'OFF' : (b.is_operational ? 'OPERATIONAL' : 'IDLE (NEEDS STAFF)');
    const reqTxt = Object.entries(b.required_professions).map(([p, [lo, hi]]) => `${p} ${lo}-${hi}`).join(', ') || 'None';
    const localTxt = Object.entries(b.local_storage).map(([k, v]) => `${k}: ${v.current}/${v.max}`).join(' | ');
    const allowedProfs = Object.keys(b.required_professions);
    const eligible = readyWorkers.filter(w => allowedProfs.includes(w.profession));
    const staffSelect = eligible.length
      ? `<select id="staffSel_${b.index}">${eligible.map(w => `<option value="${w.index}">[${w.index}] ${w.name} (${w.profession})</option>`).join('')}</select>
         <button class="ok" onclick="staffBld(${b.index})">Assign Staff</button>`
      : `<span class="meta">No ready ${allowedProfs.join('/')} available</span>`;

    const assignedBadges = b.assigned_workers.map(w =>
      `<button onclick="act('unstaff_building', [${b.index}, ${w.index}])" title="Click to unstaff">[${w.index}] ${w.name} (${w.profession}) &times;</button>`
    ).join(' ');

    const extraRows = [];
    if (b.kind === 'Producer' || b.kind === 'Farm') {
      const shiftSel = readyWorkers.length
        ? `<select id="shiftSel_${b.index}">${readyWorkers.map(w => `<option value="${w.index}">[${w.index}] ${w.name}</option>`).join('')}</select>
           <button onclick="manualShift(${b.index})">Manual Shift (15 Power)</button>`
        : '';
      if (shiftSel) extraRows.push(`<div class="row">${shiftSel}</div>`);
    }
    if (b.kind === 'Farm') {
      const crops = ['lettuce', 'wheat', 'flax', 'sunflower'];
      extraRows.push(`
        <div class="row">
          <select id="farmCrop_${b.index}">
            ${crops.map(c => `<option value="${c}" ${b.farm_crop === c ? 'selected' : ''}>${c}</option>`).join('')}
          </select>
          <select id="farmType_${b.index}">
            <option value="crop" ${b.farm_product === 'crop' ? 'selected' : ''}>Harvest Crop</option>
            <option value="seed" ${b.farm_product === 'seed' ? 'selected' : ''}>Produce Seeds</option>
          </select>
          <button class="primary" onclick="configFarm(${b.index})">Set Farm Output</button>
        </div>`);
    }
    if (b.kind === 'Research') {
      extraRows.push(`
        <div class="row">
          <select id="resPts_${b.index}">
            <option value="1">1 Research Pt (+15 Sci)</option>
            <option value="3">3 Research Pts (+45 Sci)</option>
            <option value="5">5 Research Pts (+75 Sci)</option>
          </select>
          <button class="primary" onclick="runResearch(${b.index})">Synthesize Research</button>
        </div>`);
    }

    return `
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <h3>[${b.index}] ${b.name}</h3>
          <span class="tag ${tagCls}">${tagTxt}</span>
        </div>
        <div class="meta">Type: ${b.type} | Vol: ${b.volume} m³ | Safety: ${b.safety}% | Staff: ${b.workers_count}/${b.max_workers} (${reqTxt})</div>
        <div class="meta">Upkeep/Sol: ${formatCosts(b.operating_costs)} (Standby: ${formatCosts(b.standby_costs)})</div>
        ${localTxt ? `<div class="meta" style="color:#38bdf8;">Local Storage: ${localTxt}</div>` : ''}
        <div class="row">${assignedBadges || '<span class="meta">No workers assigned</span>'}</div>
        <div class="row">${staffSelect}</div>
        <div class="row">
          <button onclick="act('toggle_building', [${b.index}])">${b.is_on ? 'Turn Off' : 'Turn On'}</button>
        </div>
        ${extraRows.join('')}
      </div>`;
  }).join('');

  renderCatalog();

  const uniBld = STATE.buildings.find(b => b.kind === 'University' && b.is_operational);
  const trainableProfs = ['Doctor', 'Engineer', 'Biologist', 'Geologist', 'Pilot'];

  document.getElementById('crewCards').innerHTML = STATE.workers.map(w => {
    const profOptions = STATE.professions.map(p =>
      `<option value="${p.code}" ${p.name === w.profession ? 'selected' : ''}>${p.name}</option>`
    ).join('');
    const uniControls = (uniBld && w.available)
      ? `<div class="row">
           <select id="uniProf_${w.index}">${trainableProfs.map(p => `<option value="${p}">${p}</option>`).join('')}</select>
           <button class="primary" onclick="uniTrain(${uniBld.index}, ${w.index})">University Train (5 Res, 20 Power, 5 Food)</button>
         </div>`
      : '';
    return `
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <h3>[${w.index}] ${w.name}</h3>
          <span class="tag ${w.available ? 'op' : 'idle'}">${w.status}</span>
        </div>
        <div class="meta">HP: ${w.health}% | Role Skill: ${w.role_skill} | Debuff: ${w.role_debuff} | Best Aptitude: <strong>${w.best_role}</strong> (${w.best_score}) | Age: ${Math.floor(w.age_days / 365)}y</div>
        <div class="row">
          <select onchange="act('assign_job', [${w.index}, parseInt(this.value, 10)])" ${w.retired || w.health <= 0 ? 'disabled' : ''}>${profOptions}</select>
          <button onclick="act('work', [${w.index}])" ${!w.available ? 'disabled' : ''}>Shift (+Power)</button>
          <button onclick="act('rest', [${w.index}])" ${w.assigned_building || w.retired || w.health <= 0 ? 'disabled' : ''}>Rest</button>
          <button onclick="act('hospital', [${w.index}])" ${!w.available ? 'disabled' : ''}>Hospital</button>
          <button onclick="act('study', [${w.index}])" ${!w.available ? 'disabled' : ''}>Study</button>
          <button class="danger" onclick="act('retire', [${w.index}])" ${w.retired || w.health <= 0 ? 'disabled' : ''}>Retire</button>
        </div>
        ${uniControls}
      </div>`;
  }).join('');

  const logEl = document.getElementById('logList');
  logEl.innerHTML = STATE.log.slice().reverse().map(line => {
    const cls = line.includes('CRISIS') || line.includes('INCIDENT') || line.includes('shortage')
      ? 'log-item crit'
      : (line.includes('Sol ') ? 'log-item sol' : 'log-item');
    return `<div class="${cls}">${line}</div>`;
  }).join('');

  if (STATE.mission_over && endShownForSol !== STATE.sol) {
    endShownForSol = STATE.sol;
    document.getElementById('endTitle').textContent = `MISSION ${STATE.mission_status}`;
    document.getElementById('endReason').textContent = STATE.mission_reason;
    document.getElementById('endStats').innerHTML = `
      <div><strong>Duration:</strong> ${STATE.sol} / ${STATE.target_sols} Sols (${STATE.elapsed_hours}h)</div>
      <div><strong>Science Achieved:</strong> ${STATE.science_points} / ${STATE.target_sci}</div>
      <div><strong>Crew Survival:</strong> ${STATE.active_crew_count} / ${STATE.total_crew_count}</div>
      <div><strong>Average Colony Safety:</strong> ${STATE.avg_safety}%</div>
    `;
    document.getElementById('endModal').classList.add('show');
  }
}

function staffBld(bIdx) {
  const sel = document.getElementById('staffSel_' + bIdx);
  if (!sel) return;
  act('staff_building', [bIdx, parseInt(sel.value, 10)]);
}

function manualShift(bIdx) {
  const sel = document.getElementById('shiftSel_' + bIdx);
  if (!sel) return showToast('No ready worker available for manual shift.', true);
  act('operate_factory', [bIdx, [parseInt(sel.value, 10)]]);
}

function configFarm(bIdx) {
  const crop = document.getElementById('farmCrop_' + bIdx).value;
  const ptype = document.getElementById('farmType_' + bIdx).value;
  act('configure_farm', [bIdx, crop, ptype]);
}

function runResearch(bIdx) {
  const pts = parseInt(document.getElementById('resPts_' + bIdx).value, 10) || 1;
  act('run_research', [bIdx, pts]);
}

function uniTrain(uniIdx, wIdx) {
  const prof = document.getElementById('uniProf_' + wIdx).value;
  act('university_train', [uniIdx, wIdx, prof]);
}

function renderCatalog() {
  if (!STATE) return;
  const q = (document.getElementById('catalogFilter').value || '').toLowerCase();
  const items = STATE.catalog.filter(c =>
    c.key.includes(q) || c.name.toLowerCase().includes(q) || c.type.toLowerCase().includes(q)
  );
  document.getElementById('catalogCards').innerHTML = items.map(c => {
    const reqs = Object.entries(c.required_professions).map(([p, [lo, hi]]) => `${p} ${lo}-${hi}`).join(', ') || 'None';
    return `
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <h3>${c.name} <span class="meta">(${c.key})</span></h3>
          <button class="primary" onclick="act('construct_building', ['${c.key}'])">Build</button>
        </div>
        <div class="meta">Build Cost: ${c.power_cost} Power, ${c.steel_cost} Steel, ${c.aluminum_cost} Al | Vol: ${c.volume} m³</div>
        <div class="meta">Staffing (${c.max_workers} max): ${reqs} | Upkeep: ${formatCosts(c.operating_costs)}</div>
      </div>`;
  }).join('');
}

fetchState();
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
                )
                self._send_json(state)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Living on Red — Colony Command Web UI")
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
