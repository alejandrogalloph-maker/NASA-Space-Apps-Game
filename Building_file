


class building:
    def __init__(self, name, maintanence_cost, production_cost, safety_rating, number_of_workers):
        self.name = name
        self.maintenance_cost = maintanence_cost
        self.production_cost = production_cost
        self.safety_rating = safety_rating
        self.number_of_workers = number_of_workers

    def get_info(self):
        return f"Building Name: {self.name}, Maintenance Cost: {self.maintenance_cost}, Production Cost: {self.production_cost}, Safety Rating: {self.safety_rating}, Number of Workers: {self.number_of_workers}"

    def calculate_total_cost(self):
        total_cost = self.maintenance_cost + self.production_cost
        return total_cost

class Factory(building):
    def __init__(self, name, maintanence_cost, production_cost, safety_rating, number_of_workers):
        super().__init__(name, maintanence_cost, production_cost, safety_rating, number_of_workers)
        self.type_of_building = "Industrial"

    def get_info(self):
        return super().get_info() + ", Type: Factory"

    
