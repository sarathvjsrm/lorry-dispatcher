import streamlit as st
import pandas as pd

st.set_page_config(page_title="Lorry Dispatch Engine", layout="wide")

st.title("🚛 Company Lorry Dispatch Engine")

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
    "Sunview Drive": {"address": "Sunview Way", "travel_min": 30, "zone": "West"},
}

site_options = sorted(list(SITE_DATABASE.keys()))

blank_rows = [
    {"Site Name": None, "Job Type": "Standard Drop-off", "Destination PJC": "N/A", "Pax": 0, "Time Deadline": "19:00", "Food Drop": "NO"}
    for _ in range(25)
]

st.subheader("📋 Input Today's Site Schedule")

edited_df = st.data_editor(
    pd.DataFrame(blank_rows),
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "Site Name": st.column_config.SelectboxColumn("Site Name", options=site_options, required=False),
        "Job Type": st.column_config.SelectboxColumn("Job Type", options=["Standard Drop-off", "PJC-to-PJC Transfer"], default="Standard Drop-off"),
        "Destination PJC": st.column_config.SelectboxColumn("Destination PJC", options=["N/A"] + site_options, default="N/A"),
        "Pax": st.column_config.NumberColumn("Pax", min_value=0, max_value=30, step=1, default=0),
        "Time Deadline": st.column_config.TextColumn("Time Deadline (e.g. 18:30, 19:00)", default="19:00"),
        "Food Drop": st.column_config.SelectboxColumn("Food Drop", options=["YES", "NO"], default="NO"),
    }
)

if st.button("🚀 Process Cluster Schedule"):
    active_df = edited_df.dropna(subset=["Site Name"]).copy()
    active_df = active_df[active_df["Site Name"] != ""]
    
    if active_df.empty:
        st.warning("⚠️ Enter at least one site job before running.")
    else:
        active_df["Zone"] = active_df["Site Name"].apply(lambda s: SITE_DATABASE.get(s, {}).get("zone", "Central"))
        
        # Mapping Zones to Specific Lorries & Drivers
        LORRY_MAPPING = {
            "Central": {"Lorry": "Lorry 1 — Central Cluster", "Driver": "Senthil (10-ft)"},
            "West": {"Lorry": "Lorry 2 — West Cluster", "Driver": "Mahendran (14-ft) / Staff Driver 5 (10-ft)"},
            "North": {"Lorry": "Lorry 3 — North Cluster", "Driver": "North Driver (10-ft)"},
            "East": {"Lorry": "Lorry 4 — East Cluster", "Driver": "Pandi (14-ft)"},
        }

        active_df["Lorry Cluster"] = active_df["Zone"].apply(lambda z: LORRY_MAPPING.get(z, {}).get("Lorry", "Lorry 1 — Central Cluster"))

        # Display Sectioned Tables Matched Exactly to Image 1
        st.divider()

        for zone_key in ["Central", "West", "North", "East"]:
            cluster_name = LORRY_MAPPING[zone_key]["Lorry"]
            driver_info = LORRY_MAPPING[zone_key]["Driver"]
            
            cluster_df = active_df[active_df["Zone"] == zone_key].copy()
            
            st.markdown(f"### {cluster_name} *(Assigned: {driver_info})*")
            
            if not cluster_df.empty:
                display_table = cluster_df[["Site Name", "Pax", "Time Deadline", "Food Drop"]].reset_index(drop=True)
                st.table(display_table)
            else:
                st.info(f"No jobs scheduled for {zone_key} Cluster today.")
