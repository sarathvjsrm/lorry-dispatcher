import streamlit as st
import pandas as pd

st.set_page_config(page_title="Lorry Dispatch Engine", layout="wide")
st.title("🚛 Operational Lorry Dispatch Engine")

# 1. Master Zone Database
SITE_DATABASE = {
    "24/12233 MOE - MI": "Central",
    "24/12201 MOE - ACJC (Dover)": "Central",
    "24/12239 MOE - PEPS": "Central",
    "24/12219 MOE - HPPS": "Central",
    "GHPL - Lor Semangka": "West",
    "24/12205 MOE - BLSS": "West",
    "24/12212 MOE - CTSS": "West",
    "26/00078 Yang Ah Kang": "West",
    "J105 - 268A Boon Lay Dr": "West",
    "J106 - Jurong West St 64": "West",
    "J115A - Nanyang Dr": "West",
    "22/00042 ITTC-GS": "West",
    "26/00017 WUXI": "West",
    "24/12204 MOE - BLGPS": "West",
    "26/00077 Micron - L and K": "North",
    "25/00070 Woh Hup": "North",
    "Punggol S11": "East",
}

site_list = sorted(list(SITE_DATABASE.keys()))

# 2. Driver & Vehicle Specs
DRIVERS = [
    {"name": "Senthil (10-ft)", "cap": 14, "home": "Central"},
    {"name": "Staff Driver 5 (10-ft)", "cap": 14, "home": "West"},
    {"name": "North Driver (10-ft)", "cap": 14, "home": "North"},
    {"name": "Pandi (14-ft)", "cap": 25, "home": "East"},
    {"name": "Mahendran (14-ft)", "cap": 25, "home": "West"},
]

# 3. Default Input Dataset
default_rows = [
    {"Origin Site": "24/12204 MOE - BLGPS", "Job Type": "PJC-to-PJC Transfer", "Destination PJC": "24/12201 MOE - ACJC (Dover)", "Pax": 3, "Deadline": "18:30", "Food Drop": "NO"},
    {"Origin Site": "24/12239 MOE - PEPS", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 1, "Deadline": "19:00", "Food Drop": "NO"},
    {"Origin Site": "24/12219 MOE - HPPS", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 3, "Deadline": "19:00", "Food Drop": "NO"},
    {"Origin Site": "J115A - Nanyang Dr", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 5, "Deadline": "19:00", "Food Drop": "NO"},
    {"Origin Site": "22/00042 ITTC-GS", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 2, "Deadline": "19:00", "Food Drop": "NO"},
    {"Origin Site": "26/00017 WUXI", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 1, "Deadline": "19:00", "Food Drop": "NO"},
    {"Origin Site": "26/00078 Yang Ah Kang", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 5, "Deadline": "21:00", "Food Drop": "NO"},
    {"Origin Site": "J105 - 268A Boon Lay Dr", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 5, "Deadline": "21:00", "Food Drop": "NO"},
    {"Origin Site": "J106 - Jurong West St 64", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 10, "Deadline": "21:00", "Food Drop": "NO"},
    {"Origin Site": "Punggol S11", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 3, "Deadline": "21:00", "Food Drop": "NO"},
    {"Origin Site": "GHPL - Lor Semangka", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 15, "Deadline": "22:00", "Food Drop": "YES"},
    {"Origin Site": "24/12205 MOE - BLSS", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 2, "Deadline": "22:00", "Food Drop": "YES"},
    {"Origin Site": "24/12212 MOE - CTSS", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 2, "Deadline": "22:00", "Food Drop": "YES"},
    {"Origin Site": "24/12233 MOE - MI", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 3, "Deadline": "22:00", "Food Drop": "YES"},
    {"Origin Site": "24/12201 MOE - ACJC (Dover)", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 10, "Deadline": "22:00", "Food Drop": "YES"},
    {"Origin Site": "26/00077 Micron - L and K", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 11, "Deadline": "22:00", "Food Drop": "YES"},
    {"Origin Site": "25/00070 Woh Hup", "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 8, "Deadline": "22:00", "Food Drop": "YES"},
]

# Add extra blank rows for user editing
for _ in range(5):
    default_rows.append({"Origin Site": None, "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 0, "Deadline": "19:00", "Food Drop": "NO"})

st.subheader("📋 Dispatch Input Sheet")

edited_df = st.data_editor(
    pd.DataFrame(default_rows),
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "Origin Site": st.column_config.SelectboxColumn("Origin Site / PJC", options=site_list),
        "Job Type": st.column_config.SelectboxColumn("Job Type", options=["Standard Drop-off", "PJC-to-PJC Transfer"]),
        "Destination PJC": st.column_config.SelectboxColumn("Destination PJC", options=["N/A"] + site_list),
        "Pax": st.column_config.NumberColumn("Pax", min_value=0, max_value=30, default=0),
        "Deadline": st.column_config.SelectboxColumn("Time Deadline", options=["18:30", "19:00", "21:00", "22:00"]),
        "Food Drop": st.column_config.SelectboxColumn("Food Drop", options=["YES", "NO"]),
    }
)

if st.button("⚡ Generate Dispatch Schedule"):
    # Clean input data
    data = edited_df.dropna(subset=["Origin Site"]).copy()
    data = data[data["Origin Site"] != ""]

    if data.empty:
        st.warning("Please fill in job details.")
    else:
        data["Zone"] = data["Origin Site"].map(SITE_DATABASE).fillna("West")
        st.divider()

        # ---------------------------------------------------
        # PHASE 1: 5:00 PM HQ FOOD PICKUPS
        # ---------------------------------------------------
        st.subheader("🍱 Phase 1: 5:00 PM HQ Food Collection & Pre-Drops")
        food_jobs = data[data["Food Drop"] == "YES"].copy()

        if not food_jobs.empty:
            food_list = []
            for _, r in food_jobs.iterrows():
                # Assign primary zone driver
                if r["Pax"] > 14:
                    driver = "Mahendran (14-ft)"
                elif r["Zone"] == "Central":
                    driver = "Senthil (10-ft)"
                elif r["Zone"] == "North":
                    driver = "North Driver (10-ft)"
                else:
                    driver = "Staff Driver 5 (10-ft)"

                food_list.append({
                    "HQ Collect": "17:00",
                    "Assigned Driver": driver,
                    "Drop Location": r["Origin Site"],
                    "Zone": r["Zone"],
                    "Pax Meals": r["Pax"],
                    "ETA Site": "18:00 - 18:30"
                })
            st.table(pd.DataFrame(food_list))

        # ---------------------------------------------------
        # PHASE 2: PJC TRANSFERS
        # ---------------------------------------------------
        st.subheader("🔄 Phase 2: PJC-to-PJC Worker Transfers")
        pjc_jobs = data[data["Job Type"] == "PJC-to-PJC Transfer"].copy()

        if not pjc_jobs.empty:
            pjc_list = []
            for _, r in pjc_jobs.iterrows():
                driver = "Staff Driver 5 (10-ft)" if r["Zone"] == "West" else "Senthil (10-ft)"
                pjc_list.append({
                    "Shuttle Window": "18:00 - 18:45",
                    "Assigned Driver": driver,
                    "Pickup PJC": r["Origin Site"],
                    "Drop-off PJC": r["Destination PJC"],
                    "Pax": r["Pax"]
                })
            st.table(pd.DataFrame(pjc_list))
        else:
            st.info("No PJC transfers scheduled.")

        # ---------------------------------------------------
        # PHASE 3: EVENING PICKUPS BY DRIVER
        # ---------------------------------------------------
        st.subheader("🚌 Phase 3: Driver Run Sheets (Enforced Capacity)")

        std_jobs = data[data["Job Type"] == "Standard Drop-off"].copy()
        time_slots = sorted(std_jobs["Deadline"].unique())

        final_assignments = []

        for slot in time_slots:
            slot_data = std_jobs[std_jobs["Deadline"] == slot]

            # Track capacity remaining for each lorry in this time slot
            caps = {d["name"]: d["cap"] for d in DRIVERS}

            for _, job in slot_data.iterrows():
                pax = job["Pax"]
                zone = job["Zone"]
                assigned_driver = None

                # Rule 1: Single job > 14 pax must go to a 14-ft lorry
                if pax > 14:
                    for d_name in ["Mahendran (14-ft)", "Pandi (14-ft)"]:
                        if caps[d_name] >= pax:
                            assigned_driver = d_name
                            break

                # Rule 2: Match home zone driver if capacity allows
                if not assigned_driver:
                    for d in DRIVERS:
                        if d["home"] == zone and caps[d["name"]] >= pax:
                            assigned_driver = d["name"]
                            break

                # Rule 3: Overflow goes to floating 14-ft lorries
                if not assigned_driver:
                    for d_name in ["Pandi (14-ft)", "Mahendran (14-ft)"]:
                        if caps[d_name] >= pax:
                            assigned_driver = d_name
                            break

                # Rule 4: Final fallback to lorry with most space
                if not assigned_driver:
                    assigned_driver = max(caps, key=caps.get)

                # Deduct capacity
                caps[assigned_driver] -= pax

                final_assignments.append({
                    "Driver": assigned_driver,
                    "Deadline": slot,
                    "Site Name": job["Origin Site"],
                    "Zone": zone,
                    "Pax": pax,
                    "Food Drop": job["Food Drop"]
                })

        schedule_df = pd.DataFrame(final_assignments)

        # Output grouped neatly by Driver
        for d in DRIVERS:
            d_name = d["name"]
            d_runs = schedule_df[schedule_df["Driver"] == d_name]
            if not d_runs.empty:
                st.markdown(f"#### 🚛 {d_name}")
                st.table(d_runs[["Deadline", "Site Name", "Zone", "Pax", "Food Drop"]].reset_index(drop=True))
