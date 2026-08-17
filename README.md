# Anderco Dynamic Lorry Dispatcher

Deterministic evening dispatch for Anderco lorries.

## Business rules (built into the engine)

1. **Pickup = end time + 10 minutes**  
   Workers finish work, scan Infotech, then board. Drivers must not pick up at 5–6 PM for a 9–10 PM site. If the lorry arrives early, it **waits** at the site until end time.

2. **Food only for sites ending at or after 22:00**  
   Food must arrive by **18:30** (hard cutoff 19:00). Sites ending 19:00 or 21:00 do **not** get a food run.

3. **Location first**  
   Nearby 22:00 sites are clustered on one lorry when workers fit (≤25) and the food route is driveable.

4. **OT drivers first**  
   Order: **Mahendran → Sridhar → Kailing → Senthil → Pandi**.  
   Staff drivers only when OT cannot cover. Named **Staff Driver 1, 2, …**

5. **OT work continuously**  
   Only traffic buffer (+15 min) is added to travel times.

6. **Return to HQ** after a pickup before the next distant job. Nearby same-band pickups can be chained.

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

## Daily workflow

1. Daily_Ops: enter Site / End Time / Workers (shifts if any)  
2. Open dispatcher → Generate Dispatch  
3. Copy Dinner / Pickup drivers into Daily_Ops if needed  
4. Read timelines: food by 6:30, pickups at end+10

## Config (`config.json`)

```json
{
  "spreadsheet_id": "1AJXN_aUILuokaJhPLCTVb7IIwLnzc3gKpPCmfrJLOdY",
  "traffic_buffer_mins": 15,
  "hq_lat": 1.2947675,
  "hq_lon": 103.6345739
}
```
