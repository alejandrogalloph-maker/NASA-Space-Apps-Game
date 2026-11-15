"""Interactive terminal shell for the colony game.

Run:  python cli.py                      (prompts for mission setup)
      python cli.py --env mars --crew 6 --sols 30 --science 500
      python cli.py --env moon --script commands.txt    (run commands from a file)

Type `help` for the command list, `help <command>` for usage. Workers can be
referenced by index or name, buildings by index or a type/name fragment
(e.g. `staff power 1`). Commands that change the colony print what happened.
"""

import argparse
import cmd
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

import main as game
from actions import SPACE_ENVIRONMENTS, build_from_catalog

PROFESSIONS = {"unassigned": 0, "doctor": 1, "engineer": 2, "biologist": 3, "geologist": 4, "pilot": 5}
CROPS = ["lettuce", "wheat", "flax", "sunflower"]
MATERIALS = ["glass", "aluminum", "steel", "plastic"]
ITEMS = ["drones", "rovers", "cars", "trucks", "satellites", "rockets"]
BUILD_TYPES = [
    "power", "water", "iceminer", "oxygen", "co2", "nitrogen", "hydrogen", "food", "fuel",
    "aluminum", "steel", "soil", "plastic", "glass",
    "farm_lettuce", "farm_wheat", "farm_flax", "farm_sunflower",
    "car_factory", "truck_factory", "rover_factory", "satellite_factory", "rocket_factory", "drone_factory",
    "habitation", "recreation", "canteen", "logistics", "research", "university",
    "medical_bay", "hospital", "graveyard", "comms_hub", "satellite_dish",
]

# name -> (router action, argument kinds, group, description).
# Kinds: worker, building, profession, crop, material, item, buildtype, int.
# A trailing '?' makes an argument optional, a trailing '*' accepts one or more.
COMMANDS: Dict[str, Tuple[str, List[str], str, str]] = {
    "work":        ("work", ["worker"], "Crew", "General shift: +electricity"),
    "rest":        ("rest", ["worker"], "Crew", "Rest to recover health and reduce debuffs"),
    "hospital":    ("hospital", ["worker"], "Crew", "Treat in hospital (2 water, 5 electricity)"),
    "study":       ("study", ["worker"], "Crew", "Train skills (5 electricity)"),
    "retire":      ("retire", ["worker"], "Crew", "Retire a worker from active duty"),
    "job":         ("assign_job", ["worker", "profession"], "Crew", "Change a worker's profession"),
    "train":       ("university_train", ["building", "worker", "profession"], "Crew", "Train a worker at a University"),
    "staff":       ("staff_building", ["building", "worker"], "Buildings", "Staff a building with a worker"),
    "unstaff":     ("unstaff_building", ["building", "worker"], "Buildings", "Remove a worker from a building"),
    "toggle":      ("toggle_building", ["building"], "Buildings", "Turn a building on/off"),
    "build":       ("construct_building", ["buildtype"], "Buildings", "Construct a building (see `catalog`)"),
    "factory":     ("operate_factory", ["building", "worker*"], "Buildings", "Manual shift at a production building"),
    "maintain":    ("maintain_buildings", [], "Buildings", "Repair/upkeep all buildings (+safety)"),
    "logistics":   ("transfer_logistics", [], "Buildings", "Move local stockpiles to colony storage"),
    "research":    ("run_research", ["building", "int?"], "Science", "Run a Research Lab for N points"),
    "moxie":       ("run_moxie", ["worker"], "Life support", "Run MOXIE for oxygen"),
    "atmosphere":  ("balance_atmosphere", [], "Life support", "Run the atmosphere processor"),
    "hydroponics": ("hydroponics", ["worker", "crop"], "Life support", "Grow a crop"),
    "refinery":    ("food_refinery", ["worker", "crop"], "Life support", "Refine a crop into food/plastic"),
    "feed":        ("feed_crew", [], "Life support", "Extra ration (advance already feeds the crew)"),
    "mine":        ("mine", ["worker"], "Industry", "Mine dirt, water, aluminum, steel"),
    "fuel":        ("produce_fuel", ["worker"], "Industry", "Synthesize fuel"),
    "refine":      ("refine_materials", ["worker", "material"], "Industry", "Refine glass/aluminum/steel/plastic"),
    "make":        ("manufacture", ["worker", "item"], "Industry", "Manufacture a vehicle/satellite/rocket"),
    "rover":       ("deploy_rover", ["worker"], "Missions", "Rover expedition (+science, dirt)"),
    "drone":       ("fly_drone", ["worker"], "Missions", "Drone recon (+science, seeds)"),
    "satellite":   ("launch_satellite", ["worker"], "Missions", "Launch a satellite"),
    "rocket":      ("launch_rocket", ["worker"], "Missions", "Rocket mission (+science, resupply)"),
    "crisis":      ("resolve_crises", [], "Missions", "Try to resolve active crises"),
}


class CommandError(Exception):
    pass


class GameShell(cmd.Cmd):
    prompt = "colony> "

    def __init__(self, router: Any, target_sols: int, target_sci: float, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.router = router
        self.state = router.state
        self.target_sols = target_sols
        self.target_sci = target_sci
        self.finished = False
        for name in COMMANDS:
            setattr(self, f"do_{name}", self._make_command(name))

    def get_names(self) -> List[str]:  # lets cmd see the generated do_* methods
        return dir(self)

    # ---------- argument resolution ----------
    def _worker(self, token: str) -> int:
        workers = self.state.workers
        if token.isdigit():
            idx = int(token)
            if idx >= len(workers):
                raise CommandError(f"No worker {idx} (valid 0-{len(workers) - 1}).")
            return idx
        matches = [i for i, w in enumerate(workers) if w.Name.lower() == token.lower()]
        if not matches:
            raise CommandError(f"No worker named '{token}'. Use `crew` to list them.")
        if len(matches) > 1:
            raise CommandError(f"'{token}' is ambiguous (workers {matches}); use the index.")
        return matches[0]

    def _building(self, token: str) -> int:
        blds = self.state.buildings
        if token.isdigit():
            idx = int(token)
            if idx >= len(blds):
                raise CommandError(f"No building {idx} (valid 0-{len(blds) - 1}).")
            return idx
        t = token.lower()
        matches = [
            i for i, b in enumerate(blds)
            if t in type(b).__name__.lower() or t in b.name.lower().replace(" ", "")
        ]
        if not matches:
            raise CommandError(f"No building matching '{token}'. Use `buildings` to list them.")
        if len(matches) > 1:
            raise CommandError(f"'{token}' matches buildings {matches}; use the index.")
        return matches[0]

    def _choice(self, token: str, options: List[str], what: str) -> str:
        t = token.lower()
        if t in options:
            return t
        raise CommandError(f"Unknown {what} '{token}'. Options: {', '.join(options)}")

    def _convert(self, kind: str, token: str) -> Any:
        if kind == "worker":
            return self._worker(token)
        if kind == "building":
            return self._building(token)
        if kind == "profession":
            return PROFESSIONS[self._choice(token, list(PROFESSIONS), "profession")]
        if kind == "crop":
            return self._choice(token, CROPS, "crop")
        if kind == "material":
            return self._choice(token, MATERIALS, "material")
        if kind == "item":
            return self._choice(token, ITEMS, "item")
        if kind == "buildtype":
            return self._choice(token, BUILD_TYPES, "building type")
        if kind == "int":
            try:
                return int(token)
            except ValueError:
                raise CommandError(f"'{token}' is not a whole number.")
        raise CommandError(f"Internal error: unknown argument kind {kind}")

    def _parse_args(self, name: str, line: str) -> List[Any]:
        action, kinds, _, _ = COMMANDS[name]
        tokens = line.split()
        required = [k for k in kinds if not k.endswith("?") and not k.endswith("*")]
        variadic = any(k.endswith("*") for k in kinds)
        max_args = None if variadic else len(kinds)
        if len(tokens) < len(required) + (1 if variadic else 0) or (max_args is not None and len(tokens) > max_args):
            raise CommandError(f"usage: {self._usage(name)}")
        args: List[Any] = []
        for i, token in enumerate(tokens):
            kind = kinds[min(i, len(kinds) - 1)].rstrip("?*")
            args.append(self._convert(kind, token))
        # Router signatures: university_train wants the profession as a name string.
        if action == "university_train":
            args[2] = [n for n, c in PROFESSIONS.items() if c == args[2]][0].capitalize()
        if action == "operate_factory":
            args = [args[0], args[1:]]
        return args

    @staticmethod
    def _usage(name: str) -> str:
        parts = []
        for k in COMMANDS[name][1]:
            base = k.rstrip("?*")
            parts.append(f"[{base}]" if k.endswith("?") else f"<{base}>..." if k.endswith("*") else f"<{base}>")
        return " ".join([name] + parts)

    def _make_command(self, name: str) -> Callable[[str], None]:
        def handler(line: str) -> None:
            try:
                args = self._parse_args(name, line)
            except CommandError as err:
                print(f"  ! {err}")
                return
            self._run(COMMANDS[name][0], *args)

        handler.__doc__ = COMMANDS[name][3]
        return handler

    def _run(self, action: str, *args: Any) -> Any:
        start = len(self.state.log)
        result = None
        try:
            result = self.router.execute(action, *args)
        except Exception as err:  # keep the shell alive on game-rule errors
            print(f"  ! {type(err).__name__}: {err}")
        for entry in self.state.log[start:]:
            print(f"  > {entry}")
        return result

    # ---------- tab completion ----------
    def completedefault(self, text: str, line: str, begidx: int, endidx: int) -> List[str]:
        tokens = line[:begidx].split()
        if not tokens:
            return []
        name = tokens[0]
        if name in ("sol", "next"):
            return []
        if name in ("status", "show"):
            options = ["resources", "buildings", "crew", "crises"]
        elif name in ("info",):
            options = [type(b).__name__.lower() for b in self.state.buildings]
        elif name in COMMANDS:
            kinds = COMMANDS[name][1]
            pos = len(tokens) - 1
            kind = kinds[min(pos, len(kinds) - 1)].rstrip("?*") if kinds else ""
            options = {
                "worker": [w.Name.lower() for w in self.state.workers] + [str(i) for i in range(len(self.state.workers))],
                "building": [type(b).__name__.lower() for b in self.state.buildings] + [str(i) for i in range(len(self.state.buildings))],
                "profession": list(PROFESSIONS), "crop": CROPS, "material": MATERIALS,
                "item": ITEMS, "buildtype": BUILD_TYPES,
            }.get(kind, [])
        else:
            return []
        return sorted({o for o in options if o.startswith(text.lower())})

    # ---------- views ----------
    def _alive(self) -> List[Any]:
        return [w for w in self.state.workers if not getattr(w, "retired", False) and w.getHealth() > 0]

    def _dashboard(self) -> None:
        s = self.state
        res = lambda k: s.resources[k].getResources()
        risk = int(s.hazard_manager.last_risk_score * 100)
        print(
            f"\nSol {s.sol}/{self.target_sols} | Crew {len(self._alive())}/{len(s.workers)} | "
            f"Water {res('water'):.0f} O2 {res('oxigen'):.0f} Food {res('food'):.0f} "
            f"Power {res('electricity'):.0f} Fuel {res('fuel'):.0f} | "
            f"Science {s.science_points:.0f}/{self.target_sci:.0f} | Risk {risk}%"
        )
        for key, vals in s.daily_report.items():
            if vals["net"] < 0 and key in ("water", "oxigen", "food", "electricity", "fuel"):
                left = res(key) / -vals["net"]
                if left < 5:
                    print(f"  WARNING: {key} runs out in ~{left:.1f} sols at last sol's rate")
        for inc in s.hazard_manager.active_incidents:
            print(f"  CRISIS [sev {inc.severity}] {inc.name}: {inc.description}")

    def do_status(self, arg: str) -> None:
        """status [resources|buildings|crew|crises]  - overview, or one section"""
        view = arg.strip().lower()
        if not view:
            self._dashboard()
        elif view.startswith("res"):
            self._show_resources()
        elif view.startswith("b"):
            self._show_buildings()
        elif view.startswith("cris"):
            self._show_crises()
        elif view.startswith("c"):
            self._show_crew()
        else:
            print("  ! usage: status [resources|buildings|crew|crises]")

    do_show = do_status

    def _show_resources(self) -> None:
        print(f"  {'resource':<16}{'current':>12}{'max':>12}")
        for name, inv in self.state.resources.items():
            if inv.getMaxResources() or inv.getResources():
                print(f"  {name:<16}{inv.getResources():>12.1f}{inv.getMaxResources():>12.0f}")
        if self.state.daily_report:
            print("  Last sol: " + ", ".join(f"{k} {v['net']:+.1f}" for k, v in self.state.daily_report.items()))

    def _show_buildings(self) -> None:
        for i, b in enumerate(self.state.buildings):
            cap = type(b).max_worker_capacity
            op = "OP" if b.is_operational() else "IDLE"
            needs = ", ".join(f"{p} {lo}-{hi}" for p, (lo, hi) in type(b).required_professions.items()) or "none"
            local = ""
            if hasattr(b, "storage"):
                local = " local[" + ", ".join(f"{k}:{v.getResources():.0f}" for k, v in b.storage.items()) + "]"
            print(f"  [{i}] {b.name:<28} {'On' if b.is_on else 'Off':<3}/{op:<4} staff {b.number_of_workers}/{cap} needs({needs}) safety {b.safety_rating:.0f}%{local}")

    def _show_crew(self) -> None:
        for i, w in enumerate(self.state.workers):
            if getattr(w, "retired", False):
                status = "Retired"
            elif w.getHealth() <= 0:
                status = "Deceased"
            elif w.assigned_building is not None:
                status = f"Staffed @ {w.assigned_building.name}"
            else:
                status = "Ready" if w.isAvailable() else "Busy"
            print(f"  [{i}] {w.Name:<10} {w.getType().name:<10} HP {w.getHealth():5.1f}  {status}")

    def _show_crises(self) -> None:
        incidents = self.state.hazard_manager.active_incidents
        if not incidents:
            print("  No active crises.")
        for inc in incidents:
            print(f"  [sev {inc.severity}] {inc.name} (active {inc.turns_active} sols): {inc.description}")

    def do_resources(self, arg: str) -> None:
        """resources  - all colony inventories"""
        self._show_resources()

    def do_buildings(self, arg: str) -> None:
        """buildings  - list buildings with indices, staffing and local storage"""
        self._show_buildings()

    def do_crew(self, arg: str) -> None:
        """crew  - list workers with indices, professions, health and status"""
        self._show_crew()

    def do_crises(self, arg: str) -> None:
        """crises  - active incidents and what they need"""
        self._show_crises()

    def do_info(self, arg: str) -> None:
        """info <building>  - full details for one building"""
        try:
            print("  " + self.state.buildings[self._building(arg.strip())].get_info())
        except (CommandError, IndexError) as err:
            print(f"  ! {err or 'usage: info <building>'}")

    def do_catalog(self, arg: str) -> None:
        """catalog  - buildable types with cost and staffing needs"""
        print(f"  {'type':<20}{'power':>7}  steel/alu  needs")
        for key in BUILD_TYPES:
            b = build_from_catalog(key)
            needs = ", ".join(f"{p} {lo}-{hi}" for p, (lo, hi) in type(b).required_professions.items()) or "none"
            print(f"  {key:<20}{round(b.production_cost * 0.05, 1):>7}  20/20      {needs}")

    def do_log(self, arg: str) -> None:
        """log [n]  - show the last n log entries (default 15)"""
        n = int(arg) if arg.strip().isdigit() else 15
        for entry in self.state.log[-n:]:
            print(f"  > {entry}")

    # ---------- time ----------
    def do_sol(self, arg: str) -> None:
        """sol [n]  - advance n sols (default 1); stops early if the mission ends"""
        n = int(arg) if arg.strip().isdigit() else 1
        for _ in range(max(1, n)):
            self._run("advance_sol")
            if self._mission_over():
                break
        self._dashboard()

    do_next = do_sol

    def _mission_over(self) -> bool:
        return not self._alive() or self.state.sol >= self.target_sols

    def do_quit(self, arg: str) -> bool:
        """quit  - end the mission and show the report"""
        game.print_mission_report(self.state, self.target_sols, self.target_sci)
        self.finished = True
        return True

    do_exit = do_quit

    def do_EOF(self, arg: str) -> bool:
        print()
        return self.do_quit(arg)

    # ---------- help / loop hooks ----------
    def do_help(self, arg: str) -> None:
        """help [command]  - list commands or show usage for one"""
        name = arg.strip().lower()
        if name in COMMANDS:
            print(f"  {self._usage(name)}\n  {COMMANDS[name][3]}")
            return
        if name:
            super().do_help(name)
            return
        groups: Dict[str, List[str]] = {}
        for n, (_, _, group, _) in COMMANDS.items():
            groups.setdefault(group, []).append(n)
        print("Views:  status [resources|buildings|crew|crises], resources, buildings, crew, crises, info, catalog, log")
        print("Time:   sol [n] (alias: next), quit")
        for group, names in groups.items():
            print(f"{group + ':':<15}" + ", ".join(names))
        print("Workers: index or name. Buildings: index or fragment (e.g. `staff power 1`). `help <command>` for usage.")

    def emptyline(self) -> bool:
        return False

    def default(self, line: str) -> None:
        print(f"  ! Unknown command '{line.split()[0]}'. Type `help`.")

    def postcmd(self, stop: bool, line: str) -> bool:
        if stop:
            return True
        if self._mission_over():
            game.print_mission_report(self.state, self.target_sols, self.target_sci)
            self.finished = True
            return True
        return False


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Colony Command terminal interface")
    p.add_argument("--env", choices=list(SPACE_ENVIRONMENTS), help="space environment")
    p.add_argument("--crew", type=int, help="crew size (2-10)")
    p.add_argument("--sols", type=int, help="target mission length (10-365)")
    p.add_argument("--science", type=float, help="science points needed to win (100-5000)")
    p.add_argument("--script", help="read commands from this file instead of the keyboard")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    if args.env or args.crew or args.sols or args.science:
        env = args.env or "mars"
        crew = max(2, min(10, args.crew or 6))
        sols = max(10, min(365, args.sols or 30))
        sci = float(max(100, min(5000, args.science or 500)))
    else:
        env, crew, sols, sci = game.choose_mission_setup()

    router = game.setup_game(space_key=env, crew_count=crew)
    stdin = open(args.script) if args.script else None
    shell = GameShell(router, sols, sci, stdin=stdin)
    if stdin is not None:
        shell.use_rawinput = False
    print(f"Mission: survive {sols} sols and reach {sci:.0f} science. Type `help` for commands.")
    shell._dashboard()
    shell.cmdloop()


if __name__ == "__main__":
    main()
