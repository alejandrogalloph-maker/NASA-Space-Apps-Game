from Resource_Class import (
    water, oxigen, CO2, Nitrogen, Hydrogen, food, electricity, fuel,
    aluminum, steel, dirt, plastic, glass,
    cars, trucks, rovers, satellites, rockets, drones,
    seed_Lettuce, seed_Wheat, seed_Flax, seed_sunflower,
    lettuce, wheat, flax, sunflower,
)
from Worker_Class import Worker
from Building_file import (
    building,
    Factory,
    SolarArray,
    MoxieUnit,
    HydroponicsBay,
    WaterExtractor,
    HabitatModule,
)
from actions import (
    SPACE_ENVIRONMENTS,
    GameState,
    ActionRouter,
    expand_resource_max,
    add_resource,
)


def choose_mission_setup() -> tuple[str, int]:
    print('Select Mission Space Environment:')
    options = list(SPACE_ENVIRONMENTS.items())
    for idx, (key, info) in enumerate(options, start=1):
        lbl = info['label']
        sol_m = info['solar_multiplier']
        pwr_s = info['power_per_space']
        o2_s = info['o2_leak_per_space']
        haz = int(info['hazard_chance'] * 100)
        print(f'  [{idx}] {lbl} ({key}) | Solar x{sol_m} | Power/Space: -{pwr_s} | O2 Leak/Space: -{o2_s} | Hazard: {haz}%')

    space_choice = input('Enter choice [1-4] (default 3 = Mars): ').strip()
    key_map = {'1': 'orbit', '2': 'moon', '3': 'mars', '4': 'deep_space'}
    if space_choice in SPACE_ENVIRONMENTS:
        selected_space = space_choice
    else:
        selected_space = key_map.get(space_choice, 'mars')

    crew_raw = input('Enter number of crew members [2-10] (default 6): ').strip()
    try:
        crew_count = max(2, min(10, int(crew_raw)))
    except ValueError:
        crew_count = 6

    return selected_space, crew_count


def setup_game(space_key: str = 'mars', crew_count: int = 6) -> ActionRouter:
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

    workers = [Worker(10000 + i * 350) for i in range(crew_count)]
    buildings = [
        SolarArray('Primary Solar Array', 85.0),
        MoxieUnit('MOXIE Unit 1'),
        HydroponicsBay('Hydroponics Bay 1'),
        WaterExtractor('Ice Drill 1'),
        Factory('Refinery Alpha', 40, 120, 0.95, 2),
    ]
    state = GameState(pool, workers, buildings, space_key=space_key)

    for key, (max_cap, current_amt) in starting_stock.items():
        expand_resource_max(state, key, max_cap)
        add_resource(state, key, current_amt)

    router = ActionRouter(state)
    default_roles = [2, 3, 4, 5, 1, 0]
    for idx in range(crew_count):
        router.execute('assign_job', idx, default_roles[idx % len(default_roles)])

    return router


def show_status(state: GameState) -> None:
    active_crew = [w for w in state.workers if not getattr(w, 'retired', False) and w.getHealth() > 0]
    total_space = max(1, sum(int(getattr(b, 'space_size', 1)) for b in state.buildings))

    space_label = state.space['label']
    print()
    print(
        f'Sol {state.sol} | {space_label} | '
        f'Crew: {len(active_crew)}/{len(state.workers)} | Space Units: {total_space} | '
        f'Science: {state.science_points:.1f} | Satellites: {state.active_satellites}'
    )
    print(
        f'Life Support: Water {water.getResources():.1f}/{water.getMaxResources():.0f} | '
        f'O2 {oxigen.getResources():.1f}/{oxigen.getMaxResources():.0f} | '
        f'CO2 {CO2.getResources():.1f}/{CO2.getMaxResources():.0f} | '
        f'N2 {Nitrogen.getResources():.1f}/{Nitrogen.getMaxResources():.0f} | '
        f'H2 {Hydrogen.getResources():.1f}/{Hydrogen.getMaxResources():.0f}'
    )
    print(
        f'Energy & Food: Food {food.getResources():.0f}/{food.getMaxResources():.0f} kcal | '
        f'Power {electricity.getResources():.1f}/{electricity.getMaxResources():.0f} kWh | '
        f'Fuel {fuel.getResources():.1f}/{fuel.getMaxResources():.0f} L'
    )
    print(
        f'Materials: Dirt {dirt.getResources():.1f} | Al {aluminum.getResources():.1f} | '
        f'Steel {steel.getResources():.1f} | Plastic {plastic.getResources():.1f} | '
        f'Glass {glass.getResources():.1f}'
    )
    print(
        f'Vehicles & Crops: Rovers {int(rovers.getResources())} | Drones {int(drones.getResources())} | '
        f'Satellites {int(satellites.getResources())} | Rockets {int(rockets.getResources())} | '
        f'Lettuce {lettuce.getResources():.1f} | Wheat {wheat.getResources():.1f} | '
        f'Flax {flax.getResources():.1f} | Sunflower {sunflower.getResources():.1f}'
    )

    if state.daily_report:
        summary_parts = []
        for res_name, vals in state.daily_report.items():
            added = vals['added']
            sub = vals['subtracted']
            net = vals['net']
            summary_parts.append(f'{res_name} (+{added:.1f} / -{sub:.1f} = {net:+.1f})')
        print('Last Sol Balance: ' + ' | '.join(summary_parts))

    print('Buildings:')
    for idx, bld in enumerate(state.buildings):
        in_str = ', '.join(f'{k}:{v}' for k, v in getattr(bld, 'daily_inputs', {}).items()) or 'none'
        out_str = ', '.join(f'{k}:{v}' for k, v in getattr(bld, 'daily_outputs', {}).items()) or 'none'
        print(
            f'  [{idx}] {bld.name} ({bld.type_of_building}) | Space: {bld.space_size} | '
            f'Safety: {int(bld.safety_rating * 100)}% | In: [{in_str}] -> Out: [{out_str}]'
        )

    print('Crew:')
    for i, w in enumerate(state.workers):
        if getattr(w, 'retired', False):
            status = 'Retired'
        elif w.getHealth() <= 0:
            status = 'Deceased'
        elif w.isAvailable():
            status = 'Ready'
        else:
            status = 'Busy'
        print(f'  [{i}] {w.Name:<10} | {w.getType().name:<10} | HP: {w.getHealth():5.1f} | {status}')


def main() -> None:
    space_key, crew_count = choose_mission_setup()
    router = setup_game(space_key=space_key, crew_count=crew_count)
    state = router.state

    while True:
        show_status(state)
        print()
        print('Routes:', ', '.join(router.available_actions()))
        print('Build types for construct_building: solar, moxie, hydroponics, extractor, habitat, factory')
        print()
        raw = input('Enter command (e.g. run_moxie 0 | construct_building hydroponics | advance_sol | quit): ').strip()
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
                b_type = parts[1].lower()
                catalog = {
                    'solar': SolarArray('Solar Array'),
                    'moxie': MoxieUnit('MOXIE Unit'),
                    'hydroponics': HydroponicsBay('Hydroponics Bay'),
                    'extractor': WaterExtractor('Ice Extractor'),
                    'habitat': HabitatModule('Habitat Module'),
                    'factory': Factory('Factory Module', 40, 120, 0.95, 2),
                }
                new_bld = catalog.get(b_type, building(parts[1], 30, 80, 0.98, 1))
                router.execute(cmd, new_bld)
            elif cmd == 'operate_factory':
                router.execute(cmd, int(parts[1]), [int(x) for x in parts[2:]])
            else:
                print('Unknown route.')
        except (IndexError, ValueError) as err:
            print('Command format error:', err)

        for entry in state.log[-5:]:
            print(' >', entry)


if __name__ == '__main__':
    main()
