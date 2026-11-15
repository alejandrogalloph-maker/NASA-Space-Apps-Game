import random
from typing import Any, List


class Incident:
    def __init__(self, name: str, description: str, severity: int):
        self.name = name
        self.description = description
        self.severity = severity  # 1 (minor) to 3 (critical)
        self.resolved = False

    def trigger(self, state: Any) -> None:
        state.log.append(f'CRITICAL INCIDENT [{self.severity}]: {self.name} - {self.description}')
        self._apply_initial_effect(state)

    def _apply_initial_effect(self, state: Any) -> None:
        pass

    def check_resolution(self, state: Any) -> bool:
        return True


class PowerGridFailure(Incident):
    def __init__(self):
        super().__init__('Grid Overload', 'Batteries venting! Need 50 aluminum and 2 Engineers to patch.', 2)

    def _apply_initial_effect(self, state: Any) -> None:
        res = state.resources.get('electricity')
        if res:
            loss = min(150.0, res.getResources())
            res.SubtractResources(loss)
            state.log.append(f'Grid Failure: Lost {loss:.1f} kWh of stored power.')
        for bld in state.buildings:
            if getattr(bld, 'type_of_building', '') == 'Power':
                bld.is_on = False

    def check_resolution(self, state: Any) -> bool:
        from actions import get_resource, spend_resource
        if get_resource(state, 'aluminum') >= 50.0:
            engineers = [w for w in state.workers if getattr(w, 'job', None) and w.job.name == 'Engineer' and w.isAvailable()]
            if len(engineers) >= 2:
                spend_resource(state, 'aluminum', 50.0)
                for eng in engineers[:2]:
                    eng.SendToWork()
                    eng.takeDamage(5.0)
                self.resolved = True
                state.log.append('INCIDENT RESOLVED: Grid patched. Power buildings can be turned back On.')
                return True
        return False


class AmmoniaLeak(Incident):
    def __init__(self):
        super().__init__('Ammonia Leak', 'Toxic leak in life support! Need 10 plastic, 15 water, and a Doctor on standby.', 3)

    def _apply_initial_effect(self, state: Any) -> None:
        active = [w for w in state.workers if not getattr(w, 'retired', False) and w.getHealth() > 0]
        for w in active:
            w.takeDamage(12.0)
        state.log.append('Ammonia Leak: All crew took 12 toxicity damage.')

    def check_resolution(self, state: Any) -> bool:
        from actions import get_resource, spend_resource
        if get_resource(state, 'plastic') >= 10.0 and get_resource(state, 'water') >= 15.0:
            doctors = [w for w in state.workers if getattr(w, 'job', None) and w.job.name == 'Doctor' and w.isAvailable()]
            if doctors:
                spend_resource(state, 'plastic', 10.0)
                spend_resource(state, 'water', 15.0)
                doc = doctors[0]
                doc.SendToWork()
                doc.takeDamage(4.0)
                self.resolved = True
                state.log.append('INCIDENT RESOLVED: Leak sealed and crew treated.')
                return True
        return False


class MeteorStrike(Incident):
    def __init__(self):
        super().__init__('Meteor Strike', 'Direct hit on base! Structural breach requires 100 steel and 100 dirt to plug.', 3)

    def _apply_initial_effect(self, state: Any) -> None:
        if state.buildings:
            target = random.choice(state.buildings)
            target.safety_rating = max(0.1, target.safety_rating - 0.40)
            state.log.append(f'Meteor Strike: {target.name} heavily damaged (Safety down 40%).')
        res = state.resources.get('oxigen')
        if res:
            loss = min(50.0, res.getResources())
            res.SubtractResources(loss)
            state.log.append(f'Decompression: Lost {loss:.1f} kg O2.')

    def check_resolution(self, state: Any) -> bool:
        from actions import get_resource, spend_resource
        if get_resource(state, 'steel') >= 100.0 and get_resource(state, 'dirt') >= 100.0:
            geologists = [w for w in state.workers if getattr(w, 'job', None) and w.job.name == 'Geologist' and w.isAvailable()]
            engineers = [w for w in state.workers if getattr(w, 'job', None) and w.job.name == 'Engineer' and w.isAvailable()]
            if geologists and engineers:
                spend_resource(state, 'steel', 100.0)
                spend_resource(state, 'dirt', 100.0)
                geo, eng = geologists[0], engineers[0]
                geo.SendToWork()
                eng.SendToWork()
                geo.takeDamage(8.0)
                eng.takeDamage(8.0)
                self.resolved = True
                state.log.append('INCIDENT RESOLVED: Breach sealed. Remember to repair the damaged building.')
                return True
        return False


class HazardManager:
    def __init__(self):
        self.active_incidents: List[Incident] = []
        self.incident_pool = [PowerGridFailure, AmmoniaLeak, MeteorStrike]

    def process_turn(self, state: Any) -> None:
        for inc in list(self.active_incidents):
            if inc.check_resolution(state):
                self.active_incidents.remove(inc)
            else:
                state.log.append(f'ONGOING CRISIS: {inc.name} unresolved. {inc.description}')

        if not self.active_incidents and random.random() < 0.10:
            new_crisis = random.choice(self.incident_pool)()
            self.active_incidents.append(new_crisis)
            new_crisis.trigger(state)
