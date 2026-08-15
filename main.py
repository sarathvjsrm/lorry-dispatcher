import gspread
import streamlit as st
import google.generativeai as genai

# Page Configuration
st.set_page_config(page_title="Daily Lorry Dispatch Generator", page_icon="🚚", layout="wide")

st.title("🚚 Daily Lorry Dispatch Generator")

# Sidebar for Gemini API Key input
st.sidebar.header("Configuration")
api_key_input = st.sidebar.text_input("Gemini API Key", type="password", key="gemini_api_key_input")

# Your exact Spreadsheet ID
SPREADSHEET_ID = "1AJXN_aUILuokaJhPLCTVb7IIwLnzc3gKpPCmfrJLOdY"


def get_clean_records(worksheet):
    """
    Safely parses worksheet rows into dictionaries, avoiding errors with empty or duplicate header cells.
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
    Loads site database and fleet drivers directly by Spreadsheet ID with fallback handling.
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
    sheet_names = [ws.title for ws in worksheets]

    def get_worksheet_by_name(preferred_name, fallback_index):
        for ws in worksheets:
            if ws.title.strip().lower() == preferred_name.strip().lower():
                return ws
        if len(worksheets) > fallback_index:
            return worksheets[fallback_index]
        raise ValueError(f"Could not find worksheet '{preferred_name}'. Available tabs: {sheet_names}")

    site_ws = get_worksheet_by_name("Site Database", 0)
    driver_ws = get_worksheet_by_name("Fleet_Drivers", 1)

    sites = get_clean_records(site_ws)
    drivers = get_clean_records(driver_ws)

    return sites, drivers


def run_dispatcher(api_key, shift_type):
    """
    Generates dispatch schedule using Gemini API and Google Sheets data.
    """
    genai.configure(api_key=api_key)
    sites, drivers = load_google_sheet_data()

    model = genai.GenerativeModel("gemini-1.5-flash")
    prompt = (
        f"You are an expert logistics and lorry dispatch planner.\n"
        f"Generate an optimized lorry dispatch schedule for the '{shift_type}' shift.\n\n"
        f"--- SITE DATABASE ---\n{sites}\n\n"
        f"--- FLEET DRIVERS ---\n{drivers}\n\n"
        f"Please organize the output clearly with formatted tables and summary instructions."
    )

    response = model.generate_content(prompt)
    return response.text


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
        with st.spinner("Fetching data from Google Sheets & generating schedule..."):
            try:
                schedule = run_dispatcher(api_key_input, shift_type)
                st.success("Schedule generated successfully!")
                st.markdown(schedule)
            except Exception as e:
                st.error(f"Error generating schedule: {e}")
