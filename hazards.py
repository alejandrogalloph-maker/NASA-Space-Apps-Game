import math
import random
from typing import Any, List


class Incident:
    def __init__(self, name: str, description: str, severity: int):
        self.name = name
        self.description = description
        self.severity = severity
        self.turns_active = 0
        self.resolved = False

    def trigger(self, state: Any) -> None:
        state.log.append(f'CRITICAL INCIDENT [Severity {self.severity}]: {self.name} - {self.description}')
        self.apply_initial_effect(state)

    def apply_initial_effect(self, state: Any) -> None:
        pass

    def apply_ongoing_penalty(self, state: Any) -> None:
        self.turns_active += 1

    def check_resolution(self, state: Any) -> bool:
        return True


class PowerGridFailure(Incident):
    def __init__(self):
        super().__init__(
            'Grid Overload',
            'Power plants tripped offline. Need 50 aluminum and 2 ready Engineers to repair.',
            2,
        )

    def apply_initial_effect(self, state: Any) -> None:
        elec = state.resources.get('electricity')
        if elec is not None:
            loss = round(min(150.0, elec.getResources() * 0.35), 1)
            elec.SubtractResources(loss)
            state.log.append(f'Grid Failure: Lost {loss} kWh from main capacitors.')
        for bld in state.buildings:
            if type(bld).__name__ == 'PowerPlant' and getattr(bld, 'is_on', True):
                bld.turn_off()

    def apply_ongoing_penalty(self, state: Any) -> None:
        self.turns_active += 1
        elec = state.resources.get('electricity')
        if elec is not None:
            drain = round(min(15.0 * self.turns_active, elec.getResources()), 1)
            if drain > 0:
                elec.SubtractResources(drain)
                state.log.append(f'Ongoing Grid Instability: Drained {drain} kWh.')

    def check_resolution(self, state: Any) -> bool:
        alum = state.resources.get('aluminum')
        if alum is None or alum.getResources() < 50.0:
            return False
        engineers = [
            w for w in state.workers
            if not getattr(w, 'retired', False)
            and w.getHealth() > 0
            and w.getType().name == 'Engineer'
            and w.isAvailable()
        ]
        if len(engineers) < 2:
            return False
        alum.SubtractResources(50.0)
        for eng in engineers[:2]:
            eng.SendToWork()
            if not eng.takeDamage(5.0):
                eng.health = 0.0
                eng.Available = False
        self.resolved = True
        state.log.append('INCIDENT RESOLVED: Grid repaired by 2 Engineers (-50 aluminum). Turn PowerPlants back On.')
        return True


class AmmoniaLeak(Incident):
    def __init__(self):
        super().__init__(
            'Ammonia Coolant Leak',
            'Toxic vapor in life-support loop. Need 10 plastic, 15 water, and 1 ready Doctor.',
            3,
        )

    def apply_initial_effect(self, state: Any) -> None:
        active = [w for w in state.workers if not getattr(w, 'retired', False) and w.getHealth() > 0]
        for w in active:
            if not w.takeDamage(10.0):
                w.health = 0.0
                w.Available = False
        state.log.append('Ammonia Leak: Active crew suffered 10 toxic exposure damage.')

    def apply_ongoing_penalty(self, state: Any) -> None:
        self.turns_active += 1
        active = [w for w in state.workers if not getattr(w, 'retired', False) and w.getHealth() > 0]
        dmg = round(4.0 * self.turns_active, 1)
        for w in active:
            if not w.takeDamage(dmg):
                w.health = 0.0
                w.Available = False
        if active:
            state.log.append(f'Ongoing Ammonia Toxicity: Active crew took {dmg} damage.')

    def check_resolution(self, state: Any) -> bool:
        plastic = state.resources.get('plastic')
        water = state.resources.get('water')
        if plastic is None or water is None:
            return False
        if plastic.getResources() < 10.0 or water.getResources() < 15.0:
            return False
        doctors = [
            w for w in state.workers
            if not getattr(w, 'retired', False)
            and w.getHealth() > 0
            and w.getType().name == 'Doctor'
            and w.isAvailable()
        ]
        if not doctors:
            return False
        plastic.SubtractResources(10.0)
        water.SubtractResources(15.0)
        doc = doctors[0]
        doc.SendToWork()
        if not doc.takeDamage(4.0):
            doc.health = 0.0
            doc.Available = False
        self.resolved = True
        state.log.append('INCIDENT RESOLVED: Ammonia loop sealed and crew stabilized (-10 plastic, -15 water).')
        return True


class MeteorStrike(Incident):
    def __init__(self):
        super().__init__(
            'Micrometeorite Hull Breach',
            'Structural hull puncture. Need 80 steel, 80 dirt, 1 ready Geologist, and 1 ready Engineer.',
            3,
        )

    def apply_initial_effect(self, state: Any) -> None:
        if state.buildings:
            target = random.choice(state.buildings)
            if target.safety_rating > 1.0:
                target.safety_rating = max(10, target.safety_rating - 35)
            else:
                target.safety_rating = max(0.10, round(target.safety_rating - 0.35, 2))
            state.log.append(f'Meteor Strike: {target.name} took heavy structural damage.')
        o2 = state.resources.get('oxigen')
        if o2 is not None:
            loss = round(min(40.0, o2.getResources() * 0.25), 1)
            o2.SubtractResources(loss)
            state.log.append(f'Hull Breach Decompression: Lost {loss} kg oxigen.')

    def apply_ongoing_penalty(self, state: Any) -> None:
        self.turns_active += 1
        o2 = state.resources.get('oxigen')
        if o2 is not None:
            leak = round(min(8.0 * self.turns_active, o2.getResources()), 1)
            if leak > 0:
                o2.SubtractResources(leak)
                state.log.append(f'Ongoing Hull Leak: Venting {leak} kg oxigen.')

    def check_resolution(self, state: Any) -> bool:
        steel = state.resources.get('steel')
        dirt = state.resources.get('dirt')
        if steel is None or dirt is None:
            return False
        if steel.getResources() < 80.0 or dirt.getResources() < 80.0:
            return False
        geologists = [
            w for w in state.workers
            if not getattr(w, 'retired', False)
            and w.getHealth() > 0
            and w.getType().name == 'Geologist'
            and w.isAvailable()
        ]
        engineers = [
            w for w in state.workers
            if not getattr(w, 'retired', False)
            and w.getHealth() > 0
            and w.getType().name == 'Engineer'
            and w.isAvailable()
        ]
        if not geologists or not engineers:
            return False
        steel.SubtractResources(80.0)
        dirt.SubtractResources(80.0)
        geo = geologists[0]
        eng = engineers[0]
        geo.SendToWork()
        eng.SendToWork()
        if not geo.takeDamage(6.0):
            geo.health = 0.0
            geo.Available = False
        if not eng.takeDamage(6.0):
            eng.health = 0.0
            eng.Available = False
        self.resolved = True
        state.log.append('INCIDENT RESOLVED: Hull breach patched with regolith concrete (-80 steel, -80 dirt).')
        return True


class HazardManager:
    def __init__(self):
        self.active_incidents: List[Incident] = []
        self.incident_pool = [PowerGridFailure, AmmoniaLeak, MeteorStrike]
        self.last_risk_score: float = 0.0

    def compute_risk_probability(self, state: Any) -> float:
        base_risk = float(state.space.get('hazard_chance', 0.25)) * 0.45

        if state.buildings:
            safety_values = []
            for bld in state.buildings:
                sr = float(getattr(bld, 'safety_rating', 95))
                safety_values.append(sr / 100.0 if sr > 1.0 else sr)
            avg_safety = sum(safety_values) / len(safety_values)
        else:
            avg_safety = 1.0
        degradation_risk = max(0.0, (1.0 - avg_safety) * 0.50)

        active_volume = sum(
            float(getattr(b, 'volume', 100))
            for b in state.buildings
            if getattr(b, 'is_on', True)
        )
        exposure_risk = 0.04 * math.log1p(active_volume / 500.0)

        active_crew = [w for w in state.workers if not getattr(w, 'retired', False) and w.getHealth() > 0]
        if active_crew:
            avg_hp = sum(w.getHealth() for w in active_crew) / len(active_crew)
            fatigue_risk = max(0.0, (100.0 - avg_hp) / 400.0)
        else:
            fatigue_risk = 0.0

        total_prob = min(0.65, max(0.05, base_risk + degradation_risk + exposure_risk + fatigue_risk))
        self.last_risk_score = round(total_prob, 3)
        return total_prob

    def process_turn(self, state: Any) -> None:
        for inc in list(self.active_incidents):
            if inc.check_resolution(state):
                self.active_incidents.remove(inc)
            else:
                inc.apply_ongoing_penalty(state)
                state.log.append(f'ONGOING CRISIS: {inc.name} - {inc.description}')

        risk_prob = self.compute_risk_probability(state)
        if len(self.active_incidents) < 2 and random.random() < risk_prob:
            active_types = {type(i) for i in self.active_incidents}
            candidates = [cls for cls in self.incident_pool if cls not in active_types]
            if candidates:
                new_crisis = random.choice(candidates)()
                self.active_incidents.append(new_crisis)
                new_crisis.trigger(state)
