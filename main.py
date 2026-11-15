import Resource_Class as resource_inventory
from Resource_Class import (
    water, oxigen, CO2, Nitrogen, Hydrogen, food, electricity, fuel,
    aluminum, steel, dirt, plastic, glass,
    cars, trucks, rovers, satellites, rockets, drones,
    seed_Lettuce, seed_Wheat, seed_Flax, seed_sunflower,
    lettuce, wheat, flax, sunflower,
)
from Worker_Class import Worker
from Building_file import (
    all_buildings,
    ResourceBuilding,
    PowerPlant,
    OxygenGenerator,
    FoodFactory,
    WaterExtractor,
    SteelMill,
    Habitation,
    LogisticsBuilding,
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
        pwr_v = info['power_per_100m3']
        o2_v = info['o2_leak_per_100m3']
        haz = int(info['hazard_chance'] * 100)
        print(f'  [{idx}] {lbl} ({key}) | Solar x{sol_m} | Power/100m3: -{pwr_v} | O2 Leak/100m3: -{o2_v} | Hazard: {haz}%')

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
    all_buildings.clear()
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
        Habitation('Main Habitation Dome', safety_rating=98),
        PowerPlant('Main Solar Power Plant', safety_rating=96),
        OxygenGenerator('MOXIE Oxygen Generator', safety_rating=95),
        FoodFactory('Hydroponic Food Factory', safety_rating=96),
        WaterExtractor('Subsurface Water Extractor', safety_rating=92),
        LogisticsBuilding('Central Logistics Hub', safety_rating=96, transfer_amount=25000),
        SteelMill('Colony Steel Mill', safety_rating=90),
    ]
    state = GameState(pool, workers, buildings, space_key=space_key)
    state.hazard_manager.compute_risk_probability(state)

    for key, (max_cap, current_amt) in starting_stock.items():
        if pool[key].getMaxResources() == 0:
            expand_resource_max(state, key, max_cap)
        if pool[key].getResources() == 0:
            add_resource(state, key, current_amt)

    router = ActionRouter(state)
    default_roles = [1, 2, 3, 4, 5, 2]
    for idx in range(crew_count):
        router.execute('assign_job', idx, default_roles[idx % len(default_roles)])

    initial_assignments = [
        (0, 0),
        (1, 1),
        (3, 2),
        (4, 3),
        (5, 4),
        (2, 5),
    ]
    for b_idx, w_idx in initial_assignments:
        if b_idx < len(buildings) and w_idx < len(workers):
            router.execute('staff_building', b_idx, w_idx)

    return router


def show_status(state: GameState) -> None:
    active_crew = [w for w in state.workers if not getattr(w, 'retired', False) and w.getHealth() > 0]
    total_volume = sum(float(getattr(b, 'volume', 100)) for b in state.buildings if getattr(b, 'is_on', True))
    space_label = state.space['label']
    risk_pct = int(state.hazard_manager.last_risk_score * 100)
    res_pts = int(resource_inventory.research.getResources()) if hasattr(resource_inventory, 'research') else 0
    elapsed_hrs = getattr(state.time_engine, 'elapsed_hours', (state.sol - 1) * 24)

    print()
    print(
        f'Sol {state.sol} ({elapsed_hrs}h) | {space_label} | '
        f'Crew: {len(active_crew)}/{len(state.workers)} | Active Volume: {total_volume:.0f} m^3 | '
        f'Science: {state.science_points:.1f} | Research Pts: {res_pts} | '
        f'Satellites: {state.active_satellites} | Crisis Risk: {risk_pct}%'
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

    if state.hazard_manager.active_incidents:
        print()
        print('ONGOING CRISES:')
        for inc in state.hazard_manager.active_incidents:
            print(f'  [Severity {inc.severity}] {inc.name}: {inc.description}')

    print()
    print('Buildings:')
    for idx, bld in enumerate(state.buildings):
        power_state = 'On' if getattr(bld, 'is_on', True) else 'Off'
        op_state = 'OP' if bld.is_operational() else 'IDLE'
        cap = getattr(type(bld), 'max_worker_capacity', 0)
        vol = getattr(bld, 'volume', 100)
        raw_safety = float(getattr(bld, 'safety_rating', 0))
        safety_pct = int(raw_safety * 100) if raw_safety <= 1.0 else int(raw_safety)
        local_txt = ''
        if isinstance(bld, ResourceBuilding):
            items = [f'{k}:{v.getResources():.1f}/{v.getMaxResources():.0f}' for k, v in bld.storage.items()]
            local_txt = ' | Local: {' + ', '.join(items) + '}'
        print(
            f'  [{idx}] {bld.name} ({type(bld).__name__}) | {power_state}/{op_state} | Vol: {vol} m^3 | '
            f'Safety: {safety_pct}% | Staff: {bld.number_of_workers}/{cap}{local_txt}'
        )

    print()
    print('Crew:')
    for i, w in enumerate(state.workers):
        if getattr(w, 'retired', False):
            status = 'Retired'
        elif w.getHealth() <= 0:
            status = 'Deceased'
        elif getattr(w, 'assigned_building', None) is not None:
            status = f'Staffed @ {w.assigned_building.name}'
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
        active_crew = [w for w in state.workers if not getattr(w, 'retired', False) and w.getHealth() > 0]
        if not active_crew:
            print()
            print(f'MISSION FAILED on Sol {state.sol}: All crew members lost. Final Science: {state.science_points:.1f}')
            break

        print()
        print('Routes:', ', '.join(router.available_actions()))
        print('Build types: power, water, iceminer, oxygen, co2, nitrogen, hydrogen, food, fuel, aluminum, steel, soil, plastic, glass, farm_lettuce, farm_wheat, habitation, recreation, canteen, logistics, research, university, medical_bay, hospital, graveyard, comms_hub, satellite_dish')
        print()
        raw = input('Enter command (e.g. unstaff_building 2 5 | mine 5 | advance_sol | advance_sols 3 | quit): ').strip()
        if not raw:
            continue
        parts = raw.split()
        cmd = parts[0]

        if cmd == 'quit':
            break

        try:
            if cmd in {'advance_sol', 'balance_atmosphere', 'feed_crew', 'maintain_buildings', 'resolve_crises', 'transfer_logistics'}:
                router.execute(cmd)
            elif cmd in {'advance_sols', 'work', 'rest', 'hospital', 'study', 'retire', 'run_moxie', 'mine', 'produce_fuel', 'deploy_rover', 'fly_drone', 'launch_satellite', 'launch_rocket', 'toggle_building'}:
                router.execute(cmd, int(parts[1]))
            elif cmd in {'assign_job', 'staff_building', 'unstaff_building', 'run_research'}:
                router.execute(cmd, int(parts[1]), int(parts[2]))
            elif cmd in {'hydroponics', 'food_refinery', 'refine_materials', 'manufacture'}:
                router.execute(cmd, int(parts[1]), parts[2])
            elif cmd == 'university_train':
                router.execute(cmd, int(parts[1]), int(parts[2]), parts[3])
            elif cmd == 'construct_building':
                router.execute(cmd, parts[1])
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
