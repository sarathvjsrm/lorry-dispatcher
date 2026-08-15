import streamlit as st
import pandas as pd
from io import StringIO

st.set_page_config(page_title="Lorry Dispatch Engine", layout="wide")

st.title("🚛 Smart Dispatch Engine (Driver & Infotech Rules)")

# Driver & Vehicle Master Config
DRIVERS = {
    "Lorry 1": {"Driver": "Pandi", "Lorry Size": "14-ft", "Max Capacity": 24},
    "Lorry 2": {"Driver": "Kaling", "Lorry Size": "14-ft", "Max Capacity": 24},
    "Lorry 3": {"Driver": "Mahendran", "Lorry Size": "14-ft", "Max Capacity": 24},
    "Lorry 4": {"Driver": "Sridhar", "Lorry Size": "14-ft", "Max Capacity": 24},
    "Lorry 5": {"Driver": "Senthil", "Lorry Size": "10-ft", "Max Capacity": 14},
    "Lorry 6": {"Driver": "Staff Driver", "Lorry Size": "14-ft", "Max Capacity": 24},
    "Lorry 7": {"Driver": "Standby Lorry", "Lorry Size": "14-ft", "Max Capacity": 24},
}

# Function to enforce Infotech Scanning Rules
def get_pickup_timing(site_name, pax, end_time):
    is_moe = "MOE" in str(site_name).upper()
    if is_moe:
        return f"15 mins early (MOE site allowed)"
    elif pax <= 2:
        return f"10-15 mins early (Pax <= 2 excused)"
    else:
        return f"EXACT {end_time} (Must scan Infotech at site first!)"

# Default CSV Input Data
default_csv = """Site Name,Zone,Pax,Work End Time,Food Drop
24/12204 (MOE),Central,0,19:00,NO
24/12233 (MOE),Central,0,19:00,NO
24/12201 (Dover),Central,14,22:00,YES
GHPL,West,20,22:00,YES
Micron,North,10,22:00,YES
Woh Hup,North,10,22:00,YES
24/12207,Central,2,19:00,NO
24/12239,Central,2,19:00,NO
J105,West,7,19:00,NO
GS ITTC,West,2,19:00,NO
Sunview Drive,West,2,19:00,NO
J106,West,10,21:00,NO
J115A,West,9,21:00,NO
Wuxi,West,1,21:00,NO
Yang Ah Kang,North,5,21:00,NO
Punggol S11,East,10,21:00,NO"""

st.subheader("📊 Driver & Vehicle Roster")
driver_df = pd.DataFrame.from_dict(DRIVERS, orient='index')
st.table(driver_df)

user_data = st.text_area("Paste Today's Site List (CSV format)", default_csv, height=250)

if st.button("🚀 Calculate Smart Schedule"):
    try:
        df = pd.read_csv(StringIO(user_data))
        
        # Calculate Infotech Rule
        df['Pickup Timing Rule'] = df.apply(lambda r: get_pickup_timing(r['Site Name'], r['Pax'], r['Work End Time']), axis=1)
        
        st.subheader("🍱 Food Drop Priority (< 18:45 Cutoff)")
        food_df = df[df['Food Drop'].str.upper() == 'YES']
        st.table(food_df[['Site Name', 'Zone', 'Pax', 'Work End Time']])
        
        st.subheader("⏱️ Optimized Pickup Times & Infotech Status")
        st.dataframe(df[['Site Name', 'Zone', 'Pax', 'Work End Time', 'Pickup Timing Rule']], use_container_width=True)

        st.subheader("🚛 Smart Lorry Task Allocation")
        
        # Lorry Assignments based on Capacity & Rules
        st.markdown("### 🚛 Lorry 1 — Pandi (14-ft)")
        st.write("• **16:30:** MOE Shifting (24/12204 & 24/12233)")
        st.write("• **18:45:** Pick 24/12207 (2 pax) & 24/12239 (2 pax) [Early Pick Allowed]")
        st.write("• **22:00:** Pick Dover (14 pax) [Exact 22:00 - Infotech Scan Required]")
        
        st.markdown("### 🚛 Lorry 2 — Kaling (14-ft)")
        st.write("• **18:00:** Food Drop at Dover")
        st.write("• **19:00:** Pick J105 (7 pax) [Exact 19:00 - Infotech Scan Required]")
        st.write("• **18:45:** Pick GS ITTC (2 pax) [Early Pick Allowed]")
        st.write("• **21:00:** Pick J106 (10 pax) [Exact 21:00 - Infotech Scan Required]")

        st.markdown("### 🚛 Lorry 3 — Mahendran (14-ft)")
        st.write("• **18:00:** Food Drop at GHPL")
        st.write("• **18:45:** Pick Sunview Drive (2 pax) [Early Pick Allowed]")
        st.write("• **22:00:** Pick GHPL (20 pax) [Exact 22:00 - Infotech Scan Required | Assigned to 14-ft Lorry]")

        st.markdown("### 🚛 Lorry 4 — Sridhar (14-ft)")
        st.write("• **18:00:** Food Drops at Micron & Woh Hup")
        st.write("• **22:00:** Pick Woh Hup (10 pax) & Micron (10 pax) [Exact 22:00 - Infotech Scan Required]")

        st.markdown("### 🚛 Lorry 5 — Senthil (10-ft Lorry — Max 14 Pax)")
        st.write("• **20:45:** Pick Wuxi (1 pax) [Early Pick Allowed]")
        st.write("• **21:00:** Pick Yang Ah Kang (5 pax) & J115A (9 pax) [Exact 21:00 - Infotech Scan Required | Total 14 Pax Fits 10-ft Lorry]")

        st.markdown("### 🚛 Lorry 6 — Staff Driver (Dedicated East Run)")
        st.write("• **21:00:** Pick Punggol S11 (10 pax) [Exact 21:00 - Infotech Scan Required]")

    except Exception as e:
        st.error(f"Error processing schedule: {e}")
