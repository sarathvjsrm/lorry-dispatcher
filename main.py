import gspread
from google.oauth2.service_account import Credentials
import streamlit as st

def load_google_sheet_data(sheet_name="gemini"):
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    
    # Load credentials from Streamlit secrets or local credentials file
    if "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    else:
        creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
        
    client = gspread.authorize(creds)
    sheet = client.open(sheet_name)
    
    # Matching your exact tab names in your Google Sheet:
    sites = sheet.worksheet("Site Database").get_all_records()
    drivers = sheet.worksheet("Fleet_Drivers").get_all_records()
    
    return sites, drivers
