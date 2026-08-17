"""
dispatch_engine.py — Anderco evening lorry dispatch (deterministic).

Rules (business):
  1. Pickup time = site end time + 10 min (workers scan Infotech before leaving).
     Drivers must NOT pick up early; they leave HQ so they arrive near that window.
  2. Food delivery ONLY for sites ending at/after 22:00.
     Food must arrive by 18:30 (hard cutoff 19:00).
  3. Location first: cluster nearby sites on one lorry when capacity allows.
  4. OT drivers first (Mahendran, Sridhar, Kailing, Senthil, Pandi).
     Staff drivers (Staff Driver 1, 2, …) only if OT cannot cover.
  5. OT drivers work continuously; only traffic buffer is added to travel times.
  6. After a pickup, return to HQ before the next distant job (nearby pickups
     at the same end-time band can be chained site-to-site).
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional, Set, Tuple

import os
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
with open(_CONFIG_PATH, "r") as f:
    config = json.load(f)

HQ_LAT = float(config.get("hq_lat", 1.2947675))
HQ_LON = float(config.get("hq_lon", 103.6345739))
EVENING_BUFFER_MIN = int(config.get("traffic_buffer_mins", 15))

# Food: only sites ending at or after this minute-of-day
DINNER_END_THRESHOLD = 22 * 60  # 22:00
DINNER_TARGET = 18 * 60 + 30    # 18:30
DINNER_HARD = 19 * 60           # 19:00

PICKUP_AFTER_END = 10           # workers pack + Infotech scan
PICKUP_HARD_EXTRA = 20          # absolute lateness allowed past deadline

# Geographic clustering
CLUSTER_KM = 6.0                # max link distance to merge dinner sites
COMBINE_PICKUP_KM = 6.0         # chain pickups without HQ return if closer
ROUTE_TIME_BUDGET = 120         # max minutes for a dinner multi-stop loop from HQ

# Preferred display order when these names appear in Fleet_Drivers.
# Anyone listed on the Fleet_Drivers sheet is an OT driver.
# Names NOT on the sheet (e.g. Senthil removed = on leave) are not used.
OT_ORDER = ["Mahendran", "Sridhar", "Kailing", "Senthil", "Pandi"]

# Staff pool used only when OT cannot cover (no OT preference)
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


def fmt_time(m: int) -> str:
    m = int(m) % 1440
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


def travel_min(dist_km: Optional[float], evening: bool = True) -> Optional[int]:
    """Driving time estimate: (km * 2 + 10) + optional evening traffic buffer."""
    if dist_km is None:
        return None
    base = dist_km * 2 + 10
    return int(round(base + (EVENING_BUFFER_MIN if evening else 0)))


def travel_from_hq(info: dict, evening: bool = True) -> int:
    """Prefer recorded HQ travel time from Site_Database when present."""
    recorded = info.get("travel_hq_min")
    if recorded is not None and not (isinstance(recorded, float) and math.isnan(recorded)):
        try:
            base = float(recorded)
            return int(round(base + (EVENING_BUFFER_MIN if evening else 0)))
        except Exception:
            pass
    d = haversine_km(HQ_LAT, HQ_LON, info.get("lat"), info.get("lon"))
    return travel_min(d, evening=evening) or 60


def route_time_from_hq(points: List[Tuple[float, float]]) -> int:
    """Nearest-neighbour loop HQ -> points (5 min service each)."""
    remaining = list(points)
    cur = (HQ_LAT, HQ_LON)
    total = 0
    while remaining:
        best_i, best_d = 0, float("inf")
        for i, p in enumerate(remaining):
            d = haversine_km(cur[0], cur[1], p[0], p[1])
            if d is not None and d < best_d:
                best_d, best_i = d, i
        total += (travel_min(best_d) or 0) + 5
        cur = remaining[best_i]
        remaining.pop(best_i)
    return total


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
        # skip duplicate header lines in the middle of the sheet
        if code == "PJC Code":
            continue
        lat = _to_float(row[9])
        lon = _to_float(row[10])
        travel_min_val = _to_float(row[7])
        sites[code] = {
            "code": code,
            "company": str(row[1]).strip(),
            "name": str(row[2]).strip(),
            "address": str(row[3]).strip(),
            "driver": str(row[4]).strip(),
            "vehicle": str(row[5]).strip(),
            "lorry": str(row[6]).strip(),
            "travel_hq_min": travel_min_val,
            "lat": lat,
            "lon": lon,
            "label": str(row[13]).strip()
            or (str(row[2]).strip() + " [" + code + "]"),
        }
    return sites



def parse_fleet(raw_rows: List[List[str]]) -> List[dict]:
    """Fleet_Drivers sheet = who is working tonight.

    - Every name on the sheet is an OT driver (must maximise their evening work).
    - Names removed from the sheet (leave) are not used at all.
    - Staff Driver 1, 2, … are synthetic backups only — never from the sheet.
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
            vehicle = str(row[1]).strip()
            if vehicle.endswith(".0"):
                vehicle = vehicle[:-2]
            # Skip empty / header junk
            if not name or name.lower().startswith("driver"):
                # allow "Driver 1" style but skip pure header repeats
                pass
            cap = _to_int(row[4], 14)
            if cap <= 0:
                cap = 25 if "14" in str(row[3]) else 14
            sheet_drivers.append(
                {
                    "name": name,
                    "vehicle": vehicle,
                    "plate": str(row[2]).strip(),
                    "type": str(row[3]).strip() or "14ft",
                    "cap": cap,
                    "is_ot": True,
                }
            )

    # Order by OT_ORDER when possible, then any other sheet names
    by_name = {d["name"]: d for d in sheet_drivers}
    fleet: List[dict] = []
    for ot_name in OT_ORDER:
        if ot_name in by_name:
            fleet.append(by_name.pop(ot_name))
    for name, d in by_name.items():
        fleet.append(d)

    # Staff backups only (never invent missing OT names like Senthil)
    existing_veh = {d["vehicle"] for d in fleet if d["vehicle"]}
    used_names = {d["name"] for d in fleet}
    for s in DEFAULT_STAFF:
        if s["vehicle"] in existing_veh:
            continue
        if s["name"] in used_names:
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
        if info["name"] and (
            info["name"].lower() == lower or lower in info["name"].lower()
        ):
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
                    # Food only when work ends at/after 22:00
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
                shifts.append(
                    {"from": frm, "to": to, "from_info": fi, "to_info": ti}
                )
    return jobs, shifts


# ---------------------------------------------------------------------------
# Clustering (location-first, capacity-safe, route-time checked)
# ---------------------------------------------------------------------------

def cluster_dinner_jobs(dinner_jobs: List[dict]) -> List[dict]:
    """Merge 22:00+ sites only if:
       - within CLUSTER_KM (pairwise for the growing set — complete-link style)
       - total workers <= 25
       - NN route from HQ fits ROUTE_TIME_BUDGET
    """
    n = len(dinner_jobs)
    if n == 0:
        return []

    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def members(r):
        return [i for i in range(n) if find(i) == r]

    def all_pairs_close(idxs: List[int]) -> bool:
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                ja, jb = dinner_jobs[idxs[a]], dinner_jobs[idxs[b]]
                if not ja["info"] or not jb["info"]:
                    return False
                d = haversine_km(
                    ja["info"]["lat"], ja["info"]["lon"],
                    jb["info"]["lat"], jb["info"]["lon"],
                )
                if d is None or d > CLUSTER_KM:
                    return False
        return True

    for a in range(n):
        for b in range(a + 1, n):
            ja, jb = dinner_jobs[a], dinner_jobs[b]
            if not ja["info"] or not jb["info"]:
                continue
            d = haversine_km(
                ja["info"]["lat"], ja["info"]["lon"],
                jb["info"]["lat"], jb["info"]["lon"],
            )
            if d is None or d > CLUSTER_KM:
                continue
            ra, rb = find(a), find(b)
            if ra == rb:
                continue
            merged = members(ra) + members(rb)
            if sum(dinner_jobs[i]["workers"] for i in merged) > 25:
                continue
            if not all_pairs_close(merged):
                continue
            pts = [
                (dinner_jobs[i]["info"]["lat"], dinner_jobs[i]["info"]["lon"])
                for i in merged
            ]
            if route_time_from_hq(pts) > ROUTE_TIME_BUDGET:
                continue
            parent[rb] = ra

    groups: Dict[int, List[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    clusters = []
    for idxs in groups.values():
        jobs = [dinner_jobs[i] for i in idxs]
        pts = [(j["info"]["lat"], j["info"]["lon"]) for j in jobs if j["info"]]
        clusters.append(
            {
                "jobs": jobs,
                "workers": sum(j["workers"] for j in jobs),
                "route_time": route_time_from_hq(pts) if pts else 0,
            }
        )
    clusters.sort(key=lambda c: -c["workers"])
    return clusters


# ---------------------------------------------------------------------------
# Assignment — OT first, staff only if needed
# ---------------------------------------------------------------------------





def verify_schedule(
    jobs: List[dict],
    shifts: List[dict],
    assignment: Dict[str, dict],
    shift_assignment: List[dict],
    fleet: Optional[List[dict]] = None,
) -> Dict[str, dict]:
    """Simulate each driver's evening.

    OT drivers: continuous day from ~5PM (food → 7PM → 9/10PM).
    Staff drivers: each pickup is an independent HQ→site→HQ sortie timed
    to the end window (no 5PM wait — they don't get OT).
    """
    ot_names: Set[str] = set()
    if fleet:
        ot_names = {d["name"] for d in fleet if d.get("is_ot")}

    driver_tasks: Dict[str, List[dict]] = {}

    for j in jobs:
        a = assignment.get(j["site_label"])
        if not a or not j["info"]:
            continue
        if a.get("dinner"):
            driver_tasks.setdefault(a["dinner"], []).append(
                {
                    "type": "Dinner",
                    "label": j["site_label"],
                    "info": j["info"],
                    "deadline": DINNER_TARGET,
                    "hard": DINNER_HARD,
                    "end_min": j["end_min"],
                }
            )
        if a.get("pickup") and j["end_min"] is not None:
            driver_tasks.setdefault(a["pickup"], []).append(
                {
                    "type": "Pickup",
                    "label": j["site_label"],
                    "info": j["info"],
                    "deadline": j["end_min"] + PICKUP_AFTER_END,
                    "hard": j["end_min"] + PICKUP_AFTER_END + PICKUP_HARD_EXTRA,
                    "end_min": j["end_min"],
                    "workers": j["workers"],
                }
            )

    shift_lookup = {s["from"]: s for s in shifts}
    for s in shift_assignment:
        sinfo = shift_lookup.get(s["from"])
        driver_tasks.setdefault(s["driver"], []).append(
            {
                "type": "Shift",
                "label": f"{s['from']} -> {s['to']}",
                "from_info": sinfo["from_info"] if sinfo else None,
                "to_info": sinfo["to_info"] if sinfo else None,
                "deadline": 19 * 60,
                "hard": 19 * 60 + 15,
            }
        )

    results: Dict[str, dict] = {}
    for driver, tasks in driver_tasks.items():
        is_ot = driver in ot_names if ot_names else not driver.startswith("Staff")

        def sort_key(t):
            if t["type"] == "Dinner":
                return (0, t["deadline"])
            if t["type"] == "Shift":
                return (1, t["deadline"])
            return (2, t["deadline"])

        tasks.sort(key=sort_key)
        log = []
        fail = False

        if not is_ot:
            # ---- STAFF: independent sorties from HQ, timed to each job ----
            for t in tasks:
                if t["type"] == "Shift":
                    fi, ti = t.get("from_info"), t.get("to_info")
                    if not fi or not ti:
                        log.append((f"Shift {t['label']}", "site not found", False))
                        fail = True
                        continue
                    # leave HQ so arrive ~deadline
                    d1 = travel_from_hq(fi, evening=True)
                    leave = t["deadline"] - (d1 or 40) - 10
                    if leave < 17 * 60:
                        leave = 17 * 60
                    clock = leave + (d1 or 40)
                    d2 = haversine_km(fi["lat"], fi["lon"], ti["lat"], ti["lon"])
                    clock += travel_min(d2) or 0
                    arrival = clock
                    ok = arrival <= t["hard"]
                    if not ok:
                        fail = True
                    status = "OK" if arrival <= t["deadline"] else (
                        f"LATE by {arrival - t['deadline']}min" if not ok
                        else f"soft late {arrival - t['deadline']}min"
                    )
                    log.append(
                        (
                            f"Shift {t['label']}",
                            f"leave HQ ~{fmt_time(leave)} → arrive {fmt_time(arrival)} "
                            f"(need by {fmt_time(t['deadline'])}) [{status}]",
                            ok,
                        )
                    )
                    continue

                info = t["info"]
                if not info or info.get("lat") is None:
                    log.append((f"{t['type']} {t['label']}", "missing coordinates", False))
                    fail = True
                    continue
                trav = travel_from_hq(info, evening=True)
                end_min = t.get("end_min") or t["deadline"] - PICKUP_AFTER_END
                # Leave HQ to arrive near end_min (staff don't wait from 5PM)
                leave = end_min - trav
                if leave < 17 * 60:
                    leave = 17 * 60
                arrival = leave + trav
                ok = arrival <= t["hard"]
                if not ok:
                    fail = True
                if arrival <= end_min + 5:
                    timing = (
                        f"leave HQ ~{fmt_time(leave)} → arrive ~{fmt_time(arrival)} "
                        f"for end {fmt_time(end_min)} [OK — staff timed pickup]"
                    )
                    ok = True
                else:
                    status = "OK" if ok else f"LATE by {arrival - t['deadline']}min"
                    timing = (
                        f"leave HQ ~{fmt_time(leave)} → arrive {fmt_time(arrival)} "
                        f"(need by {fmt_time(t['deadline'])}) [{status}]"
                    )
                log.append(
                    (f"PICKUP {t['label']} ({t.get('workers', '?')} pax)", timing, ok)
                )
            results[driver] = {"fail": fail, "log": log}
            continue

        # ---- OT: continuous evening from 5PM ----
        cur = (HQ_LAT, HQ_LON)
        clock = 17 * 60
        for i, t in enumerate(tasks):
            if t["type"] == "Shift":
                fi, ti = t.get("from_info"), t.get("to_info")
                if not fi or not ti:
                    log.append((f"Shift {t['label']}", "site not found", False))
                    fail = True
                    continue
                d1 = haversine_km(cur[0], cur[1], fi["lat"], fi["lon"])
                clock += (travel_min(d1) or 0) + 5
                d2 = haversine_km(fi["lat"], fi["lon"], ti["lat"], ti["lon"])
                clock += travel_min(d2) or 0
                arrival = clock
                clock += 5
                cur = (ti["lat"], ti["lon"])
                ok = arrival <= t["hard"]
                if not ok:
                    fail = True
                status = "OK" if arrival <= t["deadline"] else f"LATE by {arrival - t['deadline']}min"
                log.append(
                    (
                        f"Shift {t['label']}",
                        f"arrive {fmt_time(arrival)} (need by {fmt_time(t['deadline'])}) [{status}]",
                        ok,
                    )
                )
                continue

            info = t["info"]
            if not info or info.get("lat") is None:
                log.append((f"{t['type']} {t['label']}", "missing coordinates", False))
                fail = True
                continue

            from_hq = abs(cur[0] - HQ_LAT) < 0.001 and abs(cur[1] - HQ_LON) < 0.001
            if from_hq:
                trav = travel_from_hq(info, evening=True)
            else:
                d = haversine_km(cur[0], cur[1], info["lat"], info["lon"])
                # Short site-to-site hop: less buffer (already on the road)
                use_eve = not (d is not None and d <= COMBINE_PICKUP_KM)
                trav = travel_min(d, evening=use_eve) or 40

            # Same-end nearby pair: leave HQ later so both pickups fit around end_min
            if (
                t["type"] == "Pickup"
                and from_hq
                and i + 1 < len(tasks)
                and tasks[i + 1]["type"] == "Pickup"
                and tasks[i + 1].get("end_min") == t.get("end_min")
                and tasks[i + 1].get("info")
            ):
                dd = haversine_km(
                    info["lat"], info["lon"],
                    tasks[i + 1]["info"]["lat"], tasks[i + 1]["info"]["lon"],
                )
                if dd is not None and dd <= COMBINE_PICKUP_KM:
                    # leave so we arrive first site ~ end_min - 5
                    ideal_leave = (t.get("end_min") or t["deadline"]) - trav - 15
                    if ideal_leave > clock:
                        clock = ideal_leave

            arrival = clock + trav

            if t["type"] == "Dinner":
                ok = arrival <= t["hard"]
                if not ok:
                    fail = True
                if arrival <= t["deadline"]:
                    status = "OK"
                elif arrival <= t["hard"]:
                    status = f"soft late {arrival - t['deadline']}min (before 7PM OK)"
                else:
                    status = f"LATE by {arrival - t['deadline']}min"
                log.append(
                    (
                        f"FOOD {t['label']}",
                        f"leave ~{fmt_time(clock)} → arrive {fmt_time(arrival)} "
                        f"(need by {fmt_time(t['deadline'])}) [{status}]",
                        ok,
                    )
                )
                clock = arrival + 8
                cur = (info["lat"], info["lon"])
                # Return HQ before late pickups
                nxt = tasks[i + 1] if i + 1 < len(tasks) else None
                if nxt and nxt["type"] == "Pickup" and (nxt.get("end_min") or 0) >= 21 * 60:
                    back = travel_from_hq(info, evening=True)
                    clock = clock + (back or 0)
                    cur = (HQ_LAT, HQ_LON)
                elif nxt and nxt["type"] == "Dinner":
                    # continue to next food site
                    pass
                elif nxt is None or (nxt.get("end_min") or 0) >= 21 * 60:
                    back = travel_from_hq(info, evening=True)
                    clock = clock + (back or 0)
                    cur = (HQ_LAT, HQ_LON)
                continue

            # OT PICKUP — wait until end if early (slightly earlier if chaining same-end neighbour)
            end_min = t.get("end_min") or t["deadline"] - PICKUP_AFTER_END
            chain_next = False
            if (
                i + 1 < len(tasks)
                and tasks[i + 1]["type"] == "Pickup"
                and tasks[i + 1].get("end_min") == end_min
                and tasks[i + 1].get("info")
            ):
                dd = haversine_km(
                    info["lat"], info["lon"],
                    tasks[i + 1]["info"]["lat"], tasks[i + 1]["info"]["lon"],
                )
                if dd is not None and dd <= COMBINE_PICKUP_KM:
                    chain_next = True
            wait_until = end_min - (10 if chain_next else 0)
            service_start = max(arrival, wait_until)
            pickup_done = service_start + PICKUP_AFTER_END
            ok = arrival <= t["hard"]
            if arrival > t["hard"]:
                fail = True

            if arrival < end_min:
                wait = end_min - arrival
                timing = (
                    f"leave ~{fmt_time(clock)} → arrive site {fmt_time(arrival)} "
                    f"(wait {wait} min for end {fmt_time(end_min)}) → "
                    f"pickup ready ~{fmt_time(pickup_done)} "
                    f"[OK — on time for {fmt_time(t['deadline'])}]"
                )
                ok = True
            else:
                late = arrival - t["deadline"]
                status = "OK" if ok else f"LATE by {late}min"
                timing = (
                    f"leave ~{fmt_time(clock)} → arrive {fmt_time(arrival)} "
                    f"(need by {fmt_time(t['deadline'])}) [{status}]"
                )

            # Same end-time + nearby: one trip (site1→site2→HQ). Otherwise always HQ after pickup
            # (workers must be dropped at Anderco HQ / dormitory before next wave).
            nxt = tasks[i + 1] if i + 1 < len(tasks) else None
            chain = False
            if (
                nxt
                and nxt["type"] == "Pickup"
                and nxt.get("info")
                and nxt.get("end_min") == end_min
            ):
                dd = haversine_km(
                    info["lat"], info["lon"], nxt["info"]["lat"], nxt["info"]["lon"]
                )
                if dd is not None and dd <= COMBINE_PICKUP_KM:
                    chain = True
            if chain:
                timing = timing + " → next nearby same-time site (one trip)"
                log.append(
                    (f"PICKUP {t['label']} ({t.get('workers', '?')} pax)", timing, ok)
                )
                clock = pickup_done
                cur = (info["lat"], info["lon"])
            else:
                back = travel_from_hq(info, evening=True)
                hq_arrive = pickup_done + (back or 0)
                timing = timing + f" → HQ ~{fmt_time(hq_arrive)}"
                log.append(
                    (f"PICKUP {t['label']} ({t.get('workers', '?')} pax)", timing, ok)
                )
                clock = hq_arrive
                cur = (HQ_LAT, HQ_LON)

        results[driver] = {"fail": fail, "log": log}
    return results


def _ot_first(fleet: List[dict]) -> List[dict]:
    ot = [d for d in fleet if d.get("is_ot")]
    staff = [d for d in fleet if not d.get("is_ot")]
    ot_sorted = sorted(
        ot,
        key=lambda d: OT_ORDER.index(d["name"]) if d["name"] in OT_ORDER else 99,
    )
    return ot_sorted + staff


def _driver_ok_with_job(
    driver_name: str,
    jobs: List[dict],
    shifts: List[dict],
    assignment: Dict[str, dict],
    shift_assignment: List[dict],
    new_site: Optional[str] = None,
    new_dinner: bool = False,
    new_pickup: bool = True,
    new_shift: Optional[dict] = None,
) -> bool:
    """Temporarily add a job for this driver and check their timeline stays feasible."""
    trial_a = {k: dict(v) for k, v in assignment.items()}
    trial_s = list(shift_assignment)
    if new_site:
        cur = trial_a.get(new_site, {"dinner": None, "pickup": None})
        if new_dinner:
            cur["dinner"] = driver_name
        if new_pickup:
            cur["pickup"] = driver_name
        trial_a[new_site] = cur
    if new_shift:
        trial_s = trial_s + [{**new_shift, "driver": driver_name}]
    res = verify_schedule(jobs, shifts, trial_a, trial_s, fleet=None)
    r = res.get(driver_name)
    if not r:
        return True
    return not r["fail"]


def assign_drivers(
    jobs: List[dict],
    shifts: List[dict],
    fleet: List[dict],
    avoid_for_job: Optional[Dict[str, Set[str]]] = None,
):
    """
    Pack OT drivers full first (feasibility-checked), staff only when no OT fits.

    Order of work:
      1. 22:00 food clusters → OT with capacity, timeline OK
      2. Remaining 22:00 / 21:00 / 19:00 pickups → OT first if timeline OK
      3. Staff only if every OT fails capacity or timeline
      4. Shifts → staff preferred

    Anyone on Fleet_Drivers is OT. Removed name = on leave (not in fleet).
    """
    avoid_for_job = avoid_for_job or {}
    ordered = _ot_first(fleet)
    ot_list = [d for d in ordered if d.get("is_ot")]
    staff_list = [d for d in ordered if not d.get("is_ot")]

    load = {d["name"]: 0 for d in ordered}
    task_count = {d["name"]: 0 for d in ordered}
    dinner_used: Set[str] = set()
    assignment: Dict[str, dict] = {}
    shift_assignment: List[dict] = []
    cluster_notes: List[str] = []

    dinner_jobs = [j for j in jobs if j["is_dinner"]]
    other_jobs = [j for j in jobs if not j["is_dinner"]]
    clusters = cluster_dinner_jobs(dinner_jobs)

    def hist_name(j: dict) -> Optional[str]:
        if not j.get("info"):
            return None
        hist = j["info"].get("driver") or ""
        for d in ordered:
            if d["vehicle"] and d["vehicle"] in hist:
                return d["name"]
            if d["name"] and d["name"].lower() in hist.lower():
                return d["name"]
        return None

    def try_assign_cluster(cl, pool, tag_prefix):
        avoided: Set[str] = set()
        for j in cl["jobs"]:
            avoided |= avoid_for_job.get(j["site_label"], set())
        # Prefer OT with fewer tasks so we spread 10PM work
        candidates = [d for d in pool if d["name"] not in avoided and d["cap"] >= cl["workers"] and d["name"] not in dinner_used]
        candidates.sort(key=lambda d: (task_count[d["name"]], load[d["name"]]))
        for d in candidates:
            # trial assignment
            trial = {k: dict(v) for k, v in assignment.items()}
            for j in cl["jobs"]:
                trial[j["site_label"]] = {"dinner": d["name"], "pickup": d["name"]}
            res = verify_schedule(jobs, shifts, trial, shift_assignment, fleet=ordered)
            if res.get(d["name"], {}).get("fail"):
                continue
            # accept
            dinner_used.add(d["name"])
            load[d["name"]] += cl["workers"]
            task_count[d["name"]] += 1
            for j in cl["jobs"]:
                assignment[j["site_label"]] = {"dinner": d["name"], "pickup": d["name"]}
            cluster_notes.append(
                f"[{tag_prefix}] {d['name']} ({d['vehicle']}, {d['type']}, cap {d['cap']}) → "
                + ", ".join(j["site_label"] for j in cl["jobs"])
                + f"  [{cl['workers']} pax, ~{cl['route_time']} min food route]"
            )
            return True
        return False

    # ---- Phase A: food clusters — OT first; split if combined fails ----
    for cl in clusters:
        if try_assign_cluster(cl, ot_list, "OT"):
            continue
        if try_assign_cluster(cl, staff_list, "STAFF"):
            continue
        # Split into single-site food runs (still OT first)
        if len(cl["jobs"]) > 1:
            cluster_notes.append(
                f"ℹ️ Could not combine {cl['workers']} pax cluster — assigning each site separately"
            )
            for j in cl["jobs"]:
                sub = {
                    "jobs": [j],
                    "workers": j["workers"],
                    "route_time": cl["route_time"],
                }
                if try_assign_cluster(sub, ot_list, "OT"):
                    continue
                if try_assign_cluster(sub, staff_list, "STAFF"):
                    continue
                cluster_notes.append(
                    f"⚠️ NO DRIVER for food site {j['site_label']} ({j['workers']} pax)"
                )
        else:
            cluster_notes.append(
                "⚠️ NO DRIVER for "
                + f"{cl['workers']}-person cluster: "
                + ", ".join(j["site_label"] for j in cl["jobs"])
                + f" (need capacity >= {cl['workers']})"
            )

    # ---- Phase B/C: all other pickups — latest end first, OT first, check timeline ----
    others = sorted(
        other_jobs,
        key=lambda j: (-(j["end_min"] or 0), -j["workers"]),
    )
    for j in others:
        if j["site_label"] in assignment and assignment[j["site_label"]].get("pickup"):
            continue
        avoided = avoid_for_job.get(j["site_label"], set())
        pref = hist_name(j)

        def try_pool(pool):
            # historical OT first if in pool
            ordered_pool = list(pool)
            if pref:
                ordered_pool = [d for d in pool if d["name"] == pref] + [
                    d for d in pool if d["name"] != pref
                ]
            # Prefer drivers who already have work (fill continuous evening)
            # then drivers with 0 jobs (give every OT something)
            # Balance OT: fill continuous evening but do not overload one driver
            # Prefer OT with 1 job already (food) before giving a 3rd/4th; avoid 0-job OT only after
            ordered_pool = sorted(
                ordered_pool,
                key=lambda d: (
                    0 if d["name"] == pref else 1,
                    0 if task_count[d["name"]] == 1 else (1 if task_count[d["name"]] == 0 else 2),
                    task_count[d["name"]],
                    load[d["name"]],
                ),
            )
            for d in ordered_pool:
                if d["name"] in avoided:
                    continue
                if d["cap"] < j["workers"]:
                    continue
                trial = {k: dict(v) for k, v in assignment.items()}
                trial[j["site_label"]] = {"dinner": None, "pickup": d["name"]}
                res = verify_schedule(jobs, shifts, trial, shift_assignment, fleet=ordered)
                if res.get(d["name"], {}).get("fail"):
                    continue
                assignment[j["site_label"]] = {"dinner": None, "pickup": d["name"]}
                load[d["name"]] += j["workers"]
                task_count[d["name"]] += 1
                return True
            return False

        if try_pool(ot_list):
            continue
        if try_pool(staff_list):
            continue
        # last resort: force onto lightest OT even if verify fails (repair loop will move)
        fallback = [d for d in ot_list + staff_list if d["cap"] >= j["workers"]]
        fallback.sort(key=lambda d: task_count[d["name"]])
        if fallback:
            d = fallback[0]
            assignment[j["site_label"]] = {"dinner": None, "pickup": d["name"]}
            load[d["name"]] += j["workers"]
            task_count[d["name"]] += 1

    # ---- Shifts: prefer OT with light load (e.g. Pandi), one shift per driver when possible ----
    shift_drivers_used: Set[str] = set()
    for s in shifts:
        avoided = avoid_for_job.get(f"SHIFT:{s['from']}", set())
        placed = False
        # OT first (maximise OT / keep staff for pure pickups), lightest load, prefer unused for shifts
        for pool in (ot_list, staff_list):
            cands = [d for d in pool if d["name"] not in avoided]
            cands.sort(
                key=lambda d: (
                    0 if d["name"] not in shift_drivers_used else 1,
                    task_count[d["name"]],
                    load[d["name"]],
                )
            )
            for d in cands:
                trial_shifts = shift_assignment + [
                    {"from": s["from"], "to": s["to"], "driver": d["name"]}
                ]
                res = verify_schedule(
                    jobs, shifts, assignment, trial_shifts, fleet=ordered
                )
                if res.get(d["name"], {}).get("fail"):
                    continue
                shift_assignment.append(
                    {"from": s["from"], "to": s["to"], "driver": d["name"]}
                )
                load[d["name"]] += 2
                task_count[d["name"]] += 1
                shift_drivers_used.add(d["name"])
                placed = True
                break
            if placed:
                break
        if not placed and (ot_list or staff_list):
            d = (ot_list + staff_list)[0]
            shift_assignment.append(
                {"from": s["from"], "to": s["to"], "driver": d["name"]}
            )

    idle_ot = [d["name"] for d in ot_list if task_count[d["name"]] == 0]
    if idle_ot and jobs:
        cluster_notes.append(
            "ℹ️ Idle OT after packing (no feasible slot left): " + ", ".join(idle_ot)
        )
    busy = [f"{d['name']}={task_count[d['name']]} jobs" for d in ot_list]
    cluster_notes.append("OT load: " + ", ".join(busy))

    return assignment, shift_assignment, cluster_notes, load


def assign_and_verify(
    jobs: List[dict],
    shifts: List[dict],
    fleet: List[dict],
    max_iterations: int = 15,
):
    avoid_for_job: Dict[str, Set[str]] = {}
    iteration_log: List[str] = []
    results: Dict[str, dict] = {}
    assignment: Dict[str, dict] = {}
    shift_assignment: List[dict] = []
    cluster_notes: List[str] = []
    load: Dict[str, int] = {}

    for attempt in range(max_iterations):
        assignment, shift_assignment, cluster_notes, load = assign_drivers(
            jobs, shifts, fleet, avoid_for_job=avoid_for_job
        )
        results = verify_schedule(jobs, shifts, assignment, shift_assignment, fleet=fleet)
        failing = {d: r for d, r in results.items() if r["fail"]}

        if not failing:
            iteration_log.append(
                f"Attempt {attempt + 1}: all clear — verified feasible."
            )
            return (
                assignment,
                shift_assignment,
                cluster_notes,
                load,
                results,
                iteration_log,
            )

        moved = False
        for driver, res in failing.items():
            for task, timing, ok in res["log"]:
                if ok:
                    continue
                if task.startswith("Shift "):
                    frm = task[len("Shift ") :].split(" -> ")[0]
                    key = f"SHIFT:{frm}"
                elif task.startswith("PICKUP "):
                    key = task[len("PICKUP ") :].rsplit(" (", 1)[0]
                elif task.startswith("FOOD "):
                    key = task[len("FOOD ") :]
                else:
                    continue
                avoid_for_job.setdefault(key, set()).add(driver)
                moved = True
        iteration_log.append(
            f"Attempt {attempt + 1}: CONFLICT on {', '.join(sorted(failing))} — "
            "moving failing job(s) to another driver and re-verifying."
        )
        if not moved:
            iteration_log.append("No movable jobs left — stopping repair.")
            break

    iteration_log.append(
        f"Stopped after {max_iterations} repair attempts — remaining conflicts need manual check."
    )
    return assignment, shift_assignment, cluster_notes, load, results, iteration_log
