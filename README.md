# Anderco Dynamic Lorry Dispatcher

Deterministic evening dispatch for Anderco lorries — rewritten as a
**wave-based, just-in-time** engine. See the top of `dispatch_engine.py`
for the full design note; short version below.

## How it thinks

Every night's jobs are grouped into "waves" by shift-end time (7:00 PM,
9:00 PM, 10:00 PM, ...). Within a wave, jobs that are geographically close
become **one cluster and ride one lorry** — clustering runs on *every*
wave now, not just the 22:00 dinner sites. An OT driver's evening is a
chronological chain, moving straight from one task into the next:

```
[Food run] -> [middle-wave pickup, if there's a gap] -> [FINAL WAVE pickup -> HQ]
```

Three rules drive every timing decision:

1. **Pickups are just-in-time.** A driver leaves for a pickup at the
   *latest* moment that still lands them at the site ~2 min after the
   shift ends. We never send a driver out early to sit and wait at a site.
2. **HQ only shows up where workers are actually dropped off.** A pickup
   always ends with an explicit return to HQ — that's the point of a
   pickup. Food and shift legs do **not** detour through HQ: the next task
   departs straight from wherever the driver last dropped off. (This is
   the opposite of the old engine, which would send a driver out early to
   an idle wait at the pickup site, and separately forced a pointless
   round trip to HQ after every single leg regardless of whether anyone
   was actually being dropped off there.)
3. **The last wave of the night is the OT's anchor job**, spread across
   *every* OT driver rather than consolidated onto the fewest lorries —
   because that's the work that makes the OT rate worth it. It's reserved
   for each OT the moment food/shifts are locked in, so a middle-wave job
   can still use their idle time later without silently costing them that
   reservation.

## Business rules (built into the engine)

1. **Food only for sites ending at or after 22:00**, delivered by **18:30**
   target (hard cutoff 19:00). Sites ending 19:00 or 21:00 never get food.
2. **OT drivers first.** Every name on the `Fleet_Drivers` sheet is OT
   tonight — remove a name (leave) and they're gone from every list as
   soon as you hit **Refresh data**. No code change needed, and no more
   "driver removed from the sheet but still shows up" — that was a caching
   issue, fixed by the explicit refresh button.
3. **The last (latest end-time) wave is the OT's anchor job.** It's what
   makes their evening worth the OT rate, so it's OT-only and deliberately
   *spread across every OT driver* rather than consolidated onto the
   fewest lorries — if there are at least as many sites as OT, every OT
   gets one.
4. **Staff are one trip and done.** They're not OT, so they never get
   chained across multiple waves — one pickup (possibly multi-stop if
   clustered), then they're finished for the night. Staff also never touch
   the final/latest wave — that's reserved for OT.
5. **HQ only appears where workers are actually dropped off.** A pickup
   always ends with an explicit return to HQ (that's the whole point of a
   pickup). Food and shift legs do **not** force a detour through HQ — the
   driver's next task departs straight from wherever they last dropped
   off, and any OT idle time in between is used opportunistically for a
   middle-wave job *without* risking their locked-in final-wave slot.
6. **No manufactured rest windows.** OT move to their next task as soon as
   they're physically able; they eat/breathe during whatever natural gap
   the just-in-time timing leaves, not on a schedule the engine invents.
7. **Location first**, on every wave: nearby jobs share one lorry whenever
   capacity (≤25 pax, the 14ft cap) and timing allow. Clustering is decided
   by the *real* deadline math for that job type, not an arbitrary "route
   budget" constant — so it automatically adapts to how far a site is from
   HQ instead of silently under-clustering anything far out.
8. **Shifts (site-to-site, before 7 PM)** prefer a single free OT (no food
   run) to chain all of them if feasible; otherwise split across free OT,
   then busy OT, then staff.
9. **Balance OT** — every assignment step picks the driver with the fewest
   jobs/pax so far, so nobody gets a long night while another OT sits idle.
10. **Capacity** — 14ft ≈ 25 pax, 10ft ≈ 14 pax, enforced everywhere.
11. **Best-effort, never silent.** If every driver is genuinely already
    committed elsewhere, the engine widens the lateness tolerance in steps
    rather than dropping the job outright — and flags it loudly (⚠️) in the
    planning log so you can see exactly which nights the fleet is short a
    lorry, instead of the job just vanishing off the plan.

## You do not need Python on your PC

### Option A — GitHub Codespaces (browser)

1. Open the repo on GitHub
2. Code → Codespaces → Create codespace
3. In the terminal:
   ```bash
   pip install -r requirements.txt
   streamlit run app.py
   ```
4. Open the forwarded URL. Add Google service-account secret (below).

### Option B — Streamlit Community Cloud

1. Push this repo to GitHub
2. Deploy at share.streamlit.io with `app.py`
3. Add secrets under Settings → Secrets

### Streamlit secrets (GCP service account)

```toml
[gcp_service_account]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "...@....iam.gserviceaccount.com"
client_id = "..."
token_uri = "https://oauth2.googleapis.com/token"
```

Share the Google Sheet with `client_email` as Editor.

## Daily workflow (the only thing you touch nightly)

1. `Fleet_Drivers`: who's on duty tonight (add/remove names for leave).
2. `Daily_Ops`: Site / End Time / Workers, and any site-to-site shifts.
3. Open the dispatcher → **Refresh data** (if you just edited the sheet)
   → **Generate Dispatch**.
4. Copy Dinner / Pickup drivers back into `Daily_Ops` if you paper-track it.
5. Check the planning log expander for any ⚠️ / `[!]` lines — those are
   the nights the fleet is genuinely short a lorry for the geography you
   were given, not a bug to chase.

## Config (`config.json`)

```json
{
  "spreadsheet_id": "1AJXN_aUILuokaJhPLCTVb7IIwLnzc3gKpPCmfrJLOdY",
  "traffic_buffer_mins": 15,
  "hq_lat": 1.2947675,
  "hq_lon": 103.6345739
}
```

Everything else (evening start time, food target/cutoff, pickup lateness
tolerance, minimum HQ rest between waves) is a named constant near the top
of `dispatch_engine.py` — change a constant there if a rule genuinely
needs retuning; you should not need to touch the algorithm itself.
