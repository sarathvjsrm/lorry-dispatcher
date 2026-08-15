import gspread
import streamlit as st
import google.generativeai as genai

# Page Configuration
st.set_page_config(page_title="Daily Lorry Dispatch Generator", page_icon="🚚", layout="wide")

st.title("🚚 Daily Lorry Dispatch Generator")

# Sidebar for Gemini API Key input
st.sidebar.header("Configuration")
api_key_input = st.sidebar.text_input("Gemini API Key", type="password")

SPREADSHEET_ID = "1AJXN_aUILuokaJhPLCTVb7IIwLnzc3gKpPCmfrJLOdY"


def load_google_sheet_data():
    """
    Loads site database and fleet drivers directly by Spreadsheet ID with tab-name fallback.
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

    # Flexible matching by tab name (case & space insensitive) or fallback to index position
    def get_data_by_name_or_index(preferred_name, fallback_index):
        for ws in worksheets:
            if ws.title.strip().lower() == preferred_name.strip().lower():
                return ws.get_all_records()
        if len(worksheets) > fallback_index:
            return worksheets[fallback_index].get_all_records()
        raise ValueError(f"Could not find worksheet '{preferred_name}'. Available tabs: {sheet_names}")

    sites = get_data_by_name_or_index("Site Database", 0)
    drivers = get_data_by_name_or_index("Fleet_Drivers", 1)

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
)

if st.button("Generate Dispatch Schedule"):
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
