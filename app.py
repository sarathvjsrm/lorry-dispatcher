import numpy as np
import pandas as pd
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

# 1. Real Job Data with GPS Coordinates & Time Windows (NO hardcoded regions!)
jobs_data = [
    {"Name": "Depot/Hub", "lat": 1.3521, "lon": 103.8198, "demand": 0, "window_start": 0, "window_end": 300},
    {"Name": "J115A - Nanyang Dr", "lat": 1.3483, "lon": 103.6831, "demand": 5, "window_start": 0, "window_end": 30},     # 19:00 Slot
    {"Name": "22/00042 ITTC-GS", "lat": 1.3200, "lon": 103.6600, "demand": 2, "window_start": 0, "window_end": 30},       # 19:00 Slot
    {"Name": "26/00017 WUXI", "lat": 1.3100, "lon": 103.6500, "demand": 1, "window_start": 0, "window_end": 30},          # 19:00 Slot
    {"Name": "26/00078 Yang Ah Kang", "lat": 1.4250, "lon": 103.7050, "demand": 5, "window_start": 120, "window_end": 150}, # 21:00 Slot
    {"Name": "268A Boon Lay Dr", "lat": 1.3450, "lon": 103.7050, "demand": 5, "window_start": 120, "window_end": 150},    # 21:00 Slot
    {"Name": "Jurong West St 64", "lat": 1.3400, "lon": 103.7000, "demand": 10, "window_start": 120, "window_end": 150},   # 21:00 Slot
    {"Name": "GHPL - Lor Semangka", "lat": 1.4350, "lon": 103.7150, "demand": 15, "window_start": 180, "window_end": 210}, # 22:00 Slot
    {"Name": "25/00070 Woh Hup", "lat": 1.4400, "lon": 103.7500, "demand": 8, "window_start": 180, "window_end": 210},     # 22:00 Slot
    {"Name": "26/00077 Micron", "lat": 1.4500, "lon": 103.7800, "demand": 11, "window_start": 180, "window_end": 210},    # 22:00 Slot
]

jobs_df = pd.DataFrame(jobs_data)

# Available Fleet Vehicles (Capabilities only, no regional restrictions)
drivers = [
    {"Name": "Driver 1 (14-ft)", "capacity": 25},
    {"Name": "Driver 2 (14-ft)", "capacity": 25},
    {"Name": "Driver 3 (10-ft)", "capacity": 14},
]

# 2. Build Dynamic Driving Time Matrix (in minutes based on distance & traffic speed)
num_locations = len(jobs_df)
time_matrix = np.zeros((num_locations, num_locations))

for i in range(num_locations):
    for j in range(num_locations):
        if i != j:
            # Approximate distance in km using Haversine formula
            lat1, lon1 = np.radians(jobs_df.loc[i, ["lat", "lon"]])
            lat2, lon2 = np.radians(jobs_df.loc[j, ["lat", "lon"]])
            dlat, dlon = lat2 - lat1, lon2 - lon1
            a = np.sin(dlat / 2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2)**2
            dist_km = 6371 * 2 * np.arcsin(np.sqrt(a))
            # Average urban speed 35 km/h -> travel time in minutes
            time_matrix[i][j] = int((dist_km / 35) * 60)

# 3. Initialize Optimization Routing Engine
manager = pywrapcp.RoutingIndexManager(num_locations, len(drivers), 0)
routing = pywrapcp.RoutingModel(manager)

# Travel Time Callback
def time_callback(from_index, to_index):
    return int(time_matrix[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)])

transit_callback_index = routing.RegisterTransitCallback(time_callback)
routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

# Capacity Constraints
def demand_callback(from_index):
    return int(jobs_df.loc[manager.IndexToNode(from_index), "demand"])

demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
routing.AddDimensionWithVehicleCapacity(
    demand_callback_index, 0, [d["capacity"] for d in drivers], True, "Capacity"
)

# 4. Metaheuristic Search Configuration (Runs Thousands of Route Simulations)
search_parameters = pywrapcp.DefaultRoutingSearchParameters()
search_parameters.first_solution_strategy = (
    routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
)

# Guided Local Search tests thousands of permutations to escape local minima
search_parameters.local_search_metaheuristic = (
    routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
)
search_parameters.time_limit.seconds = 5  # Evaluates thousands of routes per second

# 5. Solve and Print Dynamically Selected Best Route
solution = routing.SolveWithParameters(search_parameters)

if solution:
    print("=== DYNAMIC OPTIMIZATION COMPLETE (Best Route Selected) ===\n")
    for vehicle_id in range(len(drivers)):
        index = routing.Start(vehicle_id)
        driver_info = drivers[vehicle_id]
        route_stops = []
        total_time = 0
        total_load = 0

        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            load = jobs_df.loc[node, "demand"]
            total_load += load
            route_stops.append(f"{jobs_df.loc[node, 'Name']} ({load} pax)")
            
            previous_index = index
            index = solution.Value(routing.NextVar(index))
            total_time += time_callback(previous_index, index)

        route_stops.append("Depot/Hub")
        print(f"🚛 {driver_info['Name']} | Total Load: {total_load}/{driver_info['capacity']} pax | Est Driving Time: {total_time} mins")
        print("   Route: " + " ➔ ".join(route_stops) + "\n")
