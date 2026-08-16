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

    daily_ops_ws = get_worksheet_by_name("Daily_Ops", 0)
    site_ws = get_worksheet_by_name("Site_Database", 1)
    driver_ws = get_worksheet_by_name("Fleet_Drivers", 2)

    daily_ops_data = get_raw_sheet_data(daily_ops_ws) if daily_ops_ws else []
    sites = get_clean_records(site_ws) if site_ws else []
    drivers = get_clean_records(driver_ws) if driver_ws else []

    return daily_ops_data, sites, drivers

def run_dispatcher(api_key, shift_type):
    """
    Generates dispatch schedule enforcing STRICT MATH BALANCING, REAL DRIVER NAMES, and MANDATORY DINNER.
    """
    genai.configure(api_key=api_key)
    daily_ops_data, sites, drivers = load_google_sheet_data()

    daily_ops_text = ""
    for row in daily_ops_data:
        if any(str(cell).strip() for cell in row):
            daily_ops_text += " | ".join([str(cell).strip() for cell in row]) + "\n"

    # THE FIX: Added "STEP 3: STRICT WORKLOAD DISTRIBUTION PLAN" to force the AI to mathematically divide jobs.
    prompt = (
        f"You are the Master Dispatcher. You MUST process the schedule in exact order. DO NOT skip steps.\n\n"
        f"--- TODAY'S WORKLOAD (DAILY OPS) ---\n{daily_ops_text}\n\n"
        f"--- SITE REGIONS & COORDS ---\n{sites}\n\n"
        f"--- FLEET DRIVERS ---\n{drivers}\n\n"
        f"YOU MUST OUTPUT YOUR RESPONSE EXACTLY IN THESE 4 STEPS:\n\n"
        
        f"### STEP 1: REAL DRIVER NAMES & MANDATORY DINNER ASSIGNMENT\n"
        f"CRITICAL RULE FOR NAMES: You MUST assign jobs using ONLY these exact names. NEVER use 'Driver 1' etc:\n"
        f"- MAIN 5 DRIVERS: Sridhar, Kalingarathnam, Mahendran, K. Pandi, Senthil\n"
        f"- STAFF DRIVER: Saravanan\n"
        f"DINNER OVERRIDE RULE: Identify EVERY site that ends at 22:00 (10 PM). YOU ABSOLUTELY MUST ASSIGN ONE DRIVER TO DELIVER FOOD TO THESE SITES BEFORE 22:00. Note: A driver doing a 19:00 or 21:00 pickup is STILL ALLOWED to drop off food beforehand. You MUST explicitly write their real name in the table.\n"
        f"Print this as a Markdown table with columns: '10 PM Site Name', 'Dinner Driver Assigned (REAL NAME)', 'Vehicle'.\n\n"
        
        f"### STEP 2: GEOGRAPHIC MAPPING (NO TELEPORTING)\n"
        f"List every 19:00 and 21:00 site. Next to it, state its exact Region (e.g., Tuas, Woodlands, Jurong). "
        f"If two sites at the same time are in DIFFERENT regions, declare them 'GEOGRAPHICALLY INCOMPATIBLE'.\n\n"
        
        f"### STEP 3: STRICT WORKLOAD DISTRIBUTION PLAN\n"
        f"CRITICAL RULE: The schedule MUST be perfectly fair. It is UNACCEPTABLE for one driver to do only one job while another does three.\n"
        f"Write out your assignment plan explicitly before drawing the final table:\n"
        f"1. Count the total number of 19:00 (7 PM) sites. Divide them evenly among the 5 Main Drivers. EVERY main driver MUST get at least one 19:00 job if possible before anyone gets two.\n"
        f"2. Count the total number of 21:00 (9 PM) and 22:00 (10 PM) sites. Divide them evenly among the 5 Main Drivers. EVERY main driver MUST get a late job. No driver is allowed to go home early if others are working late.\n"
        f"Write out a short summary of who gets how many jobs here.\n\n"

        f"### STEP 4: FINAL DISPATCH SCHEDULE\n"
        f"Now, build the final schedule based EXACTLY on the fair distribution from Step 3. \n"
        f"- USE REAL NAMES ONLY.\n"
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
            # Temperature 0.0 forces the AI to follow the Math logic strictly
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
        with st.spinner("Analyzing Daily Ops, forcing strict math for fair workload, and assigning drivers..."):
            try:
                schedule = run_dispatcher(api_key_input, shift_type)
                st.success("Schedule generated successfully!")
                st.markdown(schedule)
            except Exception as e:
                st.error(f"Error generating schedule: {e}")
