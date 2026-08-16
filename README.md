# 🚚 Dynamic Lorry Dispatch Generator

## Overview
This application automates daily logistics routing. It is designed to be **100% dynamic**. If you change the `Daily_Ops`, `Site_Database`, or `Fleet_Drivers` in your Google Sheet, the app automatically reads the new data, extracts the real driver names, and re-balances the workload.

## File Structure
* **`app.py`**: The core Streamlit UI and AI routing engine.
* **`main.py`**: A simple execution wrapper to run the application.
* **`config.json`**: Stores static variables like Spreadsheet IDs and traffic buffers.
* **`requirements.txt`**: Lists all required Python dependencies.

## How it Solves Previous Issues:
1. **Real Names**: The Python backend explicitly scrapes the names from your `Fleet_Drivers` sheet and mathematically forbids the AI from using generic "Driver 1" placeholders.
2. **Dynamic Workload**: It counts the rows in your daily sheet and issues a strict command to the AI to divide them equally among active drivers.
3. **Future-Proof**: Nothing is hardcoded to today's date. Tomorrow's sheet changes will instantly reflect in tomorrow's generation.

## Setup Instructions
1. Install dependencies: `pip install -r requirements.txt`
2. Ensure your `.streamlit/secrets.toml` contains your `gcp_service_account` credentials.
3. Run the app: `python main.py` or `streamlit run app.py`
