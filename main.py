import gspread
from google.oauth2.service_account import Credentials
import streamlit as st
import google.generativeai as genai

def load_google_sheet_data(sheet_name="gemini"):
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    
    if "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
        
        # Add required default token URI if missing
        if "token_uri" not in creds_dict:
            creds_dict["token_uri"] = "https://oauth2.googleapis.com/token"
            
        # Reformat private key to fix PEM parsing errors
        if "private_key" in creds_dict:
            pk = str(creds_dict["private_key"])
            pk = pk.replace("\\n", "\n").replace('\\"', '"').strip('"').strip("'")
            creds_dict["private_key"] = pk
            
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    else:
        creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
        
    client = gspread.authorize(creds)
    sheet = client.open(sheet_name)
    
    sites = sheet.worksheet("Site Database").get_all_records()
    drivers = sheet.worksheet("Fleet_Drivers").get_all_records()
    return sites, drivers

def run_dispatcher(api_key, shift_type):
    genai.configure(api_key=api_key)
    sites, drivers = load_google_sheet_data()
    
    model = genai.GenerativeModel("gemini-2.5-flash")
    prompt = f"Generate an optimized lorry dispatch schedule for {shift_type} shift using Site Database: {sites} and Fleet Drivers: {drivers}."
    
    response = model.generate_content(prompt)
    return response.text
