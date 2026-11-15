import random
import time
from enum import Enum


class Profession(Enum):
    Unassigned = 0
    Biologist = 1
    Doctor = 2
    Engineer = 3
    Pilot = 4
    Geologist = 5


class Worker:
    TotalCount: int = 0
    AvailableCount: int = 0

    def __init__(self, age: int):
        self.age: int = age          # in days
        self.health: float = 100.0   # in percentage
        self.Available: bool = True
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

    def isAvailable(self) -> bool:
        return self.Available

    def getSkills(self) -> list[float]:
        return self.skills

    def getDebuffs(self) -> list[float]:
        return self.debuffs

    def getType(self) -> Profession:
        return self.job

    def __del__(self):
        try:
            Worker.TotalCount -= 1
            if self.Available:
                Worker.AvailableCount -= 1
        except Exception:
            pass

    def SendToWork(self) -> bool:
        if self.isAvailable():
            self.Available = False
            Worker.AvailableCount -= 1
            return True
        return False

    def SendToRest(self) -> bool:
        if not self.isAvailable():
            self.Available = True
            Worker.AvailableCount += 1
            return True
        H = random.random()
        if self.health + H < 120.0:
            self.health += H
        return False

    def SendToHospital(self) -> None:
        if self.isAvailable():
            self.Available = False
            Worker.AvailableCount -= 1
        self.health += random.random() * 10.0
        if self.health > 250.0:
            self.health = 250.0

    def SendToStudy(self) -> None:
        if self.isAvailable():
            self.Available = False
            Worker.AvailableCount -= 1
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
        names = [
            "Samuel", "Bruce", "Hunter", "Tonya", "Darrick", "Kathrine",
            "Howard", "Hong", "Robinson", "Cathryn", "Daniela", "Alex",
            "Sue", "Stephonie", "Rob", "Clair", "Carroll", "Jesse", "Sophia",
            "Riley",
        ]
        return random.choice(names)

    def Retire(self) -> None:
        if self.isAvailable():
            Worker.AvailableCount -= 1
        self.Available = False

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
        else:
            self.job = Profession.Unassigned

    def resetRandomSeed(self) -> None:
        random.seed(time.time())

    def takeDamage(self, i: float) -> bool:
        H = self.getHealth() - i
        if H <= 0:
            return False
        else:
            self.health = H
            return True
