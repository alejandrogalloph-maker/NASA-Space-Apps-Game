from Resource_Class import (
    water, oxigen, CO2, Nitrogen, Hydrogen, food, electricity, fuel,
    aluminum, steel, dirt, plastic, glass,
    cars, trucks, rovers, satellites, rockets, drones,
    seed_Lettuce, seed_Wheat, seed_Flax, seed_sunflower,
    lettuce, wheat, flax, sunflower,
)
from Worker_Class import Worker
from Building_file import building, Factory
from actions import GameState, ActionRouter, expand_resource_max, add_resource

resource_pool = {
    'water': water,
    'oxigen': oxigen,
    'CO2': CO2,
    'Nitrogen': Nitrogen,
    'Hydrogen': Hydrogen,
    'food': food,
    'electricity': electricity,
    'fuel': fuel,
    'aluminum': aluminum,
    'steel': steel,
    'dirt': dirt,
    'plastic': plastic,
    'glass': glass,
    'cars': cars,
    'trucks': trucks,
    'rovers': rovers,
    'satellites': satellites,
    'rockets': rockets,
    'drones': drones,
    'seed_Lettuce': seed_Lettuce,
    'seed_Wheat': seed_Wheat,
    'seed_Flax': seed_Flax,
    'seed_sunflower': seed_sunflower,
    'lettuce': lettuce,
    'wheat': wheat,
    'flax': flax,
    'sunflower': sunflower,
}

workers = [Worker(10000), Worker(11000), Worker(12000)]
buildings = [Factory('Refinery', 50, 200, 0.95, 2)]

state = GameState(resource_pool, workers, buildings)
router = ActionRouter(state)

expand_resource_max(state, 'water', 2000)
add_resource(state, 'water', 500)

expand_resource_max(state, 'oxigen', 500)
add_resource(state, 'oxigen', 120)

expand_resource_max(state, 'electricity', 1000)
add_resource(state, 'electricity', 400)

print('Sol:', state.sol)
print('Water:', water.getResources(), '/', water.getMaxResources())
print('Workers:', [w.Name for w in state.workers])
print('Available actions:', router.available_actions())
