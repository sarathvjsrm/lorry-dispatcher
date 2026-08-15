import streamlit as st
import pandas as pd

st.set_page_config(page_title="Lorry Dispatch Engine", layout="wide")

st.title("🚛 Master Dispatch & OT Rotation Engine")
st.write("Real-world driver schedules, route grouping, and daily OT fairness tracker.")

# --- SIDEBAR: OT ROTATION TRACKER ---
st.sidebar.header("⚖️ Daily OT Fairness Tracker")
st.sidebar.write("Track who gets 10 PM OT runs to rotate drivers fairly tomorrow:")

driver_ot_today = {
    "Pandi (14-ft)": "10 PM (Dover - 14 pax)",
    "Mahendran (14-ft)": "10 PM (GHPL - 20 pax)",
    "Kaling (14-ft)": "10 PM (Woh Hup)",
    "Senthil (10-ft)": "10 PM (Micron)",
    "Sridhar (14-ft)": "9 PM (Punggol S11) ⚠️ Priority for 10 PM Tomorrow!"
}

for driver, status in driver_ot_today.items():
    if "Priority" in status:
        st.sidebar.warning(f"**{driver}**\n{status}")
    else:
        st.sidebar.success(f"**{driver}**\n{status}")

# --- MAIN SCHEDULE DISPLAY ---
st.subheader("📋 Complete Dispatch Master Plan")

schedule_data = [
    {
        "Driver": "Pandi (14-ft)",
        "Shift / Time": "7:00 PM",
        "Site / Task": "Sunview Drive + GS ITTC",
        "Operational Plan": "Pick both 7 PM sites. Reaches HQ ~8:00 PM."
    },
    {
        "Driver": "Pandi (14-ft)",
        "Shift / Time": "9:00 PM",
        "Site / Task": "Wuxi (1 pax)",
        "Operational Plan": "Quick 10-min run from HQ. Back at HQ by ~9:10 PM."
    },
    {
        "Driver": "Pandi (14-ft)",
        "Shift / Time": "10:00 PM",
        "Site / Task": "Dover 24/12201 (14 pax)",
        "Operational Plan": "Fetch 10 PM workers and return to Dorm."
    },
    {
        "Driver": "Mahendran (14-ft)",
        "Shift / Time": "18:00 / Food",
        "Site / Task": "Dover (24/12201) Food Drop",
        "Operational Plan": "Deliver dinner to Dover site before 18:45."
    },
    {
        "Driver": "Mahendran (14-ft)",
        "Shift / Time": "7:00 PM",
        "Site / Task": "MOE 24/12207 & 24/12239",
        "Operational Plan": "Fetch both MOE 7 PM sites together."
    },
    {
        "Driver": "Mahendran (14-ft)",
        "Shift / Time": "10:00 PM",
        "Site / Task": "GHPL (20 pax)",
        "Operational Plan": "Fetch 20 pax (Full 14-ft lorry load) and return to Dorm."
    },
    {
        "Driver": "Sridhar (14-ft)",
        "Shift / Time": "18:00 / Food",
        "Site / Task": "Work Up → Micron → GHPL",
        "Operational Plan": "3-site food drop loop before 18:45."
    },
    {
        "Driver": "Sridhar (14-ft)",
        "Shift / Time": "9:00 PM",
        "Site / Task": "Punggol S11 (10 pax)",
        "Operational Plan": "Direct East highway run. *Rotated to 10 PM OT tomorrow!*"
    },
    {
        "Driver": "Kaling (14-ft)",
        "Shift / Time": "7:00 PM",
        "Site / Task": "J105 (7 pax)",
        "Operational Plan": "Fetch 7 PM workers."
    },
    {
        "Driver": "Kaling (14-ft)",
        "Shift / Time": "10:00 PM",
        "Site / Task": "Woh Hup (10 PM)",
        "Operational Plan": "Drive to Woh Hup, wait for 10 PM scan, return to Dorm (~50 mins)."
    },
    {
        "Driver": "Senthil (10-ft)",
        "Shift / Time": "16:30",
        "Site / Task": "MOE Shifting / Transfer",
        "Operational Plan": "Early shifting run."
    },
    {
        "Driver": "Senthil (10-ft)",
        "Shift / Time": "10:00 PM",
        "Site / Task": "Micron (10 PM)",
        "Operational Plan": "Fetch 10 PM workers (Max capacity 14 pax)."
    },
    {
        "Driver": "Staff Driver 1",
        "Shift / Time": "7:00 PM",
        "Site / Task": "J106 (Proj: 24/00199)",
        "Operational Plan": "Dedicated 7 PM pickup run."
    },
    {
        "Driver": "Staff Driver 2",
        "Shift / Time": "9:00 PM",
        "Site / Task": "J115A → Yang Ah Kang",
        "Operational Plan": "Pick J115A first, then Yang Ah Kang (15 min gap OK). Reach Dorm ~9:35 PM."
    }
]

df_master = pd.DataFrame(schedule_data)
st.table(df_master)
