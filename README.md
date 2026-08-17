# 🚚 Dynamic Lorry Dispatch Generator

## What changed (and why the old version failed)

The original `app.py` dumped your whole Daily_Ops/Site_Database/Fleet_Drivers
data into a text prompt and asked Gemini to *imagine* a schedule as free-form
markdown. An LLM is not a calculator - it produced plausible-**looking**
times (round numbers like 18:00, 18:15, 21:00, 21:30) with no real distance
or travel-time computation behind them at all. That's how it ended up
sending one driver from Tuas to Punggol in a claimed 30 minutes when the
real drive is 83 minutes - the model never called a distance function,
because there wasn't one in the code to call.

This version replaces that with `dispatch_engine.py`: plain, deterministic
Python that:

1. **Computes real distances** - haversine formula between every pair of
   real GPS coordinates in your `Site_Database`.
2. **Computes real travel time** - `distance_km * 2 + 10 min base + 15 min
   evening traffic buffer`, calibrated against your team's actual WhatsApp
   chat history.
3. **Clusters 10 PM (dinner) sites** only when they're close enough AND a
   full nearest-neighbour route through the cluster actually fits inside a
   120-minute driving budget - not just "under 25 people and under 8km apart
   on paper."
4. **Balances load across your fleet** - prefers a site's historical driver
   only if that driver isn't already carrying 2+ other jobs; otherwise picks
   whichever eligible driver currently has the least load. This is what
   stops one driver (e.g. Mahendran) from silently absorbing every job in
   "his" territory while others sit idle.
5. **Verifies every driver's entire evening** - simulates each task in
   order with real travel times and flags anything that's actually late,
   not just plausible-sounding.
6. **Repairs conflicts automatically** - if step 5 finds a driver overloaded,
   it steers the specific conflicting job to a different driver (checking
   your other primary drivers first, then falling back to the staff/backup
   pool: Saravanan, Tianwei, Ramesh) and re-verifies, up to 6 attempts. If it
   still can't resolve everything, it says so honestly in the schedule
   instead of hiding a broken plan behind a green checkmark.

Tested end-to-end against your actual live Daily_Ops/Site_Database data
(16 sites, 92 workers, 2 dinner clusters): the first pass came back with 2
overloaded drivers (one carrying 56 workers' worth of jobs alone); the
repair loop resolved it in 6 attempts down to 8 drivers all clear, load
spread 4-29 instead of one driver doing everything.

No API key is required to run this anymore - the scheduling logic doesn't
call any AI model. It reads live from the same Google Sheet as before
(`Daily_Ops`, `Site_Database`, `Fleet_Drivers`).

## File Structure
* **`dispatch_engine.py`** - all the real logic (parsing, distance math,
  clustering, assignment, verification, repair loop). No Streamlit or
  Google Sheets dependency in here, so it can be tested standalone.
* **`app.py`** - thin Streamlit UI. Loads the sheet, calls
  `dispatch_engine.assign_and_verify()`, displays the result.
* **`main.py`** - execution wrapper (unchanged).
* **`config.json`** - HQ coordinates, traffic buffer, spreadsheet ID.
* **`requirements.txt`** - `streamlit`, `gspread`, `pandas` (no longer
  needs `google-generativeai`).

## Setup Instructions
1. Install dependencies: `pip install -r requirements.txt`
2. Ensure your `.streamlit/secrets.toml` contains your `gcp_service_account`
   credentials (unchanged from before).
3. Run the app: `python main.py` or `streamlit run app.py`

## Testing the engine without a live Google Sheets connection
`dispatch_engine.py` has no Streamlit/gspread imports, so you can unit-test
it directly:

```python
from dispatch_engine import parse_site_database, parse_fleet, parse_daily_ops, assign_and_verify

# raw_rows = same list-of-lists format gspread's get_all_values() returns
site_lookup = parse_site_database(site_raw_rows)
fleet = parse_fleet(driver_raw_rows)
jobs, shifts = parse_daily_ops(daily_ops_raw_rows, site_lookup)

assignment, shift_assignment, cluster_notes, load, results, iteration_log = assign_and_verify(jobs, shifts, fleet)
```

`results` gives you, per driver, `fail` (True/False) and a `log` of every
task with its real computed arrival time versus its deadline - the same
verification the UI displays.
