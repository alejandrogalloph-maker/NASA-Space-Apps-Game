class building:
    def __init__(
        self,
        name,
        maintanence_cost,
        production_cost,
        safety_rating,
        number_of_workers,
        daily_inputs=None,
        daily_outputs=None,
        space_size=1,
    ):
        self.name = name
        self.maintenance_cost = maintanence_cost
        self.production_cost = production_cost
        self.safety_rating = safety_rating
        self.number_of_workers = number_of_workers
        self.daily_inputs = dict(daily_inputs) if daily_inputs else {}
        self.daily_outputs = dict(daily_outputs) if daily_outputs else {}
        self.space_size = space_size
        self.type_of_building = 'General'

    def get_info(self):
        return (
            f'Building Name: {self.name}, Maintenance Cost: {self.maintenance_cost}, '
            f'Production Cost: {self.production_cost}, Safety Rating: {self.safety_rating}, '
            f'Number of Workers: {self.number_of_workers}'
        )

    def calculate_total_cost(self):
        return self.maintenance_cost + self.production_cost


class Factory(building):
    def __init__(
        self,
        name,
        maintanence_cost,
        production_cost,
        safety_rating,
        number_of_workers,
        daily_inputs=None,
        daily_outputs=None,
        space_size=2,
    ):
        super().__init__(
            name,
            maintanence_cost,
            production_cost,
            safety_rating,
            number_of_workers,
            daily_inputs=daily_inputs or {'electricity': 20.0, 'dirt': 15.0},
            daily_outputs=daily_outputs or {'steel': 8.0, 'aluminum': 8.0, 'plastic': 4.0},
            space_size=space_size,
        )
        self.type_of_building = 'Industrial'

    def get_info(self):
        return super().get_info() + ', Type: Factory'


class SolarArray(building):
    def __init__(self, name='Solar Array', output_kwh=75.0):
        super().__init__(
            name=name,
            maintanence_cost=5,
            production_cost=40,
            safety_rating=0.98,
            number_of_workers=0,
            daily_inputs={},
            daily_outputs={'electricity': output_kwh},
            space_size=0,
        )
        self.type_of_building = 'Power'


class MoxieUnit(building):
    def __init__(self, name='MOXIE Station'):
        super().__init__(
            name=name,
            maintanence_cost=10,
            production_cost=60,
            safety_rating=0.95,
            number_of_workers=1,
            daily_inputs={'electricity': 20.0, 'CO2': 4.0},
            daily_outputs={'oxigen': 7.5},
            space_size=1,
        )
        self.type_of_building = 'Life Support'


class HydroponicsBay(building):
    def __init__(self, name='Hydroponics Bay'):
        super().__init__(
            name=name,
            maintanence_cost=12,
            production_cost=70,
            safety_rating=0.96,
            number_of_workers=1,
            daily_inputs={'water': 10.0, 'electricity': 18.0, 'CO2': 2.0},
            daily_outputs={'food': 14000.0, 'oxigen': 2.0},
            space_size=2,
        )
        self.type_of_building = 'Agriculture'


class WaterExtractor(building):
    def __init__(self, name='Ice Mining Rig'):
        super().__init__(
            name=name,
            maintanence_cost=15,
            production_cost=65,
            safety_rating=0.92,
            number_of_workers=1,
            daily_inputs={'electricity': 18.0},
            daily_outputs={'water': 24.0, 'dirt': 15.0},
            space_size=1,
        )
        self.type_of_building = 'Extraction'


class HabitatModule(building):
    def __init__(self, name='Pressurized Habitat'):
        super().__init__(
            name=name,
            maintanence_cost=10,
            production_cost=80,
            safety_rating=0.99,
            number_of_workers=0,
            daily_inputs={'electricity': 10.0, 'Nitrogen': 1.0},
            daily_outputs={},
            space_size=3,
        )
        self.type_of_building = 'Habitat'
