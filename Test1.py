import random
from enum import Enum
from typing import Dict, List


# ==============================================================================
# 1. RESOURCE CLASS (Ported from your C++ 'Resource Class')
# ==============================================================================
class Resource:
    def __init__(self, name: str, current: float = 0.0, max_val: float = 1000.0, unit: str = ""):
        self.name = name
        self.unit = unit
        self._max = max(0.0, float(max_val))
        self._current = max(0.0, min(float(current), self._max))

    def get_resources(self) -> float:
        return self._current

    def get_max_resources(self) -> float:
        return self._max

    def add_resources(self, n: float) -> None:
        if n <= 0:
            return
        self._current = min(self._max, self._current + n)

    def subtract_resources(self, n: float) -> bool:
        if n < 0 or self._current < n:
            return False
        self._current -= n
        return True

    def add_max(self, n: float) -> None:
        if n > 0:
            self._max += n

    def subtract_max(self, n: float) -> bool:
        if n < 0 or self._max < n:
            return False
        self._max -= n
        if self._current > self._max:
            self._current = self._max
        return True

    def __repr__(self) -> str:
        return f"{self.name}: {self._current:.1f}/{self._max:.1f} {self.unit}".strip()


def create_colony_resources() -> Dict[str, Resource]:
    """All 27 resources defined in your C++ Resource Class file."""
    return {
        # Human necessities & energy
        "water":       Resource("Water",         500.0,   2000.0,   "L"),
        "oxigen":      Resource("Oxygen",        120.0,   500.0,    "kg"),
        "CO2":         Resource("CO2",           40.0,    300.0,    "kg"),
        "Nitrogen":    Resource("Nitrogen",      200.0,   500.0,    "kg"),
        "Hydrogen":    Resource("Hydrogen",      50.0,    300.0,    "kg"),
        "food":        Resource("Food",          90000.0, 300000.0, "kcal"),
        "electricity": Resource("Electricity",   400.0,   1000.0,   "kWh"),
        "fuel":        Resource("Fuel",          300.0,   1000.0,   "L"),
        # Raw & refined materials
        "aluminum":    Resource("Aluminum",      100.0,   2000.0,   "kg"),
        "steel":       Resource("Steel",         150.0,   2000.0,   "kg"),
        "dirt":        Resource("Dirt/Regolith", 200.0,   5000.0,   "kg"),
        "plastic":     Resource("Plastic",       80.0,    1000.0,   "kg"),
        "glass":       Resource("Glass",         60.0,    1000.0,   "kg"),
        # Vehicles & hardware
        "cars":        Resource("Cars",          1,       5,        "units"),
        "trucks":      Resource("Trucks",        1,       5,        "units"),
        "rovers":      Resource("Rovers",        2,       10,       "units"),
        "satellites":  Resource("Satellites",    1,       5,        "units"),
        "rockets":     Resource("Rockets",       1,       3,        "units"),
        "drones":      Resource("Drones",        3,       15,       "units"),
        # Seeds & crops
        "seed_Lettuce":   Resource("Lettuce Seeds",   50, 500, "seeds"),
        "seed_Wheat":     Resource("Wheat Seeds",     50, 500, "seeds"),
        "seed_Flax":      Resource("Flax Seeds",      30, 500, "seeds"),
        "seed_sunflower": Resource("Sunflower Seeds", 30, 500, "seeds"),
        "lettuce":        Resource("Lettuce",         10, 500, "kg"),
        "wheat":          Resource("Wheat",           15, 500, "kg"),
        "flax":           Resource("Flax",            5,  500, "kg"),
        "sunflower":      Resource("Sunflower",       5,  500, "kg"),
    }


# ==============================================================================
# 2. WORKER CLASS (Ported from your C++ 'Worker_Class')
# ==============================================================================
class Profession(Enum):
    Unassigned = 0
    Biologist = 1
    Doctor = 2
    Engineer = 3
    Pilot = 4
    Geologist = 5


SKILL_LABELS = ["General", "Biology", "Medicine", "Engineering", "Piloting", "Geology"]


class Worker:
    TotalCount: int = 0
    AvailableCount: int = 0

    NAMES = [
        "Samuel", "Bruce", "Hunter", "Tonya", "Darrick", "Kathrine",
        "Howard", "Hong", "Robinson", "Cathryn", "Daniela", "Alex",
        "Sue", "Stephonie", "Rob", "Clair", "Carroll", "Jesse", "Sophia",
        "Riley",
    ]

    def __init__(self, age: int):
        self.age: int = age          # in days
        self.health: float = 100.0   # in percentage
        self.available: bool = True
        self.alive: bool = True
        self.retired: bool = False
        self.status: str = "Idle"
        self.job: Profession = Profession.Unassigned
        self.name: str = self.give_name()

        n = 6
        self.skills: List[float] = [random.uniform(10.0, 100.0) for _ in range(n)]
        self.debuffs: List[float] = [random.uniform(0.0, 40.0) for _ in range(n)]

        Worker.TotalCount += 1
        Worker.AvailableCount += 1

    # --- Getters ---
    def get_age(self) -> int:
        return self.age

    def get_health(self) -> float:
        return self.health

    def is_available(self) -> bool:
        return self.available and self.alive and not self.retired

    def get_skills(self) -> List[float]:
        return list(self.skills)

    def get_debuffs(self) -> List[float]:
        return list(self.debuffs)

    def get_type(self) -> Profession:
        return self.job

    # --- Actions (matching your C++ methods) ---
    def send_to_work(self) -> bool:
        if self.is_available():
            self.available = False
            self.status = f"Working ({self.job.name})"
            Worker.AvailableCount -= 1
            return True
        return False

    def send_to_rest(self) -> bool:
        if not self.alive or self.retired:
            return False
        if not self.available:
            self.available = True
            self.status = "Resting (Available)"
            Worker.AvailableCount += 1
            return True
        # Already available -> small health recovery up to 120% (per your C++ logic)
        h = random.uniform(1.0, 5.0)
        if self.health < 120.0:
            self.health = min(120.0, self.health + h)
        self.status = "Resting (Available)"
        return False

    def send_to_hospital(self) -> None:
        if not self.alive or self.retired:
            return
        if self.available:
            self.available = False
            Worker.AvailableCount -= 1
        self.status = "In Hospital"
        self.health = min(250.0, self.health + random.uniform(5.0, 15.0))
        idx = random.randrange(len(self.debuffs))
        self.mod_debuff(-random.uniform(2.0, 6.0), idx)

    def send_to_study(self) -> None:
        if not self.alive or self.retired:
            return
        if self.available:
            self.available = False
            Worker.AvailableCount -= 1
        self.status = "Studying"
        idx = self.job.value if self.job != Profession.Unassigned else random.randrange(len(self.skills))
        self.mod_skill(random.uniform(5.0, 15.0), idx)
        self.mod_debuff(-random.uniform(1.0, 5.0), idx)

    def mod_skill(self, n: float, i: int) -> None:
        self.skills[i] = max(0.0, min(300.0, self.skills[i] + n))

    def mod_debuff(self, n: float, i: int) -> None:
        self.debuffs[i] = max(0.0, min(100.0, self.debuffs[i] + n))

    def give_name(self) -> str:
        return random.choice(self.NAMES)

    def retire(self) -> None:
        if self.retired or not self.alive:
            return
        if self.available:
            Worker.AvailableCount -= 1
        self.available = False
        self.retired = True
        self.status = "Retired"

    def set_type(self, n: int) -> None:
        """Matches your C++ switch(N): 1=Doctor, 2=Engineer, 3=Biologist, 4=Geologist, 5=Pilot."""
        mapping = {
            1: Profession.Doctor,
            2: Profession.Engineer,
            3: Profession.Biologist,
            4: Profession.Geologist,
            5: Profession.Pilot,
        }
        self.job = mapping.get(n, Profession.Unassigned)

    def take_damage(self, amount: float) -> bool:
        if not self.alive:
            return False
        self.health -= amount
        if self.health <= 0.0:
            self.health = 0.0
            self.alive = False
            if self.available:
                Worker.AvailableCount -= 1
            self.available = False
            self.status = "Deceased"
            Worker.TotalCount -= 1
            return False
        return True

    def effective_efficiency(self) -> float:
        """Calculates work multiplier from matching skill, debuff, and health."""
        idx = self.job.value
        net_skill = max(10.0, self.skills[idx] - 0.5 * self.debuffs[idx])
        health_factor = max(0.25, min(1.5, self.health / 100.0))
        return (net_skill / 50.0) * health_factor

    def summary(self) -> str:
        idx = self.job.value
        return (
            f"{self.name:<10} | {self.job.name:<10} | HP: {self.health:5.1f}% | "
            f"Skill[{SKILL_LABELS[idx]}]: {self.skills[idx]:5.1f} (Debuff: {self.debuffs[idx]:4.1f}) | "
            f"Eff: {self.effective_efficiency():.2f}x | {self.status}"
        )


# ==============================================================================
# 3. COLONY SIMULATION ENGINE (Connecting Workers + Resources per Sol)
# ==============================================================================
class ColonySimulation:
    def __init__(self, crew: List[Worker]):
        self.sol = 0
        self.science_points = 0.0
        self.resources = create_colony_resources()
        self.crew = crew

    def simulate_sol(self) -> List[str]:
        self.sol += 1
        logs = [f"\n==================== SOL {self.sol} ===================="]
        r = self.resources

        # 1. Solar array power generation
        solar_kwh = random.uniform(60.0, 95.0)
        r["electricity"].add_resources(solar_kwh)
        logs.append(f"[Power] Solar array generated +{solar_kwh:.1f} kWh.")

        # 2. Daily human life-support consumption (NASA ECLSS baseline per living crewmember)
        living_crew = [w for w in self.crew if w.alive]
        for w in living_crew:
            w.age += 1
            if not r["oxigen"].subtract_resources(0.84):
                w.take_damage(25.0)
                logs.append(f"[ALERT] Oxygen shortage! {w.name} suffered hypoxia (-25 HP).")
            if not r["water"].subtract_resources(2.5):
                w.take_damage(20.0)
                logs.append(f"[ALERT] Water shortage! {w.name} suffered dehydration (-20 HP).")
            if not r["food"].subtract_resources(3035.0):
                w.take_damage(15.0)
                logs.append(f"[ALERT] Food shortage! {w.name} suffered starvation (-15 HP).")
            r["CO2"].add_resources(1.00)

        # 3. Execute work shifts & complete hospital/study turns
        for w in living_crew:
            if w.status.startswith("Working"):
                eff = w.effective_efficiency()
                self._perform_job_shift(w, eff, logs)
                w.take_damage(random.uniform(1.0, 3.5))  # Shift fatigue
                if not w.alive:
                    logs.append(f"[CASUALTY] {w.name} died from overwork/injuries!")
                else:
                    w.available = True
                    w.status = "Idle"
                    Worker.AvailableCount += 1
            elif w.status in ("In Hospital", "Studying"):
                w.available = True
                w.status = "Idle"
                Worker.AvailableCount += 1

        # 4. Random planetary anomaly (25% chance per Sol)
        if random.random() < 0.25 and living_crew:
            event = random.choice(["dust_storm", "micrometeorite", "solar_flare"])
            target = random.choice(living_crew)
            if event == "dust_storm":
                r["electricity"].subtract_resources(30.0)
                logs.append("[EVENT] Dust storm drained 30 kWh from batteries!")
            elif event == "micrometeorite":
                r["oxigen"].subtract_resources(8.0)
                target.take_damage(12.0)
                logs.append(f"[EVENT] Micrometeorite leak (-8 kg O2)! {target.name} took 12 damage.")
            elif event == "solar_flare":
                target.mod_debuff(10.0, target.job.value)
                logs.append(f"[EVENT] Solar flare radiation spike! {target.name} gained +10 debuff.")

        return logs

    def _perform_job_shift(self, w: Worker, eff: float, logs: List[str]) -> None:
        r = self.resources
        if w.job == Profession.Engineer:
            if r["electricity"].subtract_resources(25.0) and r["CO2"].subtract_resources(4.0):
                o2_made = 5.5 * eff
                r["oxigen"].add_resources(o2_made)
                logs.append(f"[Engineer] {w.name} ran MOXIE: +{o2_made:.1f} kg O2 (Eff {eff:.2f}x).")
            else:
                logs.append(f"[Engineer] {w.name} lacked electricity/CO2 to run MOXIE.")

        elif w.job == Profession.Biologist:
            if (
                r["water"].subtract_resources(12.0)
                and r["electricity"].subtract_resources(15.0)
                and r["seed_Lettuce"].subtract_resources(2)
            ):
                r["CO2"].subtract_resources(2.0)
                crop_kg = 3.5 * eff
                kcals = crop_kg * 2500.0
                r["lettuce"].add_resources(crop_kg)
                r["food"].add_resources(kcals)
                r["oxigen"].add_resources(1.2 * eff)
                logs.append(
                    f"[Biologist] {w.name} harvested {crop_kg:.1f} kg Lettuce (+{kcals:.0f} kcal, +{1.2*eff:.1f} kg O2)."
                )
            else:
                logs.append(f"[Biologist] {w.name} lacked water, power, or seeds for hydroponics.")

        elif w.job == Profession.Geologist:
            if (
                r["rovers"].get_resources() >= 1
                and r["fuel"].subtract_resources(15.0)
                and r["electricity"].subtract_resources(15.0)
            ):
                regolith = 40.0 * eff
                ice_water = 18.0 * eff
                metal = 6.0 * eff
                r["dirt"].add_resources(regolith)
                r["water"].add_resources(ice_water)
                r["aluminum"].add_resources(metal)
                self.science_points += 10.0 * eff
                logs.append(
                    f"[Geologist] {w.name} mined +{ice_water:.1f} L water, +{metal:.1f} kg Al, +{10*eff:.1f} Sci."
                )
            else:
                logs.append(f"[Geologist] {w.name} lacked rover, fuel, or power for mining.")

        elif w.job == Profession.Pilot:
            if r["drones"].get_resources() >= 1 and r["fuel"].subtract_resources(10.0):
                sci = 22.0 * eff
                self.science_points += sci
                logs.append(f"[Pilot] {w.name} flew drone survey: +{sci:.1f} Science Points.")
            else:
                logs.append(f"[Pilot] {w.name} grounded (insufficient fuel or drones).")

        elif w.job == Profession.Doctor:
            patients = [p for p in self.crew if p.alive and p is not w]
            if patients and r["water"].subtract_resources(3.0) and r["electricity"].subtract_resources(5.0):
                patient = min(patients, key=lambda p: p.health)
                heal = 12.0 * eff
                patient.health = min(150.0, patient.health + heal)
                patient.mod_debuff(-5.0 * eff, patient.job.value)
                logs.append(f"[Doctor] {w.name} treated {patient.name} (+{heal:.1f} HP, reduced debuffs).")
            else:
                logs.append(f"[Doctor] {w.name} stood by on medical watch.")

        else:
            r["electricity"].add_resources(5.0 * eff)
            logs.append(f"[Unassigned] {w.name} maintained solar panels (+{5.0*eff:.1f} kWh).")

    def print_dashboard(self) -> None:
        r = self.resources
        print(f"\n--- CREW ROSTER (Total: {Worker.TotalCount}, Available: {Worker.AvailableCount}) ---")
        for i, w in enumerate(self.crew):
            print(f"  [{i}] {w.summary()}")
        print("\n--- KEY COLONY RESOURCES ---")
        keys = ["water", "oxigen", "CO2", "Nitrogen", "food", "electricity", "fuel", "aluminum", "dirt", "lettuce"]
        print("  " + " | ".join(str(r[k]) for k in keys[:5]))
        print("  " + " | ".join(str(r[k]) for k in keys[5:]))
        print(f"  Science Points: {self.science_points:.1f}")


# ==============================================================================
# 4. INTERACTIVE CLI LOOP
# ==============================================================================
def main() -> None:
    crew = [Worker(age=10000 + i * 365) for i in range(6)]
    # Initial roles: Engineer (2), Biologist (3), Geologist (4), Pilot (5), Doctor (1), Unassigned (0)
    for idx, code in enumerate([2, 3, 4, 5, 1, 0]):
        crew[idx].set_type(code)

    sim = ColonySimulation(crew)

    while True:
        sim.print_dashboard()
        print("\nCOMMANDS:")
        print("  [1] Assign Job (1=Doctor, 2=Engineer, 3=Biologist, 4=Geologist, 5=Pilot, 0=Unassigned)")
        print("  [2] Send Worker to Work")
        print("  [3] Send ALL Available Workers to Work")
        print("  [4] Send Worker to Rest")
        print("  [5] Send Worker to Hospital")
        print("  [6] Send Worker to Study")
        print("  [7] Retire Worker")
        print("  [8] Advance 1 Sol (Simulate Day)")
        print("  [0] Quit")

        choice = input("\nSelect action: ").strip()
        if choice == "0":
            break
        elif choice == "3":
            count = sum(1 for w in sim.crew if w.send_to_work())
            print(f"Sent {count} workers on shift.")
        elif choice == "8":
            for line in sim.simulate_sol():
                print(line)
        elif choice in {"1", "2", "4", "5", "6", "7"}:
            try:
                idx = int(input(f"Worker index [0-{len(sim.crew)-1}]: ").strip())
                w = sim.crew[idx]
            except (ValueError, IndexError):
                print("Invalid worker index.")
                continue

            if choice == "1":
                try:
                    role_code = int(input("Job code (1=Doc, 2=Eng, 3=Bio, 4=Geo, 5=Pilot, 0=None): ").strip())
                    w.set_type(role_code)
                    print(f"{w.name} is now a {w.job.name}.")
                except ValueError:
                    print("Invalid job code.")
            elif choice == "2":
                print(f"{w.name} sent to work." if w.send_to_work() else f"{w.name} cannot work right now.")
            elif choice == "4":
                w.send_to_rest()
                print(f"{w.name} is resting (HP: {w.health:.1f}%).")
            elif choice == "5":
                w.send_to_hospital()
                print(f"{w.name} admitted to hospital (HP: {w.health:.1f}%).")
            elif choice == "6":
                w.send_to_study()
                print(f"{w.name} is studying {SKILL_LABELS[w.job.value]}.")
            elif choice == "7":
                w.retire()
                print(f"{w.name} has retired.")
        else:
            print("Unknown command.")


if __name__ == "__main__":
    main()
