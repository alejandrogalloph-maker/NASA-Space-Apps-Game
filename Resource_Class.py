class resources:
    def __init__(self, current: int | float = 0, max_val: int | float = 0):
        self.max = max(0, max_val)
        self.current = max(0, min(current, self.max))

    def getResources(self):
        return self.current

    def getMaxResources(self):
        return self.max

    def addResources(self, N: int | float):
        if N < 0:
            raise ValueError("N must be non-negative (unsigned)")
        self.current = round(self.current + N, 6)
        if self.current > self.max:
            self.current = self.max

    def SubtractResources(self, N: int | float) -> bool:
        if N < 0:
            raise ValueError("N must be non-negative (unsigned)")
        if self.current - N < -1e-9:
            return False
        else:
            self.current = max(0, round(self.current - N, 6))
            return True

    def AddMax(self, N: int | float):
        if N < 0:
            raise ValueError("N must be non-negative (unsigned)")
        self.max += N

    def subtractMax(self, N: int | float) -> bool:
        if N < 0:
            raise ValueError("N must be non-negative (unsigned)")
        self.max -= N
        if self.max < 0:
            self.max += N
            return False
        if self.current > self.max:
            self.current = self.max
        return True


water = resources()
oxigen = resources()
CO2 = resources()
Nitrogen = resources()
Hydrogen = resources()
food = resources()
electricity = resources()
fuel = resources()

aluminum = resources()
steel = resources()
dirt = resources()
plastic = resources()
glass = resources()

cars = resources()
trucks = resources()
rovers = resources()
satellites = resources()
rockets = resources()
drones = resources()

seed_Lettuce = resources()
seed_Wheat = resources()
seed_Flax = resources()
seed_sunflower = resources()
lettuce = resources()
wheat = resources()
flax = resources()
sunflower = resources()

# Created here so it exists before any building or GameState uses it.
research = resources(0, 10000)
radioisotope_fuel = resources()
