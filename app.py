import streamlit as st
import pandas as pd

st.set_page_config(page_title="Dynamic Lorry Dispatcher", layout="wide")

st.title("🚛 Dynamic Auto-Updating Dispatch Engine")
st.write("Edit or paste today's site details in the table below. The engine will automatically calculate optimal assignments and track driver OT!")

# --- DEFAULT INPUT TABLE DATA ---
default_data = [
    {"Site Name": "24/12204 (MOE)", "Zone": "Central", "Pax": 0, "Work End Time": "19:00", "Food Drop": "NO"},
    {"Site Name": "24/12233 (MOE)", "Zone": "Central", "Pax": 0, "Work End Time": "19:00", "Food Drop": "NO"},
    {"Site Name": "24/12201 (Dover)", "Zone": "Central", "Pax": 14, "Work End Time": "22:00", "Food Drop": "YES"},
    {"Site Name": "GHPL", "Zone": "West", "Pax": 20, "Work End Time": "22:00", "Food Drop": "YES"},
    {"Site Name": "Micron", "Zone": "North", "Pax": 10, "Work End Time": "22:00", "Food Drop": "YES"},
    {"Site Name": "Woh Hup", "Zone": "North", "Pax": 10, "Work End Time": "22:00", "Food Drop": "YES"},
    {"Site Name": "24/12207", "Zone": "Central", "Pax": 2, "Work End Time": "19:00", "Food Drop": "NO"},
    {"Site Name": "24/12239", "Zone": "Central", "Pax": 2, "Work End Time": "19:00", "Food Drop": "NO"},
    {"Site Name": "J105", "Zone": "West", "Pax": 7, "Work End Time": "19:00", "Food Drop": "NO"},
    {"Site Name": "GS ITTC", "Zone": "West", "Pax": 2, "Work End Time": "19:00", "Food Drop": "NO"},
    {"Site Name": "Sunview Drive", "Zone": "West", "Pax": 2, "Work End Time": "19:00", "Food Drop": "NO"},
    {"Site Name": "J106 (24/00199)", "Zone": "West", "Pax": 10, "Work End Time": "19:00", "Food Drop": "NO"},
    {"Site Name": "J115A", "Zone": "West", "Pax": 9, "Work End Time": "21:00", "Food Drop": "NO"},
    {"Site Name": "Wuxi", "Zone": "West", "Pax": 1, "Work End Time": "21:00", "Food Drop": "NO"},
    {"Site Name": "Yang Ah Kang", "Zone": "North", "Pax": 5, "Work End Time": "21:00", "Food Drop": "NO"},
    {"Site Name": "Punggol S11", "Zone": "East", "Pax": 10, "Work End Time": "21:00", "Food Drop": "NO"},
]

# Create editable data table
st.subheader("📝 Edit Today's Sites (Add/Delete/Change Pax or Times)")
df_input = pd.DataFrame(default_data)

# Interactive grid for user input
edited_df = st.data_editor(
    df_input,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "Food Drop": st.column_config.SelectboxColumn("Food Drop", options=["YES", "NO"]),
        "Zone": st.column_config.SelectboxColumn("Zone", options=["West", "North", "Central", "East"]),
        "Pax": st.column_config.NumberColumn("Pax", min_value=0, max_value=30),
    }
)

# --- DYNAMIC CALCULATION LOGIC ---
if st.button("⚡ Generate Auto-Updated Dispatch & OT Plan"):
    
    # 1. Apply Infotech timing rules dynamically
    def determine_timing_rule(row):
        site = str(row["Site Name"]).upper()
        pax = row["Pax"]
        end_time = row["Work End Time"]
        
        if "MOE" in site:
            return "Early Pick Allowed (MOE Site)"
        elif pax <= 2:
            return "Early Pick Allowed (Pax <= 2)"
        else:
            return f"EXACT {end_time} (Must scan Infotech at site)"

    edited_df["Infotech Rule"] = edited_df.apply(determine_timing_rule, axis=1)

    # 2. Extract 10 PM OT Sites dynamically for Driver OT Tracker
    ot_10pm_sites = edited_df[edited_df["Work End Time"].astype(str).str.contains("22:00|10 PM|10pm|22")]
    
    # --- SIDEBAR: DYNAMIC OT FAIRNESS TRACKER ---
    st.sidebar.header("⚖️ Live Daily OT Tracker")
    st.sidebar.write("Auto-calculated from today's inputs:")
    
    # Track who gets heavy 10 PM OT
    assigned_10pm_drivers = []
    
    for idx, row in ot_10pm_sites.iterrows():
        pax = row["Pax"]
        site = row["Site Name"]
        if pax > 14:
            driver_recommendation = f"Mahendran / Pandi (14-ft for {pax} pax)"
        else:
            driver_recommendation = f"Senthil / Kaling / Sridhar (Max {pax} pax)"
        st.sidebar.success(f"**{site} ({pax} pax)**\n👉 Assigned: {driver_recommendation}")

    st.sidebar.info("💡 **OT Rule:** Driver doing 9 PM today gets priority for 10 PM tomorrow!")

    # --- MAIN DISPATCH DISPLAY ---
    st.divider()
    st.subheader("📊 Auto-Calculated Site Rules Summary")
    st.dataframe(edited_df[["Site Name", "Zone", "Pax", "Work End Time", "Food Drop", "Infotech Rule"]], use_container_width=True)

    st.subheader("🚚 Dynamic Driver Assignments")

    # Group by Food Drops
    food_df = edited_df[edited_df["Food Drop"] == "YES"]
    if not food_df.empty:
        st.markdown("### 🍱 Pre-18:45 Food Deliveries")
        st.table(food_df[["Site Name", "Zone", "Work End Time"]])

    # Process 7 PM, 9 PM, 10 PM groups dynamically
    st.markdown("### ⏱️ Pickup Shifts")
    
    p7 = edited_df[edited_df["Work End Time"].astype(str).str.contains("19:00|7 PM|7pm|19")]
    p9 = edited_df[edited_df["Work End Time"].astype(str).str.contains("21:00|9 PM|9pm|21")]
    p10 = edited_df[edited_df["Work End Time"].astype(str).str.contains("22:00|10 PM|10pm|22")]
    
    col_a, col_b, col_c = st.columns(3)
    
    with col_a:
        st.markdown("#### 🟢 7:00 PM Pickups")
        if not p7.empty:
            st.table(p7[["Site Name", "Pax", "Zone"]])
        else:
            st.write("No 7 PM pickups today.")
            
    with col_b:
        st.markdown("#### 🟡 9:00 PM Pickups")
        if not p9.empty:
            st.table(p9[["Site Name", "Pax", "Zone"]])
        else:
            st.write("No 9 PM pickups today.")

    with col_c:
        st.markdown("#### 🔴 10:00 PM Pickups (Max OT)")
        if not p10.empty:
            st.table(p10[["Site Name", "Pax", "Zone"]])
        else:
            st.write("No 10 PM pickups today.")
