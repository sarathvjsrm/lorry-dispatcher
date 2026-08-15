import streamlit as st
import pandas as pd

st.set_page_config(page_title="Lorry Dispatcher - Site Database Integration", layout="wide")

st.title("🚛 Master Lorry Dispatcher Engine")
st.write("Select sites from the drop-down menu for today's jobs. Key in **Pax** and **Work End Time** across the 25 rows below.")

# --- MASTER DATABASE FROM EXCEL SHEET ---
SITE_DATABASE = {
    "17/00212N C883 Dismantle": {"address": "Keppel", "travel_min": 55, "zone": "Central"},
    "21/00217 Bulim Square": {"address": "Jurong West", "travel_min": 42, "zone": "West"},
    "22/00042 ITTC-GS": {"address": "Tuas Check Point", "travel_min": 22, "zone": "West"},
    "22/00299 Kienta - D2017 Dismantle": {"address": "Lower Seletar cl", "travel_min": 67, "zone": "North"},
    "23/00075 JEL (Dismantle)": {"address": "Jurong Island", "travel_min": 27, "zone": "West"},
    "23/00274 C883 China State Construction": {"address": "Raeburn park", "travel_min": 55, "zone": "Central"},
    "24/00024 JEL Keppel sakara": {"address": "Jurong Island", "travel_min": 27, "zone": "West"},
    "24/00072 Wee Hur": {"address": "Soon lee road", "travel_min": 27, "zone": "West"},
    "24/00109 Tee Up- PPTL": {"address": "8 Seletar North link", "travel_min": 55, "zone": "North"},
    "24/00115 China State": {"address": "Cantonment Station", "travel_min": 55, "zone": "Central"},
    "24/00122 MOE Princess Elizabeth": {"address": "30 Bukit Batok West Ave 3", "travel_min": 37, "zone": "Central"},
    "24/00208 Takenaka VSMC": {"address": "Tampines Int Ave 2", "travel_min": 79, "zone": "East"},
    "24/00235 S11 - PPTL1B": {"address": "2 Seletar North link", "travel_min": 74, "zone": "North"},
    "24/12201 MOE - ACJC (Dover)": {"address": "25 Dover Close", "travel_min": 41, "zone": "Central"},
    "24/12202 MOE - AES": {"address": "622 Upper Bukit Timah", "travel_min": 34, "zone": "North"},
    "24/12203 MOE - APS": {"address": "30 Cashew Road", "travel_min": 44, "zone": "North"},
    "24/12204 MOE - BLGPS": {"address": "20 Boon Lay Drive", "travel_min": 34, "zone": "West"},
    "24/12205 MOE - BLSS": {"address": "11 Jurong West Street", "travel_min": 28, "zone": "West"},
    "24/12206 MOE - BBSS": {"address": "50 Bukit Batok West Ave", "travel_min": 36, "zone": "Central"},
    "24/12207 MOE - BTPS": {"address": "111 Lorong Kismis", "travel_min": 41, "zone": "Central"},
    "24/12208 MOE - BVPS": {"address": "18 Bukit Batok Street", "travel_min": 39, "zone": "Central"},
    "24/12209 MOE - BVSS": {"address": "16 Bukit Batok Street", "travel_min": 38, "zone": "Central"},
    "24/12210 MOE - CHIJ": {"address": "4 Chestnut Drive", "travel_min": 44, "zone": "North"},
    "24/12211 MOE - CPS": {"address": "8 Clementi Avenue 3", "travel_min": 36, "zone": "West"},
    "24/12212 MOE - CTSS": {"address": "10 Clementi Avenue 3", "travel_min": 35, "zone": "West"},
    "24/12213 MOE - CWSS": {"address": "698 West Coast Road", "travel_min": 34, "zone": "West"},
    "24/12214 MOE - COPS": {"address": "31 Jurong West Street", "travel_min": 30, "zone": "West"},
    "24/12215 MOE - DFO": {"address": "30 Dairy Farm Road", "travel_min": 36, "zone": "North"},
    "24/12216 MOE - FPS": {"address": "20 Jurong West", "travel_min": 27, "zone": "West"},
    "24/12218 MOE - FHSS": {"address": "5 Jurong West", "travel_min": 34, "zone": "West"},
    "24/12219 MOE - HPPS": {"address": "1 Holland Grove", "travel_min": 39, "zone": "Central"},
    "24/12220 MOE - HYSS": {"address": "60 Jurong West Street", "travel_min": 33, "zone": "West"},
    "24/12222 MOE - JPS": {"address": "320 Jurong East", "travel_min": 35, "zone": "West"},
    "24/12223 MOE - JSS": {"address": "31 Yuan Ching Road", "travel_min": 32, "zone": "West"},
    "24/12224 MOE - JWPS": {"address": "30 Jurong West Street", "travel_min": 31, "zone": "West"},
    "24/12225 MOE - JWSS": {"address": "61 Jurong West Street", "travel_min": 27, "zone": "West"},
    "24/12226 MOE - JVSS": {"address": "202 Jurong East", "travel_min": 41, "zone": "West"},
    "24/12227 MOE - JYSS": {"address": "33 Jurong West", "travel_min": 20, "zone": "West"},
    "24/12228 MOE - KMPS": {"address": "90 Bukit Batok East Ave 6", "travel_min": 41, "zone": "Central"},
    "24/12230 MOE - LSPS": {"address": "161 Corporation Walk", "travel_min": 31, "zone": "West"},
    "24/12231 MGSP": {"address": "11 Blackmore Drive", "travel_min": 44, "zone": "Central"},
    "24/12232 MOE - MGSS": {"address": "Blackmore Dr", "travel_min": 41, "zone": "Central"},
    "24/12233 MOE - MI": {"address": "60 Bukit Batok", "travel_min": 35, "zone": "Central"},
    "24/12234 MOE - NHHS": {"address": "41 Clementi Avenue", "travel_min": 40, "zone": "West"},
    "24/12235 MOE - NHPS": {"address": "30 Jalan Lempeng", "travel_min": 34, "zone": "West"},
    "24/12237 PHPPS": {"address": "7 Pei Wah Avenue Ace", "travel_min": 43, "zone": "Central"},
    "24/12238 MOE - PPS": {"address": "31 Jurong West Street", "travel_min": 31, "zone": "West"},
    "24/12239 MOE - PEPS": {"address": "30 Bukit Batok West Ave 3", "travel_min": 28, "zone": "Central"},
    "25/00014 Sinohydro": {"address": "CR207 Clementi", "travel_min": 41, "zone": "West"},
    "25/00025 S11 - PPTL1B": {"address": "2 Seletar North link", "travel_min": 90, "zone": "North"},
    "25/00026 Loh & Loh": {"address": "23 Tembusu Rd (JI)", "travel_min": 20, "zone": "West"},
    "25/00033 S11 - Changi": {"address": "Changi Lodge 2", "travel_min": 80, "zone": "East"},
    "25/00038 Loh & Loh": {"address": "23 Tembusu Rd (JI)", "travel_min": 20, "zone": "West"},
    "25/00040 China Railway J101": {"address": "770 Jurong Road", "travel_min": 36, "zone": "West"},
    "25/00070 Woh Hup": {"address": "Woodland Checkpoint", "travel_min": 44, "zone": "North"},
    "25/00076 Innovente": {"address": "Tampines Ind Ave1", "travel_min": 76, "zone": "East"},
    "25/00076D Innovente": {"address": "Tampines Ind Ave1", "travel_min": 76, "zone": "East"},
    "25/00082 Aik Cuan Cons": {"address": "Kranji Lodge", "travel_min": 40, "zone": "North"},
    "25/00098 Chian Teck": {"address": "1 North Coast Drive", "travel_min": 60, "zone": "North"},
    "25/00105 Guan Joo": {"address": "Tuas South Ave 10", "travel_min": 19, "zone": "West"},
    "25/00143 Lum Chang-Micron": {"address": "Attap Valley Road", "travel_min": 49, "zone": "North"},
    "25/00154 AIPEC": {"address": "Tuas South Ave 12", "travel_min": 14, "zone": "West"},
    "25/00180 McConnell": {"address": "Dowell", "travel_min": 42, "zone": "West"},
    "25/00182 Hua Siah": {"address": "Clementi Loop", "travel_min": 39, "zone": "West"},
    "25/00185A Concord": {"address": "Jln Boonlay", "travel_min": 29, "zone": "West"},
    "25/00215 KWRP - Site Office": {"address": "10 Kranji Road", "travel_min": 50, "zone": "North"},
    "25/0037 Loh & Loh": {"address": "23 Tembusu Rd (JI)", "travel_min": 20, "zone": "West"},
    "26/00008 Tong Bee": {"address": "IBP Boonlay Way", "travel_min": 36, "zone": "West"},
    "26/00017 WUXI": {"address": "AIPEC - Tuas", "travel_min": 13, "zone": "West"},
    "26/00026 Ampcontrol": {"address": "Tanjong Pagar", "travel_min": 56, "zone": "Central"},
    "26/00046 AIK CHUAN": {"address": "Kranji Lodge", "travel_min": 51, "zone": "North"},
    "26/00077 Micron - L and K": {"address": "1 North Coast Drive", "travel_min": 48, "zone": "North"},
    "26/00078 Yang Ah Kang": {"address": "Tuas Ave2", "travel_min": 18, "zone": "West"},
    "J105 - 268A Boon Lay Dr": {"address": "268A Boon Lay Dr", "travel_min": 30, "zone": "West"},
    "J106 - Jurong West St 64": {"address": "Jurong West St 64", "travel_min": 29, "zone": "West"},
    "J115A - Nanyang Dr": {"address": "Nanyang Dr", "travel_min": 25, "zone": "West"},
    "GHPL - Lor Semangka": {"address": "Lor Semangka", "travel_min": 39, "zone": "West"},
    "Punggol S11": {"address": "Punggol East", "travel_min": 65, "zone": "East"},
}

site_dropdown_options = sorted(list(SITE_DATABASE.keys()))

# --- CREATE 25 BLANK INPUT ROWS ---
blank_rows = [
    {"Site Name": None, "Pax": 0, "Work End Time": "19:00", "Food Drop": "NO"}
    for _ in range(25)
]

st.subheader("📋 Enter Today's Schedule (25 Rows Available)")

df_input = pd.DataFrame(blank_rows)

# Interactive grid with Site Database Drop-down across 25 blank rows
edited_df = st.data_editor(
    df_input,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "Site Name": st.column_config.SelectboxColumn("Site Name (Database Dropdown)", options=site_dropdown_options, required=False),
        "Pax": st.column_config.NumberColumn("Pax (Workers)", min_value=0, max_value=30, step=1, default=0),
        "Work End Time": st.column_config.SelectboxColumn("Work End Time", options=["19:00", "21:00", "22:00", "16:30"], default="19:00"),
        "Food Drop": st.column_config.SelectboxColumn("Food Drop Required", options=["YES", "NO"], default="NO"),
    }
)

# --- AUTO-LOOKUP AND DISPATCH LOGIC ---
if st.button("🚀 Calculate Smart Routes & OT Plan"):
    
    # Filter out empty rows where no Site Name was selected
    active_df = edited_df.dropna(subset=["Site Name"]).copy()
    active_df = active_df[active_df["Site Name"] != ""]
    
    if active_df.empty:
        st.warning("⚠️ Please select at least one site from the drop-down before calculating!")
    else:
        # Auto-fetch Address, Travel Time, and Zone from SITE_DATABASE
        active_df["Address"] = active_df["Site Name"].apply(lambda s: SITE_DATABASE.get(s, {}).get("address", "Unknown"))
        active_df["Travel Time (min)"] = active_df["Site Name"].apply(lambda s: SITE_DATABASE.get(s, {}).get("travel_min", 40))
        active_df["Zone"] = active_df["Site Name"].apply(lambda s: SITE_DATABASE.get(s, {}).get("zone", "Central"))

        # Determine Infotech timing rules
        def determine_rule(row):
            site = str(row["Site Name"]).upper()
            pax = row["Pax"]
            end_time = row["Work End Time"]
            
            if "MOE" in site:
                return "Early Pickup OK (MOE Site)"
            elif pax <= 2:
                return "Early Pickup OK (Pax <= 2)"
            else:
                return f"EXACT {end_time} (Must Scan Infotech at Site)"

        active_df["Infotech Rule"] = active_df.apply(determine_rule, axis=1)

        # --- SIDEBAR: AUTOMATIC OT TRACKER ---
        st.sidebar.header("⚖️ Live Driver OT Rotation")
        st.sidebar.write("Calculated based on today's inputs:")
        
        p10_runs = active_df[active_df["Work End Time"] == "22:00"]
        if p10_runs.empty:
            st.sidebar.write("No 10 PM OT runs entered for today.")
        else:
            for idx, row in p10_runs.iterrows():
                pax = row["Pax"]
                site = row["Site Name"]
                if pax > 14:
                    st.sidebar.success(f"**{site} ({pax} pax)**\n👉 Assign 14-ft Lorry (Mahendran/Pandi)")
                else:
                    st.sidebar.info(f"**{site} ({pax} pax)**\n👉 Assign 10-ft (Senthil) or 14-ft Lorry")

        st.sidebar.warning("⚠️ **OT Fairness Rule:** Driver taking 9 PM run today gets priority for 10 PM OT tomorrow!")

        # --- MAIN TABLE DISPLAY ---
        st.divider()
        st.subheader("📊 Auto-Populated Active Dispatch Schedule")
        
        display_cols = ["Site Name", "Address", "Zone", "Pax", "Work End Time", "Travel Time (min)", "Food Drop", "Infotech Rule"]
        st.dataframe(active_df[display_cols], use_container_width=True)

        # --- TIME SLOTS DISPLAY ---
        col1, col2, col3 = st.columns(3)

        with col1:
            st.markdown("### 🟢 7:00 PM Pickups")
            p7 = active_df[active_df["Work End Time"] == "19:00"]
            if not p7.empty:
                st.table(p7[["Site Name", "Zone", "Pax", "Travel Time (min)"]])
            else:
                st.write("No 7 PM pickups scheduled.")

        with col2:
            st.markdown("### 🟡 9:00 PM Pickups")
            p9 = active_df[active_df["Work End Time"] == "21:00"]
            if not p9.empty:
                st.table(p9[["Site Name", "Zone", "Pax", "Travel Time (min)"]])
            else:
                st.write("No 9 PM pickups scheduled.")

        with col3:
            st.markdown("### 🔴 10:00 PM Pickups (Max OT)")
            p10 = active_df[active_df["Work End Time"] == "22:00"]
            if not p10.empty:
                st.table(p10[["Site Name", "Zone", "Pax", "Travel Time (min)"]])
            else:
                st.write("No 10 PM pickups scheduled.")
