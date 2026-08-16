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
    Generates dispatch schedule enforcing EQUAL WORKLOAD, REAL DRIVER NAMES, and STRICT GEOGRAPHY.
    """
    genai.configure(api_key=api_key)
    daily_ops_data, sites, drivers = load_google_sheet_data()

    # Convert the raw Daily Ops grid into a readable string for the AI
    daily_ops_text = ""
    for row in daily_ops_data:
        if any(str(cell).strip() for cell in row):
            daily_ops_text += " | ".join([str(cell).strip() for cell in row]) + "\n"

    prompt = (
        f"You are the Master Dispatcher. You MUST process the schedule in exact order. DO NOT skip steps.\n\n"
        f"--- TODAY'S WORKLOAD (DAILY OPS) ---\n{daily_ops_text}\n\n"
        f"--- SITE REGIONS & COORDS ---\n{sites}\n\n"
        f"--- FLEET DRIVERS ---\n{drivers}\n\n"
        f"YOU MUST OUTPUT YOUR RESPONSE EXACTLY IN THESE 3 STEPS:\n\n"
        
        f"### STEP 1: REAL DRIVER NAMES & DINNER ASSIGNMENT\n"
        f"CRITICAL RULE: NEVER use generic names like 'Driver 1' or 'Driver 2'. You MUST use the actual names of the main 5 drivers (e.g., Sridhar, Kalingarathnam, Mahendran, K. Pandi, Senthil) and the 'Staff Driver' (Saravanan) as listed in the Fleet Drivers data.\n"
        f"First, identify EVERY site that ends at 22:00 (10 PM). Assign one available driver using their REAL NAME to be the 'Dinner Driver' to deliver food BEFORE 22:00. Print this as a Markdown table.\n\n"
        
        f"### STEP 2: GEOGRAPHIC MAPPING (NO TELEPORTING)\n"
        f"List every 19:00 and 21:00 site. Next to it, state its exact Region (e.g., Tuas, Woodlands, Jurong). "
        f"If two sites at the same time are in DIFFERENT regions, declare them 'GEOGRAPHICALLY INCOMPATIBLE' so they are not put on the same lorry.\n\n"
        
        f"### STEP 3: FINAL DISPATCH SCHEDULE (EQUAL BALANCING)\n"
        f"Now, build the final schedule. \n"
        f"- EQUAL WORKLOAD: You MUST distribute the jobs evenly across the 5 Main Drivers. Do NOT cram all jobs onto one driver just because they have vehicle capacity. Ensure every driver gets a fair share of the 19:00 and 21:00/22:00 runs so no one is resting while another is overloaded.\n"
        f"- Use their REAL NAMES.\n"
        f"- Do NOT group geographically incompatible sites from Step 2.\n"
        f"- Respect Lorry Capacity limits.\n"
        f"Print the final schedule in a Markdown table with columns: Driver Name, Vehicle, Assigned Sites (with times), Total Workers."
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
            # Temperature 0.0 forces the AI to be completely logical and fair based on instructions
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(temperature=0.0) 
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
        with st.spinner("Analyzing Daily Ops, Map Coordinates, and balancing driver workload..."):
            try:
                schedule = run_dispatcher(api_key_input, shift_type)
                st.success("Schedule generated successfully!")
                st.markdown(schedule)
            except Exception as e:
                st.error(f"Error generating schedule: {e}")
