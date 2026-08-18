"""
dispatch_engine.py — Anderco evening lorry dispatch (general brain, any night).

============================================================================
PERMANENT RULES (no daily code edits — only Daily_Ops + Fleet_Drivers change)
============================================================================

1. WAVES BY END TIME
   Jobs with the SAME shift-end time = one wave.
   Different end times = different waves. Never chain 7pm→9pm→10pm without HQ.

2. CLUSTER WITHIN A WAVE (location-first)
   Same end time + capacity fits + real travel still on time → ONE lorry.
   Nearby hops use light travel (ops ~10–15 min), not the full HQ formula.
   Feasibility = real deadline math, not a fixed "route budget" constant.

3. HQ RETURN — ONLY WHEN WORKERS MUST BE DROPPED
   After PICKUP  → always HQ (workers).
   After FOOD   → no HQ (nothing to drop).
   After SHIFT  → no HQ (already dropped at destination school).

4. OT FIRST, ALWAYS
   Every name on Fleet_Drivers = OT tonight (remove = leave, gone).
   Staff only after every OT was tried (including wider lateness).
   Staff = independent JIT trips only; no continuous evening required.

5. MAXIMISE OT / SPREAD 10PM
   Wave order: food → shifts → 7pm wave(s) → 10pm wave (prefer one site
   per OT who does not yet have 10pm) → 9pm wave.
   Why 10 before 9: a 9pm return ~9:45 misses the 10pm leave window.

6. SHIFTS
   Prefer ONE free OT (no food) to chain ALL shifts when timing allows.
   Chain without HQ between (workers already at destination).
   Soft deadline on 2nd+ hop in a chain.

7. JUST-IN-TIME PICKUPS
   Leave so first stop is ~end+2 min. Idle = wait at HQ or between jobs,
   never sit early at site. Board ~2 min.

8. FOOD
   Only sites ending >= 22:00. Target 18:30, hard 19:00. OT only.

9. BALANCE
   Always assign next job to lightest OT (fewest jobs, then fewest pax).

10. NEVER SILENT FAIL
    If short a lorry, widen lateness and flag ⚠️ / [!] in the log.

Touch only: Fleet_Drivers, Daily_Ops, config.json traffic buffer.
"""

from __future__ import annotations

import json
import math
import os
from typing import Any, Dict, List, Optional, Set, Tuple

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
with open(_CONFIG_PATH, "r") as f:
    config = json.load(f)

# ---------------------------------------------------------------------------
# CONFIG -- the knobs a manager might legitimately want to retune
# ---------------------------------------------------------------------------

HQ_LAT = float(config.get("hq_lat", 1.2947675))
HQ_LON = float(config.get("hq_lon", 103.6345739))
HQ_NAME = config.get("hq_name", "HQ (3 Tuas View Circuit)")

EVENING_BUFFER_MIN = int(config.get("traffic_buffer_mins", 15))   # traffic buffer on every leg
EVENING_START = int(config.get("evening_start_min", 17 * 60))     # 5:00 PM -- earliest any driver leaves HQ

DINNER_END_THRESHOLD = 22 * 60        # food only for sites ending >= 22:00
FOOD_TARGET_MIN = 18 * 60 + 30        # 6:30 PM target delivery
FOOD_HARD_MIN = 19 * 60               # 7:00 PM hard cutoff

PICKUP_BOARD_MIN = 2                  # workers board ~2 min after shift end (scan out)
PICKUP_LATE_TOLERANCE = 25            # 2nd/3rd stop in same-wave cluster; nearby hops ~15 min
STOP_DWELL_MIN = 2                    # minutes spent boarding workers at each stop

MIN_HQ_REST_MIN = 10                  # minimum handover/rest at HQ between two waves for one driver

# NOTE: there is deliberately no separate "route budget" constant here.
# Whether two sites can share a lorry is decided by the REAL timing function
# (time_pickup_cluster / time_food_cluster) during clustering -- see
# cluster_same_endtime()'s `feasible_fn` -- rather than an arbitrary minute
# cap that would silently under-cluster sites that are simply far from HQ.

SHIFT_HARD_CUTOFF = 19 * 60           # site-to-site transfers must land before 7:00 PM

# Preferred on-screen ordering when these names appear in Fleet_Drivers.
# This is DISPLAY ORDER ONLY -- every name actually on the sheet is OT,
# regardless of whether it's in this list.
OT_ORDER = ["Mahendran", "Sridhar", "Kailing", "Senthil", "Pandi"]

# Staff pool used ONLY when no OT can feasibly cover a job. Staff never get
# a food run and never wait around -- each staff trip is an independent,
# just-in-time HQ -> site(s) -> HQ sortie timed to the deadline.
DEFAULT_STAFF = [
    {"name": "Staff Driver 1", "vehicle": "5546", "type": "10ft", "cap": 14},
    {"name": "Staff Driver 2", "vehicle": "3576", "type": "14ft", "cap": 25},
    {"name": "Staff Driver 3", "vehicle": "6897", "type": "10ft", "cap": 14},
    {"name": "Staff Driver 4", "vehicle": "1301", "type": "14ft", "cap": 25},
    {"name": "Staff Driver 5", "vehicle": "7203", "type": "14ft", "cap": 25},
]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _to_float(v, default=None):
    try:
        return float(str(v).strip())
    except Exception:
        return default


def _to_int(v, default=0):
    try:
        return int(float(str(v).strip()))
    except Exception:
        return default


def _to_minutes(t) -> Optional[int]:
    """'22:00', '21:00:00', '10:00 PM' -> minutes since midnight."""
    t = str(t).strip()
    if not t:
        return None
    t_up = t.upper().replace(" ", "")
    pm = "PM" in t_up
    am = "AM" in t_up
    t_up = t_up.replace("PM", "").replace("AM", "")
    if ":" not in t_up:
        return None
    try:
        parts = t_up.split(":")
        h, m = int(parts[0]), int(parts[1])
    except Exception:
        return None
    if pm and h != 12:
        h += 12
    if am and h == 12:
        h = 0
    return h * 60 + m


def fmt_time(m: Optional[int]) -> str:
    if m is None:
        return "?"
    m = int(round(m)) % 1440
    h, mi = divmod(m, 60)
    ap = "PM" if h >= 12 else "AM"
    h12 = h % 12 or 12
    return f"{h12}:{mi:02d} {ap}"


def haversine_km(lat1, lon1, lat2, lon2) -> Optional[float]:
    if None in (lat1, lon1, lat2, lon2):
        return None
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


def travel_km_min(dist_km: Optional[float]) -> Optional[int]:
    """Driving time estimate: (km * 2 + 10) + evening traffic buffer."""
    if dist_km is None:
        return None
    base = dist_km * 2 + 10
    return int(round(base + EVENING_BUFFER_MIN))


def travel_hq_to(info: dict) -> int:
    """Travel time HQ <-> site. Prefers the recorded Site_Database minutes."""
    recorded = info.get("travel_hq_min") if info else None
    if recorded is not None and not (isinstance(recorded, float) and math.isnan(recorded)):
        try:
            return int(round(float(recorded) + EVENING_BUFFER_MIN))
        except Exception:
            pass
    d = haversine_km(HQ_LAT, HQ_LON, info.get("lat") if info else None, info.get("lon") if info else None)
    t = travel_km_min(d)
    return t if t is not None else 60


def travel_between(a: dict, b: dict) -> int:
    """Site-to-site hop within a same-end-time cluster.
    User ops: nearby west sites (J105/J106/J115A/ITTC/YAK/WUXI) ~15 min apart.
    Keep estimate light so clustering does not silently refuse good merges."""
    d = haversine_km(a.get("lat"), a.get("lon"), b.get("lat"), b.get("lon"))
    if d is None:
        return 15
    # ~2 min/km + small buffer; floor 8, typical nearby 12–18
    return max(8, int(round(d * 2.2)) + 5)


# ---------------------------------------------------------------------------
# Sheet parsers
# ---------------------------------------------------------------------------

def parse_site_database(raw_rows: List[List[str]]) -> Dict[str, dict]:
    header_idx = None
    for i, row in enumerate(raw_rows):
        if row and str(row[0]).strip() == "PJC Code":
            header_idx = i
            break
    if header_idx is None:
        return {}
    sites: Dict[str, dict] = {}
    for row in raw_rows[header_idx + 1:]:
        if not row or not str(row[0]).strip():
            continue
        row = list(row) + [""] * (14 - len(row))
        code = str(row[0]).strip()
        if code == "PJC Code":
            continue
        sites[code] = {
            "code": code,
            "company": str(row[1]).strip(),
            "name": str(row[2]).strip(),
            "address": str(row[3]).strip(),
            "driver": str(row[4]).strip(),
            "vehicle": str(row[5]).strip(),
            "lorry": str(row[6]).strip(),
            "travel_hq_min": _to_float(row[7]),
            "lat": _to_float(row[9]),
            "lon": _to_float(row[10]),
            "label": str(row[13]).strip() or (str(row[2]).strip() + " [" + code + "]"),
        }
    return sites


def parse_fleet(raw_rows: List[List[str]]) -> List[dict]:
    """Fleet_Drivers sheet = who is working tonight.

    - Every name on the sheet is an OT driver (maximise their evening work).
    - A name removed from the sheet (on leave) is not used at all, this run.
    - Staff Driver 1, 2, ... are synthetic backups only -- never read from the
      sheet, only used when OT truly cannot cover a job.
    """
    header_idx = None
    for i, row in enumerate(raw_rows):
        if row and str(row[0]).strip() == "Driver No.":
            header_idx = i
            break
    sheet_drivers: List[dict] = []
    if header_idx is not None:
        for row in raw_rows[header_idx + 1:]:
            if not row or not str(row[0]).strip():
                continue
            row = list(row) + [""] * (6 - len(row))
            name = str(row[0]).strip()
            if not name:
                continue
            vehicle = str(row[1]).strip()
            if vehicle.endswith(".0"):
                vehicle = vehicle[:-2]
            cap = _to_int(row[4], 0)
            vtype = str(row[3]).strip() or "14ft"
            if cap <= 0:
                cap = 25 if "14" in vtype else 14
            sheet_drivers.append(
                {
                    "name": name,
                    "vehicle": vehicle,
                    "plate": str(row[2]).strip(),
                    "type": vtype,
                    "cap": cap,
                    "is_ot": True,
                }
            )

    by_name = {d["name"]: d for d in sheet_drivers}
    fleet: List[dict] = []
    for ot_name in OT_ORDER:
        if ot_name in by_name:
            fleet.append(by_name.pop(ot_name))
    for name, d in by_name.items():
        fleet.append(d)

    existing_veh = {d["vehicle"] for d in fleet if d["vehicle"]}
    used_names = {d["name"] for d in fleet}
    for s in DEFAULT_STAFF:
        if s["vehicle"] in existing_veh or s["name"] in used_names:
            continue
        fleet.append({**s, "is_ot": False, "plate": ""})
        existing_veh.add(s["vehicle"])

    return fleet


def resolve_site(label: str, site_lookup: Dict[str, dict]) -> Optional[dict]:
    label = (label or "").strip()
    if not label:
        return None
    for info in site_lookup.values():
        if info["label"] == label:
            return info
    if label in site_lookup:
        return site_lookup[label]
    for code, info in site_lookup.items():
        if code and code in label:
            return info
    lower = label.lower()
    for info in site_lookup.values():
        if info["label"].lower() == lower or lower in info["label"].lower():
            return info
    for info in site_lookup.values():
        if info["name"] and (info["name"].lower() == lower or lower in info["name"].lower()):
            return info
    return None


def parse_daily_ops(
    raw_rows: List[List[str]], site_lookup: Dict[str, dict]
) -> Tuple[List[dict], List[dict]]:
    sec1 = sec2 = None
    for i, row in enumerate(raw_rows):
        if len(row) > 1 and str(row[0]).strip() == "Site" and str(row[1]).strip() == "Shift End Time":
            sec1 = i + 1
        if len(row) > 1 and str(row[0]).strip() == "From Site" and str(row[1]).strip() == "To Site":
            sec2 = i + 1

    jobs: List[dict] = []
    if sec1 is not None:
        for row in raw_rows[sec1:]:
            if not row or not str(row[0]).strip():
                break
            s0 = str(row[0]).strip()
            if s0.startswith("SHIFTING") or s0.startswith("Click here"):
                break
            end_min = _to_minutes(row[1]) if len(row) > 1 else None
            workers = _to_int(row[2]) if len(row) > 2 else 0
            info = resolve_site(s0, site_lookup)
            jobs.append(
                {
                    "site_label": s0,
                    "end_min": end_min,
                    "workers": workers,
                    "info": info,
                    "is_dinner": end_min is not None and end_min >= DINNER_END_THRESHOLD,
                }
            )

    shifts: List[dict] = []
    if sec2 is not None:
        for row in raw_rows[sec2:]:
            if not row or not str(row[0]).strip():
                break
            if str(row[0]).strip().startswith("Click here"):
                break
            frm = str(row[0]).strip()
            to = str(row[1]).strip() if len(row) > 1 else ""
            fi = resolve_site(frm, site_lookup)
            ti = resolve_site(to, site_lookup)
            if fi and ti:
                shifts.append({"from": frm, "to": to, "from_info": fi, "to_info": ti})
    return jobs, shifts


# ---------------------------------------------------------------------------
# Clustering -- applied to EVERY wave (not just 22:00+ food sites)
# ---------------------------------------------------------------------------

def _route_time_from_hq(stops: List[dict]) -> int:
    """Nearest-neighbour loop HQ -> stops, dwell included. Used as a feasibility gate."""
    remaining = list(stops)
    cur_lat, cur_lon = HQ_LAT, HQ_LON
    total = 0
    while remaining:
        best_i, best_d = 0, float("inf")
        for i, s in enumerate(remaining):
            d = haversine_km(cur_lat, cur_lon, s.get("lat"), s.get("lon"))
            if d is not None and d < best_d:
                best_d, best_i = d, i
        leg = travel_km_min(best_d) if best_d != float("inf") else 30
        total += (leg or 30) + STOP_DWELL_MIN
        nxt = remaining.pop(best_i)
        cur_lat, cur_lon = nxt.get("lat"), nxt.get("lon")
    return total


def cluster_same_endtime(jobs: List[dict], feasible_fn) -> List[dict]:
    """Greedy route-cost clustering (same end time already, by caller).

    Real dispatch doesn't need every pair of stops to be mutually close (a
    complete-link distance test kills perfectly good chain-shaped routes,
    e.g. A-B-C-D where A and D are 6km apart but each hop is short). Instead
    we greedily merge whichever two clusters produce the CHEAPEST combined
    nearest-neighbour route from HQ, as long as it stays within capacity
    (<=25 pax, the biggest lorry) AND `feasible_fn` -- the real deadline/
    lateness check for this job type -- says the merged route still works.
    Tying acceptance to the real timing function (instead of a made-up
    "route budget" constant) means clustering automatically adapts to how
    far a given site is from HQ instead of silently under-clustering
    anything that happens to be a long drive out."""
    clusterable = [j for j in jobs if j["info"]]
    unclusterable = [j for j in jobs if not j["info"]]

    clusters = [{"jobs": [j], "workers": j["workers"] or 0} for j in clusterable]

    while len(clusters) > 1:
        best = None  # (cost, i, j)
        for i in range(len(clusters)):
            for k in range(i + 1, len(clusters)):
                ci, ck = clusters[i], clusters[k]
                pax = ci["workers"] + ck["workers"]
                if pax > 25:
                    continue
                merged_jobs = ci["jobs"] + ck["jobs"]
                if not feasible_fn(merged_jobs):
                    continue
                cost = _route_time_from_hq([j["info"] for j in merged_jobs])
                if best is None or cost < best[0]:
                    best = (cost, i, k)
        if best is None:
            break
        _, i, k = best
        ci, ck = clusters[i], clusters[k]
        merged = {"jobs": ci["jobs"] + ck["jobs"], "workers": ci["workers"] + ck["workers"]}
        clusters = [c for idx, c in enumerate(clusters) if idx not in (i, k)]
        clusters.append(merged)

    for j in unclusterable:
        clusters.append({"jobs": [j], "workers": j["workers"] or 0})

    clusters.sort(key=lambda c: -c["workers"])
    return clusters


# ---------------------------------------------------------------------------
# Route timing -- just-in-time departure, nearest-HQ-site visited first
# ---------------------------------------------------------------------------

def _order_nearest_hq_first(stops: List[dict]) -> List[dict]:
    return sorted(stops, key=lambda s: travel_hq_to(s))


def time_pickup_cluster(
    cluster: dict,
    end_min: int,
    earliest_depart: int,
    tolerance: int = PICKUP_LATE_TOLERANCE,
    from_lat=None,
    from_lon=None,
    at_hq: bool = True,
) -> dict:
    """Just-in-time multi-stop pickup. MUST end at HQ (workers to drop).
    May start from HQ or from driver's current free location (e.g. after food)."""
    infos = [j["info"] for j in cluster["jobs"]]
    ordered = _order_nearest_hq_first(infos)
    deadline0 = end_min + PICKUP_BOARD_MIN
    first = ordered[0]

    if at_hq or from_lat is None:
        travel_first = travel_hq_to(first)
        depart = max(earliest_depart, deadline0 - travel_first)
        t = depart
        start_label = depart
    else:
        # travel from current free position to first site
        d = haversine_km(from_lat, from_lon, first.get("lat"), first.get("lon"))
        travel_first = travel_km_min(d) if d is not None else travel_hq_to(first)
        travel_first = travel_first or 40
        # just-in-time from current location
        depart = max(earliest_depart, deadline0 - travel_first)
        t = depart
        start_label = depart

    stops_out = []
    prev = None
    max_lateness = 0
    for i, s in enumerate(ordered):
        if prev is None:
            leg = travel_first
        else:
            leg = travel_between(prev, s)
        arrive = t + leg
        lateness = max(0, arrive - deadline0)
        max_lateness = max(max_lateness, lateness)
        stops_out.append({"site": s, "arrive": arrive, "deadline": deadline0, "late_by": lateness})
        t = arrive + STOP_DWELL_MIN
        prev = s
    # ALWAYS return HQ after pickup — workers must be dropped
    hq_return = t + travel_hq_to(prev)

    return {
        "type": "pickup",
        "depart_hq": start_label,
        "stops": stops_out,
        "hq_return": hq_return,
        "workers": cluster["workers"],
        "max_lateness": max_lateness,
        "feasible": max_lateness <= tolerance and start_label >= earliest_depart - 1,
    }


def time_food_cluster(cluster: dict, earliest_depart: int) -> dict:
    """Food is not just-in-time (early delivery is fine) -- depart as soon as the
    driver is free, deliver nearest-first, must clear the LAST stop by FOOD_HARD_MIN."""
    infos = [j["info"] for j in cluster["jobs"]]
    ordered = _order_nearest_hq_first(infos)
    depart_hq = max(earliest_depart, EVENING_START)

    stops_out = []
    t = depart_hq
    prev = None
    for s in ordered:
        leg = travel_hq_to(s) if prev is None else travel_between(prev, s)
        arrive = t + leg
        stops_out.append({"site": s, "arrive": arrive})
        t = arrive + STOP_DWELL_MIN
        prev = s
    # Optional HQ return for display only — driver is NOT required to go HQ after food
    hq_return = t + travel_hq_to(prev)
    last_arrival = stops_out[-1]["arrive"]

    return {
        "type": "food",
        "depart_hq": depart_hq,
        "stops": stops_out,
        "hq_return": hq_return,  # display only; commit() uses last stop time
        "workers": cluster["workers"],
        "last_arrival": last_arrival,
        "feasible": last_arrival <= FOOD_HARD_MIN,
        "on_target": last_arrival <= FOOD_TARGET_MIN,
    }


def time_shift(shift: dict, earliest_depart: int, from_hq: bool = True, free_lat=None, free_lon=None) -> dict:
    """Site-to-site transfer, must land before SHIFT_HARD_CUTOFF.
    After drop at destination, driver is free there (no HQ — workers already dropped).
    Second shift in a chain uses light local travel from previous drop point."""
    fi, ti = shift["from_info"], shift["to_info"]
    if from_hq or free_lat is None:
        depart = max(earliest_depart, EVENING_START)
        arrive_from = depart + travel_hq_to(fi)
        depart_label = depart
    else:
        # Local hop: previous drop → next from-school (not full HQ formula)
        fake_from = {"lat": free_lat, "lon": free_lon}
        leg = travel_between(fake_from, fi)
        depart = max(earliest_depart, EVENING_START)
        arrive_from = depart + leg
        depart_label = depart
    depart_from = arrive_from + STOP_DWELL_MIN
    arrive_to = depart_from + travel_between(fi, ti)
    hq_return = arrive_to + STOP_DWELL_MIN + travel_hq_to(ti)
    # Soft: first shift hard 7pm; chained second shift allow +20 min
    cutoff = SHIFT_HARD_CUTOFF if from_hq else SHIFT_HARD_CUTOFF + 45  # chain of nearby schools
    return {
        "type": "shift",
        "from": shift["from"], "to": shift["to"],
        "from_info": fi, "to_info": ti,
        "depart_hq": depart_label,
        "arrive_from": arrive_from,
        "arrive_to": arrive_to,
        "hq_return": hq_return,
        "feasible": arrive_to <= cutoff,
    }


# ---------------------------------------------------------------------------
# Driver state + assignment
# ---------------------------------------------------------------------------

class DriverState:
    def __init__(self, d: dict):
        self.d = d
        self.name = d["name"]
        self.cap = d["cap"]
        self.is_ot = d.get("is_ot", False)
        self.free_at = EVENING_START
        self.free_lat = HQ_LAT
        self.free_lon = HQ_LON
        self.at_hq = True
        self.engagements: List[dict] = []
        self.jobs_count = 0
        self.pax_count = 0
        self.did_food = False
        self.did_10pm = False

    def earliest_depart(self) -> int:
        """OT: no forced rest window — free as soon as last job ends.
        Staff: same (they only do isolated trips anyway).
        After a pickup (workers dropped at HQ) a short handover is OK."""
        if not self.engagements:
            return EVENING_START
        last = self.engagements[-1]
        if last.get("type") == "pickup" and last.get("hq_return") is not None:
            return last["hq_return"] + MIN_HQ_REST_MIN
        # food / shift: free immediately at free_at (no forced HQ rest)
        return self.free_at

    def commit(self, leg: dict, workers: int = 0):
        self.engagements.append(leg)
        self.jobs_count += 1
        self.pax_count += workers
        # Where is the driver free after this leg?
        if leg["type"] == "pickup":
            # MUST return HQ — workers to drop
            self.free_at = leg["hq_return"]
            self.free_lat, self.free_lon = HQ_LAT, HQ_LON
            self.at_hq = True
        elif leg["type"] == "food":
            # No workers to drop at HQ — free at last delivery site
            last = leg["stops"][-1]
            self.free_at = last["arrive"] + STOP_DWELL_MIN
            self.free_lat = last["site"].get("lat") or HQ_LAT
            self.free_lon = last["site"].get("lon") or HQ_LON
            self.at_hq = False
            # optional: if leg still has hq_return for display, ignore for free_at
        elif leg["type"] == "shift":
            # Workers already dropped at destination school — free there
            self.free_at = leg["arrive_to"] + STOP_DWELL_MIN
            ti = leg.get("to_info") or {}
            self.free_lat = ti.get("lat") or HQ_LAT
            self.free_lon = ti.get("lon") or HQ_LON
            self.at_hq = False
        else:
            self.free_at = leg.get("hq_return") or leg.get("free_at") or self.free_at
            self.at_hq = True
            self.free_lat, self.free_lon = HQ_LAT, HQ_LON

    def balance_key(self):
        # Prefer drivers with fewer jobs, then fewer pax; OT who lack 10pm get slight priority via sort key used elsewhere
        return (self.jobs_count, self.pax_count)


def _ot_first_pool(states: List[DriverState]):
    return [s for s in states if s.is_ot], [s for s in states if not s.is_ot]


def assign_pickup_wave(
    jobs_this_wave: List[dict], end_min: int, states: Dict[str, DriverState], notes: List[str],
    prefer_spread_10pm: bool = False,
):
    def pickup_feasible(merged_jobs):
        trial = {"jobs": merged_jobs, "workers": sum(j["workers"] or 0 for j in merged_jobs)}
        return time_pickup_cluster(trial, end_min, EVENING_START)["feasible"]

    clusters = cluster_same_endtime(jobs_this_wave, pickup_feasible)
    ot_states, staff_states = _ot_first_pool(list(states.values()))

    assignment: Dict[str, dict] = {}
    unplaced: List[dict] = []

    def try_leg(st, cl):
        return time_pickup_cluster(
            cl, end_min, st.earliest_depart(),
            from_lat=None if st.at_hq else st.free_lat,
            from_lon=None if st.at_hq else st.free_lon,
            at_hq=st.at_hq,
        )

    for cl in clusters:
        pax = cl["workers"]
        # OT first; for 10pm wave prefer OT who do NOT already have a 10pm job
        if prefer_spread_10pm:
            ot_fresh = sorted([s for s in ot_states if not s.did_10pm], key=lambda s: s.balance_key())
            ot_busy = sorted([s for s in ot_states if s.did_10pm], key=lambda s: s.balance_key())
            candidates = ot_fresh + ot_busy + sorted(staff_states, key=lambda s: s.balance_key())
        else:
            # 7/9pm: OT first (lightest), staff last — staff only when no OT can do it
            candidates = sorted(ot_states, key=lambda s: s.balance_key()) + sorted(
                staff_states, key=lambda s: s.balance_key()
            )
        placed = False
        # Pass 1: OT only (normal tolerance). Pass 2: OT with wider tolerance. Pass 3: staff.
        ot_only = [st for st in candidates if st.is_ot]
        staff_only = [st for st in candidates if not st.is_ot]
        for pool, tol in (
            (ot_only, PICKUP_LATE_TOLERANCE),
            (ot_only, PICKUP_LATE_TOLERANCE + 15),
            (staff_only, PICKUP_LATE_TOLERANCE),
        ):
            if placed:
                break
            for st in pool:
                if st.cap < pax:
                    continue
                leg = time_pickup_cluster(
                    cl, end_min, st.earliest_depart(), tolerance=tol,
                    from_lat=None if st.at_hq else st.free_lat,
                    from_lon=None if st.at_hq else st.free_lon,
                    at_hq=st.at_hq,
                )
                if not leg["feasible"]:
                    continue
                st.commit(leg, workers=pax)
                if end_min >= 22 * 60:
                    st.did_10pm = True
                for stop in leg["stops"]:
                    site_label = next(j["site_label"] for j in cl["jobs"] if j["info"] is stop["site"])
                    assignment[site_label] = {"pickup": st.name}
                tag = "OT" if st.is_ot else "STAFF"
                names = ", ".join(j["site_label"] for j in cl["jobs"])
                notes.append(
                    f"[{fmt_time(end_min)} wave] [{tag}] {st.name} -> {names} "
                    f"({pax} pax) -- leave {fmt_time(leg['depart_hq'])}, "
                    f"back HQ {fmt_time(leg['hq_return'])}"
                    + (f", up to {leg['max_lateness']}min late on later stop" if leg["max_lateness"] > 0 else "")
                )
                placed = True
                break
        if not placed:
            if len(cl["jobs"]) > 1:
                notes.append(f"[i] Splitting {pax}-pax cluster ({fmt_time(end_min)})")
                for j in cl["jobs"]:
                    sub = {"jobs": [j], "workers": j["workers"]}
                    sub_placed = False
                    for st in candidates:
                        if st.cap < (j["workers"] or 0):
                            continue
                        leg = try_leg(st, sub)
                        if not leg["feasible"]:
                            continue
                        st.commit(leg, workers=j["workers"])
                        if end_min >= 22 * 60:
                            st.did_10pm = True
                        assignment[j["site_label"]] = {"pickup": st.name}
                        tag = "OT" if st.is_ot else "STAFF"
                        notes.append(
                            f"[{fmt_time(end_min)} wave] [{tag}] {st.name} -> {j['site_label']} "
                            f"({j['workers']} pax) -- leave {fmt_time(leg['depart_hq'])}, back HQ {fmt_time(leg['hq_return'])}"
                        )
                        sub_placed = True
                        break
                    if not sub_placed:
                        unplaced.append(j)
            else:
                unplaced.append(cl["jobs"][0])

    # Best-effort fallback: rather than leaving a job with literally no ride,
    # widen the lateness tolerance in steps and take whichever driver (OT
    # first) becomes feasible soonest. This only fires when every driver was
    # already committed elsewhere within the normal tolerance -- it is
    # flagged loudly in the notes so a manager can add capacity if this
    # keeps happening, rather than the job silently vanishing off the plan.
    for j in unplaced:
        sub = {"jobs": [j], "workers": j["workers"]}
        placed = False
        for tol in (PICKUP_LATE_TOLERANCE * 2, PICKUP_LATE_TOLERANCE * 3, PICKUP_LATE_TOLERANCE * 5):
            cands = sorted(ot_states, key=lambda s: s.balance_key()) + sorted(staff_states, key=lambda s: s.balance_key())
            for st in cands:
                if st.cap < (j["workers"] or 0):
                    continue
                leg = time_pickup_cluster(
                    sub, end_min, st.earliest_depart(), tolerance=tol,
                    from_lat=None if st.at_hq else st.free_lat,
                    from_lon=None if st.at_hq else st.free_lon,
                    at_hq=st.at_hq,
                )
                if not leg["feasible"]:
                    continue
                st.commit(leg, workers=j["workers"])
                if end_min >= 22 * 60:
                    st.did_10pm = True
                assignment[j["site_label"]] = {"pickup": st.name}
                tag = "OT" if st.is_ot else "STAFF"
                notes.append(
                    f"⚠️ [{fmt_time(end_min)} wave] [{tag}] {st.name} -> {j['site_label']} "
                    f"({j['workers']} pax) -- running {leg['max_lateness']}min late. Leave {fmt_time(leg['depart_hq'])}."
                )
                placed = True
                break
            if placed:
                break
        if not placed:
            notes.append(f"[!] NO DRIVER AT ALL for pickup {j['site_label']} ({j['workers']} pax, ends {fmt_time(end_min)})")

    return assignment


def assign_food_waves(dinner_jobs: List[dict], states: Dict[str, DriverState], notes: List[str]):
    """Food only for >=22:00 sites, delivered by 6:30pm target. We cluster ALL
    dinner sites together regardless of exact end-minute differences (food
    timing only cares about the 6:30 target, not the pickup end time)."""
    if not dinner_jobs:
        return {}

    def food_feasible(merged_jobs):
        trial = {"jobs": merged_jobs, "workers": sum(j["workers"] or 0 for j in merged_jobs)}
        return time_food_cluster(trial, EVENING_START)["feasible"]

    clusters = cluster_same_endtime(dinner_jobs, food_feasible)
    ot_states, staff_states = _ot_first_pool(list(states.values()))
    assignment: Dict[str, dict] = {}

    for cl in clusters:
        pax = cl["workers"]
        placed = False
        for st in sorted(ot_states, key=lambda s: s.balance_key()):
            if st.cap < pax:
                continue
            leg = time_food_cluster(cl, st.earliest_depart())
            if not leg["feasible"]:
                continue
            st.commit(leg)
            st.did_food = True
            for j in cl["jobs"]:
                assignment[j["site_label"]] = {"dinner": st.name}
            names = ", ".join(j["site_label"] for j in cl["jobs"])
            warn = "" if leg["on_target"] else " (past 6:30 target, still before 7:00 hard cutoff)"
            notes.append(
                f"[FOOD] {st.name} -> {names} ({pax} pax) -- leave HQ {fmt_time(leg['depart_hq'])}, "
                f"last delivery {fmt_time(leg['stops'][-1]['arrive'])}{warn}"
            )
            placed = True
            break
        if not placed:
            for j in cl["jobs"]:
                notes.append(f"[!] NO OT free for food at {j['site_label']} ({j['workers']} pax) -- check fleet size vs dinner-site count")
    return assignment


def assign_shifts(shifts: List[dict], states: Dict[str, DriverState], notes: List[str]):
    """Site-to-site transfers before 7pm.

    Prefer ONE free OT (no food) for ALL shifts when feasible — chain without
    HQ between stops (workers already dropped at destination school).
    Nearby schools → same ACJC drop = one driver, one continuous run.
    """
    if not shifts:
        return []
    ot_states, staff_states = _ot_first_pool(list(states.values()))
    free_ot = sorted([s for s in ot_states if not s.did_food], key=lambda s: s.balance_key())
    busy_ot = sorted([s for s in ot_states if s.did_food], key=lambda s: s.balance_key())

    result = []
    remaining = list(shifts)

    def chain_all(st, items):
        """Try continuous chain: after first drop, leave from destination to next from-site."""
        trials = []
        floor = st.earliest_depart()
        at_hq = st.at_hq
        flat, flon = st.free_lat, st.free_lon
        for s in items:
            leg = time_shift(s, floor, from_hq=at_hq, free_lat=flat, free_lon=flon)
            if not leg["feasible"]:
                return None
            trials.append(leg)
            # next leg starts from this destination (no HQ)
            floor = leg["arrive_to"] + STOP_DWELL_MIN
            at_hq = False
            ti = s["to_info"]
            flat, flon = ti.get("lat"), ti.get("lon")
        return trials

    # Order shifts for a tight chain: farthest from HQ first, then nearest to last drop
    def ordered_for_chain(items):
        if len(items) <= 1:
            return list(items)
        # start with farthest from HQ
        first = max(items, key=lambda s: travel_hq_to(s["from_info"]))
        left = [s for s in items if s is not first]
        ordered = [first]
        cur = first["to_info"]
        while left:
            nxt = min(left, key=lambda s: haversine_km(
                cur.get("lat"), cur.get("lon"),
                s["from_info"].get("lat"), s["from_info"].get("lon")
            ) or 99)
            ordered.append(nxt)
            left.remove(nxt)
            cur = nxt["to_info"]
        return ordered

    # Try put ALL shifts on one free OT (one continuous school run)
    for st in free_ot:
        trials = chain_all(st, ordered_for_chain(remaining))
        if trials:
            remaining_ordered = ordered_for_chain(remaining)
            for s, leg in zip(remaining_ordered, trials):
                st.commit(leg)
                result.append({"from": s["from"], "to": s["to"], "driver": st.name})
                notes.append(
                    f"[SHIFT] {s['from']} -> {s['to']} -> {st.name} "
                    f"(leave {fmt_time(leg['depart_hq'])}, drop {fmt_time(leg['arrive_to'])}, no HQ required)"
                )
            remaining = []
            break

    for s in remaining:
        placed = False
        for pool in (free_ot, busy_ot, staff_states):
            for st in sorted(pool, key=lambda x: x.balance_key()):
                leg = time_shift(
                    s, st.earliest_depart(),
                    from_hq=st.at_hq, free_lat=st.free_lat, free_lon=st.free_lon,
                )
                if not leg["feasible"]:
                    continue
                st.commit(leg)
                result.append({"from": s["from"], "to": s["to"], "driver": st.name})
                tag = "OT" if st.is_ot else "STAFF"
                notes.append(
                    f"[SHIFT] [{tag}] {s['from']} -> {s['to']} -> {st.name} "
                    f"(leave {fmt_time(leg['depart_hq'])}, drop {fmt_time(leg['arrive_to'])}, no HQ required)"
                )
                placed = True
                break
            if placed:
                break
        if not placed:
            notes.append(f"[!] NO DRIVER for shift {s['from']} -> {s['to']}")
    return result


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------

def build_schedule(jobs: List[dict], shifts: List[dict], fleet: List[dict]):
    """Returns (assignment, shift_assignment, notes, states) where:
      assignment[site_label] = {"dinner": name|None, "pickup": name|None}
      states[name] = DriverState with .engagements for the full timeline.
    """
    notes: List[str] = []
    states: Dict[str, DriverState] = {d["name"]: DriverState(d) for d in fleet}

    resolvable_jobs = [j for j in jobs if j["info"] and j["end_min"] is not None]
    unresolved = [j for j in jobs if not j["info"] or j["end_min"] is None]
    for j in unresolved:
        notes.append(f"[!] Skipped '{j['site_label']}' -- missing site coordinates or end time in the sheets.")

    assignment: Dict[str, dict] = {j["site_label"]: {"dinner": None, "pickup": None} for j in jobs}

    # 1) FOOD first (OT, no HQ return after — free at last site)
    dinner_jobs = [j for j in resolvable_jobs if j["is_dinner"]]
    food_result = assign_food_waves(dinner_jobs, states, notes)
    for label, a in food_result.items():
        assignment[label]["dinner"] = a["dinner"]

    # 2) SHIFTS — free OT preferred; no HQ return after drop at destination
    shift_assignment = assign_shifts(shifts, states, notes)

    # 3) Pickup waves: 7pm first, then 10pm (spread across OT), then 9pm.
    #    Why 10 before 9: a 9pm run returns ~9:45 and misses the 10pm leave window.
    #    OT who take 10pm skip 9pm; remaining OT take 9pm; staff fill gaps.
    waves = sorted({j["end_min"] for j in resolvable_jobs})
    early = [e for e in waves if e < 21 * 60]       # 7pm etc
    late_10 = [e for e in waves if e >= 22 * 60]     # 10pm
    mid_9 = [e for e in waves if 21 * 60 <= e < 22 * 60]  # 9pm
    for end_min in early + late_10 + mid_9:
        wave_jobs = [j for j in resolvable_jobs if j["end_min"] == end_min]
        is_10 = end_min >= 22 * 60
        pickup_result = assign_pickup_wave(
            wave_jobs, end_min, states, notes, prefer_spread_10pm=is_10
        )
        for label, a in pickup_result.items():
            assignment[label]["pickup"] = a["pickup"]

    ot_states = [s for s in states.values() if s.is_ot]
    ot_summary = ", ".join(f"{s.name}={s.jobs_count} jobs/{s.pax_count} pax" for s in ot_states)
    notes.append(f"OT balance: {ot_summary}")
    idle = [s.name for s in ot_states if s.jobs_count == 0]
    if idle:
        notes.append(f"[i] Idle OT tonight (no feasible slot found): {', '.join(idle)}")
    used_staff = [s.name for s in states.values() if not s.is_ot and s.jobs_count > 0]
    if used_staff:
        notes.append(f"[i] Staff used tonight (OT could not fully cover): {', '.join(used_staff)}")

    return assignment, shift_assignment, notes, states


def driver_timeline_rows(state: DriverState) -> List[Tuple[str, str]]:
    """Human-readable (Task, Timing) rows for one driver's whole night, in order,
    with HQ shown on every leg as required."""
    rows = []
    prev_return = None
    for leg in state.engagements:
        if prev_return is not None and leg.get("depart_hq") and leg["depart_hq"] > prev_return:
            rest = leg["depart_hq"] - prev_return
            if rest >= 5:
                rows.append(("Available / move", f"{fmt_time(prev_return)} -> {fmt_time(leg['depart_hq'])} ({rest} min)"))
        if leg["type"] == "food":
            names = ", ".join(s["site"]["label"] for s in leg["stops"])
            arrivals = ", ".join(f"{s['site']['label']} {fmt_time(s['arrive'])}" for s in leg["stops"])
            rows.append((f"Food run: {names}", f"Leave HQ {fmt_time(leg['depart_hq'])} -> {arrivals} (no HQ required after food)"))
        elif leg["type"] == "pickup":
            for s in leg["stops"]:
                late = f" (LATE {s['late_by']}min)" if s["late_by"] > 0 else " (on time)"
                rows.append((f"Pickup: {s['site']['label']} ({leg['workers']} pax total on lorry)",
                              f"Arrive {fmt_time(s['arrive'])} for {fmt_time(s['deadline'])}{late}"))
            rows.append(("-> HQ", f"Leave HQ {fmt_time(leg['depart_hq'])} ... back to HQ {fmt_time(leg['hq_return'])}"))
        elif leg["type"] == "shift":
            rows.append((f"Shift: {leg['from']} -> {leg['to']}",
                         f"Leave {fmt_time(leg['depart_hq'])} -> pickup {fmt_time(leg['arrive_from'])} -> drop {fmt_time(leg['arrive_to'])} (free at destination, no HQ required)"))
        if leg["type"] == "pickup":
            prev_return = leg.get("hq_return")
        elif leg["type"] == "food" and leg.get("stops"):
            prev_return = leg["stops"][-1]["arrive"] + STOP_DWELL_MIN
        elif leg["type"] == "shift":
            prev_return = leg.get("arrive_to")
        else:
            prev_return = leg.get("hq_return")
    return rows
