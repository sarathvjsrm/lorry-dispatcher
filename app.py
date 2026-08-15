import streamlit as st
import json
from main import run_dispatcher, load_google_sheet_data

st.set_page_config(page_title="Lorry Dispatcher Engine", layout="wide")
st.title("🚛 Daily Lorry Dispatch Generator")

# Sidebar settings
st.sidebar.header("Configuration")
api_key = st.sidebar.text_input("Gemini API Key", type="password")

# Shift selection dropdown
shift_type = st.selectbox(
    "Select Shift Type", 
    ["MORNING", "EVENING_1900", "EVENING_2100_2200"]
)

if st.button("Generate Dispatch Schedule"):
    if not api_key:
        st.error("Please enter your Gemini API Key in the sidebar.")
    else:
        with st.spinner("Reading Google Sheet data and generating optimized schedule..."):
            try:
                # Load site & dorm data from Google Sheets
                sites_data, dorms_data = load_google_sheet_data()
                
                # Generate route schedule using main logic
                schedule_result = run_dispatcher(api_key, shift_type, sites_data)
                
                st.subheader("Generated Schedule Result")
                st.markdown(schedule_result)
            except Exception as e:
                st.error(f"Error generating schedule: {str(e)}")
