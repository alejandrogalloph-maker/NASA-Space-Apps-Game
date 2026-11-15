import random
from typing import Any, List


class Incident:
    """Base state and hooks shared by all colony incidents."""

    def __init__(self, name: str, description: str, severity: int):
        """Store incident details and initialize its unresolved state."""
        self.name = name
        self.description = description
        self.severity = severity
        self.turns_active = 0
        self.resolved = False

    def trigger(self, state: Any) -> None:
        """Report the incident and apply its immediate effect to the colony."""
        state.log.append(f'CRITICAL INCIDENT [Severity {self.severity}]: {self.name} - {self.description}')
        self.apply_initial_effect(state)

    def apply_initial_effect(self, state: Any) -> None:
        """Hook for incident-specific effects applied once when it begins."""
        pass

    def apply_ongoing_penalty(self, state: Any) -> None:
        """Advance the incident duration; subclasses may also apply ongoing damage."""
        self.turns_active += 1

    def check_resolution(self, state: Any) -> bool:
        """Hook for incident-specific resolution requirements."""
        return True


class PowerGridFailure(Incident):
    """Disrupts power and requires materials and engineers to repair the grid."""

    definition = (
        "A power surge trips the solar plants offline, drains stored electricity, "
        "and increases grid instability until repaired."
    )

    def __init__(self):
        super().__init__(
            'Grid Overload',
            'Power plants tripped offline. Need 50 aluminum and 2 ready Engineers to repair.',
            2,
        )

    def apply_initial_effect(self, state: Any) -> None:
        """Drain part of stored electricity and switch off power plants."""
        elec = state.resources.get('electricity')
        if elec is not None:
            loss = round(min(150.0, elec.getResources() * 0.35), 1)
            elec.SubtractResources(loss)
            state.log.append(f'Grid Failure: Lost {loss} kWh from main capacitors.')
        for bld in state.buildings:
            if type(bld).__name__ == 'PowerPlant' and getattr(bld, 'is_on', True):
                bld.turn_off()

    def apply_ongoing_penalty(self, state: Any) -> None:
        """Increase the power drain each turn the failure remains unresolved."""
        self.turns_active += 1
        elec = state.resources.get('electricity')
        if elec is not None:
            drain = round(min(15.0 * self.turns_active, elec.getResources()), 1)
            if drain > 0:
                elec.SubtractResources(drain)
                state.log.append(f'Ongoing Grid Instability: Drained {drain} kWh.')

    def check_resolution(self, state: Any) -> bool:
        """Repair the grid if aluminum and two available engineers are present."""
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
    """Damages living crew until a doctor seals the coolant leak."""

    definition = (
        "Toxic ammonia escapes from the coolant loop into life support, exposing "
        "living human crew and causing escalating damage until sealed."
    )

    def __init__(self):
        super().__init__(
            'Ammonia Coolant Leak',
            'Toxic vapor in life-support loop. Need 10 plastic, 15 water, and 1 ready Doctor.',
            3,
        )

    def apply_initial_effect(self, state: Any) -> None:
        """Apply the initial toxic exposure to every active worker."""
        active = [
            w for w in state.workers
            if not getattr(w, 'is_robot', False)
            and not getattr(w, 'retired', False)
            and w.getHealth() > 0
        ]
        for w in active:
            if not w.takeDamage(10.0):
                w.health = 0.0
                w.Available = False
        state.log.append('Ammonia Leak: Active crew suffered 10 toxic exposure damage.')

    def apply_ongoing_penalty(self, state: Any) -> None:
        """Increase crew exposure damage with each unresolved turn."""
        self.turns_active += 1
        active = [
            w for w in state.workers
            if not getattr(w, 'is_robot', False)
            and not getattr(w, 'retired', False)
            and w.getHealth() > 0
        ]
        dmg = round(4.0 * self.turns_active, 1)
        for w in active:
            if not w.takeDamage(dmg):
                w.health = 0.0
                w.Available = False
        if active:
            state.log.append(f'Ongoing Ammonia Toxicity: Active crew took {dmg} damage.')

    def check_resolution(self, state: Any) -> bool:
        """Seal the leak using plastic, water, and one available doctor."""
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
    """Damages a random building and causes an oxygen leak."""

    definition = (
        "A micrometeorite punctures a colony structure, reducing its safety and "
        "venting oxygen until the hull breach is patched."
    )

    def __init__(self):
        super().__init__(
            'Micrometeorite Hull Breach',
            'Structural hull puncture. Need 80 steel, 80 dirt, 1 ready Geologist, and 1 ready Engineer.',
            3,
        )

    def apply_initial_effect(self, state: Any) -> None:
        """Reduce one building's safety and vent some of the stored oxygen."""
        if state.buildings:
            target = random.choice(state.buildings)
            target.safety_rating = max(10, target.safety_rating - 35)
            state.log.append(f'Meteor Strike: {target.name} took heavy structural damage.')
        o2 = state.resources.get('oxigen')
        if o2 is not None:
            loss = round(min(40.0, o2.getResources() * 0.25), 1)
            o2.SubtractResources(loss)
            state.log.append(f'Hull Breach Decompression: Lost {loss} kg oxigen.')

    def apply_ongoing_penalty(self, state: Any) -> None:
        """Increase the oxygen leak each turn until the hull is repaired."""
        self.turns_active += 1
        o2 = state.resources.get('oxigen')
        if o2 is not None:
            leak = round(min(8.0 * self.turns_active, o2.getResources()), 1)
            if leak > 0:
                o2.SubtractResources(leak)
                state.log.append(f'Ongoing Hull Leak: Venting {leak} kg oxigen.')

    def check_resolution(self, state: Any) -> bool:
        """Patch the breach using steel, dirt, a geologist, and an engineer."""
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
    """Calculate colony hazard risk and manage active incident lifecycles."""

    DAILY_CHANCE_PER_HAZARD = 0.01

    def __init__(self):
        """Set up the incident list, available incident types, and risk score."""
        self.active_incidents: List[Incident] = []
        self.incident_pool = [PowerGridFailure, AmmoniaLeak, MeteorStrike]
        self.last_risk_score: float = 0.0

    def compute_risk_probability(self, state: Any) -> float:
        """Return the chance of at least one independent daily hazard."""
        total_prob = 1.0 - (
            1.0 - self.DAILY_CHANCE_PER_HAZARD
        ) ** len(self.incident_pool)
        self.last_risk_score = round(total_prob, 3)
        return total_prob

    def process_turn(self, state: Any) -> None:
        """Resolve existing incidents and independently roll each hazard once."""
        for inc in list(self.active_incidents):
            if inc.check_resolution(state):
                self.active_incidents.remove(inc)
            else:
                inc.apply_ongoing_penalty(state)
                state.log.append(f'ONGOING CRISIS: {inc.name} - {inc.description}')

        self.compute_risk_probability(state)
        active_types = {type(incident) for incident in self.active_incidents}
        for incident_type in self.incident_pool:
            if (
                incident_type not in active_types
                and random.random() < self.DAILY_CHANCE_PER_HAZARD
            ):
                new_crisis = incident_type()
                self.active_incidents.append(new_crisis)
                active_types.add(incident_type)
                new_crisis.trigger(state)
