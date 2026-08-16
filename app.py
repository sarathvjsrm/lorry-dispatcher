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
    
    # Implement retry backoff to handle Google Sheets 429 Rate Limits gracefully
    max_retries = 3
    for attempt in range(max_retries):
        try:
            sheet = client.open_by_key(SPREADSHEET_ID)
            
            # Fetch all worksheet values in a structured sequence with minimal overhead
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

    # 1. Format Daily Ops into readable text for any given day
    daily_ops_text = "\n".join([" | ".join([str(cell).strip() for cell in row]) for row in daily_ops_data if any(row)])

    # 2. Extract REAL Driver Names programmatically to force the AI to use them
    driver_names_list = []
    for d in drivers:
        name = d.get("Driver Name", d.get("Name", d.get("Driver", str(list(d.values())[0]))))
        driver_names_list.append(name)
    
    active_drivers_string = ", ".join(driver_names_list)

    # 3. The Bulletproof Dynamic Prompt
    prompt = (
        f"You are a master Logistics AI. You are generating a schedule for the '{shift_type}' shift.\n\n"
        f"--- TODAY'S DYNAMIC WORKLOAD ---\n{daily_ops_text}\n\n"
        f"--- SITE DATABASE (COORDINATES) ---\n{sites}\n\n"
        f"--- ACTIVE FLEET DRIVERS ---\n{drivers}\n\n"
        
        f"CRITICAL SYSTEM RULES (MUST OBEY):\n"
        f"1. REAL DRIVER NAMES ONLY: You are strictly forbidden from using 'Driver 1', 'Driver 2', etc. "
        f"You MUST assign jobs using ONLY these active names from the database: {active_drivers_string}.\n"
        f"2. MATHEMATICAL BALANCING: Look at the total number of sites in Today's Workload. You MUST distribute these sites evenly across the active drivers. Do not overload one driver while leaving another empty.\n"
        f"3. DYNAMIC DINNER DELIVERY: Identify ANY site in Today's Workload ending at 22:00. You MUST assign a specific driver (by their real name) to deliver food to them before pickup.\n"
        f"4. TRAVEL REALITY: Use the Latitude/Longitude from the Site Database. Do not assign sites that are geographically impossible to reach sequentially.\n\n"
        
        f"OUTPUT FORMAT (Provide exactly these 3 sections in Markdown):\n\n"
        f"### 🍽️ DINNER DELIVERY ASSIGNMENTS\n"
        f"(Table: Site Name | Dinner Driver (Real Name) | Vehicle)\n\n"
        f"### ⚖️ WORKLOAD BALANCING AUDIT\n"
        f"(Briefly list each active driver by name and state exactly how many sites they were assigned to prove the load is balanced.)\n\n"
        f"### 🚚 DYNAMIC DISPATCH SCHEDULE\n"
        f"(Table: Driver Name (Real Name) | Vehicle | Assigned Sites & Times | Total Workers)\n"
    )

    # Using gemini-2.0-flash which is widely supported across modern API versions
    model = genai.GenerativeModel("gemini-2.0-flash")
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
        with st.spinner("Extracting real names, balancing workload mathematically, and routing..."):
            try:
                schedule_output = generate_dynamic_schedule(api_key_input, shift_selection)
                st.success("Schedule Generated Successfully!")
                st.markdown(schedule_output)
            except Exception as e:
                st.error(f"System Error: {e}")
