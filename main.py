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
    Generates dispatch schedule using Gemini API with strict geographic and capacity rules.
    """
    genai.configure(api_key=api_key)
    daily_ops_data, sites, drivers = load_google_sheet_data()

    # Convert the raw Daily Ops grid into a readable string for the AI
    daily_ops_text = ""
    for row in daily_ops_data:
        # Ignore completely empty rows to save tokens
        if any(str(cell).strip() for cell in row):
            daily_ops_text += " | ".join([str(cell).strip() for cell in row]) + "\n"

    prompt = (
        f"You are the Master Dispatcher for a Singapore logistics fleet.\n"
        f"Generate an optimized lorry dispatch schedule for the '{shift_type}' shift based EXACTLY on the jobs filled out in the 'Daily Ops' data below.\n\n"
        f"--- TODAY'S WORKLOAD (DAILY OPS) ---\n"
        f"NOTE: Read this carefully. The top section contains regular shift end times. The bottom section (around row 24/25) contains 'SHIFTING WORKERS / Site-to-Site Transfers'. You must schedule BOTH.\n\n"
        f"{daily_ops_text}\n\n"
        f"--- SITE DATABASE (FOR LAT/LNG AND REGIONS) ---\n{sites}\n\n"
        f"--- FLEET DRIVERS ---\n{drivers}\n\n"
        f"CRITICAL DISPATCH RULES:\n"
        f"1. GEOGRAPHIC REALITY (NO TELEPORTING): You MUST cross-reference the Daily Ops sites with the Site Database to estimate distance (using Latitude/Longitude or Region). A driver CANNOT pick up from two distant sites at the exact same time (e.g., Jurong and Woodlands at 21:00). If sites are distant, ASSIGN DIFFERENT DRIVERS.\n"
        f"2. PRIORITIZE 5 MAIN DRIVERS: You MUST fill the 5 main OT drivers' schedules first. Maximize their routes (up to 25 pax for 14ft, 14 pax for 10ft) without causing time conflicts. Do not waste extra lorries.\n"
        f"3. STAFF DRIVER BACKUP: ONLY utilize the Staff Driver if the main 5 drivers are completely full or if a route is geographically impossible for the main drivers to cover simultaneously.\n"
        f"4. DINNER DRIVER (FOOD): For any sites ending at 22:00 (10 PM), you MUST assign a driver to bring food to that site beforehand. Clearly indicate this 'Dinner Delivery' duty in your output.\n\n"
        f"Output the final schedule in a clear markdown table including: Driver Name, Vehicle, Assigned Sites, Pickup Times, Total Workers, and Dinner Duty.\n"
        f"Below the table, provide a 'Routing Logic Check' showing the estimated travel time between clustered sites to prove the route is physically possible in Singapore."
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
            # Setting temperature to 0.1 makes the AI strictly logical and stops hallucinations
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
