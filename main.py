import gspread
import streamlit as st
import google.generativeai as genai

# Page Configuration
st.set_page_config(page_title="Dynamic Lorry Dispatch Generator", page_icon="🚚", layout="wide")
st.title("🚚 Dynamic Lorry Dispatch Generator")

# Sidebar for Gemini API Key input
st.sidebar.header("Configuration")
api_key_input = st.sidebar.text_input("Gemini API Key", type="password", key="gemini_api_key_input")

SPREADSHEET_ID = "1AJXN_aUILuokaJhPLCTVb7IIwLnzc3gKpPCmfrJLOdY"

def get_raw_sheet_data(worksheet):
    """
    Extracts raw 2D array for Daily Ops to capture dynamic daily changes.
    """
    return worksheet.get_all_values()

def get_clean_records(worksheet):
    """
    Parses standard databases (Sites, Drivers) into clean, dynamic dictionaries.
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
    Loads dynamic data directly from Google Sheets.
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

    daily_ops_ws = get_worksheet_by_name("Daily_Ops", 0)
    site_ws = get_worksheet_by_name("Site_Database", 1)
    driver_ws = get_worksheet_by_name("Fleet_Drivers", 2)

    daily_ops_data = get_raw_sheet_data(daily_ops_ws) if daily_ops_ws else []
    sites = get_clean_records(site_ws) if site_ws else []
    drivers = get_clean_records(driver_ws) if driver_ws else []

    return daily_ops_data, sites, drivers

def run_dispatcher(api_key, shift_type):
    """
    Generates a dynamic dispatch schedule based on real-time spreadsheet variables, Lat/Lng math, and universal rules.
    """
    genai.configure(api_key=api_key)
    daily_ops_data, sites, drivers = load_google_sheet_data()

    daily_ops_text = ""
    for row in daily_ops_data:
        if any(str(cell).strip() for cell in row):
            daily_ops_text += " | ".join([str(cell).strip() for cell in row]) + "\n"

    # THE FIX: This prompt is completely dynamic. It relies entirely on what is in the sheets today, 
    # enforces the 50km/h rule via Lat/Lng, and forces dynamic balancing.
    prompt = (
        f"You are an advanced Logistics Dispatcher AI. Process the daily schedule dynamically based strictly on the data provided below.\n\n"
        f"--- TODAY'S DYNAMIC WORKLOAD (DAILY OPS) ---\n{daily_ops_text}\n\n"
        f"--- SITE DATABASE (LATITUDE & LONGITUDE) ---\n{sites}\n\n"
        f"--- ACTIVE FLEET DRIVERS ---\n{drivers}\n\n"
        f"CRITICAL UNIVERSAL RULES (APPLY TO ANY DATA SET):\n"
        f"1. DYNAMIC DRIVER NAMES: Extract driver names directly from the 'Active Fleet Drivers' list provided above. NEVER use placeholders like 'Driver 1'.\n"
        f"2. LAT/LNG TRAVEL MATH: Cross-reference the sites in Daily Ops with their Latitude and Longitude in the Site Database. You MUST calculate route feasibility based on a heavy lorry speed limit of 50 km/h, adding a mandatory 15-minute traffic/wait buffer between sites. Do not assign impossible routes.\n"
        f"3. DYNAMIC DINNER OVERRIDE: Identify ANY site ending at 22:00 (10 PM) in today's data. You MUST explicitly assign a specific, named driver to deliver food to these sites BEFORE 22:00.\n"
        f"4. DYNAMIC BALANCING: Count the total number of sites for this shift. Divide them equally among the available main drivers listed in the data. No driver should have 4 jobs while another has 1.\n\n"
        
        f"YOU MUST OUTPUT YOUR RESPONSE EXACTLY IN THESE 3 SECTIONS:\n\n"
        
        f"### 🍽️ DYNAMIC DINNER ASSIGNMENTS\n"
        f"Print a Markdown table for any 22:00 sites identified today. Columns: 'Site Name', 'Assigned Driver (Real Name)', 'Vehicle'.\n\n"
        
        f"### 🗺️ ROUTING & TRAVEL TIME CALCULATION\n"
        f"Briefly explain your routing logic for the busiest drivers, proving that travel times between their assigned sites are physically possible at 50 km/h with a 15-minute buffer using their Lat/Lng coordinates.\n\n"
        
        f"### 🚚 FINAL DISPATCH SCHEDULE\n"
        f"Print the balanced schedule in a Markdown table with columns: 'Driver Name', 'Vehicle', 'Assigned Sites (with times)', 'Total Workers'. Respect dynamic vehicle capacities."
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
            # Temperature 0.1 locks the AI into strict analytical mode for mapping and math
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
        "MORNING_0700_1500",
        "AFTERNOON_1500_2300",
        "EVENING_2100_2200",
        "NIGHT_2300_0700",
    ],
    key="shift_type_select"
)

if st.button("Generate Dispatch Schedule", key="generate_schedule_btn"):
    if not api_key_input:
        st.error("Please enter your Gemini API Key in the sidebar.")
    else:
        with st.spinner("Analyzing today's dynamic data, calculating 50km/h routing with buffers, and balancing workload..."):
            try:
                schedule = run_dispatcher(api_key_input, shift_type)
                st.success("Schedule generated successfully!")
                st.markdown(schedule)
            except Exception as e:
                st.error(f"Error generating schedule: {e}")
