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


def setup_game() -> ActionRouter:
    pool = {
        'water': water, 'oxigen': oxigen, 'CO2': CO2, 'Nitrogen': Nitrogen,
        'Hydrogen': Hydrogen, 'food': food, 'electricity': electricity, 'fuel': fuel,
        'aluminum': aluminum, 'steel': steel, 'dirt': dirt, 'plastic': plastic,
        'glass': glass, 'cars': cars, 'trucks': trucks, 'rovers': rovers,
        'satellites': satellites, 'rockets': rockets, 'drones': drones,
        'seed_Lettuce': seed_Lettuce, 'seed_Wheat': seed_Wheat,
        'seed_Flax': seed_Flax, 'seed_sunflower': seed_sunflower,
        'lettuce': lettuce, 'wheat': wheat, 'flax': flax, 'sunflower': sunflower,
    }

    starting_stock = {
        'water': (2000, 500), 'oxigen': (500, 120), 'CO2': (300, 60),
        'Nitrogen': (500, 200), 'Hydrogen': (300, 80), 'food': (300000, 90000),
        'electricity': (1000, 500), 'fuel': (1000, 300), 'aluminum': (2000, 200),
        'steel': (2000, 200), 'dirt': (5000, 300), 'plastic': (1000, 100),
        'glass': (1000, 100), 'cars': (5, 1), 'trucks': (5, 1), 'rovers': (10, 2),
        'satellites': (5, 1), 'rockets': (5, 1), 'drones': (15, 3),
        'seed_Lettuce': (500, 30), 'seed_Wheat': (500, 30),
        'seed_Flax': (500, 30), 'seed_sunflower': (500, 30),
        'lettuce': (500, 15), 'wheat': (500, 15), 'flax': (500, 10), 'sunflower': (500, 10),
    }

    workers = [Worker(10000 + i * 350) for i in range(6)]
    buildings = [Factory('Refinery Alpha', 40, 120, 0.95, 2)]
    state = GameState(pool, workers, buildings)

    for key, (max_cap, current_amt) in starting_stock.items():
        expand_resource_max(state, key, max_cap)
        add_resource(state, key, current_amt)

    router = ActionRouter(state)
    for idx, role_code in enumerate([2, 3, 4, 5, 1, 0]):
        router.execute('assign_job', idx, role_code)

    return router


def show_status(state: GameState) -> None:
    print(f'\nSol {state.sol} | Science: {state.science_points:.1f} | Satellites: {state.active_satellites}')
    print(
        f'Water: {water.getResources():.1f} | O2: {oxigen.getResources():.1f} | '
        f'CO2: {CO2.getResources():.1f} | Food: {food.getResources():.0f} | '
        f'Power: {electricity.getResources():.1f} | Fuel: {fuel.getResources():.1f}'
    )
    print(
        f'Dirt: {dirt.getResources():.1f} | Al: {aluminum.getResources():.1f} | '
        f'Steel: {steel.getResources():.1f} | Plastic: {plastic.getResources():.1f} | '
        f'Glass: {glass.getResources():.1f}'
    )
    for i, w in enumerate(state.workers):
        status = 'Ready' if w.isAvailable() else 'Busy/Inactive'
        print(f'  [{i}] {w.Name:<10} | {w.getType().name:<10} | HP: {w.getHealth():5.1f} | {status}')


def main() -> None:
    router = setup_game()
    state = router.state

    while True:
        show_status(state)
        print('\nRoutes:', ', '.join(router.available_actions()))
        raw = input('\nEnter command (e.g. run_moxie 0 | hydroponics 1 lettuce | advance_sol | quit): ').strip()
        if not raw:
            continue
        parts = raw.split()
        cmd = parts[0]

        if cmd == 'quit':
            break

        try:
            if cmd in {'advance_sol', 'balance_atmosphere', 'feed_crew', 'maintain_buildings'}:
                router.execute(cmd)
            elif cmd in {'work', 'rest', 'hospital', 'study', 'retire', 'run_moxie', 'mine', 'produce_fuel', 'deploy_rover', 'fly_drone', 'launch_satellite', 'launch_rocket'}:
                router.execute(cmd, int(parts[1]))
            elif cmd == 'assign_job':
                router.execute(cmd, int(parts[1]), int(parts[2]))
            elif cmd in {'hydroponics', 'food_refinery', 'refine_materials', 'manufacture'}:
                router.execute(cmd, int(parts[1]), parts[2])
            elif cmd == 'construct_building':
                router.execute(cmd, building(parts[1], 30, 80, 0.98, 1))
            elif cmd == 'operate_factory':
                router.execute(cmd, int(parts[1]), [int(x) for x in parts[2:]])
            else:
                print('Unknown route.')
        except (IndexError, ValueError) as err:
            print('Command format error:', err)

        for entry in state.log[-4:]:
            print(' >', entry)


if __name__ == '__main__':
    main()
