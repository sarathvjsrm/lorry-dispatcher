import streamlit as st
import pandas as pd

st.set_page_config(page_title="Auto-Zone Lorry Dispatcher", layout="wide")

st.title("🚛 Smart Lorry Dispatcher (Auto-Zone Lookup)")
st.write("Pick sites from the dropdown list, key in workers and end times. The engine auto-assigns zones and optimizes lorry schedules.")

# --- MASTER SITE DATABASE (Auto-Zone Lookup) ---
# Add any new sites and their zones here in the future
SITE_MASTER_DB = {
    "24/12204 (MOE)": "Central",
    "24/12233 (MOE)": "Central",
    "24/12201 (Dover)": "Central",
    "24/12207": "Central",
    "24/12239": "Central",
    "GHPL": "West",
    "J105": "West",
    "GS ITTC": "West",
    "Sunview Drive": "West",
    "J106 (24/00199)": "West",
    "J115A": "West",
    "Wuxi": "West",
    "Micron": "North",
    "Woh Hup": "North",
    "Work Up": "North",
    "Yang Ah Kang": "North",
    "Punggol S11": "East",
}

site_options = list(SITE_MASTER_DB.keys())

# --- DEFAULT DAILY INPUT TABLE ---
default_rows = [
    {"Site Name": "24/12204 (MOE)", "Pax": 0, "Work End Time": "19:00", "Food Drop": "NO"},
    {"Site Name": "24/12233 (MOE)", "Pax": 0, "Work End Time": "19:00", "Food Drop": "NO"},
    {"Site Name": "24/12201 (Dover)", "Pax": 14, "Work End Time": "22:00", "Food Drop": "YES"},
    {"Site Name": "GHPL", "Pax": 20, "Work End Time": "22:00", "Food Drop": "YES"},
    {"Site Name": "Micron", "Pax": 10, "Work End Time": "22:00", "Food Drop": "YES"},
    {"Site Name": "Woh Hup", "Pax": 10, "Work End Time": "22:00", "Food Drop": "YES"},
    {"Site Name": "24/12207", "Pax": 2, "Work End Time": "19:00", "Food Drop": "NO"},
    {"Site Name": "24/12239", "Pax": 2, "Work End Time": "19:00", "Food Drop": "NO"},
    {"Site Name": "J105", "Pax": 7, "Work End Time": "19:00", "Food Drop": "NO"},
    {"Site Name": "GS ITTC", "Pax": 2, "Work End Time": "19:00", "Food Drop": "NO"},
    {"Site Name": "Sunview Drive", "Pax": 2, "Work End Time": "19:00", "Food Drop": "NO"},
    {"Site Name": "J106 (24/00199)", "Pax": 10, "Work End Time": "19:00", "Food Drop": "NO"},
    {"Site Name": "J115A", "Pax": 9, "Work End Time": "21:00", "Food Drop": "NO"},
    {"Site Name": "Wuxi", "Pax": 1, "Work End Time": "21:00", "Food Drop": "NO"},
    {"Site Name": "Yang Ah Kang", "Pax": 5, "Work End Time": "21:00", "Food Drop": "NO"},
    {"Site Name": "Punggol S11", "Pax": 10, "Work End Time": "21:00", "Food Drop": "NO"},
]

st.subheader("📋 Select Sites & Enter Today's Operational Details")

df_input = pd.DataFrame(default_rows)

# Interactive editor with dropdown menu for Site Names
edited_df = st.data_editor(
    df_input,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "Site Name": st.column_config.SelectboxColumn("Site Name", options=site_options, required=True),
        "Pax": st.column_config.NumberColumn("Pax (Workers)", min_value=0, max_value=30, step=1, default=0),
        "Work End Time": st.column_config.SelectboxColumn("Work End Time", options=["19:00", "21:00", "22:00", "16:30"], required=True),
        "Food Drop": st.column_config.SelectboxColumn("Food Drop", options=["YES", "NO"], required=True),
    }
)

# --- AUTOMATIC CALCULATION & DISPATCH ENGINE ---
if st.button("🚀 Auto-Assign Zones & Generate Dispatch Schedule"):
    
    # Auto-assign Zone based on Site Database
    edited_df["Zone"] = edited_df["Site Name"].map(SITE_MASTER_DB).fillna("Unknown")

    # Determine Infotech Scanning Timing Rule
    def timing_rule(row):
        site = str(row["Site Name"]).upper()
        pax = row["Pax"]
        end_time = row["Work End Time"]
        
        if "MOE" in site:
            return "15 Mins Early (MOE Allowed)"
        elif pax <= 2:
            return "15 Mins Early (Pax <= 2 Excused)"
        else:
            return f"EXACT {end_time} (Must Scan Infotech at Site)"

    edited_df["Timing Rule"] = edited_df.apply(timing_rule, axis=1)

    # Sidebar OT Tracking
    st.sidebar.header("⚖️ Live Driver OT Status")
    ot_10pm = edited_df[edited_df["Work End Time"] == "22:00"]
    
    for _, row in ot_10pm.iterrows():
        pax = row["Pax"]
        site = row["Site Name"]
        if pax > 14:
            st.sidebar.success(f"**{site} ({pax} pax)**\n👉 Must use 14-ft Lorry (Mahendran / Pandi)")
        else:
            st.sidebar.info(f"**{site} ({pax} pax)**\n👉 Can use 10-ft (Senthil) or 14-ft Lorry")

    st.sidebar.warning("⚠️ **OT Rule:** Sridhar (9 PM today) gets priority for 10 PM OT tomorrow!")

    # Master Output Display
    st.divider()
    st.subheader("📍 Auto-Zoned Daily Site List")
    st.dataframe(edited_df[["Site Name", "Zone", "Pax", "Work End Time", "Food Drop", "Timing Rule"]], use_container_width=True)

    # Shifts Breakdown
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("### 🟢 7:00 PM Pickups")
        p7 = edited_df[edited_df["Work End Time"] == "19:00"]
        st.table(p7[["Site Name", "Zone", "Pax", "Timing Rule"]])

    with col2:
        st.markdown("### 🟡 9:00 PM Pickups")
        p9 = edited_df[edited_df["Work End Time"] == "21:00"]
        st.table(p9[["Site Name", "Zone", "Pax", "Timing Rule"]])

    with col3:
        st.markdown("### 🔴 10:00 PM Pickups (Max OT)")
        p10 = edited_df[edited_df["Work End Time"] == "22:00"]
        st.table(p10[["Site Name", "Zone", "Pax", "Timing Rule"]])
