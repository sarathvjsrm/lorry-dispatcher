import time
import gspread
import streamlit as st
import pandas as pd

from dispatch_engine import (
    config,
    parse_site_database,
    parse_fleet,
    parse_daily_ops,
    build_schedule,
    driver_timeline_rows,
    EVENING_BUFFER_MIN,
    DINNER_END_THRESHOLD,
    fmt_time,
)

st.set_page_config(page_title="Anderco Lorry Dispatcher", page_icon="🚚", layout="wide")
st.title("🚚 Anderco Dynamic Lorry Dispatcher")
st.caption(
    "OT first · food only for ≥22:00 sites, delivered by 6:30 PM · pickups are "
    "just-in-time (never sent early to wait at a site) · HQ shown on every leg · "
    "location-first clustering on EVERY wave, not just dinner."
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


top_l, top_r = st.columns([5, 1])
with top_r:
    if st.button("🔄 Refresh data"):
        st.cache_data.clear()
        st.rerun()
st.caption(
    "Sheet data is cached for up to 2 minutes for speed. If you just edited "
    "Fleet_Drivers or Daily_Ops (e.g. removed someone on leave), hit **Refresh data** "
    "before generating tonight's dispatch so you're not looking at a stale sheet."
)

try:
    daily_ops_raw, site_raw, driver_raw = load_google_sheet_data()
    site_lookup = parse_site_database(site_raw)
    fleet = parse_fleet(driver_raw)
    jobs, shifts = parse_daily_ops(daily_ops_raw, site_lookup)
except Exception as e:
    st.error(f"Could not load Google Sheet: {e}")
    st.stop()

with st.sidebar:
    st.header("Fleet tonight (OT first)")
    df_fleet = pd.DataFrame(fleet)[["name", "vehicle", "type", "cap", "is_ot"]]
    st.dataframe(df_fleet, hide_index=True)
    st.caption(
        "Every name on Fleet_Drivers = OT tonight. Remove a name (leave) and they "
        "disappear from every list immediately after Refresh data. Staff Driver "
        "N are backups only, used when OT truly can't cover a job."
    )

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

preview = []
for j in jobs:
    end = fmt_time(j["end_min"]) if j["end_min"] is not None else "?"
    preview.append(
        {
            "Site": j["site_label"],
            "End": end,
            "Workers": j["workers"],
            "Food?": "YES" if j["is_dinner"] else "—",
            "Coords": "OK" if j["info"] and j["info"].get("lat") else "MISSING",
        }
    )
st.dataframe(pd.DataFrame(preview), hide_index=True, use_container_width=True)

if st.button("🚀 Generate Dispatch", type="primary"):
    with st.spinner("Clustering every wave by location · OT-first, just-in-time timing..."):
        assignment, shift_assignment, notes, states = build_schedule(jobs, shifts, fleet)

    problems = [n for n in notes if n.startswith("[!]") or n.startswith("⚠️")]
    if problems:
        st.error(f"{len(problems)} item(s) need your attention tonight — see below.")
    else:
        st.success("Every site has a driver, on time, within tolerance.")

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

    if shift_assignment:
        st.subheader("🔄 Shifting workers")
        st.table(pd.DataFrame(shift_assignment))

    st.subheader("🚚 Driver timelines")
    st.caption(
        "Just-in-time: a driver leaves HQ at the latest moment that still makes "
        "the pickup on time. Idle time shows as 'Rest at HQ', never as waiting at a site."
    )
    ot_names = [d["name"] for d in fleet if d.get("is_ot")]
    ordered_drivers = [n for n in ot_names if n in states] + [
        n for n in states if n not in ot_names
    ]
    for driver in ordered_drivers:
        st_ = states[driver]
        if not st_.engagements:
            continue
        tag = "OT" if st_.is_ot else "STAFF"
        icon = "🟢"
        for leg in st_.engagements:
            if leg.get("max_lateness", 0) > 0 or not leg.get("feasible", True):
                icon = "🟡"
        with st.expander(f"{icon} [{tag}] {driver} — {st_.jobs_count} job(s), {st_.pax_count} pax"):
            df = pd.DataFrame(driver_timeline_rows(st_), columns=["Task", "Timing"])
            st.table(df)

    idle_ot = [d["name"] for d in fleet if d.get("is_ot") and not states[d["name"]].engagements]
    if idle_ot:
        st.warning(f"Idle OT tonight (no feasible slot found for them): {', '.join(idle_ot)}")

    st.subheader("🗒️ Full planning log")
    with st.expander("Show every clustering / assignment decision made tonight"):
        for note in notes:
            st.write("- " + note)

    st.caption(
        f"Travel = Site_Database real HQ minutes (or km×2+10) + {EVENING_BUFFER_MIN} min "
        "traffic buffer on HQ legs; lighter estimate for short site-to-site hops within a cluster."
    )
