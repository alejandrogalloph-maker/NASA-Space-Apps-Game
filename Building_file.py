import Resource_Class as resource_inventory


class building:
    maintenance_cost: int | float = 0
    production_cost: int | float = 0
    worker_cost: int | float = 0
    max_worker_capacity: int = 0
    volume: int | float = 100

    def __init__(
        self,
        name: str,
        safety_rating: int | float = 0,
        number_of_workers: int = 0,
    ):
        building_type = type(self)
        if min(
            building_type.maintenance_cost,
            building_type.production_cost,
            building_type.worker_cost,
        ) < 0:
            raise ValueError("Building costs must be non-negative")

        self.name = name
        self.maintenance_cost = building_type.maintenance_cost
        self.production_cost = building_type.production_cost
        self.worker_cost = building_type.worker_cost
        self.safety_rating = safety_rating
        self.number_of_workers = number_of_workers
        self.is_on = True

    @property
    def number_of_workers(self) -> int:
        return self._number_of_workers

    @number_of_workers.setter
    def number_of_workers(self, count: int) -> None:
        if not isinstance(count, int) or isinstance(count, bool):
            raise TypeError("Number of workers must be an integer")
        if count < 0:
            raise ValueError("Number of workers must be non-negative")
        if count > type(self).max_worker_capacity:
            raise ValueError(
                f"{type(self).__name__} capacity is "
                f"{type(self).max_worker_capacity} workers"
            )
        self._number_of_workers = count

    def get_info(self) -> str:
        return (
            f"Building Name: {self.name}, "
            f"Maintenance Cost: {self.maintenance_cost}, "
            f"Production Cost: {self.production_cost}, "
            f"Worker Cost: {self.worker_cost * self.number_of_workers}, "
            f"Safety Rating: {self.safety_rating}, "
            f"Number of Workers: {self.number_of_workers}/"
            f"{type(self).max_worker_capacity}, "
            f"Volume: {self.volume} m^3, "
            f"State: {'On' if self.is_on else 'Off'}"
        )

    def calculate_total_cost(self) -> int | float:
        return (
            self.maintenance_cost
            + self.production_cost
            + self.worker_cost * self.number_of_workers
        )

    def turn_on(self) -> None:
        self.is_on = True

    def turn_off(self) -> None:
        self.is_on = False


class ResourceBuilding(building):
    resource_attribute: str
    production_rate: int | float = 1
    storage_capacity: int | float = 1000

    def __init__(
        self,
        name: str,
        safety_rating: int | float = 0,
        number_of_workers: int = 0,
    ):
        super().__init__(name, safety_rating, number_of_workers)
        self.storage: dict[str, resource_inventory.resources] = {}
        self._get_storage(self.resource_attribute)

    def _get_storage(self, attribute: str) -> resource_inventory.resources:
        if attribute not in self.storage:
            self.storage[attribute] = resource_inventory.resources(
                max_val=type(self).storage_capacity
            )
        return self.storage[attribute]

    def get_info(self) -> str:
        storage_info = ", ".join(
            f"{name}: {inventory.getResources()}/{inventory.getMaxResources()}"
            for name, inventory in self.storage.items()
        )
        return super().get_info() + f", Local Storage: {{{storage_info}}}"

    def produce(self, amount: int | float | None = None) -> int | float:
        quantity = self.production_rate if amount is None else amount
        if quantity < 0:
            raise ValueError("Production amount must be non-negative")
        if not self.is_on:
            return 0

        storage = self._get_storage(self.resource_attribute)
        previous_amount = storage.getResources()
        storage.addResources(quantity)
        return storage.getResources() - previous_amount


class WaterExtractor(ResourceBuilding):
    resource_attribute = "water"
    maintenance_cost = 8
    production_cost = 450
    worker_cost = 3
    max_worker_capacity = 5


class OxygenGenerator(ResourceBuilding):
    resource_attribute = "oxigen"
    maintenance_cost = 6
    production_cost = 400
    worker_cost = 3
    max_worker_capacity = 4


class CarbonDioxideGenerator(ResourceBuilding):
    resource_attribute = "CO2"
    maintenance_cost = 5
    production_cost = 350
    worker_cost = 3
    max_worker_capacity = 3


class NitrogenGenerator(ResourceBuilding):
    resource_attribute = "Nitrogen"
    maintenance_cost = 7
    production_cost = 500
    worker_cost = 3
    max_worker_capacity = 4


class HydrogenGenerator(ResourceBuilding):
    resource_attribute = "Hydrogen"
    maintenance_cost = 9
    production_cost = 650
    worker_cost = 4
    max_worker_capacity = 5


class FoodFactory(ResourceBuilding):
    resource_attribute = "food"
    maintenance_cost = 12
    production_cost = 800
    worker_cost = 4
    max_worker_capacity = 8


class PowerPlant(ResourceBuilding):
    resource_attribute = "electricity"
    maintenance_cost = 15
    production_cost = 1000
    worker_cost = 5
    max_worker_capacity = 8


class FuelRefinery(ResourceBuilding):
    resource_attribute = "fuel"
    maintenance_cost = 14
    production_cost = 900
    worker_cost = 5
    max_worker_capacity = 8


class AluminumMine(ResourceBuilding):
    resource_attribute = "aluminum"
    maintenance_cost = 12
    production_cost = 750
    worker_cost = 4
    max_worker_capacity = 8


class SteelMill(ResourceBuilding):
    resource_attribute = "steel"
    maintenance_cost = 16
    production_cost = 1000
    worker_cost = 5
    max_worker_capacity = 10


class SoilProcessor(ResourceBuilding):
    resource_attribute = "dirt"
    maintenance_cost = 8
    production_cost = 550
    worker_cost = 3
    max_worker_capacity = 6


class PlasticFactory(ResourceBuilding):
    resource_attribute = "plastic"
    maintenance_cost = 13
    production_cost = 900
    worker_cost = 5
    max_worker_capacity = 8


class GlassFactory(ResourceBuilding):
    resource_attribute = "glass"
    maintenance_cost = 10
    production_cost = 750
    worker_cost = 4
    max_worker_capacity = 6


class CarFactory(ResourceBuilding):
    resource_attribute = "cars"
    maintenance_cost = 20
    production_cost = 1500
    worker_cost = 6
    max_worker_capacity = 10


class TruckFactory(ResourceBuilding):
    resource_attribute = "trucks"
    maintenance_cost = 24
    production_cost = 1800
    worker_cost = 6
    max_worker_capacity = 12


class RoverFactory(ResourceBuilding):
    resource_attribute = "rovers"
    maintenance_cost = 28
    production_cost = 2200
    worker_cost = 7
    max_worker_capacity = 10


class SatelliteFactory(ResourceBuilding):
    resource_attribute = "satellites"
    maintenance_cost = 35
    production_cost = 3000
    worker_cost = 8
    max_worker_capacity = 12


class RocketFactory(ResourceBuilding):
    resource_attribute = "rockets"
    maintenance_cost = 60
    production_cost = 6000
    worker_cost = 12
    max_worker_capacity = 20


class DroneFactory(ResourceBuilding):
    resource_attribute = "drones"
    maintenance_cost = 18
    production_cost = 1300
    worker_cost = 5
    max_worker_capacity = 10


class Farm(ResourceBuilding):
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
        normalized_crop = crop.lower()
        if normalized_crop not in self.CROP_RESOURCES:
            raise ValueError(f"Unsupported crop: {crop}")
        self.crop = normalized_crop
        self._update_resource_attribute()

    maintenance_cost = 10
    production_cost = 650
    worker_cost = 3
    max_worker_capacity = 6

    def set_product_type(self, product_type: str) -> None:
        if product_type not in ("seed", "crop"):
            raise ValueError("Product type must be 'seed' or 'crop'")
        self.product_type = product_type
        self._update_resource_attribute()

    def _update_resource_attribute(self) -> None:
        if self.crop and self.product_type:
            resource_index = 0 if self.product_type == "seed" else 1
            self.resource_attribute = self.CROP_RESOURCES[self.crop][resource_index]
            if hasattr(self, "storage"):
                self._get_storage(self.resource_attribute)


class IceMinor(WaterExtractor):
    type_of_building = "Industrial"

    def get_info(self) -> str:
        return super().get_info() + ", Type: IceMinor"


class Habitation(building):
    maintenance_cost = 20
    production_cost = 1200
    worker_cost = 4
    max_worker_capacity = 6
    volume = 500
    resident_capacity = 20


class RecreationCenter(building):
    maintenance_cost = 12
    production_cost = 800
    worker_cost = 3
    max_worker_capacity = 6
    volume = 250


class Canteen(building):
    maintenance_cost = 15
    production_cost = 900
    worker_cost = 4
    max_worker_capacity = 8
    volume = 200


class LogisticsBuilding(building):
    maintenance_cost = 18
    production_cost = 1100
    worker_cost = 5
    max_worker_capacity = 8
    volume = 300
    transfer_amount: int | float = 100

    def __init__(
        self,
        name: str,
        safety_rating: int | float = 0,
        number_of_workers: int = 0,
        transfer_amount: int | float = 100,
    ):
        if transfer_amount < 0:
            raise ValueError("Transfer amount must be non-negative")
        super().__init__(name, safety_rating, number_of_workers)
        self.transfer_amount = transfer_amount

    def get_info(self) -> str:
        return (
            super().get_info()
            + f", Transfer Amount per Resource Building per Turn: "
            f"{self.transfer_amount}"
        )

    def process_turn(
        self, buildings: list[ResourceBuilding]
    ) -> dict[str, int | float]:
        transferred: dict[str, int | float] = {}
        for source in buildings:
            if not isinstance(source, ResourceBuilding):
                raise TypeError("Logistics can only transfer from resource buildings")
            for resource_name, local_storage in source.storage.items():
                requested = min(
                    self.transfer_amount,
                    local_storage.getResources(),
                )
                if requested <= 0:
                    continue

                colony_inventory = getattr(resource_inventory, resource_name)
                previous_amount = colony_inventory.getResources()
                colony_inventory.addResources(requested)
                accepted = colony_inventory.getResources() - previous_amount
                if accepted:
                    local_storage.SubtractResources(accepted)
                    transferred[resource_name] = (
                        transferred.get(resource_name, 0) + accepted
                    )
        return transferred
