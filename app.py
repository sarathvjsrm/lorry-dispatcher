import numpy as np
import pandas as pd
from ortools.constraint_solver import pywrapcp, routing_enums_pb2
import streamlit as st

st.set_page_config(
    page_title="Dynamic Lorry Dispatcher", page_icon="🚛", layout="wide"
)

st.title("🚛 Daily Lorry Route Dispatcher")
st.write(
    "Edit or paste today's job sites, PJC transfers, and pax numbers directly below."
)

# Default starting list (Editable directly on screen)
default_jobs = [
    {
        "Site / Job Name": "J115A - Nanyang Dr",
        "Slot": "19:00",
        "Pax": 5,
        "Lat": 1.3483,
        "Lon": 103.6831,
    },
    {
        "Site / Job Name": "22/00042 ITTC-GS",
        "Slot": "19:00",
        "Pax": 2,
        "Lat": 1.3200,
        "Lon": 103.6600,
    },
    {
        "Site / Job Name": "26/00017 WUXI",
        "Slot": "19:00",
        "Pax": 1,
        "Lat": 1.3100,
        "Lon": 103.6500,
    },
    {
        "Site / Job Name": "26/00078 Yang Ah Kang",
        "Slot": "21:00",
        "Pax": 5,
        "Lat": 1.4250,
        "Lon": 103.7050,
    },
    {
        "Site / Job Name": "268A Boon Lay Dr",
        "Slot": "21:00",
        "Pax": 5,
        "Lat": 1.3450,
        "Lon": 103.7050,
    },
    {
        "Site / Job Name": "Jurong West St 64",
        "Slot": "21:00",
        "Pax": 10,
        "Lat": 1.3400,
        "Lon": 103.7000,
    },
    {
        "Site / Job Name": "GHPL - Lor Semangka",
        "Slot": "22:00",
        "Pax": 15,
        "Lat": 1.4350,
        "Lon": 103.7150,
    },
    {
        "Site / Job Name": "25/00070 Woh Hup",
        "Slot": "22:00",
        "Pax": 8,
        "Lat": 1.4400,
        "Lon": 103.7500,
    },
    {
        "Site / Job Name": "26/00077 Micron",
        "Slot": "22:00",
        "Pax": 11,
        "Lat": 1.4500,
        "Lon": 103.7800,
    },
]

drivers = [
    {"Name": "Driver 1 (14-ft)", "capacity": 25},
    {"Name": "Driver 2 (14-ft)", "capacity": 25},
    {"Name": "Driver 3 (10-ft)", "capacity": 14},
]

depot = {"Name": "Depot/Hub", "lat": 1.3521, "lon": 103.8198, "demand": 0}

st.subheader("📝 Today's Site List (Add/Edit Rows Here)")
edited_df = st.data_editor(
    pd.DataFrame(default_jobs), num_rows="dynamic", use_container_width=True
)

if st.button("🚀 Calculate Dispatch Routes", type="primary"):
    if edited_df.empty:
        st.error("Please add at least one site to compute routes.")
    else:
        # Get unique time slots dynamically based on what you typed
        unique_slots = sorted(edited_df["Slot"].dropna().unique())

        for slot in unique_slots:
            slot_jobs = edited_df[edited_df["Slot"] == slot].to_dict("records")
            st.subheader(f"⏰ Shift Run: {slot}")

            # Prepare routing locations
            locations = [depot] + [
                {
                    "Name": j["Site / Job Name"],
                    "lat": float(j.get("Lat", 1.35)),
                    "lon": float(j.get("Lon", 103.8)),
                    "demand": int(j.get("Pax", 0)),
                }
                for j in slot_jobs
            ]

            n_locs = len(locations)
            df_locs = pd.DataFrame(locations)

            # Build Distance Matrix
            time_matrix = np.zeros((n_locs, n_locs))
            for i in range(n_locs):
                for j in range(n_locs):
                    if i != j:
                        lat1, lon1 = np.radians(df_locs.loc[i, ["lat", "lon"]])
                        lat2, lon2 = np.radians(df_locs.loc[j, ["lat", "lon"]])
                        dlat, dlon = lat2 - lat1, lon2 - lon1
                        a = (
                            np.sin(dlat / 2) ** 2
                            + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
                        )
                        time_matrix[i][j] = int(
                            (6371 * 2 * np.arcsin(np.sqrt(a)) / 35) * 60
                        )

            # Solve Route
            manager = pywrapcp.RoutingIndexManager(n_locs, len(drivers), 0)
            routing = pywrapcp.RoutingModel(manager)

            def time_cb(i, j):
                return int(
                    time_matrix[manager.IndexToNode(i)][manager.IndexToNode(j)]
                )

            transit_idx = routing.RegisterTransitCallback(time_cb)
            routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)

            def demand_cb(i):
                return int(df_locs.loc[manager.IndexToNode(i), "demand"])

            demand_idx = routing.RegisterUnaryTransitCallback(demand_cb)
            routing.AddDimensionWithVehicleCapacity(
                demand_idx,
                0,
                [d["capacity"] for d in drivers],
                True,
                "Capacity",
            )

            for v in range(len(drivers)):
                routing.SetFixedCostOfVehicle(100, v)

            search_params = pywrapcp.DefaultRoutingSearchParameters()
            search_params.first_solution_strategy = (
                routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
            )

            solution = routing.SolveWithParameters(search_params)

            if solution:
                cols = st.columns(len(drivers))
                active_col = 0
                for v_id in range(len(drivers)):
                    idx = routing.Start(v_id)
                    stops = []
                    load = 0

                    while not routing.IsEnd(idx):
                        node = manager.IndexToNode(idx)
                        if node != 0:
                            stops.append(
                                f"{df_locs.loc[node, 'Name']} ({df_locs.loc[node, 'demand']} pax)"
                            )
                            load += df_locs.loc[node, "demand"]
                        idx = solution.Value(routing.NextVar(idx))

                    if stops:
                        with cols[active_col]:
                            st.info(
                                f"**{drivers[v_id]['Name']}**\n\n"
                                f"**Load:** {load} / {drivers[v_id]['capacity']} pax\n\n"
                                f"**Route:** Depot ➔ "
                                + " ➔ ".join(stops)
                                + " ➔ Depot"
                            )
                        active_col += 1
