import numpy as np
import pandas as pd
from ortools.constraint_solver import pywrapcp, routing_enums_pb2
import streamlit as st

st.set_page_config(
    page_title="Lorry Route Dispatcher", page_icon="🚛", layout="wide"
)

st.title("🚛 Dynamic Lorry Route Dispatcher (Time Window Enforced)")
st.write(
    "Strictly enforces chronological delivery time slots (19:00 -> 21:00 -> 22:00) and vehicle capacities."
)

# 1. Define Jobs with exact Minute Windows (0 = 19:00, 120 = 21:00, 180 = 22:00)
jobs_data = [
    {
        "Name": "Depot/Hub",
        "lat": 1.3521,
        "lon": 103.8198,
        "demand": 0,
        "Slot": "Depot",
        "start": 0,
        "end": 360,
    },
    {
        "Name": "J115A - Nanyang Dr",
        "lat": 1.3483,
        "lon": 103.6831,
        "demand": 5,
        "Slot": "19:00",
        "start": 0,
        "end": 45,
    },
    {
        "Name": "22/00042 ITTC-GS",
        "lat": 1.3200,
        "lon": 103.6600,
        "demand": 2,
        "Slot": "19:00",
        "start": 0,
        "end": 45,
    },
    {
        "Name": "26/00017 WUXI",
        "lat": 1.3100,
        "lon": 103.6500,
        "demand": 1,
        "Slot": "19:00",
        "start": 0,
        "end": 45,
    },
    {
        "Name": "26/00078 Yang Ah Kang",
        "lat": 1.4250,
        "lon": 103.7050,
        "demand": 5,
        "Slot": "21:00",
        "start": 120,
        "end": 165,
    },
    {
        "Name": "268A Boon Lay Dr",
        "lat": 1.3450,
        "lon": 103.7050,
        "demand": 5,
        "Slot": "21:00",
        "start": 120,
        "end": 165,
    },
    {
        "Name": "Jurong West St 64",
        "lat": 1.3400,
        "lon": 103.7000,
        "demand": 10,
        "Slot": "21:00",
        "start": 120,
        "end": 165,
    },
    {
        "Name": "GHPL - Lor Semangka",
        "lat": 1.4350,
        "lon": 103.7150,
        "demand": 15,
        "Slot": "22:00",
        "start": 180,
        "end": 225,
    },
    {
        "Name": "25/00070 Woh Hup",
        "lat": 1.4400,
        "lon": 103.7500,
        "demand": 8,
        "Slot": "22:00",
        "start": 180,
        "end": 225,
    },
    {
        "Name": "26/00077 Micron",
        "lat": 1.4500,
        "lon": 103.7800,
        "demand": 11,
        "Slot": "22:00",
        "start": 180,
        "end": 225,
    },
]

drivers = [
    {"Name": "Driver 1 (14-ft)", "capacity": 25},
    {"Name": "Driver 2 (14-ft)", "capacity": 25},
    {"Name": "Driver 3 (10-ft)", "capacity": 14},
]

jobs_df = pd.DataFrame(jobs_data)

col1, col2 = st.columns(2)
with col1:
    st.subheader("📦 Delivery Jobs")
    st.dataframe(
        jobs_df[["Name", "Slot", "demand"]], use_container_width=True
    )
with col2:
    st.subheader("🚚 Available Vehicles")
    st.dataframe(pd.DataFrame(drivers), use_container_width=True)

if st.button("🚀 Calculate Optimal Driver Routes", type="primary"):
    num_locations = len(jobs_df)
    time_matrix = np.zeros((num_locations, num_locations))

    # Travel time matrix calculation
    for i in range(num_locations):
        for j in range(num_locations):
            if i != j:
                lat1, lon1 = np.radians(jobs_df.loc[i, ["lat", "lon"]])
                lat2, lon2 = np.radians(jobs_df.loc[j, ["lat", "lon"]])
                dlat, dlon = lat2 - lat1, lon2 - lon1
                a = (
                    np.sin(dlat / 2) ** 2
                    + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
                )
                dist_km = 6371 * 2 * np.arcsin(np.sqrt(a))
                time_matrix[i][j] = int((dist_km / 35) * 60)

    manager = pywrapcp.RoutingIndexManager(num_locations, len(drivers), 0)
    routing = pywrapcp.RoutingModel(manager)

    def time_callback(from_idx, to_idx):
        return int(
            time_matrix[manager.IndexToNode(from_idx)][
                manager.IndexToNode(to_idx)
            ]
        )

    transit_idx = routing.RegisterTransitCallback(time_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)

    # 1. Capacity Dimension
    def demand_callback(from_idx):
        return int(jobs_df.loc[manager.IndexToNode(from_idx), "demand"])

    demand_idx = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(
        demand_idx,
        0,
        [d["capacity"] for d in drivers],
        True,
        "Capacity",
    )

    # 2. Time Window Dimension (CRITICAL FIX)
    routing.AddDimension(
        transit_idx,
        60,  # Max wait time allowed at stop
        360,  # Max total shift time (mins)
        False,  # Don't force start at zero
        "Time",
    )
    time_dimension = routing.GetDimensionOrDie("Time")

    for loc_idx in range(num_locations):
        index = manager.NodeToIndex(loc_idx)
        time_dimension.CumulVar(index).SetRange(
            int(jobs_df.loc[loc_idx, "start"]), int(jobs_df.loc[loc_idx, "end"])
        )

    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    search_params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search_params.time_limit.seconds = 5

    solution = routing.SolveWithParameters(search_params)

    if solution:
        st.success("✅ Chronological Optimization Complete!")
        for vehicle_id in range(len(drivers)):
            index = routing.Start(vehicle_id)
            d_info = drivers[vehicle_id]
            route_stops = []
            total_load = 0

            while not routing.IsEnd(index):
                node = manager.IndexToNode(index)
                load = jobs_df.loc[node, "demand"]
                slot = jobs_df.loc[node, "Slot"]
                total_load += load
                route_stops.append(
                    f"[{slot}] {jobs_df.loc[node, 'Name']} ({load} pax)"
                )
                index = solution.Value(routing.NextVar(index))

            route_stops.append("Depot/Hub")

            with st.expander(
                f"🚛 {d_info['Name']} — Total Load: {total_load}/{d_info['capacity']} pax",
                expanded=True,
            ):
                st.write(" ➔ ".join(route_stops))
    else:
        st.error(
            "No valid route matches these time slots and vehicle limits. Try increasing vehicle capacity or adding another lorry."
        )
