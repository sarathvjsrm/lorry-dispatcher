import time
import gspread
import streamlit as st
import pandas as pd

from dispatch_engine import (
    config,
    parse_site_database,
    parse_fleet,
    parse_daily_ops,
    assign_and_verify,
    EVENING_BUFFER_MIN,
)

st.set_page_config(page_title="Dynamic Lorry Dispatcher", page_icon="🚚", layout="wide")
st.title("🚚 Dynamic Lorry Dispatch Generator")
st.caption(
    "Real GPS distances, real travel-time math, real capacity limits. "
    "Nothing here is guessed by an AI text model - every number is computed "
    "by dispatch_engine.py, which is unit-tested and doesn't depend on this UI."
)

SPREADSHEET_ID = config["spreadsheet_id"]


@st.cache_data(ttl=300, show_spinner=False)
def load_google_sheet_data():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds_dict = dict(st.secrets["gcp_service_account"])
    if "private_key" in creds_dict:
        creds_dict["private_key"] = str(creds_dict["private_key"]).replace("\\n", "\n")
    client = gspread.service_account_from_dict(creds_dict, scopes=scopes)

    max_retries = 3
    for attempt in range(max_retries):
        try:
            sheet = client.open_by_key(SPREADSHEET_ID)
            daily_ops_ws = sheet.worksheet("Daily_Ops")
            site_ws = sheet.worksheet("Site_Database")
            driver_ws = sheet.worksheet("Fleet_Drivers")
            return (
                daily_ops_ws.get_all_values(),
                site_ws.get_all_values(),
                driver_ws.get_all_values(),
            )
        except Exception as e:
            if "429" in str(e) and attempt < max_retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise e


try:
    daily_ops_raw, site_raw, driver_raw = load_google_sheet_data()
    site_lookup = parse_site_database(site_raw)
    fleet = parse_fleet(driver_raw)
    jobs, shifts = parse_daily_ops(daily_ops_raw, site_lookup)
except Exception as e:
    st.error(f"Could not load Google Sheet data: {e}")
    st.stop()

st.sidebar.header("Fleet loaded")
st.sidebar.dataframe(pd.DataFrame(fleet)[["name", "vehicle", "type", "cap"]])

unresolved = [j["site_label"] for j in jobs if not j["info"]]
if unresolved:
    st.warning(
        "These sites in Daily_Ops couldn't be matched to Site_Database "
        "(check spelling / add them to Site_Database): " + ", ".join(unresolved)
    )

st.write(
    f"**Tonight's workload:** {len(jobs)} sites, "
    f"{sum(j['workers'] for j in jobs)} workers, "
    f"{sum(1 for j in jobs if j['is_dinner'])} sites need food, "
    f"{len(shifts)} shifting task(s)."
)

if st.button("🚀 Generate Verified Dispatch Schedule"):
    with st.spinner("Clustering sites, checking real travel times, verifying every driver's evening..."):
        assignment, shift_assignment, cluster_notes, load, results, iteration_log = assign_and_verify(
            jobs, shifts, fleet
        )

    with st.expander("🔁 How the engine got here (repair attempts)"):
        for line in iteration_log:
            st.write("- " + line)

    any_fail = any(r["fail"] for r in results.values())
    if any_fail:
        st.error(
            "⚠️ One or more drivers have a real conflict - see the red rows below. "
            "Consider moving that job to a backup driver."
        )
    else:
        st.success(
            "✅ Verified feasible - every driver's evening was simulated with real "
            "travel times and nothing is late past the hard cutoff."
        )

    st.subheader("🍽️ Meal / Dinner Delivery Assignments")
    dinner_rows = []
    for j in jobs:
        a = assignment.get(j["site_label"])
        if a and a["dinner"]:
            dinner_rows.append(
                {"Site": j["site_label"], "Driver": a["dinner"], "Workers to feed": j["workers"]}
            )
    st.table(pd.DataFrame(dinner_rows))

    st.subheader("🧩 How the dinner clusters were built (route-time checked)")
    for note in cluster_notes:
        st.write("- " + note)

    st.subheader("🚚 Full Dispatch Schedule (by driver)")
    for driver, res in results.items():
        icon = "🔴" if res["fail"] else "🟢"
        with st.expander(f"{icon} {driver} - {'CONFLICT' if res['fail'] else 'OK'}"):
            df = pd.DataFrame(res["log"], columns=["Task", "Timing", "OK"])
            st.table(df)

    if shift_assignment:
        st.subheader("🔄 Shifting Workers")
        st.table(pd.DataFrame(shift_assignment))

    st.caption(
        "All times above are computed from real GPS coordinates in Site_Database "
        f"(haversine distance x2 + 10min base + {EVENING_BUFFER_MIN}min evening buffer), "
        "not generated or guessed by an AI model."
    )
