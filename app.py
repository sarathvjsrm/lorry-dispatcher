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
    DINNER_END_THRESHOLD,
    fmt_time,
)

st.set_page_config(page_title="Anderco Lorry Dispatcher", page_icon="🚚", layout="wide")
st.title("🚚 Anderco Dynamic Lorry Dispatcher")
st.caption(
    "Location-first · OT drivers first · Food only for ≥22:00 sites · "
    "Pickup at end-time + 2 min (board ~2 min) · Traffic buffer only. "
    "All times from GPS + Site_Database travel records."
)

SPREADSHEET_ID = config["spreadsheet_id"]


@st.cache_data(ttl=120, show_spinner=False)
def load_google_sheet_data():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds_dict = dict(st.secrets["gcp_service_account"])
    if "private_key" in creds_dict:
        creds_dict["private_key"] = str(creds_dict["private_key"]).replace("\\n", "\n")
    client = gspread.service_account_from_dict(creds_dict, scopes=scopes)

    for attempt in range(3):
        try:
            sheet = client.open_by_key(SPREADSHEET_ID)
            return (
                sheet.worksheet("Daily_Ops").get_all_values(),
                sheet.worksheet("Site_Database").get_all_values(),
                sheet.worksheet("Fleet_Drivers").get_all_values(),
            )
        except Exception as e:
            if "429" in str(e) and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            raise e


try:
    daily_ops_raw, site_raw, driver_raw = load_google_sheet_data()
    site_lookup = parse_site_database(site_raw)
    fleet = parse_fleet(driver_raw)
    jobs, shifts = parse_daily_ops(daily_ops_raw, site_lookup)
except Exception as e:
    st.error(f"Could not load Google Sheet: {e}")
    st.stop()

with st.sidebar:
    st.header("Fleet (OT first)")
    df_fleet = pd.DataFrame(fleet)[["name", "vehicle", "type", "cap", "is_ot"]]
    st.dataframe(df_fleet, hide_index=True)
    st.caption("Names on Fleet_Drivers sheet = OT. Staff Driver N only if needed. Remove a name = on leave.")

unresolved = [j["site_label"] for j in jobs if not j["info"]]
if unresolved:
    st.warning(
        "Sites not matched in Site_Database (fix spelling / add row): "
        + ", ".join(unresolved)
    )

dinner_count = sum(1 for j in jobs if j["is_dinner"])
st.write(
    f"**Tonight:** {len(jobs)} sites · {sum(j['workers'] for j in jobs)} workers · "
    f"**{dinner_count} need food** (≥22:00) · {len(shifts)} shift(s)"
)

# Preview table
preview = []
for j in jobs:
    end = fmt_time(j["end_min"]) if j["end_min"] is not None else "?"
    preview.append(
        {
            "Site": j["site_label"],
            "End": end,
            "Workers": j["workers"],
            "Food?": "YES" if j["is_dinner"] else "—",
            "Pickup window": (
                f"{fmt_time(j['end_min'] + 10)}" if j["end_min"] is not None else "?"
            ),
            "Coords": "OK" if j["info"] and j["info"].get("lat") else "MISSING",
        }
    )
st.dataframe(pd.DataFrame(preview), hide_index=True, use_container_width=True)

if st.button("🚀 Generate Dispatch", type="primary"):
    with st.spinner("Clustering by location · OT-first assign · verifying timelines..."):
        (
            assignment,
            shift_assignment,
            cluster_notes,
            load,
            results,
            iteration_log,
        ) = assign_and_verify(jobs, shifts, fleet)

    with st.expander("Repair attempts"):
        for line in iteration_log:
            st.write("- " + line)

    any_fail = any(r["fail"] for r in results.values())
    if any_fail:
        st.error("Some drivers still have conflicts — see red expanders.")
    else:
        st.success("All drivers feasible under traffic buffer + pickup windows.")

    # Assignment summary for Daily_Ops paste-back
    st.subheader("📋 Assignment (paste into Daily_Ops Dinner / Pickup columns)")
    rows = []
    for j in jobs:
        a = assignment.get(j["site_label"], {})
        rows.append(
            {
                "Site": j["site_label"],
                "End": fmt_time(j["end_min"]) if j["end_min"] else "",
                "Workers": j["workers"],
                "Dinner Driver": a.get("dinner") or "",
                "Pickup Driver": a.get("pickup") or "",
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    st.subheader("🍽️ Food clusters (22:00+ only)")
    if cluster_notes:
        for note in cluster_notes:
            st.write("- " + note)
    else:
        st.write("No 22:00+ sites tonight — no food runs.")

    st.subheader("🚚 Driver timelines")
    st.caption(
        "Pickup: driver may arrive early and **wait** until site end time "
        "(workers still working / board ~2 min). Food must hit 6:30 PM."
    )
    # OT first in display
    ot_names = [d["name"] for d in fleet if d.get("is_ot")]
    ordered_drivers = [n for n in ot_names if n in results] + [
        n for n in results if n not in ot_names
    ]
    for driver in ordered_drivers:
        res = results[driver]
        icon = "🔴" if res["fail"] else "🟢"
        tag = "OT" if driver in ot_names else "STAFF"
        with st.expander(f"{icon} [{tag}] {driver} — {'CONFLICT' if res['fail'] else 'OK'}"):
            df = pd.DataFrame(res["log"], columns=["Task", "Timing", "OK"])
            st.table(df)

    if shift_assignment:
        st.subheader("🔄 Shifting workers")
        st.table(pd.DataFrame(shift_assignment))

    st.caption(
        f"Travel = Site_Database real minutes (or km×2+10) + {EVENING_BUFFER_MIN} min traffic buffer."
    )
