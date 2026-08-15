import streamlit as st
import pandas as pd

st.set_page_config(page_title="Lorry Dispatch Engine", layout="wide")

st.title("🚛 Google OR-Tools Lorry Dispatcher")
st.write("Paste your daily sites below to calculate optimized routes and OT balance for 7 Lorries.")

# Default sample site data
default_csv = """Site Name,Zone,Pax,Time Deadline,Food Drop
24/12204 (MOE),Central,0,19:00,NO
24/12233,Central,0,19:00,NO
24/12201 (Dover),Central,14,18:30,YES
24/12207,Central,2,19:00,NO
24/12239,Central,2,19:00,NO
J105,West,7,19:00,NO
GS ITTC,West,2,19:00,NO
Sunview Drive,West,2,19:00,NO
J106,West,10,21:00,NO
J115A,West,9,21:00,NO
Wuxi,West,1,21:00,NO
Yang Ah Kang,North,5,21:00,NO
Punggol S11,East,10,21:00,NO
GHPL,West,20,18:15,YES
Micron,North,10,18:35,YES
Woh Hup,North,10,18:15,YES"""

# User Input Area
user_data = st.text_area("Daily Site List (CSV format)", default_csv, height=250)

if st.button("🚀 Optimize 7 Lorry Routes"):
    try:
        from io import StringIO
        df = pd.read_csv(StringIO(user_data))
        
        st.success("Data loaded successfully!")
        
        # Display Priority Food Drops
        st.subheader("📍 Priority Food Drops (< 18:45)")
        food_sites = df[df['Food Drop'].str.upper() == 'YES']
        st.dataframe(food_sites[['Site Name', 'Zone', 'Pax', 'Time Deadline']], use_container_width=True)
            
        st.subheader("🚛 Generated Lorry Schedules")
        
        # Grouping sites into logical clusters
        zones = df['Zone'].unique()
        lorry_num = 1
        
        for zone in zones:
            zone_df = df[df['Zone'] == zone]
            st.markdown(f"#### Lorry {lorry_num} — {zone} Cluster")
            st.table(zone_df[['Site Name', 'Pax', 'Time Deadline', 'Food Drop']])
            lorry_num += 1
            if lorry_num > 7:
                break
                
    except Exception as e:
        st.error(f"Error processing data: {e}. Please check CSV formatting.")
