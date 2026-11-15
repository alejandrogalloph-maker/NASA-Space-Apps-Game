"""Building types, their local resource storage, and colony logistics."""

import Resource_Class as resource_inventory
from typing import Protocol


class ProfessionLike(Protocol):
    """The profession name exposed by a worker's profession enum."""

    name: str


class BuildingWorker(Protocol):
    """Worker operations that buildings need for staffing and wages."""

    def getType(self) -> ProfessionLike: ...

    def getWage(self) -> int | float: ...

    def setProfession(self, profession: ProfessionLike) -> None: ...

    def isAvailable(self) -> bool: ...

    def SendToWork(self) -> bool: ...

    def SendToRest(self) -> bool: ...


class building:
    """Common state, staffing limits, and operating costs for a building."""

    # Subclasses set these values to define their own fixed costs and capacity.
    maintenance_cost: int | float = 0
    production_cost: int | float = 0
    worker_cost: int | float = 0
    max_worker_capacity: int = 0
    # Role name maps to the minimum and maximum workers of that profession.
    required_professions: dict[str, tuple[int, int]] = {}
    # Physical volume in cubic meters; subclasses can override the default.
    volume: int | float = 100

    def __init__(
        self,
        name: str,
        safety_rating: int | float = 0,
        number_of_workers: int = 0,
    ):
        """Create a building and copy its type's fixed costs onto the instance."""
        building_type = type(self)
        # Reject invalid type-level costs before creating a usable building.
        if min(
            building_type.maintenance_cost,
            building_type.production_cost,
            building_type.worker_cost,
        ) < 0:
            raise ValueError("Building costs must be non-negative")
        if number_of_workers != 0:
            raise ValueError(
                "Assign Worker objects with assign_worker() instead of setting "
                "number_of_workers"
            )

        self.name = name
        self.maintenance_cost = building_type.maintenance_cost
        self.production_cost = building_type.production_cost
        self.worker_cost = building_type.worker_cost
        self.safety_rating = safety_rating
        self.workers: list[BuildingWorker] = []
        # Buildings begin operational; turning one off does not clear its storage.
        self.is_on = True

    @property
    def number_of_workers(self) -> int:
        """Return the number of actual Worker objects assigned to this building."""
        return len(self.workers)

    def _profession_counts(self) -> dict[str, int]:
        """Count assigned workers by profession name."""
        counts: dict[str, int] = {}
        for worker in self.workers:
            profession = worker.getType().name
            counts[profession] = counts.get(profession, 0) + 1
        return counts

    def assign_worker(self, worker: BuildingWorker) -> None:
        """Assign an available worker if their profession is permitted and in capacity."""
        profession = worker.getType().name
        if profession not in type(self).required_professions:
            raise ValueError(
                f"{profession} workers cannot work in {type(self).__name__}"
            )
        if worker in self.workers:
            raise ValueError("Worker is already assigned to this building")
        if not worker.isAvailable():
            raise ValueError("Worker must be available before assignment")
        if self.number_of_workers >= type(self).max_worker_capacity:
            raise ValueError(
                f"{type(self).__name__} capacity is "
                f"{type(self).max_worker_capacity} workers"
            )

        _, maximum = type(self).required_professions[profession]
        current_count = self._profession_counts().get(profession, 0)
        if current_count >= maximum:
            raise ValueError(
                f"{type(self).__name__} allows at most {maximum} "
                f"{profession} worker(s)"
            )
        if not worker.SendToWork():
            raise ValueError("Worker could not be assigned")
        self.workers.append(worker)

    def remove_worker(self, worker: BuildingWorker) -> None:
        """Remove an assigned worker and return them to the available workforce."""
        if worker not in self.workers:
            raise ValueError("Worker is not assigned to this building")
        self.workers.remove(worker)
        worker.SendToRest()

    def has_required_staff(self) -> bool:
        """Check that minimum staffing for every required profession is met."""
        counts = self._profession_counts()
        return all(
            counts.get(profession, 0) >= minimum
            for profession, (minimum, _) in type(self).required_professions.items()
        )

    def is_operational(self) -> bool:
        """A building operates only when on and all role minimums are staffed."""
        return self.is_on and self.has_required_staff()

    def get_info(self) -> str:
        """Return a readable summary of costs, staffing, volume, and state."""
        worker_cost = sum(worker.getWage() for worker in self.workers)
        role_counts = self._profession_counts()
        staffing_info = ", ".join(
            f"{profession}: {role_counts.get(profession, 0)}/{minimum}-{maximum}"
            for profession, (minimum, maximum) in type(self).required_professions.items()
        )
        return (
            f"Building Name: {self.name}, "
            f"Maintenance Cost: {self.maintenance_cost}, "
            f"Production Cost: {self.production_cost}, "
            f"Worker Cost: {self.worker_cost * self.number_of_workers + worker_cost}, "
            f"Safety Rating: {self.safety_rating}, "
            f"Number of Workers: {self.number_of_workers}/"
            f"{type(self).max_worker_capacity}, "
            f"Staffing: {{{staffing_info}}}, "
            f"Volume: {self.volume} m^3, "
            f"State: {'On' if self.is_on else 'Off'}, "
            f"Operational: {self.is_operational()}"
        )

    def calculate_total_cost(self) -> int | float:
        """Add fixed maintenance/production costs and cost per assigned worker."""
        return (
            self.maintenance_cost
            + self.production_cost
            + self.worker_cost * self.number_of_workers
            + sum(worker.getWage() for worker in self.workers)
        )

    def turn_on(self) -> None:
        """Enable the building's operational behavior."""
        self.is_on = True

    def turn_off(self) -> None:
        """Disable operational behavior without discarding stored resources."""
        self.is_on = False


class ResourceBuilding(building):
    """Building that produces one resource into its own local storage."""

    resource_attribute: str
    production_rate: int | float = 1
    # Each produced resource has its own bounded local inventory.
    storage_capacity: int | float = 1000

    def __init__(
        self,
        name: str,
        safety_rating: int | float = 0,
        number_of_workers: int = 0,
    ):
        """Set up local storage for the resource produced by this building type."""
        super().__init__(name, safety_rating, number_of_workers)
        self.storage: dict[str, resource_inventory.resources] = {}
        self._get_storage(self.resource_attribute)

    def _get_storage(self, attribute: str) -> resource_inventory.resources:
        """Get or lazily create storage for a resource, using the type's capacity."""
        if attribute not in self.storage:
            self.storage[attribute] = resource_inventory.resources(
                max_val=type(self).storage_capacity
            )
        return self.storage[attribute]

    def get_info(self) -> str:
        """Include local inventory levels in the common building summary."""
        storage_info = ", ".join(
            f"{name}: {inventory.getResources()}/{inventory.getMaxResources()}"
            for name, inventory in self.storage.items()
        )
        return super().get_info() + f", Local Storage: {{{storage_info}}}"

    def produce(self, amount: int | float | None = None) -> int | float:
        """Produce up to the requested amount; return the amount storage accepted."""
        quantity = self.production_rate if amount is None else amount
        if quantity < 0:
            raise ValueError("Production amount must be non-negative")
        if not self.is_operational():
            return 0

        storage = self._get_storage(self.resource_attribute)
        # Report actual accepted production so a full store does not overstate output.
        previous_amount = storage.getResources()
        storage.addResources(quantity)
        return storage.getResources() - previous_amount


class WaterExtractor(ResourceBuilding):
    """Extracts water into local storage."""
    resource_attribute = "water"
    maintenance_cost = 8
    production_cost = 450
    worker_cost = 3
    max_worker_capacity = 5
    required_professions = {"Geologist": (1, 5)}


class OxygenGenerator(ResourceBuilding):
    """Generates oxygen into local storage."""
    resource_attribute = "oxigen"
    maintenance_cost = 6
    production_cost = 400
    worker_cost = 3
    max_worker_capacity = 4
    required_professions = {"Engineer": (1, 4)}


class CarbonDioxideGenerator(ResourceBuilding):
    """Generates carbon dioxide into local storage."""
    resource_attribute = "CO2"
    maintenance_cost = 5
    production_cost = 350
    worker_cost = 3
    max_worker_capacity = 3
    required_professions = {"Engineer": (1, 3)}


class NitrogenGenerator(ResourceBuilding):
    """Generates nitrogen into local storage."""
    resource_attribute = "Nitrogen"
    maintenance_cost = 7
    production_cost = 500
    worker_cost = 3
    max_worker_capacity = 4
    required_professions = {"Geologist": (1, 4)}


class HydrogenGenerator(ResourceBuilding):
    """Generates hydrogen into local storage."""
    resource_attribute = "Hydrogen"
    maintenance_cost = 9
    production_cost = 650
    worker_cost = 4
    max_worker_capacity = 5
    required_professions = {"Engineer": (1, 5)}


class FoodFactory(ResourceBuilding):
    """Produces food into local storage."""
    resource_attribute = "food"
    maintenance_cost = 12
    production_cost = 800
    worker_cost = 4
    max_worker_capacity = 8
    required_professions = {"Biologist": (1, 8)}


class PowerPlant(ResourceBuilding):
    """Produces electricity into local storage."""
    resource_attribute = "electricity"
    maintenance_cost = 15
    production_cost = 1000
    worker_cost = 5
    max_worker_capacity = 8
    required_professions = {"Engineer": (1, 8)}


class FuelRefinery(ResourceBuilding):
    """Produces fuel into local storage."""
    resource_attribute = "fuel"
    maintenance_cost = 14
    production_cost = 900
    worker_cost = 5
    max_worker_capacity = 8
    required_professions = {"Engineer": (1, 8)}


class AluminumMine(ResourceBuilding):
    """Produces aluminum into local storage."""
    resource_attribute = "aluminum"
    maintenance_cost = 12
    production_cost = 750
    worker_cost = 4
    max_worker_capacity = 8
    required_professions = {"Geologist": (1, 8)}


class SteelMill(ResourceBuilding):
    """Produces steel into local storage."""
    resource_attribute = "steel"
    maintenance_cost = 16
    production_cost = 1000
    worker_cost = 5
    max_worker_capacity = 10
    required_professions = {"Engineer": (1, 10)}


class SoilProcessor(ResourceBuilding):
    """Produces processed dirt into local storage."""
    resource_attribute = "dirt"
    maintenance_cost = 8
    production_cost = 550
    worker_cost = 3
    max_worker_capacity = 6
    required_professions = {"Geologist": (1, 6)}


class PlasticFactory(ResourceBuilding):
    """Produces plastic into local storage."""
    resource_attribute = "plastic"
    maintenance_cost = 13
    production_cost = 900
    worker_cost = 5
    max_worker_capacity = 8
    required_professions = {"Engineer": (1, 8)}


class GlassFactory(ResourceBuilding):
    """Produces glass into local storage."""
    resource_attribute = "glass"
    maintenance_cost = 10
    production_cost = 750
    worker_cost = 4
    max_worker_capacity = 6
    required_professions = {"Engineer": (1, 6)}


class CarFactory(ResourceBuilding):
    """Produces cars into local storage."""
    resource_attribute = "cars"
    maintenance_cost = 20
    production_cost = 1500
    worker_cost = 6
    max_worker_capacity = 10
    required_professions = {"Engineer": (1, 10)}


class TruckFactory(ResourceBuilding):
    """Produces trucks into local storage."""
    resource_attribute = "trucks"
    maintenance_cost = 24
    production_cost = 1800
    worker_cost = 6
    max_worker_capacity = 12
    required_professions = {"Engineer": (1, 8), "Pilot": (0, 4)}


class RoverFactory(ResourceBuilding):
    """Produces rovers into local storage."""
    resource_attribute = "rovers"
    maintenance_cost = 28
    production_cost = 2200
    worker_cost = 7
    max_worker_capacity = 10
    required_professions = {"Engineer": (1, 8), "Pilot": (0, 2)}


class SatelliteFactory(ResourceBuilding):
    """Produces satellites into local storage."""
    resource_attribute = "satellites"
    maintenance_cost = 35
    production_cost = 3000
    worker_cost = 8
    max_worker_capacity = 12
    required_professions = {"Engineer": (1, 10), "Pilot": (0, 2)}


class RocketFactory(ResourceBuilding):
    """Produces rockets into local storage."""
    resource_attribute = "rockets"
    maintenance_cost = 60
    production_cost = 6000
    worker_cost = 12
    max_worker_capacity = 20
    required_professions = {"Engineer": (2, 18), "Pilot": (0, 2)}


class DroneFactory(ResourceBuilding):
    """Produces drones into local storage."""
    resource_attribute = "drones"
    maintenance_cost = 18
    production_cost = 1300
    worker_cost = 5
    max_worker_capacity = 10
    required_professions = {"Engineer": (1, 8), "Pilot": (0, 2)}


class Farm(ResourceBuilding):
    """Produces seeds or crops for one selected crop variety."""

    # Each crop maps to its seed resource name and its harvested resource name.
    CROP_RESOURCES = {
        "lettuce": ("seed_Lettuce", "lettuce"),
        "wheat": ("seed_Wheat", "wheat"),
        "flax": ("seed_Flax", "flax"),
        "sunflower": ("seed_sunflower", "sunflower"),
    }

    def __init__(
        self,
        name: str,
        crop: str = "lettuce",
        product_type: str = "crop",
        safety_rating: int | float = 0,
        number_of_workers: int = 0,
    ):
        """Create a farm after validating its crop and chosen product."""
        normalized_crop = crop.lower()
        if normalized_crop not in self.CROP_RESOURCES:
            raise ValueError(f"Unsupported crop: {crop}")
        if product_type not in ("seed", "crop"):
            raise ValueError("Product type must be 'seed' or 'crop'")
        self.crop = normalized_crop
        self.product_type = product_type
        self._update_resource_attribute()
        super().__init__(
            name,
            safety_rating,
            number_of_workers,
        )

    def set_crop(self, crop: str) -> None:
        """Choose which supported crop this farm produces."""
        normalized_crop = crop.lower()
        if normalized_crop not in self.CROP_RESOURCES:
            raise ValueError(f"Unsupported crop: {crop}")
        self.crop = normalized_crop
        self._update_resource_attribute()

    maintenance_cost = 10
    production_cost = 650
    worker_cost = 3
    max_worker_capacity = 6
    required_professions = {"Biologist": (1, 6)}

    def set_product_type(self, product_type: str) -> None:
        """Switch production between the selected crop's seeds and harvested crop."""
        if product_type not in ("seed", "crop"):
            raise ValueError("Product type must be 'seed' or 'crop'")
        self.product_type = product_type
        self._update_resource_attribute()

    def _update_resource_attribute(self) -> None:
        """Resolve the selected crop/product to its inventory resource name."""
        if self.crop and self.product_type:
            # Keep each product in separate storage when switching farm modes.
            resource_index = 0 if self.product_type == "seed" else 1
            self.resource_attribute = self.CROP_RESOURCES[self.crop][resource_index]
            if hasattr(self, "storage"):
                self._get_storage(self.resource_attribute)


class IceMinor(WaterExtractor):
    """Water extractor representing an industrial ice-mining facility."""

    type_of_building = "Industrial"

    def get_info(self) -> str:
        """Append the specific facility type to the inherited building summary."""
        return super().get_info() + ", Type: IceMinor"


class Habitation(building):
    """Provides residential space and a maximum number of residents."""

    maintenance_cost = 20
    production_cost = 1200
    worker_cost = 4
    max_worker_capacity = 6
    volume = 500
    resident_capacity = 20
    required_professions = {"Doctor": (1, 6)}


class RecreationCenter(building):
    """Provides recreation facilities for the colony."""

    maintenance_cost = 12
    production_cost = 800
    worker_cost = 3
    max_worker_capacity = 6
    volume = 250
    required_professions = {"Doctor": (1, 4), "Biologist": (0, 2)}


class Canteen(building):
    """Provides shared meal facilities for the colony."""

    maintenance_cost = 15
    production_cost = 900
    worker_cost = 4
    max_worker_capacity = 8
    volume = 200
    required_professions = {"Biologist": (1, 8)}


class LogisticsBuilding(building):
    """Transfers locally stored resources into the colony-wide inventories."""

    maintenance_cost = 18
    production_cost = 1100
    worker_cost = 5
    max_worker_capacity = 8
    volume = 300
    transfer_amount: int | float = 100
    required_professions = {"Pilot": (1, 8)}

    def __init__(
        self,
        name: str,
        safety_rating: int | float = 0,
        number_of_workers: int = 0,
        transfer_amount: int | float = 100,
    ):
        """Configure a non-negative per-resource transfer limit for each turn."""
        if transfer_amount < 0:
            raise ValueError("Transfer amount must be non-negative")
        super().__init__(name, safety_rating, number_of_workers)
        self.transfer_amount = transfer_amount

    def get_info(self) -> str:
        """Include the configured per-turn resource transfer limit."""
        return (
            super().get_info()
            + f", Transfer Amount per Resource Building per Turn: "
            f"{self.transfer_amount}"
        )

    def process_turn(
        self, buildings: list[ResourceBuilding]
    ) -> dict[str, int | float]:
        """Transfer available resources, returning the accepted amount by resource."""
        transferred: dict[str, int | float] = {}
        if not self.has_required_staff():
            return transferred
        for source in buildings:
            if not isinstance(source, ResourceBuilding):
                raise TypeError("Logistics can only transfer from resource buildings")
            for resource_name, local_storage in source.storage.items():
                # Limit transfer by both the configured cap and local stock.
                requested = min(
                    self.transfer_amount,
                    local_storage.getResources(),
                )
                if requested <= 0:
                    continue

                colony_inventory = getattr(resource_inventory, resource_name)
                previous_amount = colony_inventory.getResources()
                colony_inventory.addResources(requested)
                # Remove only what global storage accepted, preserving overflow locally.
                accepted = colony_inventory.getResources() - previous_amount
                if accepted:
                    local_storage.SubtractResources(accepted)
                    transferred[resource_name] = (
                        transferred.get(resource_name, 0) + accepted
                    )
        return transferred


class ResearchBuilding(building):
    """Consumes colony resources to create globally available research points."""

    maintenance_cost = 25
    production_cost = 2000
    worker_cost = 6
    max_worker_capacity = 10
    volume = 350
    required_professions = {"Engineer": (1, 6), "Biologist": (1, 4)}

    # Default inputs required for one research point; callers can supply another recipe.
    DEFAULT_RESOURCE_COSTS = {
        "electricity": 10,
        "aluminum": 2,
        "food": 1,
    }

    def __init__(
        self,
        name: str,
        safety_rating: int | float = 0,
        number_of_workers: int = 0,
        resource_costs: dict[str, int | float] | None = None,
    ):
        """Create a lab with a configurable amount of colony resources per point."""
        super().__init__(name, safety_rating, number_of_workers)
        self.resource_costs = dict(
            self.DEFAULT_RESOURCE_COSTS if resource_costs is None else resource_costs
        )

        # Validate the recipe up front so processing cannot fail halfway through.
        for resource_name, cost in self.resource_costs.items():
            inventory = getattr(resource_inventory, resource_name, None)
            if not isinstance(inventory, resource_inventory.resources):
                raise ValueError(f"Unknown colony resource: {resource_name}")
            if resource_name == "research":
                raise ValueError("Research points cannot be used as research inputs")
            if cost < 0:
                raise ValueError("Resource costs must be non-negative")

    def get_info(self) -> str:
        """Include the research recipe in the building summary."""
        return super().get_info() + f", Resource Cost per Point: {self.resource_costs}"

    def produce_research(self, amount: int | float = 1) -> int | float:
        """Spend the full recipe and add research points, or leave stocks unchanged."""
        if amount < 0:
            raise ValueError("Research amount must be non-negative")
        if not self.is_operational() or amount == 0:
            return 0

        research_inventory = resource_inventory.research
        if research_inventory.getMaxResources() - research_inventory.getResources() < amount:
            return 0

        # Check every input before subtracting any, so an incomplete recipe costs nothing.
        required_resources = {
            resource_name: cost * amount
            for resource_name, cost in self.resource_costs.items()
        }
        for resource_name, required in required_resources.items():
            inventory = getattr(resource_inventory, resource_name)
            if inventory.getResources() < required:
                return 0

        for resource_name, required in required_resources.items():
            getattr(resource_inventory, resource_name).SubtractResources(required)

        research_inventory.addResources(amount)
        return amount


class University(building):
    """Trains workers into professions and produces a modest amount of research."""

    maintenance_cost = 30
    production_cost = 1800
    worker_cost = 7
    max_worker_capacity = 8
    volume = 450
    required_professions = {"Doctor": (1, 3), "Biologist": (1, 5)}

    RESEARCH_RESOURCE_COSTS = {"electricity": 10, "food": 2}
    RESEARCH_OUTPUT_PER_TURN = 1
    TRAINING_RESEARCH_COST = 5
    TRAINING_RESOURCE_COSTS = {"electricity": 20, "food": 5}
    TRAINABLE_PROFESSIONS = {
        "Biologist",
        "Doctor",
        "Engineer",
        "Pilot",
        "Geologist",
    }

    def __init__(
        self,
        name: str,
        safety_rating: int | float = 0,
        number_of_workers: int = 0,
    ):
        """Create a university with configurable class-level research recipes."""
        super().__init__(name, safety_rating, number_of_workers)

    @staticmethod
    def _consume_resources(resource_costs: dict[str, int | float]) -> bool:
        """Consume a recipe only when every required colony inventory can pay it."""
        inventories = {
            resource_name: getattr(resource_inventory, resource_name)
            for resource_name in resource_costs
        }
        if any(
            inventory.getResources() < amount
            for resource_name, inventory in inventories.items()
            for amount in (resource_costs[resource_name],)
        ):
            return False
        for resource_name, amount in resource_costs.items():
            inventories[resource_name].SubtractResources(amount)
        return True

    def produce_research(self) -> int | float:
        """Spend the research recipe and add one point when the university can operate."""
        if not self.is_operational():
            return 0
        if not self._consume_resources(self.RESEARCH_RESOURCE_COSTS):
            return 0
        resource_inventory.research.addResources(self.RESEARCH_OUTPUT_PER_TURN)
        return self.RESEARCH_OUTPUT_PER_TURN

    def train_worker(self, worker: BuildingWorker, profession_name: str) -> bool:
        """Train an available worker in a profession, charging research and resources."""
        if not self.is_operational():
            return False
        if not worker.isAvailable():
            raise ValueError("Worker must be available to receive training")
        if profession_name not in self.TRAINABLE_PROFESSIONS:
            raise ValueError(f"Unsupported profession: {profession_name}")

        profession_type = type(worker.getType())
        profession = getattr(profession_type, profession_name, None)
        if profession is None:
            raise ValueError(f"Worker does not support profession: {profession_name}")
        if resource_inventory.research.getResources() < self.TRAINING_RESEARCH_COST:
            return False
        if any(
            getattr(resource_inventory, name).getResources() < amount
            for name, amount in self.TRAINING_RESOURCE_COSTS.items()
        ):
            return False

        # Check all costs before deducting any, so failed training spends nothing.
        if not self._consume_resources(self.TRAINING_RESOURCE_COSTS):
            return False
        resource_inventory.research.SubtractResources(self.TRAINING_RESEARCH_COST)
        worker.setProfession(profession)
        return True


class MedicalBay(building):
    """Provides basic medical facilities staffed by a doctor."""

    maintenance_cost = 18
    production_cost = 1300
    worker_cost = 5
    max_worker_capacity = 8
    volume = 250
    patient_capacity = 4
    required_professions = {"Doctor": (1, 8)}


class Hospital(building):
    """Provides a larger medical facility with expanded patient capacity."""

    maintenance_cost = 35
    production_cost = 2800
    worker_cost = 8
    max_worker_capacity = 16
    volume = 600
    patient_capacity = 20
    required_professions = {"Doctor": (2, 12), "Biologist": (0, 4)}


class Graveyard(building):
    """Provides land reserved for burials."""

    maintenance_cost = 5
    production_cost = 300
    worker_cost = 1
    max_worker_capacity = 2
    volume = 1000
    burial_capacity = 100


class CommunicationsHub(building):
    """Coordinates colony communications and satellite links."""

    maintenance_cost = 15
    production_cost = 1200
    worker_cost = 5
    max_worker_capacity = 6
    volume = 250
    required_professions = {"Engineer": (1, 4), "Pilot": (0, 2)}


class SatelliteDish(building):
    """Provides an antenna for establishing a satellite communications link."""

    maintenance_cost = 8
    production_cost = 700
    worker_cost = 3
    max_worker_capacity = 3
    volume = 80
    required_professions = {"Engineer": (1, 2), "Pilot": (0, 1)}
