class resources:
    """Track a resource's current amount and maximum storage capacity."""

    def __init__(self, current: int | float = 0, max_val: int | float = 0):
        """Create an inventory, clamping its starting amount to valid limits."""
        self.max = max(0, max_val)
        self.current = max(0, min(current, self.max))

    def getResources(self):
        """Return the amount currently stored."""
        return self.current

    def getMaxResources(self):
        """Return the inventory's current storage capacity."""
        return self.max

    def addResources(self, N: int | float):
        """Add a non-negative amount without exceeding the storage capacity."""
        if N < 0:
            raise ValueError("N must be non-negative (unsigned)")
        self.current += N
        # Any amount above capacity is discarded.
        if self.current > self.max:
            self.current = self.max

    def SubtractResources(self, N: int | float) -> bool:
        """Remove an amount if available; return False without changing stock otherwise."""
        if N < 0:
            raise ValueError("N must be non-negative (unsigned)")
        if self.current - N < 0:
            return False
        else:
            self.current -= N
            return True

    def AddMax(self, N: int | float):
        """Increase the inventory's storage capacity."""
        if N < 0:
            raise ValueError("N must be non-negative (unsigned)")
        self.max += N

    def subtractMax(self, N: int | float) -> bool:
        """Reduce capacity, refusing reductions below zero and trimming excess stock."""
        if N < 0:
            raise ValueError("N must be non-negative (unsigned)")
        self.max -= N
        # Restore the previous maximum if the requested reduction was too large.
        if self.max < 0:
            self.max += N
            return False
        # Existing resources cannot exceed the new capacity.
        if self.current > self.max:
            self.current = self.max
        return True


# Colony-wide inventories used by buildings and other simulation systems.
# Capacity defaults to zero, so add capacity with AddMax before storing resources.
water = resources()
oxigen = resources()
CO2 = resources()
Nitrogen = resources()
Hydrogen = resources()
food = resources()         # Food supply, measured in kilocalories.
electricity = resources()  # Electrical energy, measured in kilowatt-hours.
fuel = resources()         # Fuel supply, measured in liters.

# Construction and manufacturing materials.
aluminum = resources()     # kg
steel = resources()        # kg
dirt = resources()         # kg
plastic = resources()      # kg
glass = resources()        # kg

# Colony vehicles and equipment.
cars = resources()
trucks = resources()
rovers = resources()
satellites = resources()
rockets = resources()
drones = resources()

# Seeds for planting and harvested crops.
seed_Lettuce = resources()
seed_Wheat = resources()
seed_Flax = resources()
seed_sunflower = resources()
lettuce = resources()
wheat = resources()
flax = resources()
sunflower = resources()
