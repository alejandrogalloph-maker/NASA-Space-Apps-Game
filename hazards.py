import random
from typing import Any, List


def _can_fill_role(worker: Any, profession: str) -> bool:
    return getattr(worker, "is_robot", False) or worker.getType().name == profession


class Incident:
    """Base state and hooks shared by all colony incidents."""

    eligible_environments = frozenset({"orbit", "moon", "mars", "deep_space"})
    blocks_communications = False

    def __init__(self, name: str, description: str, severity: int):
        """Store incident details and initialize its unresolved state."""
        self.name = name
        self.description = description
        self.definition = getattr(type(self), "definition", description)
        self.severity = severity
        self.turns_active = 0
        self.resolved = False

    def trigger(self, state: Any) -> None:
        """Report the incident and apply its immediate effect to the colony."""
        state.crisis_events.append({
            "name": self.name,
            "description": self.description,
            "cause": self.definition,
            "severity": self.severity,
            "sol": state.sol,
        })
        state.log.append(f'CRITICAL INCIDENT [Severity {self.severity}]: {self.name} - {self.description}')
        blockers = [
            incident.name
            for incident in state.hazard_manager.active_incidents
            if getattr(incident, "blocks_communications", False)
        ]
        if blockers:
            problem = " and ".join(blockers)
            state.log.append(
                f"... [No message received due to {problem}], "
                "with the current crisis there."
            )
        else:
            state.log.append(
                f'HOUSTON MISSION CONTROL: Incident update — {self.name}. '
                f'{self.definition}'
            )
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
            elec.consumeResources(loss)
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
                elec.consumeResources(drain)
                state.log.append(f'Ongoing Grid Instability: Drained {drain} kWh.')

    def check_resolution(self, state: Any) -> bool:
        """Repair the grid if aluminum and two available engineers are present."""
        alum = state.resources.get('aluminum')
        if alum is None or alum.getResources() < alum.required_amount(50.0):
            return False
        engineers = [
            w for w in state.workers
            if not getattr(w, 'retired', False)
            and w.getHealth() > 0
            and _can_fill_role(w, 'Engineer')
            and w.isAvailable()
        ]
        if len(engineers) < 2:
            return False
        alum.consumeResources(50.0)
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
        if (
            plastic.getResources() < plastic.required_amount(10.0)
            or water.getResources() < water.required_amount(15.0)
        ):
            return False
        doctors = [
            w for w in state.workers
            if not getattr(w, 'retired', False)
            and w.getHealth() > 0
            and _can_fill_role(w, 'Doctor')
            and w.isAvailable()
        ]
        if not doctors:
            return False
        plastic.consumeResources(10.0)
        water.consumeResources(15.0)
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
            target.health = max(0.0, target.health - 35.0)
            if target.health <= 0:
                target.turn_off()
            state.log.append(f'Meteor Strike: {target.name} took heavy structural damage.')
        o2 = state.resources.get('oxigen')
        if o2 is not None:
            loss = round(min(40.0, o2.getResources() * 0.25), 1)
            o2.consumeResources(loss)
            state.log.append(f'Hull Breach Decompression: Lost {loss} kg oxigen.')

    def apply_ongoing_penalty(self, state: Any) -> None:
        """Increase the oxygen leak each turn until the hull is repaired."""
        self.turns_active += 1
        o2 = state.resources.get('oxigen')
        if o2 is not None:
            leak = round(min(8.0 * self.turns_active, o2.getResources()), 1)
            if leak > 0:
                o2.consumeResources(leak)
                state.log.append(f'Ongoing Hull Leak: Venting {leak} kg oxigen.')

    def check_resolution(self, state: Any) -> bool:
        """Patch the breach using steel, dirt, a geologist, and an engineer."""
        steel = state.resources.get('steel')
        dirt = state.resources.get('dirt')
        if steel is None or dirt is None:
            return False
        if (
            steel.getResources() < steel.required_amount(80.0)
            or dirt.getResources() < dirt.required_amount(80.0)
        ):
            return False
        geologists = [
            w for w in state.workers
            if not getattr(w, 'retired', False)
            and w.getHealth() > 0
            and _can_fill_role(w, 'Geologist')
            and w.isAvailable()
        ]
        engineers = [
            w for w in state.workers
            if not getattr(w, 'retired', False)
            and w.getHealth() > 0
            and _can_fill_role(w, 'Engineer')
            and w.isAvailable()
        ]
        geo = geologists[0] if geologists else None
        eng = next((worker for worker in engineers if worker is not geo), None)
        if geo is None or eng is None:
            return False
        steel.consumeResources(80.0)
        dirt.consumeResources(80.0)
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


class EnvironmentalIncident(Incident):
    """Resource-driven incident shared by location-specific hazards."""

    resource_name = "electricity"
    initial_loss = 50.0
    ongoing_loss = 10.0
    repair_resource = "steel"
    repair_amount = 10.0
    repair_profession = "Engineer"
    crew_damage = 0.0

    def apply_initial_effect(self, state: Any) -> None:
        inventory = state.resources.get(self.resource_name)
        if inventory is not None:
            loss = min(self.initial_loss, inventory.getResources())
            inventory.consumeResources(loss)
        if self.crew_damage:
            self._damage_crew(state, self.crew_damage)

    def apply_ongoing_penalty(self, state: Any) -> None:
        self.turns_active += 1
        inventory = state.resources.get(self.resource_name)
        if inventory is not None:
            loss = min(self.ongoing_loss * self.turns_active, inventory.getResources())
            inventory.consumeResources(loss)
        if self.crew_damage:
            self._damage_crew(state, self.crew_damage / 2.0)

    def _damage_crew(self, state: Any, amount: float) -> None:
        affected = [
            worker for worker in state.workers
            if not getattr(worker, "is_robot", False)
            and not getattr(worker, "retired", False)
            and worker.getHealth() > 0
        ]
        for worker in affected:
            if not worker.takeDamage(amount):
                worker.health = 0.0
                worker.Available = False

    def check_resolution(self, state: Any) -> bool:
        material = state.resources.get(self.repair_resource)
        if (
            material is None
            or material.getResources() < material.required_amount(self.repair_amount)
        ):
            return False
        workers = [
            worker for worker in state.workers
            if not getattr(worker, "retired", False)
            and worker.getHealth() > 0
            and _can_fill_role(worker, self.repair_profession)
            and worker.isAvailable()
        ]
        if not workers:
            return False
        material.consumeResources(self.repair_amount)
        worker = workers[0]
        worker.SendToWork()
        worker.available_after_sol = state.sol + 1
        if not worker.takeDamage(2.0):
            worker.health = 0.0
            worker.Available = False
        self.resolved = True
        state.log.append(
            f"INCIDENT RESOLVED: {self.name} repaired using "
            f"{self.repair_amount:g} {self.repair_resource} and a "
            f"{self.repair_profession}."
        )
        return True


class SolarFlare(EnvironmentalIncident):
    eligible_environments = frozenset({"orbit", "moon", "mars", "deep_space"})
    blocks_communications = True
    resource_name = "electricity"
    initial_loss = 100.0
    ongoing_loss = 20.0
    repair_resource = "glass"
    repair_amount = 10.0
    repair_profession = "Pilot"

    def __init__(self):
        super().__init__(
            "Solar Flare",
            "Charged particles disrupt exposed power systems and block communications; wait at least three Sols for the flare to pass.",
            2,
        )

    def check_resolution(self, state: Any) -> bool:
        """Solar activity subsides only after three full affected turns."""
        return self.turns_active >= 3


class MartianDustStorm(EnvironmentalIncident):
    eligible_environments = frozenset({"mars"})
    resource_name = "electricity"
    initial_loss = 80.0
    ongoing_loss = 18.0
    repair_resource = "aluminum"
    repair_amount = 15.0

    def __init__(self):
        super().__init__(
            "Martian Dust Storm",
            "Dust obscures solar arrays and drains power until an Engineer clears the panels.",
            2,
        )


class RadiationStorm(EnvironmentalIncident):
    eligible_environments = frozenset({"moon", "mars", "deep_space"})
    resource_name = "oxigen"
    initial_loss = 15.0
    ongoing_loss = 3.0
    repair_resource = "plastic"
    repair_amount = 15.0
    repair_profession = "Doctor"
    crew_damage = 8.0

    def __init__(self):
        super().__init__(
            "Radiation Storm",
            "Radiation exposure strains crew and shielding reserves; a Doctor can patch 15 plastic shielding.",
            3,
        )


class ThermalControlFailure(EnvironmentalIncident):
    eligible_environments = frozenset({"moon", "mars", "deep_space"})
    resource_name = "water"
    initial_loss = 60.0
    ongoing_loss = 12.0
    repair_resource = "steel"
    repair_amount = 15.0

    def __init__(self):
        super().__init__(
            "Thermal Control Failure",
            "A cooling-loop fault wastes water and threatens habitat temperature.",
            3,
        )


class LunarQuake(EnvironmentalIncident):
    eligible_environments = frozenset({"moon"})
    resource_name = "dirt"
    initial_loss = 50.0
    ongoing_loss = 8.0
    repair_resource = "steel"
    repair_amount = 20.0
    repair_profession = "Geologist"

    def __init__(self):
        super().__init__(
            "Lunar Regolith Quake",
            "A moonquake shifts regolith around the habitat; a Geologist can stabilize the foundation.",
            3,
        )


class CommunicationsBlackout(EnvironmentalIncident):
    eligible_environments = frozenset({"orbit", "moon", "mars", "deep_space"})
    blocks_communications = True
    resource_name = "electricity"
    initial_loss = 30.0
    ongoing_loss = 8.0
    repair_resource = "glass"
    repair_amount = 8.0
    repair_profession = "Pilot"

    def __init__(self):
        super().__init__(
            "Communications Blackout",
            "Antenna damage interrupts research telemetry until a Pilot repairs the array.",
            1,
        )


class BioContamination(EnvironmentalIncident):
    eligible_environments = frozenset({"orbit", "moon", "mars", "deep_space"})
    resource_name = "food"
    initial_loss = 8000.0
    ongoing_loss = 2000.0
    repair_resource = "plastic"
    repair_amount = 10.0
    repair_profession = "Biologist"

    def __init__(self):
        super().__init__(
            "Bio-Loop Contamination",
            "Contamination spoils stored food until a Biologist seals the affected loop.",
            2,
        )


class MartianPerchlorateDust(EnvironmentalIncident):
    eligible_environments = frozenset({"mars"})
    resource_name = "food"
    initial_loss = 3000.0
    ongoing_loss = 750.0
    repair_resource = "water"
    repair_amount = 20.0
    repair_profession = "Biologist"

    def __init__(self):
        super().__init__(
            "Perchlorate Dust Intrusion",
            "Reactive Martian dust contaminated crop filters; a Biologist can flush them with 20 water.",
            2,
        )


class LunarNightColdSnap(EnvironmentalIncident):
    eligible_environments = frozenset({"moon"})
    resource_name = "electricity"
    initial_loss = 90.0
    ongoing_loss = 22.0
    repair_resource = "aluminum"
    repair_amount = 20.0
    repair_profession = "Engineer"

    def __init__(self):
        super().__init__(
            "Lunar Night Cold Snap",
            "A long polar shadow overwhelms habitat heaters; an Engineer can reinforce the thermal array with 20 aluminum.",
            3,
        )


class OrbitalDebrisStrike(EnvironmentalIncident):
    eligible_environments = frozenset({"orbit"})
    resource_name = "oxigen"
    initial_loss = 20.0
    ongoing_loss = 5.0
    repair_resource = "steel"
    repair_amount = 15.0
    repair_profession = "Pilot"

    def __init__(self):
        super().__init__(
            "Orbital Debris Strike",
            "High-velocity debris damaged the station's outer seal; a Pilot can secure it with 15 steel.",
            3,
        )


class DeepSpaceRadiatorFailure(EnvironmentalIncident):
    eligible_environments = frozenset({"deep_space"})
    resource_name = "water"
    initial_loss = 50.0
    ongoing_loss = 15.0
    repair_resource = "plastic"
    repair_amount = 20.0
    repair_profession = "Engineer"

    def __init__(self):
        super().__init__(
            "Deep-Space Radiator Failure",
            "A radiator panel froze open during transit, wasting coolant until an Engineer patches it with 20 plastic.",
            3,
        )


class HazardManager:
    """Calculate colony hazard risk and manage active incident lifecycles."""

    DAILY_CHANCE_PER_HAZARD = 0.01
    DAILY_CHANCE_INCREASE_PER_SOL = 0.00025
    DAILY_CHANCE_CAP = 0.03

    def __init__(self):
        """Set up the incident list, available incident types, and risk score."""
        self.active_incidents: List[Incident] = []
        self.incident_pool = [
            PowerGridFailure,
            AmmoniaLeak,
            MeteorStrike,
            SolarFlare,
            MartianDustStorm,
            RadiationStorm,
            ThermalControlFailure,
            LunarQuake,
            CommunicationsBlackout,
            BioContamination,
            MartianPerchlorateDust,
            LunarNightColdSnap,
            OrbitalDebrisStrike,
            DeepSpaceRadiatorFailure,
        ]
        self.last_risk_score: float = 0.0

    def compute_risk_probability(self, state: Any) -> float:
        """Return the chance of at least one independent daily hazard."""
        eligible_count = sum(
            state.space_key in incident_type.eligible_environments
            for incident_type in self.incident_pool
        )
        per_hazard = self.chance_per_hazard(state)
        total_prob = 1.0 - (1.0 - per_hazard) ** eligible_count
        self.last_risk_score = round(total_prob, 3)
        return total_prob

    def chance_per_hazard(self, state: Any) -> float:
        return min(
            self.DAILY_CHANCE_CAP,
            self.DAILY_CHANCE_PER_HAZARD
            + max(0, int(state.sol) - 1) * self.DAILY_CHANCE_INCREASE_PER_SOL,
        )

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
                state.space_key in incident_type.eligible_environments
                and
                incident_type not in active_types
                and random.random() < self.chance_per_hazard(state)
            ):
                new_crisis = incident_type()
                self.active_incidents.append(new_crisis)
                active_types.add(incident_type)
                new_crisis.trigger(state)
