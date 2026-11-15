import random
import time
from enum import Enum


class Profession(Enum):
    """Jobs workers can be assigned to within the colony."""

    Doctor = 1
    Engineer = 2
    Biologist = 3
    Geologist = 4
    Pilot = 5
    Unassigned = 0


class Worker:
    """Represent a colonist, including availability, health, skills, and job."""

    # Counts are shared across all Worker instances.
    TotalCount: int = 0
    AvailableCount: int = 0

    def __init__(self, age: int):
        """Create an available, unassigned worker with randomized abilities."""
        self.age: int = age          # in days
        self.health: float = 100.0   # in percentage
        self.Available: bool = True
        self.retired: bool = False
        self.job: Profession = Profession.Unassigned
        Worker.TotalCount += 1
        Worker.AvailableCount += 1
        self.Name: str = self.GiveName()

        # Six skill and debuff categories are initialized with independent values.
        N = 6
        self.skills: list[float] = [random.random() * 100.0 for _ in range(N)]
        self.debuffs: list[float] = [random.random() * 100.0 for _ in range(N)]

    def getAge(self) -> int:
        """Return the worker's age in days."""
        return self.age

    def getHealth(self) -> float:
        """Return the worker's current health score."""
        return self.health

    def isAvailable(self) -> bool:
        """Return whether the worker can be assigned, excluding retired workers."""
        return self.Available and not self.retired

    def getSkills(self) -> list[float]:
        """Return the worker's skill values."""
        return self.skills

    def getDebuffs(self) -> list[float]:
        """Return the worker's debuff values."""
        return self.debuffs

    def getType(self) -> Profession:
        """Return the worker's currently assigned profession."""
        return self.job

    def __del__(self):
        """Update shared worker counts when this worker is destroyed."""
        try:
            Worker.TotalCount -= 1
            if self.Available:
                Worker.AvailableCount -= 1
        except Exception:
            pass

    def SendToWork(self) -> bool:
        """Mark an available worker busy and update the colony's available count."""
        if self.isAvailable():
            self.Available = False
            Worker.AvailableCount -= 1
            return True
        return False

    def SendToRest(self) -> bool:
        """Make a working worker available again, or recover slightly while resting."""
        if self.retired:
            return False
        if not self.isAvailable():
            self.Available = True
            Worker.AvailableCount += 1
            return True
        # Resting health recovery is small and randomized, with a 120-point cap.
        H = random.random()
        if self.health + H < 120.0:
            self.health += H
        return False

    def SendToHospital(self) -> None:
        """Mark the worker busy and restore a random amount of health."""
        if self.retired:
            return
        if self.isAvailable():
            self.Available = False
            Worker.AvailableCount -= 1
        # Hospital treatment adds up to 10 health, capped at 250.
        self.health += random.random() * 10.0
        if self.health > 250.0:
            self.health = 250.0

    def SendToStudy(self) -> None:
        """Mark the worker busy, improve a random skill, and reduce a random debuff."""
        if self.retired:
            return
        if self.isAvailable():
            self.Available = False
            Worker.AvailableCount -= 1
        self.modSkill(random.random() * 15.0, int(random.random() * len(self.skills)))
        self.modDebuff(random.random() * -5.0, int(random.random() * len(self.debuffs)))

    def modSkill(self, n: float, i: int) -> None:
        """Adjust one skill value, keeping it from exceeding 300."""
        if self.skills[i] + n > 300.0:
            self.skills[i] = 300.0
        else:
            self.skills[i] += n

    def modDebuff(self, n: float, i: int) -> None:
        """Adjust one debuff value, keeping it from falling below zero."""
        if self.debuffs[i] + n < 0.0:
            self.debuffs[i] = 0.0
        else:
            self.debuffs[i] += n

    def GiveName(self) -> str:
        """Choose a display name randomly from the built-in name list."""
        names = [
            "Samuel", "Bruce", "Hunter", "Tonya", "Darrick", "Kathrine",
            "Howard", "Hong", "Robinson", "Cathryn", "Daniela", "Alex",
            "Sue", "Stephonie", "Rob", "Clair", "Carroll", "Jesse", "Sophia",
            "Riley",
        ]
        return random.choice(names)

    def Retire(self) -> None:
        """Permanently remove this worker from the available workforce."""
        if self.isAvailable():
            Worker.AvailableCount -= 1
        self.Available = False
        self.retired = True

    def setType(self, N: int) -> None:
        """Set profession using the legacy numeric profession identifiers."""
        if N == 1:
            self.job = Profession.Doctor
        elif N == 2:
            self.job = Profession.Engineer
        elif N == 3:
            self.job = Profession.Biologist
        elif N == 4:
            self.job = Profession.Geologist
        elif N == 5:
            self.job = Profession.Pilot
        else:
            self.job = Profession.Unassigned

    def resetRandomSeed(self) -> None:
        """Reseed the random number generator using the current time."""
        random.seed(time.time())

    def takeDamage(self, i: float) -> bool:
        """Apply damage; return False if it would reduce health to zero or below."""
        H = self.getHealth() - i
        if H <= 0:
            return False
        else:
            self.health = H
            return True
