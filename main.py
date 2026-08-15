def load_google_sheet_data(sheet_name="gemini"):
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    
    if "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
        # Fix escaped newlines in the private key string
        if "private_key" in creds_dict:
            creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    else:
        creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
        
    client = gspread.authorize(creds)
    sheet = client.open(sheet_name)
    
    sites = sheet.worksheet("Site Database").get_all_records()
    drivers = sheet.worksheet("Fleet_Drivers").get_all_records()
    return sites, drivers
