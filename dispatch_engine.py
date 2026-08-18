"""
dispatch_engine.py — Anderco evening lorry dispatch.

ONE BRAIN. Any night. Only Daily_Ops + Fleet_Drivers change nightly.

RULES
-----
1. Same shift-end time = one WAVE. Cluster nearby sites in that wave onto
   one lorry when capacity and travel still hit the deadline.
2. Different end times never share a trip. HQ between waves (workers drop).
3. HQ return ONLY after pickup (workers on board).
   Food delivery → free at last site (no HQ).
   School shift drop → free at destination (no HQ).
4. OT first: every name on Fleet_Drivers is OT. Staff only after all OT tried.
5. Maximise OT work. On 10pm wave, spread clusters across OT who do not
   yet have a 10pm job. Order: food → shifts → early waves (7pm…) →
   10pm → mid waves (9pm…). 10 before 9 so a 9pm return does not block 10pm leave.
6. Shifts: prefer one free OT to chain all; no HQ between drops.
7. Pickups just-in-time (arrive ~end+2 min). Food only for end >= 22:00,
   target 18:30, hard 19:00.
8. Balance: next job to lightest OT (fewest jobs, then pax).
9. Never silent: widen lateness and log ⚠️ / [!] if short a lorry.
"""

from __future__ import annotations

import json
import math
import os
from typing import Any, Dict, List, Optional, Tuple

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
with open(_CONFIG_PATH, "r") as f:
    config = json.load(f)

# ---------------------------------------------------------------------------
# Config knobs (manager may retune; algorithm stays the same)
# ---------------------------------------------------------------------------
HQ_LAT = float(config.get("hq_lat", 1.2947675))
HQ_LON = float(config.get("hq_lon", 103.6345739))
EVENING_BUFFER_MIN = int(config.get("traffic_buffer_mins", 15))
EVENING_START = int(config.get("evening_start_min", 17 * 60))

DINNER_END_THRESHOLD = 22 * 60
FOOD_TARGET_MIN = 18 * 60 + 30
FOOD_HARD_MIN = 19 * 60

PICKUP_BOARD_MIN = 2
PICKUP_LATE_TOLERANCE = 20          # later stops in a same-wave cluster
STOP_DWELL_MIN = 2
MIN_HQ_REST_AFTER_PICKUP = 5        # only after workers dropped at HQ
SHIFT_HARD_CUTOFF = 19 * 60
SHIFT_CHAIN_SOFT = 19 * 60 + 45     # 2nd+ shift in a chain

OT_DISPLAY_ORDER = ["Mahendran", "Sridhar", "Kailing", "Senthil", "Pandi"]

DEFAULT_STAFF = [
    {"name": "Staff Driver 1", "vehicle": "5546", "type": "10ft", "cap": 14},
    {"name": "Staff Driver 2", "vehicle": "3576", "type": "14ft", "cap": 25},
    {"name": "Staff Driver 3", "vehicle": "6897", "type": "10ft", "cap": 14},
    {"name": "Staff Driver 4", "vehicle": "1301", "type": "14ft", "cap": 25},
    {"name": "Staff Driver 5", "vehicle": "7203", "type": "14ft", "cap": 25},
]


# ---------------------------------------------------------------------------
# Helpers
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
    t = str(t).strip()
    if not t:
        return None
    u = t.upper().replace(" ", "")
    pm, am = "PM" in u, "AM" in u
    u = u.replace("PM", "").replace("AM", "")
    if ":" not in u:
        return None
    try:
        parts = u.split(":")
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
    return f"{h % 12 or 12}:{mi:02d} {ap}"


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


def travel_hq_to(info: dict) -> int:
    """HQ ↔ site: prefer recorded Site_Database minutes + traffic buffer."""
    rec = info.get("travel_hq_min") if info else None
    if rec is not None and not (isinstance(rec, float) and math.isnan(rec)):
        try:
            return int(round(float(rec) + EVENING_BUFFER_MIN))
        except Exception:
            pass
    d = haversine_km(HQ_LAT, HQ_LON, info.get("lat") if info else None, info.get("lon") if info else None)
    if d is None:
        return 60
    return int(round(d * 2 + 10 + EVENING_BUFFER_MIN))


def travel_between(a: dict, b: dict) -> int:
    """Local hop inside a wave (~10–15 min for nearby sites). Not HQ formula."""
    d = haversine_km(a.get("lat"), a.get("lon"), b.get("lat"), b.get("lon"))
    if d is None:
        return 15
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
    """Every name on Fleet_Drivers = OT. Staff = synthetic backup only."""
    header_idx = None
    for i, row in enumerate(raw_rows):
        if row and str(row[0]).strip() == "Driver No.":
            header_idx = i
            break
    sheet: List[dict] = []
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
            vtype = str(row[3]).strip() or "14ft"
            cap = _to_int(row[4], 0) or (25 if "14" in vtype else 14)
            sheet.append({
                "name": name,
                "vehicle": vehicle,
                "plate": str(row[2]).strip(),
                "type": vtype,
                "cap": cap,
                "is_ot": True,
            })

    by_name = {d["name"]: d for d in sheet}
    fleet: List[dict] = []
    for n in OT_DISPLAY_ORDER:
        if n in by_name:
            fleet.append(by_name.pop(n))
    fleet.extend(by_name.values())

    used_v = {d["vehicle"] for d in fleet if d["vehicle"]}
    used_n = {d["name"] for d in fleet}
    for s in DEFAULT_STAFF:
        if s["vehicle"] in used_v or s["name"] in used_n:
            continue
        fleet.append({**s, "is_ot": False, "plate": ""})
        used_v.add(s["vehicle"])
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
    low = label.lower()
    for info in site_lookup.values():
        if info["label"].lower() == low or low in info["label"].lower():
            return info
        if info["name"] and (info["name"].lower() == low or low in info["name"].lower()):
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
            jobs.append({
                "site_label": s0,
                "end_min": end_min,
                "workers": workers,
                "info": info,
                "is_dinner": end_min is not None and end_min >= DINNER_END_THRESHOLD,
            })

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
# Clustering (same end-time wave only)
# ---------------------------------------------------------------------------

def _nn_route_minutes(stops: List[dict]) -> int:
    remaining = list(stops)
    cur_lat, cur_lon = HQ_LAT, HQ_LON
    total = 0
    while remaining:
        best_i, best_d = 0, float("inf")
        for i, s in enumerate(remaining):
            d = haversine_km(cur_lat, cur_lon, s.get("lat"), s.get("lon"))
            if d is not None and d < best_d:
                best_d, best_i = d, i
        leg = travel_hq_to(remaining[best_i]) if best_d == float("inf") else max(8, int(round(best_d * 2.2)) + 5)
        total += leg + STOP_DWELL_MIN
        nxt = remaining.pop(best_i)
        cur_lat, cur_lon = nxt.get("lat"), nxt.get("lon")
    return total


def _cluster_diameter_km(jobs: List[dict]) -> float:
    """Max pairwise distance inside a cluster — human rule: keep stops local."""
    infos = [j["info"] for j in jobs if j.get("info")]
    if len(infos) < 2:
        return 0.0
    best = 0.0
    for i in range(len(infos)):
        for k in range(i + 1, len(infos)):
            d = haversine_km(infos[i].get("lat"), infos[i].get("lon"),
                             infos[k].get("lat"), infos[k].get("lon"))
            if d is not None and d > best:
                best = d
    return best


def _min_link_km(jobs_a: List[dict], jobs_b: List[dict]) -> float:
    """Closest site-to-site between two clusters (proximity merge key)."""
    best = 999.0
    for ja in jobs_a:
        for jb in jobs_b:
            ia, ib = ja.get("info"), jb.get("info")
            if not ia or not ib:
                continue
            d = haversine_km(ia.get("lat"), ia.get("lon"), ib.get("lat"), ib.get("lon"))
            if d is not None and d < best:
                best = d
    return best


# Same-wave cluster: max geographic diameter (km). ~12 km ≈ 15–20 min local hop.
CLUSTER_MAX_DIAMETER_KM = 12.0


def cluster_wave(jobs: List[dict], feasible_fn) -> List[dict]:
    """Human-style clustering for one end-time wave:

    Merge the CLOSEST pair of clusters first (min link distance), not the
    cheapest route-from-HQ. Refuse merge if:
      - capacity > 25
      - cluster diameter would exceed CLUSTER_MAX_DIAMETER_KM
      - feasible_fn (deadline) fails

    That keeps west sites with west sites and stops random pairings like
    Jurong West + a distant school while a nearer site sits alone.
    """
    clusterable = [j for j in jobs if j.get("info")]
    unclusterable = [j for j in jobs if not j.get("info")]
    clusters = [{"jobs": [j], "workers": j["workers"] or 0} for j in clusterable]

    while len(clusters) > 1:
        best = None  # (link_km, i, k)
        for i in range(len(clusters)):
            for k in range(i + 1, len(clusters)):
                ci, ck = clusters[i], clusters[k]
                pax = ci["workers"] + ck["workers"]
                if pax > 25:
                    continue
                merged_jobs = ci["jobs"] + ck["jobs"]
                if _cluster_diameter_km(merged_jobs) > CLUSTER_MAX_DIAMETER_KM:
                    continue
                if not feasible_fn(merged_jobs):
                    continue
                link = _min_link_km(ci["jobs"], ck["jobs"])
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
# Timing
# ---------------------------------------------------------------------------

def _order_nearest_hq(stops: List[dict]) -> List[dict]:
    return sorted(stops, key=lambda s: travel_hq_to(s))


def time_food(cluster: dict, earliest: int) -> dict:
    infos = [j["info"] for j in cluster["jobs"]]
    ordered = _order_nearest_hq(infos)
    depart = max(earliest, EVENING_START)
    t, prev, stops_out = depart, None, []
    for s in ordered:
        leg = travel_hq_to(s) if prev is None else travel_between(prev, s)
        arrive = t + leg
        stops_out.append({"site": s, "arrive": arrive})
        t = arrive + STOP_DWELL_MIN
        prev = s
    last = stops_out[-1]["arrive"]
    return {
        "type": "food",
        "depart": depart,
        "stops": stops_out,
        "workers": cluster["workers"],
        "last_arrival": last,
        "feasible": last <= FOOD_HARD_MIN,
        "on_target": last <= FOOD_TARGET_MIN,
        # free after food = last site (no HQ)
        "free_at": last + STOP_DWELL_MIN,
        "free_lat": prev.get("lat") if prev else HQ_LAT,
        "free_lon": prev.get("lon") if prev else HQ_LON,
        "at_hq": False,
    }


def time_pickup(
    cluster: dict,
    end_min: int,
    earliest: int,
    tolerance: int = PICKUP_LATE_TOLERANCE,
    at_hq: bool = True,
    free_lat=None,
    free_lon=None,
) -> dict:
    """Just-in-time multi-stop. ALWAYS ends at HQ (workers)."""
    infos = [j["info"] for j in cluster["jobs"]]
    ordered = _order_nearest_hq(infos)
    deadline = end_min + PICKUP_BOARD_MIN
    first = ordered[0]

    if at_hq or free_lat is None:
        leg0 = travel_hq_to(first)
    else:
        leg0 = travel_between({"lat": free_lat, "lon": free_lon}, first)

    depart = max(earliest, deadline - leg0)
    t, prev, stops_out, max_late = depart, None, [], 0
    for i, s in enumerate(ordered):
        leg = leg0 if i == 0 else travel_between(prev, s)
        arrive = t + leg
        late = max(0, arrive - deadline)
        max_late = max(max_late, late)
        stops_out.append({"site": s, "arrive": arrive, "deadline": deadline, "late_by": late})
        t = arrive + STOP_DWELL_MIN
        prev = s

    hq_return = t + travel_hq_to(prev)
    return {
        "type": "pickup",
        "depart": depart,
        "stops": stops_out,
        "hq_return": hq_return,
        "workers": cluster["workers"],
        "max_lateness": max_late,
        "feasible": max_late <= tolerance and depart >= earliest - 1,
        "free_at": hq_return,
        "free_lat": HQ_LAT,
        "free_lon": HQ_LON,
        "at_hq": True,
    }


def time_shift(
    shift: dict,
    earliest: int,
    at_hq: bool = True,
    free_lat=None,
    free_lon=None,
    chain: bool = False,
) -> dict:
    fi, ti = shift["from_info"], shift["to_info"]
    if at_hq or free_lat is None:
        depart = max(earliest, EVENING_START)
        arrive_from = depart + travel_hq_to(fi)
    else:
        depart = max(earliest, EVENING_START)
        arrive_from = depart + travel_between({"lat": free_lat, "lon": free_lon}, fi)
    arrive_to = arrive_from + STOP_DWELL_MIN + travel_between(fi, ti)
    cutoff = SHIFT_CHAIN_SOFT if chain else SHIFT_HARD_CUTOFF
    return {
        "type": "shift",
        "from": shift["from"],
        "to": shift["to"],
        "from_info": fi,
        "to_info": ti,
        "depart": depart,
        "arrive_from": arrive_from,
        "arrive_to": arrive_to,
        "feasible": arrive_to <= cutoff,
        "free_at": arrive_to + STOP_DWELL_MIN,
        "free_lat": ti.get("lat") or HQ_LAT,
        "free_lon": ti.get("lon") or HQ_LON,
        "at_hq": False,
    }


# ---------------------------------------------------------------------------
# Driver state
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

    def earliest(self) -> int:
        if not self.engagements:
            return EVENING_START
        last = self.engagements[-1]
        if last["type"] == "pickup":
            return last["free_at"] + MIN_HQ_REST_AFTER_PICKUP
        return last["free_at"]  # food / shift: free immediately

    def commit(self, leg: dict, workers: int = 0):
        self.engagements.append(leg)
        self.jobs_count += 1
        self.pax_count += workers
        self.free_at = leg["free_at"]
        self.free_lat = leg["free_lat"]
        self.free_lon = leg["free_lon"]
        self.at_hq = leg["at_hq"]

    def balance_key(self):
        return (self.jobs_count, self.pax_count)


def _ot_staff(states: List[DriverState]):
    return [s for s in states if s.is_ot], [s for s in states if not s.is_ot]


# ---------------------------------------------------------------------------
# Assignment phases
# ---------------------------------------------------------------------------

def assign_food(dinner_jobs: List[dict], states: Dict[str, DriverState], notes: List[str]) -> Dict[str, str]:
    if not dinner_jobs:
        return {}
    def feas(jobs):
        return time_food({"jobs": jobs, "workers": sum(j["workers"] or 0 for j in jobs)}, EVENING_START)["feasible"]
    clusters = cluster_wave(dinner_jobs, feas)
    ot, _ = _ot_staff(list(states.values()))
    out: Dict[str, str] = {}
    for cl in clusters:
        placed = False
        for st in sorted(ot, key=lambda s: s.balance_key()):
            if st.cap < cl["workers"]:
                continue
            leg = time_food(cl, st.earliest())
            if not leg["feasible"]:
                continue
            st.commit(leg)
            st.did_food = True
            for j in cl["jobs"]:
                out[j["site_label"]] = st.name
            names = ", ".join(j["site_label"] for j in cl["jobs"])
            warn = "" if leg["on_target"] else " (after 6:30 target, before 7:00 hard)"
            notes.append(
                f"[FOOD] {st.name} → {names} ({cl['workers']} pax) — "
                f"leave {fmt_time(leg['depart'])}, last {fmt_time(leg['last_arrival'])}{warn}, no HQ after"
            )
            placed = True
            break
        if not placed:
            for j in cl["jobs"]:
                notes.append(f"[!] NO OT free for food {j['site_label']}")
    return out


def assign_shifts(shifts: List[dict], states: Dict[str, DriverState], notes: List[str]) -> List[dict]:
    if not shifts:
        return []
    ot, staff = _ot_staff(list(states.values()))
    free_ot = sorted([s for s in ot if not s.did_food], key=lambda s: s.balance_key())
    busy_ot = sorted([s for s in ot if s.did_food], key=lambda s: s.balance_key())
    result = []
    remaining = list(shifts)

    def ordered(items):
        if len(items) <= 1:
            return list(items)
        first = max(items, key=lambda s: travel_hq_to(s["from_info"]))
        left = [s for s in items if s is not first]
        out = [first]
        cur = first["to_info"]
        while left:
            nxt = min(
                left,
                key=lambda s: haversine_km(
                    cur.get("lat"), cur.get("lon"),
                    s["from_info"].get("lat"), s["from_info"].get("lon"),
                ) or 99,
            )
            out.append(nxt)
            left.remove(nxt)
            cur = nxt["to_info"]
        return out

    def try_chain(st, items):
        trials = []
        floor = st.earliest()
        at_hq = st.at_hq
        flat, flon = st.free_lat, st.free_lon
        for i, s in enumerate(items):
            leg = time_shift(s, floor, at_hq=at_hq, free_lat=flat, free_lon=flon, chain=(i > 0))
            if not leg["feasible"]:
                return None
            trials.append(leg)
            floor = leg["free_at"]
            at_hq = False
            flat, flon = leg["free_lat"], leg["free_lon"]
        return trials

    for st in free_ot:
        ord_items = ordered(remaining)
        trials = try_chain(st, ord_items)
        if trials:
            for s, leg in zip(ord_items, trials):
                st.commit(leg)
                result.append({"from": s["from"], "to": s["to"], "driver": st.name})
                notes.append(
                    f"[SHIFT] {s['from']} → {s['to']} → {st.name} "
                    f"(leave {fmt_time(leg['depart'])}, drop {fmt_time(leg['arrive_to'])}, no HQ after)"
                )
            remaining = []
            break

    for s in remaining:
        placed = False
        for pool in (free_ot, busy_ot, staff):
            for st in sorted(pool, key=lambda x: x.balance_key()):
                leg = time_shift(s, st.earliest(), at_hq=st.at_hq, free_lat=st.free_lat, free_lon=st.free_lon)
                if not leg["feasible"]:
                    continue
                st.commit(leg)
                result.append({"from": s["from"], "to": s["to"], "driver": st.name})
                tag = "OT" if st.is_ot else "STAFF"
                notes.append(
                    f"[SHIFT] [{tag}] {s['from']} → {s['to']} → {st.name} "
                    f"(leave {fmt_time(leg['depart'])}, drop {fmt_time(leg['arrive_to'])}, no HQ after)"
                )
                placed = True
                break
            if placed:
                break
        if not placed:
            notes.append(f"[!] NO DRIVER for shift {s['from']} → {s['to']}")
    return result


def assign_pickup_wave(
    wave_jobs: List[dict],
    end_min: int,
    states: Dict[str, DriverState],
    notes: List[str],
    spread_10pm: bool = False,
) -> Dict[str, str]:
    def feas(jobs):
        trial = {"jobs": jobs, "workers": sum(j["workers"] or 0 for j in jobs)}
        return time_pickup(trial, end_min, EVENING_START)["feasible"]

    clusters = cluster_wave(wave_jobs, feas)
    ot, staff = _ot_staff(list(states.values()))
    assignment: Dict[str, str] = {}
    unplaced: List[dict] = []

    def try_assign(st, cl, tol):
        return time_pickup(
            cl, end_min, st.earliest(), tolerance=tol,
            at_hq=st.at_hq, free_lat=st.free_lat, free_lon=st.free_lon,
        )

    for cl in clusters:
        pax = cl["workers"]
        if spread_10pm:
            ot_pool = sorted([s for s in ot if not s.did_10pm], key=lambda s: s.balance_key()) + \
                      sorted([s for s in ot if s.did_10pm], key=lambda s: s.balance_key())
        else:
            ot_pool = sorted(ot, key=lambda s: s.balance_key())
        staff_pool = sorted(staff, key=lambda s: s.balance_key())

        placed = False
        for pool, tol in (
            (ot_pool, PICKUP_LATE_TOLERANCE),
            (ot_pool, PICKUP_LATE_TOLERANCE + 15),
            (staff_pool, PICKUP_LATE_TOLERANCE),
        ):
            if placed:
                break
            for st in pool:
                if st.cap < pax:
                    continue
                leg = try_assign(st, cl, tol)
                if not leg["feasible"]:
                    continue
                st.commit(leg, workers=pax)
                if end_min >= 22 * 60:
                    st.did_10pm = True
                for j in cl["jobs"]:
                    assignment[j["site_label"]] = st.name
                tag = "OT" if st.is_ot else "STAFF"
                names = ", ".join(j["site_label"] for j in cl["jobs"])
                late = f", up to {leg['max_lateness']}min late on later stop" if leg["max_lateness"] else ""
                notes.append(
                    f"[{fmt_time(end_min)} wave] [{tag}] {st.name} → {names} "
                    f"({pax} pax) — leave {fmt_time(leg['depart'])}, HQ {fmt_time(leg['hq_return'])}{late}"
                )
                placed = True
                break

        if not placed:
            if len(cl["jobs"]) > 1:
                notes.append(f"[i] Split {pax}-pax cluster at {fmt_time(end_min)} — no single lorry")
                for j in cl["jobs"]:
                    sub = {"jobs": [j], "workers": j["workers"]}
                    sub_ok = False
                    for pool, tol in ((ot_pool, PICKUP_LATE_TOLERANCE), (ot_pool, 40), (staff_pool, 40)):
                        if sub_ok:
                            break
                        for st in pool:
                            if st.cap < (j["workers"] or 0):
                                continue
                            leg = try_assign(st, sub, tol)
                            if not leg["feasible"]:
                                continue
                            st.commit(leg, workers=j["workers"])
                            if end_min >= 22 * 60:
                                st.did_10pm = True
                            assignment[j["site_label"]] = st.name
                            tag = "OT" if st.is_ot else "STAFF"
                            notes.append(
                                f"[{fmt_time(end_min)} wave] [{tag}] {st.name} → {j['site_label']} "
                                f"({j['workers']} pax) — leave {fmt_time(leg['depart'])}, HQ {fmt_time(leg['hq_return'])}"
                            )
                            sub_ok = True
                            break
                    if not sub_ok:
                        unplaced.append(j)
            else:
                unplaced.append(cl["jobs"][0])

    for j in unplaced:
        sub = {"jobs": [j], "workers": j["workers"]}
        placed = False
        for tol in (40, 60, 90):
            for st in sorted(ot, key=lambda s: s.balance_key()) + sorted(staff, key=lambda s: s.balance_key()):
                if st.cap < (j["workers"] or 0):
                    continue
                leg = try_assign(st, sub, tol)
                if not leg["feasible"]:
                    continue
                st.commit(leg, workers=j["workers"])
                if end_min >= 22 * 60:
                    st.did_10pm = True
                assignment[j["site_label"]] = st.name
                tag = "OT" if st.is_ot else "STAFF"
                notes.append(
                    f"⚠️ [{fmt_time(end_min)} wave] [{tag}] {st.name} → {j['site_label']} "
                    f"({j['workers']} pax) — {leg['max_lateness']}min late. Leave {fmt_time(leg['depart'])}."
                )
                placed = True
                break
            if placed:
                break
        if not placed:
            notes.append(
                f"[!] NO DRIVER for {j['site_label']} ({j['workers']} pax, ends {fmt_time(end_min)})"
            )
    return assignment


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _rebalance_staff_to_ot(assignment, resolvable, states, notes):
    """Human check: staff should not keep a job an OT can still do on time."""
    ot = sorted([s for s in states.values() if s.is_ot], key=lambda s: s.balance_key())
    staff_names = {s.name for s in states.values() if not s.is_ot}

    # Group current pickup assignments that are on staff, by end_min
    by_end: Dict[int, List[dict]] = {}
    for j in resolvable:
        name = assignment.get(j["site_label"], {}).get("pickup")
        if not name or name not in staff_names:
            continue
        by_end.setdefault(j["end_min"], []).append(j)

    for end_min, job_list in sorted(by_end.items()):
        # rebuild clusters of staff-held jobs for this wave
        def feas(jobs):
            trial = {"jobs": jobs, "workers": sum(x["workers"] or 0 for x in jobs)}
            return time_pickup(trial, end_min, EVENING_START)["feasible"]
        clusters = cluster_wave(job_list, feas)
        for cl in clusters:
            pax = cl["workers"]
            moved = False
            for st in ot:
                if st.cap < pax:
                    continue
                leg = time_pickup(
                    cl, end_min, st.earliest(),
                    at_hq=st.at_hq, free_lat=st.free_lat, free_lon=st.free_lon,
                )
                if not leg["feasible"]:
                    continue
                # Unhook from staff in notes only; commit to OT
                st.commit(leg, workers=pax)
                if end_min >= 22 * 60:
                    st.did_10pm = True
                for j in cl["jobs"]:
                    assignment[j["site_label"]]["pickup"] = st.name
                names = ", ".join(j["site_label"] for j in cl["jobs"])
                notes.append(
                    f"[REBALANCE] moved {names} ({pax} pax) off staff → OT {st.name} "
                    f"(leave {fmt_time(leg['depart'])}, HQ {fmt_time(leg['hq_return'])})"
                )
                moved = True
                break
            if not moved:
                continue


def build_schedule(jobs: List[dict], shifts: List[dict], fleet: List[dict]):
    notes: List[str] = []
    states = {d["name"]: DriverState(d) for d in fleet}
    assignment = {j["site_label"]: {"dinner": None, "pickup": None} for j in jobs}

    resolvable = [j for j in jobs if j["info"] and j["end_min"] is not None]
    for j in jobs:
        if not j["info"] or j["end_min"] is None:
            notes.append(f"[!] Skipped '{j['site_label']}' — missing coords or end time")

    # 1 Food
    dinner = [j for j in resolvable if j["is_dinner"]]
    for label, name in assign_food(dinner, states, notes).items():
        assignment[label]["dinner"] = name

    # 2 Shifts
    shift_assignment = assign_shifts(shifts, states, notes)

    # 3 Pickups: early waves → 10pm → mid (9pm)
    ends = sorted({j["end_min"] for j in resolvable})
    early = [e for e in ends if e < 21 * 60]
    late10 = [e for e in ends if e >= 22 * 60]
    mid9 = [e for e in ends if 21 * 60 <= e < 22 * 60]

    for end_min in early + late10 + mid9:
        wave = [j for j in resolvable if j["end_min"] == end_min]
        is10 = end_min >= 22 * 60
        for label, name in assign_pickup_wave(wave, end_min, states, notes, spread_10pm=is10).items():
            assignment[label]["pickup"] = name

    # 4) Rebalance: if staff holds a pickup and an OT is free in time, steal to OT
    _rebalance_staff_to_ot(assignment, resolvable, states, notes)

    ot = [s for s in states.values() if s.is_ot]
    notes.append(
        "OT balance: " + ", ".join(f"{s.name}={s.jobs_count} jobs/{s.pax_count} pax" for s in ot)
    )
    idle = [s.name for s in ot if s.jobs_count == 0]
    if idle:
        notes.append(f"[i] Idle OT: {', '.join(idle)}")
    used_staff = [s.name for s in states.values() if not s.is_ot and s.jobs_count > 0]
    if used_staff:
        notes.append(f"[i] Staff used (OT could not cover): {', '.join(used_staff)}")

    return assignment, shift_assignment, notes, states


def driver_timeline_rows(state: DriverState) -> List[Tuple[str, str]]:
    rows = []
    prev_free = None
    for leg in state.engagements:
        if prev_free is not None and leg.get("depart") and leg["depart"] > prev_free + 4:
            rows.append((
                "Available / move",
                f"{fmt_time(prev_free)} → {fmt_time(leg['depart'])} ({leg['depart'] - prev_free} min)",
            ))
        if leg["type"] == "food":
            names = ", ".join(s["site"]["label"] for s in leg["stops"])
            arr = ", ".join(f"{s['site']['label']} {fmt_time(s['arrive'])}" for s in leg["stops"])
            rows.append((f"Food: {names}", f"Leave {fmt_time(leg['depart'])} → {arr} (no HQ after food)"))
        elif leg["type"] == "pickup":
            for s in leg["stops"]:
                late = f" (LATE {s['late_by']}min)" if s["late_by"] else " (on time)"
                rows.append((
                    f"Pickup: {s['site']['label']} ({leg['workers']} pax on lorry)",
                    f"Arrive {fmt_time(s['arrive'])} for {fmt_time(s['deadline'])}{late}",
                ))
            rows.append((
                "→ HQ (workers drop)",
                f"Leave {fmt_time(leg['depart'])} … HQ {fmt_time(leg['hq_return'])}",
            ))
        elif leg["type"] == "shift":
            rows.append((
                f"Shift: {leg['from']} → {leg['to']}",
                f"Leave {fmt_time(leg['depart'])} → pick {fmt_time(leg['arrive_from'])} → "
                f"drop {fmt_time(leg['arrive_to'])} (no HQ after shift)",
            ))
        prev_free = leg["free_at"]
    return rows
