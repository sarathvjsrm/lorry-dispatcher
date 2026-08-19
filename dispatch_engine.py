"""
dispatch_engine.py — Anderco evening lorry dispatch (deterministic, wave-based).

============================================================================
HOW THIS THINKS (read this before touching the constants below)
============================================================================
Every night's jobs are grouped into "waves" by shift-end time (e.g. 7:00 PM,
9:00 PM, 10:00 PM). Within a wave, jobs that are geographically close become
ONE cluster and ride ONE lorry (location-first).

  1. PICKUPS ARE JUST-IN-TIME. A driver departs for a pickup at the LATEST
     moment that still lands them at the site ~2 min after the shift ends.
     We never send a driver out early to sit and wait at a site.
  2. HQ ONLY APPEARS WHERE WORKERS ARE ACTUALLY DROPPED OFF. A pickup always
     ends with an explicit return to HQ (that's the point of a pickup). Food
     and shift legs do NOT force a detour through HQ afterward -- the
     driver's next task departs straight from wherever they last dropped
     off, whether that's a food site, a shift's "to" site, or HQ itself.
  3. THE LAST WAVE OF THE NIGHT (typically the 22:00 dinner pickup) IS THE
     OT's ANCHOR JOB. It's what makes the evening worth the OT rate, so it
     is OT-only and deliberately SPREAD ACROSS EVERY OT DRIVER rather than
     consolidated onto the fewest lorries. It's reserved for each OT right
     after food/shifts are locked in (see reserve_final_wave /
     finalize_final_wave) -- reserved, not yet timed -- so a middle-wave job
     can still use an OT's idle gap afterward without silently costing them
     that reservation.
  4. STAFF ARE ONE TRIP AND DONE. They're not OT, so they never chain across
     multiple waves and never touch the final wave -- one pickup (possibly
     multi-stop if clustered), then they're finished for the night.
  5. NO MANUFACTURED REST WINDOWS. OT move to their next task the moment
     they're physically able; they eat/breathe during whatever natural gap
     the just-in-time timing leaves, not on a schedule this engine invents.

Everything else (food only for >=22:00, capacity, OT balancing) is built on
top of that timing skeleton.

============================================================================
DAILY UPDATE SURFACE (the only two sheets you touch nightly)
============================================================================
  - Fleet_Drivers: who is on duty tonight. Every name on this sheet = an OT
    driver. Remove a name (e.g. someone on leave) and they vanish everywhere,
    immediately (no code change, no stale caching once you hit "Refresh data").
  - Daily_Ops: tonight's sites / end times / worker counts, and any
    site-to-site shift transfers.

Everything below this line is the "one-time brain" -- business logic that
should NOT need nightly edits. If a rule needs to change, change a constant
in the CONFIG block, not the algorithm.
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
PICKUP_LATE_TOLERANCE = 25  # 2nd stop in same-wave cluster (Tuas/west hops ~15 min)            # a 2nd/3rd stop in a cluster may run up to this late
STOP_DWELL_MIN = 2                    # minutes spent boarding workers at each stop

# NOTE: deliberately no "minimum rest" constant. OT move straight to their
# next task the moment they're free -- they eat/breathe during whatever
# natural gap the just-in-time timing leaves, not on a schedule we invent.

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
    """Site-to-site hop (no recorded data source -- haversine only), used both
    for short in-cluster hops AND longer cross-region jumps now that a driver
    can move directly from a food/shift drop-off straight into their next
    task without detouring via HQ. A single flat "+10 base, full traffic
    buffer" formula (correct for pulling a lorry out of HQ onto the highway)
    made a 1km hop between neighbouring sites look like 25+ minutes, so short
    hops get a lighter local-roads estimate; longer hops fall back to the
    same highway-style formula used for HQ legs."""
    d = haversine_km(a.get("lat"), a.get("lon"), b.get("lat"), b.get("lon"))
    if d is None:
        return 25
    if d <= 12:
        local_buffer = max(3, int(round(EVENING_BUFFER_MIN * 0.3)))
        return int(round(d * 3.0)) + 3 + local_buffer
    t = travel_km_min(d)
    return t if t is not None else 30


def travel_from(loc: Optional[dict], site: dict) -> int:
    """Travel time from a driver's current location to `site`. `loc=None`
    means the driver is at HQ (the only place a night can start); otherwise
    `loc` is the site-info dict of wherever they last dropped off (food) or
    handed over (shift) -- no forced HQ detour in between."""
    if loc is None:
        return travel_hq_to(site)
    return travel_between(loc, site)


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
                # Prefer close pairs (save fuel): refuse wide clusters
                infos = [j["info"] for j in merged_jobs if j.get("info")]
                diam = 0.0
                for a in range(len(infos)):
                    for b in range(a + 1, len(infos)):
                        d = haversine_km(infos[a].get("lat"), infos[a].get("lon"),
                                         infos[b].get("lat"), infos[b].get("lon"))
                        if d is not None and d > diam:
                            diam = d
                if diam > 8.0:  # tight zone: Tuas together, Jurong together — not ACJC+Jurong SS
                    continue
                # merge score = closest link (not HQ route cost) so nearby same-time stick
                link = 999.0
                for ja in clusters[i]["jobs"]:
                    for jb in clusters[k]["jobs"]:
                        ia, ib = ja.get("info"), jb.get("info")
                        if not ia or not ib:
                            continue
                        d = haversine_km(ia.get("lat"), ia.get("lon"), ib.get("lat"), ib.get("lon"))
                        if d is not None and d < link:
                            link = d
                if best is None or link < best[0]:
                    best = (link, i, k)
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
# Route timing -- just-in-time departure, HQ only appears when workers are
# actually dropped there (i.e. at the end of a pickup). Food and shifts end
# wherever the last stop is; the driver's NEXT task departs from there.
# ---------------------------------------------------------------------------

def _order_nearest_first(stops: List[dict], start_loc: Optional[dict]) -> List[dict]:
    return sorted(stops, key=lambda s: travel_from(start_loc, s))


def time_pickup_cluster(
    cluster: dict, end_min: int, earliest_depart: int,
    start_loc: Optional[dict] = None, tolerance: int = PICKUP_LATE_TOLERANCE,
) -> dict:
    """Just-in-time multi-stop pickup route, starting from wherever the driver
    currently is (HQ, or the tail of their last food/shift task). First
    (nearest-to-start) stop arrives right at end_min+board; later stops may
    run a little late (tolerance), never early-wait. A pickup ALWAYS ends
    with an explicit return to HQ -- that's the one place a detour is
    mandatory, because that's where the workers actually get dropped off."""
    infos = [j["info"] for j in cluster["jobs"]]
    ordered = _order_nearest_first(infos, start_loc)
    deadline0 = end_min + PICKUP_BOARD_MIN
    depart = max(earliest_depart, deadline0 - travel_from(start_loc, ordered[0]))

    stops_out = []
    t = depart
    prev = None
    max_lateness = 0
    for s in ordered:
        leg = travel_from(start_loc, s) if prev is None else travel_between(prev, s)
        arrive = t + leg
        lateness = max(0, arrive - deadline0)
        max_lateness = max(max_lateness, lateness)
        stops_out.append({"site": s, "arrive": arrive, "deadline": deadline0, "late_by": lateness})
        t = arrive + STOP_DWELL_MIN
        prev = s
    hq_return = t + travel_hq_to(prev)

    return {
        "type": "pickup",
        "depart_time": depart,
        "depart_from": start_loc,
        "stops": stops_out,
        "hq_return": hq_return,
        "finish_time": hq_return,
        "finish_location": None,   # workers dropped at HQ -> driver is at HQ
        "workers": cluster["workers"],
        "max_lateness": max_lateness,
        "feasible": max_lateness <= tolerance and depart >= earliest_depart,
    }


def time_food_cluster(cluster: dict, earliest_depart: int) -> dict:
    """Food is always the first task of the night (start_loc is always HQ) and
    is not just-in-time (early delivery is fine) -- depart as soon as the
    driver is free, deliver nearest-first, must clear the LAST stop by
    FOOD_HARD_MIN. No forced HQ return afterward: food isn't dropping anyone
    at HQ, so the driver's next task departs straight from the last site."""
    infos = [j["info"] for j in cluster["jobs"]]
    ordered = _order_nearest_first(infos, None)
    depart = max(earliest_depart, EVENING_START)

    stops_out = []
    t = depart
    prev = None
    for s in ordered:
        leg = travel_hq_to(s) if prev is None else travel_between(prev, s)
        arrive = t + leg
        stops_out.append({"site": s, "arrive": arrive})
        t = arrive + STOP_DWELL_MIN
        prev = s
    last_arrival = stops_out[-1]["arrive"]

    return {
        "type": "food",
        "depart_time": depart,
        "stops": stops_out,
        "finish_time": t,
        "finish_location": prev,   # driver is at the last delivery site, not HQ
        "workers": cluster["workers"],
        "last_arrival": last_arrival,
        "feasible": last_arrival <= FOOD_HARD_MIN,
        "on_target": last_arrival <= FOOD_TARGET_MIN,
    }


def time_shift(shift: dict, earliest_depart: int, start_loc: Optional[dict] = None) -> dict:
    """Site-to-site transfer, must land before SHIFT_HARD_CUTOFF. Workers are
    dropped at the TO site, not HQ, so no forced HQ leg -- the driver's next
    task departs straight from the TO site."""
    fi, ti = shift["from_info"], shift["to_info"]
    depart = max(earliest_depart, EVENING_START)
    arrive_from = depart + travel_from(start_loc, fi)
    depart_from = arrive_from + STOP_DWELL_MIN
    arrive_to = depart_from + travel_between(fi, ti)
    finish_time = arrive_to + STOP_DWELL_MIN
    return {
        "type": "shift",
        "from": shift["from"], "to": shift["to"],
        "depart_time": depart,
        "arrive_from": arrive_from,
        "arrive_to": arrive_to,
        "finish_time": finish_time,
        "finish_location": ti,   # driver is at the TO site, not HQ
        "feasible": arrive_to <= SHIFT_HARD_CUTOFF,
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
        self.free_at = EVENING_START     # when this driver is next available
        self.location: Optional[dict] = None  # None = at HQ
        self.engagements: List[dict] = []  # chronological legs
        self.jobs_count = 0
        self.pax_count = 0
        self.did_food = False
        self.food_sites = set()
        self.got_final_wave = False
        self.final_wave_jobs: List[dict] = []   # reserved (not yet timed) final-wave stops
        self.final_wave_end_min: Optional[int] = None
        self.used_tonight = False        # staff: True after their one trip

    def earliest_depart(self) -> int:
        # No manufactured rest window: OT and staff both move on to their next
        # task the moment they're physically free. They eat/breathe during
        # whatever natural gap the just-in-time timing leaves -- we don't
        # schedule it.
        return self.free_at

    def commit(self, leg: dict, workers: int = 0):
        self.engagements.append(leg)
        self.free_at = leg["finish_time"]
        self.location = leg["finish_location"]
        self.jobs_count += 1
        self.pax_count += workers
        if not self.is_ot:
            self.used_tonight = True

    def balance_key(self):
        return (self.jobs_count, self.pax_count)



def time_multi_shift(
    from_shifts: list,
    earliest_depart: int,
    start_loc=None,
) -> dict:
    """ONE run: pick several FROM schools, then ONE drop at shared TO.
    Example: BBSS + Boon Lay Garden → ACJC before 7pm.
    Driver free at TO (no HQ)."""
    if not from_shifts:
        return {"feasible": False}
    ti = from_shifts[0]["to_info"]
    to_label = from_shifts[0]["to"]
    # farthest from TO first, closest last
    ordered = sorted(
        from_shifts,
        key=lambda s: -(haversine_km(
            s["from_info"].get("lat"), s["from_info"].get("lon"),
            ti.get("lat"), ti.get("lon")) or 0),
    )
    depart = max(earliest_depart, EVENING_START)
    t = depart
    prev = None
    pick_stops = []
    start = start_loc
    for s in ordered:
        fi = s["from_info"]
        leg = travel_from(start if prev is None else None, fi) if prev is None else travel_between(prev, fi)
        if prev is None:
            leg = travel_from(start_loc, fi)
        arrive = t + leg
        pick_stops.append({"site": fi, "label": s["from"], "arrive": arrive})
        t = arrive + STOP_DWELL_MIN
        prev = fi
    arrive_to = t + travel_between(prev, ti)
    finish = arrive_to + STOP_DWELL_MIN
    # multi-school transfer: allow until 7:30 if needed (must prefer finish before 7)
    soft = SHIFT_HARD_CUTOFF + 60  # one lorry for multi-school shift must succeed
    return {
        "type": "shift_multi",
        "from_list": [s["from"] for s in ordered],
        "to": to_label,
        "depart_time": depart,
        "pick_stops": pick_stops,
        "arrive_to": arrive_to,
        "finish_time": finish,
        "finish_location": ti,
        "feasible": arrive_to <= soft,
        "workers": 0,
    }



def _ot_first_pool(states: List[DriverState]):
    return [s for s in states if s.is_ot], [s for s in states if not s.is_ot and not s.used_tonight]


def _try_commit_protecting_reservation(st: DriverState, leg: dict, workers: int = 0) -> bool:
    """Commit `leg` to this driver UNLESS doing so would blow the driver's
    already-reserved final-wave slot (see reserve_final_wave). If the
    driver has no reservation, this is just a normal commit -- used so
    middle-wave assignment can freely use an OT's idle gap without
    silently costing them their locked-in 10pm site."""
    if st.final_wave_jobs:
        trial = {"jobs": st.final_wave_jobs, "workers": sum(x["workers"] or 0 for x in st.final_wave_jobs)}
        check = time_pickup_cluster(trial, st.final_wave_end_min, leg["finish_time"], start_loc=leg["finish_location"])
        if not check["feasible"]:
            return False
    st.commit(leg, workers=workers)
    return True


def assign_pickup_wave(
    jobs_this_wave: List[dict], end_min: int, states: Dict[str, DriverState], notes: List[str]
):
    """Middle waves (everything except the final/latest one). OT FIRST (maximise OT pay). Staff only if no OT can cover without
    breaking reserved 10pm. Staff one-trip only (see _try_commit_protecting_reservation)."""
    def pickup_feasible(merged_jobs):
        trial = {"jobs": merged_jobs, "workers": sum(j["workers"] or 0 for j in merged_jobs)}
        return time_pickup_cluster(trial, end_min, EVENING_START)["feasible"]

    clusters = cluster_same_endtime(jobs_this_wave, pickup_feasible)
    ot_states, staff_states = _ot_first_pool(list(states.values()))

    assignment: Dict[str, dict] = {}  # site_label -> {"pickup": name}
    unplaced: List[dict] = []

    def candidate_pool(cl):
        # OT first. Among OT: nearest to cluster (post-shift at ACJC → nearby MOE first)
        # so we don't pay OT for empty time while staff take local 7pm jobs.
        infos = [j["info"] for j in cl["jobs"] if j.get("info")]
        def near(st):
            if not st.is_ot:
                return 999
            if st.location is None:  # at HQ
                if not infos:
                    return 50
                return min(travel_hq_to(i) for i in infos)
            return min(
                (haversine_km(st.location.get("lat"), st.location.get("lon"),
                              i.get("lat"), i.get("lon")) or 99)
                for i in infos
            ) if infos else 99
        ot_sorted = sorted(ot_states, key=lambda s: (near(s), s.balance_key()))
        staff_sorted = sorted(staff_states, key=lambda s: s.balance_key())
        return ot_sorted + staff_sorted

    for cl in clusters:
        pax = cl["workers"]
        placed = False
        for st in candidate_pool(cl):
            if st.cap < pax:
                continue
            leg = time_pickup_cluster(cl, end_min, st.earliest_depart(), start_loc=st.location)
            if not leg["feasible"]:
                continue
            if not _try_commit_protecting_reservation(st, leg, workers=pax):
                continue
            for stop in leg["stops"]:
                site_label = next(j["site_label"] for j in cl["jobs"] if j["info"] is stop["site"])
                assignment[site_label] = {"pickup": st.name}
            tag = "OT" if st.is_ot else "STAFF"
            names = ", ".join(j["site_label"] for j in cl["jobs"])
            notes.append(
                f"[{fmt_time(end_min)} wave] [{tag}] {st.name} -> {names} "
                f"({pax} pax) -- leave {fmt_time(leg['depart_time'])}, "
                f"back to HQ {fmt_time(leg['hq_return'])}"
                + (f", up to {leg['max_lateness']}min late on later stop" if leg["max_lateness"] > 0 else "")
            )
            placed = True
            break
        if not placed:
            if len(cl["jobs"]) > 1:
                notes.append(f"[i] Splitting {pax}-pax cluster ({fmt_time(end_min)}) -- no single lorry could take it as one trip.")
                for j in cl["jobs"]:
                    sub = {"jobs": [j], "workers": j["workers"]}
                    sub_placed = False
                    for st in candidate_pool(cl):
                        if st.cap < j["workers"]:
                            continue
                        leg = time_pickup_cluster(sub, end_min, st.earliest_depart(), start_loc=st.location)
                        if not leg["feasible"]:
                            continue
                        if not _try_commit_protecting_reservation(st, leg, workers=j["workers"]):
                            continue
                        assignment[j["site_label"]] = {"pickup": st.name}
                        tag = "OT" if st.is_ot else "STAFF"
                        notes.append(
                            f"[{fmt_time(end_min)} wave] [{tag}] {st.name} -> {j['site_label']} "
                            f"({j['workers']} pax) -- leave {fmt_time(leg['depart_time'])}, back to HQ {fmt_time(leg['hq_return'])}"
                        )
                        sub_placed = True
                        break
                    if not sub_placed:
                        unplaced.append(j)
            else:
                unplaced.append(cl["jobs"][0])

    # Best-effort fallback: rather than leaving a job with literally no ride,
    # widen the lateness tolerance in steps and take whichever driver becomes
    # feasible soonest -- still respecting any final-wave reservation. This
    # only fires when every driver was already committed elsewhere within
    # the normal tolerance -- it is flagged loudly in the notes so a manager
    # can add capacity if this keeps happening, rather than the job silently
    # vanishing off the plan.
    for j in unplaced:
        sub = {"jobs": [j], "workers": j["workers"]}
        placed = False
        for tol in (PICKUP_LATE_TOLERANCE * 2, PICKUP_LATE_TOLERANCE * 3, PICKUP_LATE_TOLERANCE * 5):
            for st in candidate_pool(cl):
                if st.cap < j["workers"]:
                    continue
                leg = time_pickup_cluster(sub, end_min, st.earliest_depart(), start_loc=st.location, tolerance=tol)
                if not leg["feasible"]:
                    continue
                if not _try_commit_protecting_reservation(st, leg, workers=j["workers"]):
                    continue
                assignment[j["site_label"]] = {"pickup": st.name}
                tag = "OT" if st.is_ot else "STAFF"
                notes.append(
                    f"⚠️ [{fmt_time(end_min)} wave] [{tag}] {st.name} -> {j['site_label']} "
                    f"({j['workers']} pax) -- every driver was already committed; running "
                    f"{leg['max_lateness']}min late, no alternative tonight. Leave {fmt_time(leg['depart_time'])}."
                )
                placed = True
                break
            if placed:
                break
        if not placed:
            notes.append(f"[!] NO DRIVER AT ALL for pickup {j['site_label']} ({j['workers']} pax, ends {fmt_time(end_min)}) -- fleet is short a lorry tonight.")

    return assignment


def reserve_final_wave(
    final_jobs: List[dict], end_min: int, states: Dict[str, DriverState], notes: List[str]
) -> List[dict]:
    """The LAST wave of the night (typically the 22:00 dinner pickup) is the
    OT drivers' anchor job -- it is what makes their evening worth the OT
    rate, so it is OT-only and deliberately spread across every OT driver
    instead of being consolidated onto the fewest possible lorries. If there
    are at least as many sites as OT, every OT gets one.

    This only RESERVES the mapping (site -> OT) on each DriverState -- it does
    not commit a timed leg yet. That happens in finalize_final_wave(), after
    the middle waves have had a chance to use any OT idle time without
    breaking this reservation. Returns any jobs that couldn't be reserved to
    any OT at all (handled by an emergency fallback afterward)."""
    ot_states = [s for s in states.values() if s.is_ot]
    remaining = [j for j in final_jobs if j["info"]]
    remaining.sort(key=lambda j: -(j["workers"] or 0))
    driver_jobs: Dict[str, List[dict]] = {ot.name: [] for ot in ot_states}
    unplaced: List[dict] = []

    # Prefer: empty 10pm slot first, then food continuity for this site, then light load
    for j in remaining:
        placed = False
        def rank(o):
            n = len(driver_jobs[o.name])
            food_hit = 1 if j["site_label"] in o.food_sites else 0
            return (n, -food_hit, sum(x["workers"] or 0 for x in driver_jobs[o.name]))
        for ot in sorted(ot_states, key=rank):
            # Spread: if every OT can have one site, do not stack on OT who already has one
            if driver_jobs[ot.name] and len(remaining) <= len(ot_states):
                if any(len(driver_jobs[o.name]) == 0 for o in ot_states):
                    continue
            trial_jobs = driver_jobs[ot.name] + [j]
            trial = {"jobs": trial_jobs, "workers": sum(x["workers"] or 0 for x in trial_jobs)}
            if trial["workers"] > ot.cap:
                continue
            leg = time_pickup_cluster(trial, end_min, ot.earliest_depart(), start_loc=ot.location)
            if not leg["feasible"]:
                continue
            driver_jobs[ot.name] = trial_jobs
            placed = True
            break
        if not placed:
            # second pass: allow stack if needed
            for ot in sorted(ot_states, key=rank):
                trial_jobs = driver_jobs[ot.name] + [j]
                trial = {"jobs": trial_jobs, "workers": sum(x["workers"] or 0 for x in trial_jobs)}
                if trial["workers"] > ot.cap:
                    continue
                leg = time_pickup_cluster(trial, end_min, ot.earliest_depart(), start_loc=ot.location)
                if not leg["feasible"]:
                    continue
                driver_jobs[ot.name] = trial_jobs
                placed = True
                break
        if not placed:
            unplaced.append(j)

    for ot in ot_states:
        if driver_jobs.get(ot.name):
            ot.final_wave_jobs = driver_jobs[ot.name]
            ot.final_wave_end_min = end_min

    idle_ot = [ot.name for ot in ot_states if not ot.final_wave_jobs]
    if idle_ot and remaining:
        notes.append(f"[i] These OT won't get a {fmt_time(end_min)} (final wave) site tonight -- not enough distinct sites to go around: {', '.join(idle_ot)}")

    return unplaced


def finalize_final_wave(end_min: int, states: Dict[str, DriverState], notes: List[str]) -> Dict[str, dict]:
    """Commit the actual timed leg for every OT holding a final-wave
    reservation, using their free_at/location AS OF NOW (i.e. after food,
    shifts, and any middle-wave jobs that were confirmed compatible)."""
    assignment: Dict[str, dict] = {}
    for st in states.values():
        if not st.final_wave_jobs:
            continue
        jobs_list = st.final_wave_jobs
        trial = {"jobs": jobs_list, "workers": sum(x["workers"] or 0 for x in jobs_list)}
        leg = time_pickup_cluster(trial, st.final_wave_end_min, st.earliest_depart(), start_loc=st.location)
        st.commit(leg, workers=trial["workers"])
        st.got_final_wave = True
        for stop in leg["stops"]:
            site_label = next(x["site_label"] for x in jobs_list if x["info"] is stop["site"])
            assignment[site_label] = {"pickup": st.name}
        names = ", ".join(x["site_label"] for x in jobs_list)
        notes.append(
            f"[{fmt_time(end_min)} FINAL WAVE] [OT] {st.name} -> {names} "
            f"({trial['workers']} pax) -- leave {fmt_time(leg['depart_time'])}, back to HQ {fmt_time(leg['hq_return'])}"
            + (f", up to {leg['max_lateness']}min late on later stop" if leg["max_lateness"] > 0 else "")
        )
    return assignment


def emergency_fallback_final(
    unplaced_jobs: List[dict], end_min: int, states: Dict[str, DriverState], notes: List[str]
) -> Dict[str, dict]:
    """A final-wave site that couldn't be reserved to any OT (more dinner
    sites than OT drivers, or a capacity mismatch). Since this is the LAST
    wave of the night there's nothing downstream to protect, so we just
    widen tolerance and take whoever's available -- OT or staff."""
    assignment: Dict[str, dict] = {}
    for j in unplaced_jobs:
        sub = {"jobs": [j], "workers": j["workers"]}
        placed = False
        all_states = sorted(states.values(), key=lambda s: s.balance_key())
        for tol in (PICKUP_LATE_TOLERANCE * 2, PICKUP_LATE_TOLERANCE * 4):
            for st in all_states:
                if st.cap < j["workers"] or (not st.is_ot and st.used_tonight):
                    continue
                leg = time_pickup_cluster(sub, end_min, st.earliest_depart(), start_loc=st.location, tolerance=tol)
                if not leg["feasible"]:
                    continue
                st.commit(leg, workers=j["workers"])
                assignment[j["site_label"]] = {"pickup": st.name}
                tag = "OT" if st.is_ot else "STAFF"
                notes.append(
                    f"⚠️ [{fmt_time(end_min)} FINAL WAVE] [{tag}] {st.name} -> {j['site_label']} "
                    f"({j['workers']} pax) -- no OT had room; running {leg['max_lateness']}min late."
                )
                placed = True
                break
            if placed:
                break
        if not placed:
            notes.append(f"[!] NO DRIVER AT ALL for {j['site_label']} ({j['workers']} pax, final wave) -- fleet is short a lorry tonight.")
    return assignment


def assign_food_waves(dinner_jobs: List[dict], states: Dict[str, DriverState], notes: List[str]):
    """Food only for >=22:00 sites, delivered by 6:30pm target. We cluster ALL
    dinner sites together regardless of exact end-minute differences (food
    timing only cares about the 6:30 target, not the pickup end time). Food
    is always the night's first task, so start_loc is always HQ here."""
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
                st.food_sites.add(j["site_label"])
            names = ", ".join(j["site_label"] for j in cl["jobs"])
            warn = "" if leg["on_target"] else " (past 6:30 target, still before 7:00 hard cutoff)"
            notes.append(
                f"[FOOD] {st.name} -> {names} ({pax} pax) -- leave HQ {fmt_time(leg['depart_time'])}, "
                f"last delivery {fmt_time(leg['stops'][-1]['arrive'])}{warn}"
            )
            placed = True
            break
        if not placed:
            for j in cl["jobs"]:
                notes.append(f"[!] NO OT free for food at {j['site_label']} ({j['workers']} pax) -- check fleet size vs dinner-site count")
    return assignment


def assign_shifts(shifts: List[dict], states: Dict[str, DriverState], notes: List[str]):
    """Site-to-site transfers before 7pm. Prefer ONE free OT (no food run) for
    ALL of them if that OT can feasibly chain them; never use staff while a
    free OT can do it. Runs before the final wave, so committing an OT here
    still leaves plenty of runway for their 10pm slot later."""
    if not shifts:
        return []
    ot_states, staff_states = _ot_first_pool(list(states.values()))
    free_ot = sorted([s for s in ot_states if not s.did_food], key=lambda s: s.balance_key())
    busy_ot = sorted([s for s in ot_states if s.did_food], key=lambda s: s.balance_key())

    result = []
    remaining = list(shifts)

    # Same destination (by coords/code, not display text) → ONE multi-pickup → one drop
    def to_key(s):
        ti = s.get("to_info") or {}
        code = ti.get("code") or ""
        if code:
            return code
        lat, lon = ti.get("lat"), ti.get("lon")
        if lat is not None and lon is not None:
            return f"{round(float(lat),5)},{round(float(lon),5)}"
        return (s.get("to") or "").strip().lower()

    by_to = {}
    for s in remaining:
        by_to.setdefault(to_key(s), []).append(s)

    still = []
    for _key, group in sorted(by_to.items(), key=lambda kv: -len(kv[1])):
        to_label = group[0]["to"]
        placed = False
        # Prefer ONE free OT for the whole group — never split across two drivers
        for pool in (free_ot, busy_ot):
            for st in pool:
                leg = time_multi_shift(group, st.earliest_depart(), start_loc=st.location)
                if not leg["feasible"]:
                    continue
                st.commit(leg)
                for s in group:
                    result.append({"from": s["from"], "to": s["to"], "driver": st.name})
                notes.append(
                    f"[SHIFT] {st.name}: pick {' + '.join(leg['from_list'])} → drop {to_label} "
                    f"(leave {fmt_time(leg['depart_time'])}, drop {fmt_time(leg['arrive_to'])}, "
                    f"ONE lorry only)"
                )
                placed = True
                break
            if placed:
                break
        if not placed:
            # last resort: still try ONE driver with soft single-leg chain, not two drivers
            for st in free_ot + busy_ot:
                loc = st.location
                floor = st.earliest_depart()
                trials = []
                ok = True
                for s in group:
                    leg = time_shift(s, floor, start_loc=loc)
                    if not leg["feasible"]:
                        ok = False
                        break
                    trials.append((s, leg))
                    floor = leg["finish_time"]
                    loc = leg["finish_location"]
                if ok and trials:
                    for s, leg in trials:
                        st.commit(leg)
                        result.append({"from": s["from"], "to": s["to"], "driver": st.name})
                    notes.append(
                        f"[SHIFT] {st.name}: chained {len(trials)} → {to_label} (ONE driver)"
                    )
                    placed = True
                    break
        if not placed:
            still.extend(group)
    remaining = still

    for s in remaining:
        placed = False
        for pool in (free_ot, busy_ot, staff_states):
            for st in sorted(pool, key=lambda s: s.balance_key()):
                leg = time_shift(s, st.earliest_depart(), start_loc=st.location)
                if not leg["feasible"]:
                    continue
                st.commit(leg)
                result.append({"from": s["from"], "to": s["to"], "driver": st.name})
                tag = "OT" if st.is_ot else "STAFF"
                notes.append(
                    f"[SHIFT] [{tag}] {s['from']} -> {s['to']} -> {st.name} "
                    f"(leave {fmt_time(leg['depart_time'])}, drop {fmt_time(leg['arrive_to'])})"
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

    Order matters: food -> shifts -> the FINAL (latest end-time) wave, all
    locked in for OT first, so every OT's anchor jobs for the night are
    guaranteed before the busier middle waves (7pm/9pm) get filled in --
    primarily by staff, one trip each -- around them.
    """
    notes: List[str] = []
    states: Dict[str, DriverState] = {d["name"]: DriverState(d) for d in fleet}

    resolvable_jobs = [j for j in jobs if j["info"] and j["end_min"] is not None]
    unresolved = [j for j in jobs if not j["info"] or j["end_min"] is None]
    for j in unresolved:
        notes.append(f"[!] Skipped '{j['site_label']}' -- missing site coordinates or end time in the sheets.")

    assignment: Dict[str, dict] = {j["site_label"]: {"dinner": None, "pickup": None} for j in jobs}

    # Phase 1 -- food (OT only, earliest task of the night).
    dinner_jobs = [j for j in resolvable_jobs if j["is_dinner"]]
    food_result = assign_food_waves(dinner_jobs, states, notes)
    for label, a in food_result.items():
        assignment[label]["dinner"] = a["dinner"]

    # Phase 2 -- shifts (site-to-site, before 7pm; OT preferred).
    shift_assignment = assign_shifts(shifts, states, notes)

    # Phase 3 -- reserve (not yet time) the LAST wave of the night, the OT's
    # anchor job: OT-only, spread across every OT driver rather than
    # consolidated. Reserving now (instead of timing it immediately) lets
    # Phase 4 use any OT idle time on a middle wave without silently
    # costing that OT their 10pm slot.
    waves = sorted({j["end_min"] for j in resolvable_jobs})
    final_unplaced: List[dict] = []
    final_end_min = None
    if waves:
        final_end_min = waves[-1]
        final_jobs = [j for j in resolvable_jobs if j["end_min"] == final_end_min]
        final_unplaced = reserve_final_wave(final_jobs, final_end_min, states, notes)
        middle_waves = waves[:-1]
    else:
        middle_waves = []

    # Phase 4 -- every earlier wave (7pm, 9pm, ...): staff-first, one trip
    # each. OT can help fill a gap here too, but only in ways that don't
    # jeopardize the final-wave reservation just made above.
    for end_min in middle_waves:
        wave_jobs = [j for j in resolvable_jobs if j["end_min"] == end_min]
        pickup_result = assign_pickup_wave(wave_jobs, end_min, states, notes)
        for label, a in pickup_result.items():
            assignment[label]["pickup"] = a["pickup"]

    # Phase 5 -- now that every OT's day-up-to-that-point is locked in, time
    # and commit their actual final-wave leg, then mop up anything that
    # couldn't be reserved to any OT at all.
    if final_end_min is not None:
        final_result = finalize_final_wave(final_end_min, states, notes)
        for label, a in final_result.items():
            assignment[label]["pickup"] = a["pickup"]
        if final_unplaced:
            fallback_result = emergency_fallback_final(final_unplaced, final_end_min, states, notes)
            for label, a in fallback_result.items():
                assignment[label]["pickup"] = a["pickup"]

    ot_states = [s for s in states.values() if s.is_ot]
    ot_summary = ", ".join(f"{s.name}={s.jobs_count} jobs/{s.pax_count} pax" for s in ot_states)
    notes.append(f"OT balance: {ot_summary}")
    idle = [s.name for s in ot_states if s.jobs_count == 0]
    if idle:
        notes.append(f"[i] Idle OT tonight (no feasible slot found): {', '.join(idle)}")
    used_staff = [s.name for s in states.values() if not s.is_ot and s.jobs_count > 0]
    if used_staff:
        notes.append(f"[i] Staff used tonight (one trip each): {', '.join(used_staff)}")

    return assignment, shift_assignment, notes, states


def driver_timeline_rows(state: DriverState) -> List[Tuple[str, str]]:
    """Human-readable (Task, Timing) rows for one driver's whole night, in
    order. No manufactured 'rest' rows: OT and staff move to their next task
    as soon as they're physically able, and eat/breathe during whatever gap
    that naturally leaves. HQ only appears where workers are actually
    dropped there -- i.e. at the end of a pickup."""
    rows = []
    for leg in state.engagements:
        if leg["type"] == "food":
            names = ", ".join(s["site"]["label"] for s in leg["stops"])
            arrivals = ", ".join(f"{s['site']['label']} {fmt_time(s['arrive'])}" for s in leg["stops"])
            rows.append((f"Food run: {names}", f"Leave HQ {fmt_time(leg['depart_time'])} -> {arrivals}"))
        elif leg["type"] == "pickup":
            for s in leg["stops"]:
                late = f" (LATE {s['late_by']}min)" if s["late_by"] > 0 else " (on time)"
                rows.append((f"Pickup: {s['site']['label']} ({leg['workers']} pax total on lorry)",
                              f"Arrive {fmt_time(s['arrive'])} for {fmt_time(s['deadline'])}{late}"))
            rows.append(("-> HQ (drop workers)", f"Leave {fmt_time(leg['depart_time'])} ... back to HQ {fmt_time(leg['hq_return'])}"))
        elif leg["type"] == "shift":
            rows.append((f"Shift: {leg['from']} -> {leg['to']}",
                         f"Leave {fmt_time(leg['depart_time'])} -> pickup {fmt_time(leg['arrive_from'])} -> drop {fmt_time(leg['arrive_to'])}"))
        elif leg["type"] == "shift_multi":
            picks = " → ".join(f"{p['label']} {fmt_time(p['arrive'])}" for p in leg.get("pick_stops", []))
            rows.append((
                f"Shift: {' + '.join(leg.get('from_list', []))} → {leg['to']}",
                f"Leave {fmt_time(leg['depart_time'])} → {picks} → drop {fmt_time(leg['arrive_to'])} (one lorry)",
            ))
    return rows
