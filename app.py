import streamlit as st
from main import run_dispatcher, load_google_sheet_data

st.set_page_config(page_title="Lorry Dispatch Generator")
st.title("🚛 Daily Lorry Dispatch Generator")

api_key = st.sidebar.text_input("Gemini API Key", type="password")
shift_type = st.selectbox("Select Shift Type", ["EVENING_2100_2200", "MORNING_0700_0800"])

if st.button("Generate Dispatch Schedule"):
    if not api_key:
        st.error("Please enter your Gemini API Key in the sidebar.")
    else:
        try:
            with st.spinner("Generating schedule..."):
                result = run_dispatcher(api_key, shift_type)
                st.success("Dispatch Schedule Generated!")
                st.write(result)
        except Exception as e:
            st.error(f"Error generating schedule: {e}")
