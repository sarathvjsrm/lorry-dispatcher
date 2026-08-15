import json
import gspread
import streamlit as st
from google.oauth2.service_account import Credentials
import google.generativeai as genai

# Load rules from local config.json
with open("config.json", "r") as f:
    CONFIG = json.load(f)

# Connect to Google Sheets using Streamlit Secrets or local credentials.json
def load_google_sheet_data(sheet_name="Dispatch_Master"):
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    
    if "gcp_service_account" in st.secrets:
        creds = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"], scopes=scopes
        )
    else:
        creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
        
    client = gspread.authorize(creds)
    sheet = client.open(sheet_name)
    
    sites = sheet.worksheet("Sites_Master").get_all_records()
    dorms = sheet.worksheet("Dormitories").get_all_records()
    return sites, dorms

def build_ai_prompt(shift_type, active_requests):
    prompt = f"""
    You are an automated dispatch intelligence engine using past WhatsApp transport records.
    
    DRIVER RULES:
    1. PRIMARY DRIVERS: {json.dumps(CONFIG['drivers']['primary'])}
    2. STAFF DRIVER (Saravanan - AG664): Utilize Saravanan as a staff driver when needed for long-distance runs (Tuas, Jurong Island, Woodlands) or heavy overflow runs.
    3. RESIGNED DRIVERS: NEVER assign A. Mani (AI1048) or Ramesh (AG670).
    
    HISTORICAL PAIRING RULES:
    {json.dumps(CONFIG['route_rules'])}
    
    CURRENT REQUEST DATA:
    {json.dumps(active_requests)}
    
    Generate the complete vehicle assignment schedule for {shift_type}.
    """
    return prompt

def run_dispatcher(api_key, shift_type, request_data):
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    
    prompt = build_ai_prompt(shift_type, request_data)
    response = model.generate_content(prompt)
    return response.text
