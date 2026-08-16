import gspread
import streamlit as st
import google.generativeai as genai

# Page Configuration
st.set_page_config(page_title="Daily Lorry Dispatch Generator", page_icon="🚚", layout="wide")
st.title("🚚 Daily Lorry Dispatch Generator")

# Sidebar for Gemini API Key input
st.sidebar.header("Configuration")
api_key_input = st.sidebar.text_input("Gemini API Key", type="password", key="gemini_api_key_input")

SPREADSHEET_ID = "1AJXN_aUILuokaJhPLCTVb7IIwLnzc3gKpPCmfrJLOdY"

def get_raw_sheet_data(worksheet):
    """
    Extracts the raw 2D array of the sheet. We need this for 'Daily_Ops' because 
    it has a complex layout (headers at the top, shifting workers at the bottom).
    """
    return worksheet.get_all_values()

def get_clean_records(worksheet):
    """
    Safely parses standard database worksheets (like Site_Database) into dictionaries.
    """
    all_values = worksheet.get_all_values()
    if not all_values or len(all_values) < 2:
        return []
    
    raw_headers = all_values[0]
    clean_headers = []
    seen_counts = {}

    for idx, header in enumerate(raw_headers):
        h_text = str(header).strip()
        if not h_text:
            h_text = f"Column_{idx + 1}"
        if h_text in seen_counts:
            seen_counts[h_text] += 1
            h_text = f"{h_text}_{seen_counts[h_text]}"
        else:
            seen_counts[h_text] = 0
        clean_headers.append(h_text)

    records = []
    for row in all_values[1:]:
        if not any(str(cell).strip() for cell in row):
            continue
        row_dict = {}
        for idx, cell_val in enumerate(row):
            if idx < len(clean_headers):
                row_dict[clean_headers[idx]] = cell_val
        records.append(row_dict)
    return records

def load_google_sheet_data():
    """
    Loads Daily Ops, Site Database, and Fleet Drivers.
    """
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    creds_dict = dict(st.secrets["gcp_service_account"])
    if "private_key" in creds_dict:
        creds_dict["private_key"] = str(creds_dict["private_key"]).replace("\\n", "\n")
        
    client = gspread.service_account_from_dict(creds_dict, scopes=scopes)
    sheet = client.open_by_key(SPREADSHEET_ID)
    worksheets = sheet.worksheets()

    def get_worksheet_by_name(preferred_name, fallback_index):
        for ws in worksheets:
            if ws.title.strip().lower() == preferred_name.strip().lower():
                return ws
        if len(worksheets) > fallback_index:
            return worksheets[fallback_index]
        return None

    # Fetch exactly the tabs you mentioned
    daily_ops_ws = get_worksheet_by_name("Daily_Ops", 0)
    site_ws = get_worksheet_by_name("Site_Database", 1)
    driver_ws = get_worksheet_by_name("Fleet_Drivers", 2)

    # Use raw 2D array for Daily Ops so the LLM can read the MOE transfer section at the bottom
    daily_ops_data = get_raw_sheet_data(daily_ops_ws) if daily_ops_ws else []
    
    # Use clean dictionaries for databases
    sites = get_clean_records(site_ws) if site_ws else []
    drivers = get_clean_records(driver_ws) if driver_ws else []

    return daily_ops_data, sites, drivers

def run_dispatcher(api_key, shift_type):
    """
    Generates dispatch schedule using Gemini API with strict geographic, capacity, and mandatory dinner rules.
    """
    genai.configure(api_key=api_key)
    daily_ops_data, sites, drivers = load_google_sheet_data()

    # Convert the raw Daily Ops grid into a readable string for the AI
    daily_ops_text = ""
    for row in daily_ops_data:
        if any(str(cell).strip() for cell in row):
            daily_ops_text += " | ".join([str(cell).strip() for cell in row]) + "\n"

    prompt = (
        f"You are the Master Dispatcher for a Singapore logistics fleet.\n"
        f"Generate an optimized lorry dispatch schedule for the '{shift_type}' shift based EXACTLY on the 'Daily Ops' data below.\n\n"
        f"--- TODAY'S WORKLOAD (DAILY OPS) ---\n"
        f"NOTE: Read this carefully. The top section contains regular shift end times. The bottom section (around row 24/25) contains 'SHIFTING WORKERS / Site-to-Site Transfers'. You must schedule BOTH.\n\n"
        f"{daily_ops_text}\n\n"
        f"--- SITE DATABASE (FOR LAT/LNG AND REGIONS) ---\n{sites}\n\n"
        f"--- FLEET DRIVERS ---\n{drivers}\n\n"
        f"CRITICAL DISPATCH RULES:\n"
        f"1. GEOGRAPHIC REALITY: Use Lat/Lng and Regions to estimate distance. A driver CANNOT pick up from distant sites at the exact same time (e.g., West vs North). Assign DIFFERENT DRIVERS to distant sites.\n"
        f"2. PRIORITIZE 5 MAIN DRIVERS: Fill their schedules first (up to 25 pax for 14ft, 14 pax for 10ft). Do not waste extra lorries.\n"
        f"3. STAFF DRIVER BACKUP: ONLY utilize Staff Driver if the main 5 are completely full or geographically impossible.\n"
        f"4. MANDATORY DINNER DELIVERY (10 PM SITES): You MUST identify every site ending at 22:00 (10 PM). You MUST explicitly assign a driver to deliver dinner to these sites before the pickup.\n\n"
        f"YOU MUST USE THIS EXACT OUTPUT FORMAT:\n\n"
        f"### 🍽️ DINNER DELIVERY ASSIGNMENTS (Strictly for 22:00 Sites)\n"
        f"| 10 PM Site Name | Dinner Driver Assigned | Vehicle |\n"
        f"|---|---|---|\n"
        f"(List every 22:00 site and the driver assigned to bring them food)\n\n"
        f"### 🚚 MAIN PICKUP DISPATCH SCHEDULE\n"
        f"| Driver Name | Vehicle | Assigned Sites | Pickup Times | Total Workers |\n"
        f"|---|---|---|---|---|\n"
        f"(List all pickups here)\n\n"
        f"### 🗺️ ROUTING LOGIC CHECK\n"
        f"(Prove travel times between clustered sites are geographically possible in Singapore)"
    )

    candidate_models = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]
    
    try:
        available_models = [
            m.name.replace("models/", "")
            for m in genai.list_models()
            if "generateContent" in m.supported_generation_methods
        ]
        for item in available_models:
            if item not in candidate_models and "2.5" not in item:
                candidate_models.append(item)
    except Exception:
        pass

    last_exception = None
    for model_name in candidate_models:
        try:
            model = genai.GenerativeModel(model_name)
            # Temperature 0.1 locks the AI into strict logic mode so it stops hallucinating
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(temperature=0.1)
            )
            return response.text
        except Exception as e:
            last_exception = e
            continue

    raise last_exception

# Main UI Elements
shift_type = st.selectbox(
    "Select Shift Type",
    [
        "EVENING_2100_2200",
        "MORNING_0700_1500",
        "AFTERNOON_1500_2300",
        "NIGHT_2300_0700",
    ],
    key="shift_type_select"
)

if st.button("Generate Dispatch Schedule", key="generate_schedule_btn"):
    if not api_key_input:
        st.error("Please enter your Gemini API Key in the sidebar.")
    else:
        with st.spinner("Analyzing Daily Ops, Map Coordinates, and generating schedule..."):
            try:
                schedule = run_dispatcher(api_key_input, shift_type)
                st.success("Schedule generated successfully!")
                st.markdown(schedule)
            except Exception as e:
                st.error(f"Error generating schedule: {e}")
