import streamlit as st
import pandas as pd

st.set_page_config(page_title="Chained Food & Pickup Engine", layout="wide")

st.title("🚛 Chained Dispatch Engine (5:00 PM Food HQ ➡️ 7:00 PM Worker Pickup)")

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

blank_rows = [
    {"Site Name": None, "Pax": 0, "Time Deadline": "19:00", "Food Drop": "NO"}
    for _ in range(15)
]

st.subheader("📋 Dispatch Input")

edited_df = st.data_editor(
    pd.DataFrame(blank_rows),
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "Site Name": st.column_config.SelectboxColumn("Site Name", options=site_options),
        "Pax": st.column_config.NumberColumn("Pax", min_value=0, max_value=30, default=0),
        "Time Deadline": st.column_config.TextColumn("Time Deadline", default="19:00"),
        "Food Drop": st.column_config.SelectboxColumn("Food Drop", options=["YES", "NO"], default="NO"),
    }
)

if st.button("🚀 Calculate Optimized Food & Worker Route"):
    df = edited_df.dropna(subset=["Site Name"]).copy()
    df = df[df["Site Name"] != ""]
    
    if df.empty:
        st.warning("Please enter site details.")
    else:
        df["Zone"] = df["Site Name"].apply(lambda s: SITE_DATABASE.get(s, {}).get("zone", "West"))
        
        st.divider()
        st.subheader("🍱 Step 1: 5:00 PM HQ Food Pickups & Pre-Drop Runs (Arrive 5:45 PM – 6:30 PM)")
        
        food_sites = df[df["Food Drop"] == "YES"].copy()
        
        if not food_sites.empty:
            food_summary = []
            for _, row in food_sites.iterrows():
                assigned_driver = "Senthil (10-ft)" if row["Zone"] == "Central" else (
                    "North Driver (10-ft)" if row["Zone"] == "North" else "Mahendran (14-ft)"
                )
                food_summary.append({
                    "HQ Collect Time": "17:00",
                    "Assigned Driver": assigned_driver,
                    "Target Drop Site": row["Site Name"],
                    "Zone": row["Zone"],
                    "Est. Site Arrival": "18:00 - 18:30 (Before Dinner)",
                    "Next Action": f"Wait on-site for {row['Time Deadline']} Pickup"
                })
            st.table(pd.DataFrame(food_summary))
        else:
            st.info("No food drop required for today's sites.")

        st.subheader("🚌 Step 2: Linked Worker Pickups & Dorm Drop-Offs")
        
        df["Driver / Action"] = ""
        for idx, row in df.iterrows():
            d_name = "Senthil (10-ft)" if row["Zone"] == "Central" else (
                "North Driver (10-ft)" if row["Zone"] == "North" else (
                    "Pandi (14-ft)" if row["Zone"] == "East" else "Staff Driver 5 / Mahendran"
                )
            )
            
            if row["Food Drop"] == "YES" and row["Time Deadline"] in ["18:30", "19:00"]:
                df.loc[idx, "Driver / Action"] = f"🍱 {d_name} (Delivered food at 18:15 ➡️ Pick up workers at {row['Time Deadline']})"
            else:
                df.loc[idx, "Driver / Action"] = f"🚌 {d_name} (Standard Pickup run at {row['Time Deadline']})"

        st.table(df[["Site Name", "Zone", "Pax", "Time Deadline", "Food Drop", "Driver / Action"]].reset_index(drop=True))
