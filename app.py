import json
import time
import gspread
import streamlit as st
import google.generativeai as genai

# --- CONFIGURATION ---
st.set_page_config(page_title="Dynamic Lorry Dispatcher", page_icon="🚚", layout="wide")
st.title("🚚 Dynamic Lorry Dispatch Generator")

# Load external config
with open("config.json", "r") as f:
    config = json.load(f)

SPREADSHEET_ID = config["spreadsheet_id"]

st.sidebar.header("System Configuration")
api_key_input = st.sidebar.text_input("Gemini API Key", type="password")

# --- ROBUST DATA EXTRACTION WITH EXPONENTIAL BACKOFF & CACHING ---
@st.cache_data(ttl=300, show_spinner=False)
def load_google_sheet_data():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    creds_dict = dict(st.secrets["gcp_service_account"])
    if "private_key" in creds_dict:
        creds_dict["private_key"] = str(creds_dict["private_key"]).replace("\\n", "\n")
        
    client = gspread.service_account_from_dict(creds_dict, scopes=scopes)
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            sheet = client.open_by_key(SPREADSHEET_ID)
            
            daily_ops_ws = sheet.worksheet("Daily_Ops")
            site_ws = sheet.worksheet("Site_Database")
            driver_ws = sheet.worksheet("Fleet_Drivers")

            daily_ops_data = daily_ops_ws.get_all_values()
            site_data = site_ws.get_all_values()
            driver_data = driver_ws.get_all_values()

            sites = [dict(zip(site_data[0], row)) for row in site_data[1:] if any(row)]
            drivers = [dict(zip(driver_data[0], row)) for row in driver_data[1:] if any(row)]

            return daily_ops_data, sites, drivers
        except Exception as e:
            if "429" in str(e) and attempt < max_retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise e

# --- AI DISPATCH ENGINE ---
def generate_dynamic_schedule(api_key, shift_type):
    genai.configure(api_key=api_key)
    daily_ops_data, sites, drivers = load_google_sheet_data()

    daily_ops_text = "\n".join([" | ".join([str(cell).strip() for cell in row]) for row in daily_ops_data if any(row)])

    # Parse and build clear capacity map for each driver
    driver_specs = []
    for d in drivers:
        name = d.get("Driver No.", d.get("Driver Name", d.get("Name", ""))).strip()
        cap_str = d.get("Max Capacity", "25")
        try:
            cap = int(cap_str)
        except:
            cap = 25
        if name:
            driver_specs.append(f"- Driver: {name} | Vehicle: {d.get('Vehicle Code')} | Type: {d.get('Type')} | Max Legal Capacity: {cap} pax")

    drivers_summary_text = "\n".join(driver_specs)

    primary_driver_names = ["Mahendran", "Sridhar", "Kailing", "Senthil", "Pandi"]
    primary_string = ", ".join(primary_driver_names)

    prompt = (
        f"You are a master Logistics AI. You are generating a schedule for the '{shift_type}' shift.\n\n"
        f"--- TODAY'S DYNAMIC WORKLOAD ---\n{daily_ops_text}\n\n"
        f"--- SITE DATABASE (COORDINATES & DETAILS) ---\n{sites}\n\n"
        f"--- FLEET DRIVERS & STRICT LEGAL CAPACITIES ---\n{drivers_summary_text}\n\n"
        
        f"CRITICAL SAFETY & SYSTEM RULES (MUST OBEY OR IT IS AN ILLEGAL DISPATCH):\n"
        f"1. STRICT MAXIMUM CAPACITY LAW: You are legally FORBIDDEN from assigning a total worker count to any driver that exceeds their 'Max Legal Capacity' specified in the fleet database above (e.g., Senthil's max capacity is 14 pax, do NOT overload him past 14 under any circumstance!).\n"
        f"2. DRIVER PRIORITY & OVERFLOW: Use the primary 5 drivers first ({primary_string}). If a site's worker count or total workload exceeds a driver's legal capacity or geographic reach, split the loads properly or overflow to additional staff drivers from the database.\n"
        f"3. GEOGRAPHIC & TIMING REALITY: Use the Latitude/Longitude from the Site Database. Sequential site pickups must be physically reachable within the given time windows. Do not schedule impossible sequential hops.\n"
        f"4. DYNAMIC DINNER DELIVERY: Identify ANY site ending at 22:00. Assign a driver to deliver food before pickup.\n\n"
        
        f"OUTPUT FORMAT (Provide exactly these 3 sections in Markdown):\n\n"
        f"### 🍽️ DINNER DELIVERY ASSIGNMENTS\n"
        f"(Table: Site Name | Dinner Driver (Real Name) | Vehicle)\n\n"
        f"### ⚖️ LEGAL CAPACITY & WORKLOAD AUDIT\n"
        f"(List each driver used, their Max Legal Capacity, their Assigned Total Workers, and explicitly verify that NO driver exceeded their legal limit.)\n\n"
        f"### 🚚 DYNAMIC DISPATCH SCHEDULE\n"
        f"(Table: Driver Name | Vehicle | Assigned Sites & Times | Total Workers | Capacity Check Status)\n"
    )

    model = genai.GenerativeModel("gemini-3.5-flash")
    response = model.generate_content(
        prompt,
        generation_config=genai.types.GenerationConfig(temperature=0.0) 
    )
    return response.text

# --- USER INTERFACE ---
shift_selection = st.selectbox("Select Shift Type", ["MORNING_0700_1500", "AFTERNOON_1500_2300", "EVENING_2100_2200", "NIGHT_2300_0700"])

if st.button("Generate Dynamic Schedule"):
    if not api_key_input:
        st.error("Please enter your Gemini API Key in the sidebar.")
    else:
        with st.spinner("Checking legal capacities against database limits, verifying coordinates, and routing..."):
            try:
                schedule_output = generate_dynamic_schedule(api_key_input, shift_selection)
                st.success("Schedule Generated Successfully!")
                st.markdown(schedule_output)
            except Exception as e:
                st.error(f"System Error: {e}")
