import streamlit as st
import pandas as pd

st.set_page_config(page_title="Dynamic Dispatch Engine", layout="wide")
st.title("🧠 Smart Dynamic Fleet Dispatch Engine")

# Master Zone Database
SITE_DATABASE = {
    "24/12233 MOE - MI": {"zone": "Central"},
    "24/12201 MOE - ACJC (Dover)": {"zone": "Central"},
    "24/12239 MOE - PEPS": {"zone": "Central"},
    "24/12219 MOE - HPPS": {"zone": "Central"},
    "GHPL - Lor Semangka": {"zone": "West"},
    "24/12205 MOE - BLSS": {"zone": "West"},
    "24/12212 MOE - CTSS": {"zone": "West"},
    "26/00078 Yang Ah Kang": {"zone": "West"},
    "J105 - 268A Boon Lay Dr": {"zone": "West"},
    "J106 - Jurong West St 64": {"zone": "West"},
    "J115A - Nanyang Dr": {"zone": "West"},
    "22/00042 ITTC-GS": {"zone": "West"},
    "26/00017 WUXI": {"zone": "West"},
    "24/12204 MOE - BLGPS": {"zone": "West"},
    "26/00077 Micron - L and K": {"zone": "North"},
    "25/00070 Woh Hup": {"zone": "North"},
    "Punggol S11": {"zone": "East"},
}

site_options = sorted(list(SITE_DATABASE.keys()))

default_data = [
    {"Origin Site": "24/12204 MOE - BLGPS", "Job Type": "PJC-to-PJC Transfer", "Destination PJC": "24/12201 MOE - ACJC (Dover)", "Pax": 3, "Time Deadline": "18:30", "Food Drop": "NO"},
    {"Origin Site": "24/12239 MOE - PEPS", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 1, "Time Deadline": "19:00", "Food Drop": "NO"},
    {"Origin Site": "24/12219 MOE - HPPS", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 3, "Time Deadline": "19:00", "Food Drop": "NO"},
    {"Origin Site": "J115A - Nanyang Dr", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 5, "Time Deadline": "19:00", "Food Drop": "NO"},
    {"Origin Site": "22/00042 ITTC-GS", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 2, "Time Deadline": "19:00", "Food Drop": "NO"},
    {"Origin Site": "26/00017 WUXI", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 1, "Time Deadline": "19:00", "Food Drop": "NO"},
    {"Origin Site": "26/00078 Yang Ah Kang", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 5, "Time Deadline": "21:00", "Food Drop": "NO"},
    {"Origin Site": "J105 - 268A Boon Lay Dr", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 5, "Time Deadline": "21:00", "Food Drop": "NO"},
    {"Origin Site": "J106 - Jurong West St 64", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 10, "Time Deadline": "21:00", "Food Drop": "NO"},
    {"Origin Site": "Punggol S11", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 3, "Time Deadline": "21:00", "Food Drop": "NO"},
    {"Origin Site": "GHPL - Lor Semangka", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 15, "Time Deadline": "22:00", "Food Drop": "YES"},
    {"Origin Site": "24/12205 MOE - BLSS", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 2, "Time Deadline": "22:00", "Food Drop": "YES"},
    {"Origin Site": "24/12212 MOE - CTSS", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 2, "Time Deadline": "22:00", "Food Drop": "YES"},
    {"Origin Site": "24/12233 MOE - MI", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 3, "Time Deadline": "22:00", "Food Drop": "YES"},
    {"Origin Site": "24/12201 MOE - ACJC (Dover)", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 10, "Time Deadline": "22:00", "Food Drop": "YES"},
    {"Origin Site": "26/00077 Micron - L and K", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 11, "Time Deadline": "22:00", "Food Drop": "YES"},
    {"Origin Site": "25/00070 Woh Hup", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 8, "Time Deadline": "22:00", "Food Drop": "YES"},
]

edited_df = st.data_editor(
    pd.DataFrame(default_data),
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "Origin Site": st.column_config.SelectboxColumn("Origin Site", options=site_options),
        "Job Type": st.column_config.SelectboxColumn("Job Type", options=["Standard Drop-off", "PJC-to-PJC Transfer"]),
        "Destination PJC": st.column_config.SelectboxColumn("Destination PJC", options=["N/A"] + site_options),
        "Pax": st.column_config.NumberColumn("Pax", min_value=0, max_value=30),
        "Time Deadline": st.column_config.SelectboxColumn("Time Deadline", options=["18:30", "19:00", "21:00", "22:00"]),
        "Food Drop": st.column_config.SelectboxColumn("Food Drop", options=["YES", "NO"]),
    }
)

if st.button("🚀 Run Dynamic Optimization"):
    df = edited_df.dropna(subset=["Origin Site"]).copy()
    df = df[df["Origin Site"] != ""]
    
    if df.empty:
        st.warning("Please enter valid site data.")
    else:
        df["Zone"] = df["Origin Site"].apply(lambda s: SITE_DATABASE.get(s, {}).get("zone", "West"))
        
        # Fleet database setup
        fleet = [
            {"id": "Senthil (10-ft)", "cap": 14, "home": "Central"},
            {"id": "Staff Driver 5 (10-ft)", "cap": 14, "home": "West"},
            {"id": "North Driver (10-ft)", "cap": 14, "home": "North"},
            {"id": "Pandi (14-ft)", "cap": 25, "home": "East"},
            {"id": "Mahendran (14-ft)", "cap": 25, "home": "West"},
        ]

        # 1. Food Drop Routing (5:00 PM HQ dispatch)
        food_jobs = df[df["Food Drop"] == "YES"]
        st.subheader("🍱 Step 1: 5:00 PM HQ Food Pickup & Site Delivery")
        food_table = []
        for _, row in food_jobs.iterrows():
            # Match home zone driver
            driver = next((d["id"] for d in fleet if d["home"] == row["Zone"]), "Pandi (14-ft)")
            food_table.append({
                "HQ Pick Time": "17:00",
                "Driver": driver,
                "Site": row["Origin Site"],
                "Pax to Feed": row["Pax"],
                "ETA Site": "18:00 - 18:30"
            })
        st.table(pd.DataFrame(food_table))

        # 2. PJC Transfers
        pjc_jobs = df[df["Job Type"] == "PJC-to-PJC Transfer"]
        st.subheader("🔄 Step 2: Early PJC-to-PJC Shuttle Runs")
        if not pjc_jobs.empty:
            pjc_table = []
            for _, row in pjc_jobs.iterrows():
                driver = "Staff Driver 5 (10-ft)" if row["Zone"] == "West" else "Senthil (10-ft)"
                pjc_table.append({
                    "Time": row["Time Deadline"],
                    "Driver": driver,
                    "From": row["Origin Site"],
                    "To": row["Destination PJC"],
                    "Pax": row["Pax"]
                })
            st.table(pd.DataFrame(pjc_table))
        else:
            st.info("No PJC Transfers found.")

        # 3. Dynamic Bin-Packing Allocation for Standard Runs
        st.subheader("🚌 Step 3: Dynamic Capacity-Optimized Pickup Schedule")
        
        std_jobs = df[df["Job Type"] == "Standard Drop-off"].copy()
        time_slots = sorted(std_jobs["Time Deadline"].unique())
        
        assigned_runs = []

        for slot in time_slots:
            slot_jobs = std_jobs[std_jobs["Time Deadline"] == slot]
            
            # Reset driver capacities for this time slot
            driver_states = {d["id"]: {"cap_left": d["cap"], "home": d["home"]} for d in fleet}
            
            for _, job in slot_jobs.iterrows():
                j_pax = job["Pax"]
                j_zone = job["Zone"]
                
                # Priority 1: Match zone driver with capacity
                best_driver = None
                for d_id, state in driver_states.items():
                    if state["home"] == j_zone and state["cap_left"] >= j_pax:
                        best_driver = d_id
                        break
                
                # Priority 2: If primary driver full/overloaded, find floating 14-ft relief driver
                if not best_driver:
                    for d_id in ["Pandi (14-ft)", "Mahendran (14-ft)"]:
                        if driver_states[d_id]["cap_left"] >= j_pax:
                            best_driver = d_id
                            break
                            
                # Fallback: Assign to highest remaining capacity
                if not best_driver:
                    best_driver = max(driver_states, key=lambda k: driver_states[k]["cap_left"])

                # Update driver available capacity state
                driver_states[best_driver]["cap_left"] -= j_pax
                
                assigned_runs.append({
                    "Time Deadline": slot,
                    "Assigned Driver": best_driver,
                    "Site Name": job["Origin Site"],
                    "Zone": j_zone,
                    "Pax": j_pax,
                    "Food Drop": job["Food Drop"]
                })

        schedule_df = pd.DataFrame(assigned_runs)

        for d in [df_item["id"] for df_item in fleet]:
            d_runs = schedule_df[schedule_df["Assigned Driver"] == d]
            if not d_runs.empty:
                st.markdown(f"#### 🚛 {d}")
                st.table(d_runs[["Time Deadline", "Site Name", "Zone", "Pax", "Food Drop"]].reset_index(drop=True))
