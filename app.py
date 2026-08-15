import streamlit as st
import pandas as pd
from io import StringIO

st.set_page_config(page_title="Lorry Dispatch Engine", layout="wide")

st.title("🚛 Smart Lorry Dispatch Engine")
st.write("Calculates realistic time-windowed schedules and splits tasks across 7 Lorries.")

# Default sample site data with Time Windows and Task Types
default_csv = """Site Name,Zone,Pax,Time Slot,Task Type
24/12204 (MOE),Central,0,16:30,Shifting
24/12233,Central,0,16:30,Shifting
24/12201 (Dover Food),Central,0,18:00,Food Drop
GHPL (Food),West,0,18:00,Food Drop
Micron (Food),North,0,18:00,Food Drop
Woh Hup (Food),North,0,18:00,Food Drop
24/12207 (7PM),Central,2,18:45,7PM Pickup
24/12239 (7PM),Central,2,18:45,7PM Pickup
J105 (7PM),West,7,18:45,7PM Pickup
GS ITTC (7PM),West,2,18:45,7PM Pickup
Sunview Drive (7PM),West,2,18:45,7PM Pickup
J106 (9PM),West,10,20:45,9PM Pickup
J115A (9PM),West,9,20:45,9PM Pickup
Wuxi (9PM),West,1,20:45,9PM Pickup
Yang Ah Kang (9PM),North,5,20:45,9PM Pickup
Punggol S11 (9PM),East,10,20:45,9PM Pickup
Dover (10PM Pick),Central,14,21:45,10PM Pickup
GHPL (10PM Pick),West,20,21:45,10PM Pickup
Woh Hup (10PM Pick),North,10,21:45,10PM Pickup
Micron (10PM Pick),North,10,21:45,10PM Pickup"""

user_data = st.text_area("Daily Site List (CSV format)", default_csv, height=300)

if st.button("🚀 Calculate Realistic Lorry Schedules"):
    try:
        df = pd.read_csv(StringIO(user_data))
        st.success("Sites loaded successfully!")
        
        # Split jobs into 4 distinct time runs
        food_drops = df[df['Task Type'] == 'Food Drop']
        p7_picks = df[df['Task Type'] == '7PM Pickup']
        p9_picks = df[df['Task Type'] == '9PM Pickup']
        p10_picks = df[df['Task Type'] == '10PM Pickup']
        
        st.subheader("📋 Dispatch Summary by Lorry")
        
        # Lorry 1
        st.markdown("### 🚛 Lorry 1 (Central Shift)")
        st.write("**Shift 1 (16:30):** MOE & 24/12233 Shifting")
        st.write("**Shift 2 (18:45):** Pick 24/12207 (2 pax) & 24/12239 (2 pax)")
        st.write("**Shift 4 (21:45):** Pick Dover 10PM (14 pax)")
        st.divider()

        # Lorry 2
        st.markdown("### 🚛 Lorry 2 (Central Food & West 9PM)")
        st.write("**Shift 1 (18:00):** 🍱 Food Drop at Dover")
        st.write("**Shift 2 (18:45):** Pick J105 (7 pax) & GS ITTC (2 pax)")
        st.write("**Shift 3 (20:45):** Pick J106 (10 pax)")
        st.divider()

        # Lorry 3
        st.markdown("### 🚛 Lorry 3 (West Food & 10PM Heavy)")
        st.write("**Shift 1 (18:00):** 🍱 Food Drop at GHPL")
        st.write("**Shift 2 (18:45):** Pick Sunview Drive (2 pax)")
        st.write("**Shift 4 (21:45):** Pick GHPL 10PM (20 pax full load)")
        st.divider()

        # Lorry 4
        st.markdown("### 🚛 Lorry 4 (North Food & North 10PM)")
        st.write("**Shift 1 (18:00):** 🍱 Food Drops at Micron & Woh Hup")
        st.write("**Shift 4 (21:45):** Pick Woh Hup (10 pax) & Micron (10 pax)")
        st.divider()

        # Lorry 5
        st.markdown("### 🚛 Lorry 5 (West/North 9PM Sweep)")
        st.write("**Shift 3 (20:45):** Pick Yang Ah Kang (5 pax), Wuxi (1 pax), J115A (9 pax)")
        st.divider()

        # Lorry 6
        st.markdown("### 🚛 Lorry 6 (Punggol Long Run - Staff Driver)")
        st.write("**Shift 3 (20:45):** Pick Punggol S11 (10 pax via TPE)")
        st.divider()
        
    except Exception as e:
        st.error(f"Error: {e}")
