import random
import time
from enum import Enum


class Profession(Enum):
    Doctor = 1
    Engineer = 2
    Biologist = 3
    Geologist = 4
    Pilot = 5
    Robot = 6
    Unassigned = 0


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
        self.age: int = age
        self.health: float = 100.0
        self.morale: float = 65.0
        self.is_robot: bool = False
        self.powered_on: bool = True
        self.Available: bool = True
        self.available_after_sol: int = 0
        self.retired: bool = False
        self.assigned_building = None
        self.wage: int = 10
        self.job: Profession = Profession.Unassigned
        Worker.TotalCount += 1
        Worker.AvailableCount += 1
        self.Name: str = self.GiveName()

        N = 6
        self.skills: list[float] = [random.random() * 100.0 for _ in range(N)]
        self.debuffs: list[float] = [random.random() * 100.0 for _ in range(N)]

    def getAge(self) -> int:
        return self.age

    def getHealth(self) -> float:
        return self.health

    def getWage(self) -> int | float:
        return self.wage

    def isAvailable(self) -> bool:
        return (
            self.Available
            and self.powered_on
            and not self.retired
            and self.health > 0
            and self.assigned_building is None
        )

    def getSkills(self) -> list[float]:
        return self.skills

    def getDebuffs(self) -> list[float]:
        return self.debuffs

    def getType(self) -> Profession:
        return self.job

    def setProfession(self, profession: Profession) -> None:
        if isinstance(profession, Profession):
            self.job = profession
        elif isinstance(profession, str):
            self.job = Profession[profession]
        else:
            raise ValueError('Invalid profession')

    def SendToWork(self) -> bool:
        if self.isAvailable():
            self.Available = False
            Worker.AvailableCount = max(0, Worker.AvailableCount - 1)
            return True
        return False

    def SendToRest(self) -> bool:
        if self.retired or self.health <= 0 or self.assigned_building is not None:
            return False
        self.available_after_sol = 0
        if not self.Available:
            self.Available = True
            Worker.AvailableCount += 1
            return True
        H = random.random()
        if self.health + H < 120.0:
            self.health += H
        return True

    def SendToHospital(self) -> None:
        if self.retired or self.health <= 0:
            return
        if self.Available:
            self.Available = False
            Worker.AvailableCount = max(0, Worker.AvailableCount - 1)
        self.health += random.random() * 10.0
        if self.health > 250.0:
            self.health = 250.0

    def SendToStudy(self) -> None:
        if self.retired or self.health <= 0:
            return
        if self.Available:
            self.Available = False
            Worker.AvailableCount = max(0, Worker.AvailableCount - 1)
        self.modSkill(random.random() * 15.0, int(random.random() * len(self.skills)))
        self.modDebuff(random.random() * -5.0, int(random.random() * len(self.debuffs)))

    def modSkill(self, n: float, i: int) -> None:
        if self.skills[i] + n > 300.0:
            self.skills[i] = 300.0
        else:
            self.skills[i] += n

    def modDebuff(self, n: float, i: int) -> None:
        if self.debuffs[i] + n < 0.0:
            self.debuffs[i] = 0.0
        else:
            self.debuffs[i] += n

    def GiveName(self) -> str:
        return random.choice(self.NAMES)

    def Retire(self) -> None:
        if self.assigned_building is not None:
            bld = self.assigned_building
            self.assigned_building = None
            try:
                bld.remove_worker(self)
            except Exception:
                pass
        if self.Available:
            Worker.AvailableCount = max(0, Worker.AvailableCount - 1)
        self.Available = False
        self.retired = True

    def setType(self, N: int) -> None:
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
        elif N == 6 and self.is_robot:
            self.job = Profession.Robot
        else:
            self.job = Profession.Robot if self.is_robot else Profession.Unassigned

    def resetRandomSeed(self) -> None:
        random.seed(time.time())

    def takeDamage(self, i: float) -> bool:
        if self.health <= 0:
            return False
        H = self.getHealth() - i
        if H <= 0:
            if self.assigned_building is not None:
                bld = self.assigned_building
                self.assigned_building = None
                try:
                    bld.remove_worker(self)
                except Exception:
                    pass
            if self.Available:
                Worker.AvailableCount = max(0, Worker.AvailableCount - 1)
            self.Available = False
            self.health = 0.0
            Worker.TotalCount = max(0, Worker.TotalCount - 1)
            return False
        else:
            self.health = H
            return True


class RobotWorker(Worker):
    """Worker-compatible robot that can be powered down and repaired."""

    def __init__(self, name: str):
        super().__init__(age=0)
        self.Name = name
        self.is_robot = True
        self.wage = 0
        self.job = Profession.Robot
