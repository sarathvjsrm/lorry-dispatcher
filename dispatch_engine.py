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

"""
Anderco evening dispatch engine — ONE-TIME brain rules (do not retune nightly)

1. OT first (names on Fleet_Drivers). Staff only if OT cannot cover.
2. Food only for sites ending >= 22:00; target arrive by 18:30 (hard 19:00).
3. Pickup: board ~2 min after end (Infotech scan short). Show HQ return time always.
4. After each pickup wave → HQ (drop workers at 3 Tuas View Circuit), then next wave.
   Exception: same end-time + nearby sites = one trip then HQ.
5. Shifts must finish before 19:00; prefer OT with NO food run (free 17:00–18:30).
6. Staff: independent timed sorties (no 5PM wait / no OT padding).
7. Balance OT jobs; location + capacity + timeline feasibility before assign.
"""

HQ_LAT = float(config.get("hq_lat", 1.2947675))
HQ_LON = float(config.get("hq_lon", 103.6345739))
EVENING_BUFFER_MIN = int(config.get("traffic_buffer_mins", 15))

# Food: only sites ending at or after this minute-of-day
DINNER_END_THRESHOLD = 22 * 60  # 22:00
DINNER_TARGET = 18 * 60 + 30    # 18:30
DINNER_HARD = 19 * 60           # 19:00

PICKUP_AFTER_END = 2  # workers board in ~2 min
PICKUP_HARD_EXTRA = 15  # soft buffer only for traffic          # absolute lateness allowed past deadline

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
                    # leave HQ early enough for from→to by 7PM (shifts often start ~5:30)
                    d1 = travel_from_hq(fi, evening=True) or 40
                    d2 = travel_min(
                        haversine_km(fi["lat"], fi["lon"], ti["lat"], ti["lon"]),
                        evening=True,
                    ) or 30
                    leave = t["deadline"] - d1 - d2 - 15
                    if leave < 17 * 60:
                        leave = 17 * 60
                    arrival = leave + d1 + d2
                    ok = arrival <= t["hard"]
                    if not ok:
                        fail = True
                    status = "OK" if arrival <= t["deadline"] else (
                        f"LATE by {arrival - t['deadline']}min" if not ok
                        else f"soft late {arrival - t['deadline']}min"
                    )
                    # return HQ after shift
                    back = travel_from_hq(ti, evening=True) or 30
                    hq_arrive = arrival + 3 + back
                    log.append(
                        (
                            f"Shift {t['label']}",
                            f"leave HQ ~{fmt_time(leave)} → arrive to-site {fmt_time(arrival)} "
                            f"(need by {fmt_time(t['deadline'])}) [{status}] → HQ ~{fmt_time(hq_arrive)}",
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
                leave = clock
                d1 = haversine_km(cur[0], cur[1], fi["lat"], fi["lon"])
                clock += (travel_min(d1) or 0) + 3  # load at from
                d2 = haversine_km(fi["lat"], fi["lon"], ti["lat"], ti["lon"])
                clock += travel_min(d2) or 0
                arrival = clock
                clock += 3  # unload at to
                # After shift, if next is not immediate pickup from 'to', return HQ
                nxt = tasks[i + 1] if i + 1 < len(tasks) else None
                back = travel_from_hq(ti, evening=True) or 30
                hq_arrive = clock + back
                clock = hq_arrive
                cur = (HQ_LAT, HQ_LON)
                ok = arrival <= t["hard"]
                if not ok:
                    fail = True
                status = "OK" if arrival <= t["deadline"] else f"LATE by {arrival - t['deadline']}min"
                log.append(
                    (
                        f"Shift {t['label']}",
                        f"leave ~{fmt_time(leave)} → arrive to-site {fmt_time(arrival)} "
                        f"(need by {fmt_time(t['deadline'])}) [{status}] → HQ ~{fmt_time(hq_arrive)}",
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
    return ot + staff


def assign_drivers(
    jobs: List[dict],
    shifts: List[dict],
    fleet: List[dict],
    avoid_for_job: Optional[Dict[str, Set[str]]] = None,
) -> Tuple[Dict[str, dict], List[dict], List[str], Dict[str, int]]:
    """Human logistics-manager style assignment.

    Priority order every night:
      1. Map sites by end-time + geography
      2. Food (>=22:00) → OT, nearby sites share one food run when feasible
      3. Shifts (before 7pm) → OT with no food run (free 5:00–6:30)
      4. Pickups → balance OT (equalish job count + pax), HQ between waves
      5. Staff only for leftover pickups (timed, no OT padding)
    """
    avoid_for_job = avoid_for_job or {}
    ordered = _ot_first(fleet)
    ot_list = [d for d in ordered if d.get("is_ot")]
    staff_list = [d for d in ordered if not d.get("is_ot")]

    assignment: Dict[str, dict] = {
        j["site_label"]: {"dinner": None, "pickup": None} for j in jobs
    }
    shift_assignment: List[dict] = []
    cluster_notes: List[str] = []
    load: Dict[str, int] = {d["name"]: 0 for d in ordered}
    task_count: Dict[str, int] = {d["name"]: 0 for d in ordered}
    dinner_used: Set[str] = set()

    def ot_balance_key(d):
        # Prefer fewer tasks then lighter pax — keeps OT evenings even
        return (task_count[d["name"]], load[d["name"]], d["name"])

    def can_take(driver_name: str, trial_assignment=None, trial_shifts=None) -> bool:
        a = trial_assignment if trial_assignment is not None else assignment
        sa = trial_shifts if trial_shifts is not None else shift_assignment
        res = verify_schedule(jobs, shifts, a, sa, fleet=ordered)
        return not res.get(driver_name, {}).get("fail", False)

    # ---------- Phase A: FOOD (OT only, balance) ----------
    dinner_jobs = [j for j in jobs if j.get("is_dinner")]
    other_jobs = [j for j in jobs if not j.get("is_dinner")]
    clusters = cluster_dinner_jobs(dinner_jobs)

    def try_food_cluster(cl, pool):
        avoided: Set[str] = set()
        for j in cl["jobs"]:
            avoided |= avoid_for_job.get(j["site_label"], set())
        cands = [
            d for d in pool
            if d["name"] not in avoided
            and d["name"] not in dinner_used
            and d["cap"] >= cl["workers"]
        ]
        cands.sort(key=ot_balance_key)
        for d in cands:
            trial = {k: dict(v) for k, v in assignment.items()}
            for j in cl["jobs"]:
                trial[j["site_label"]] = {"dinner": d["name"], "pickup": d["name"]}
            if not can_take(d["name"], trial_assignment=trial):
                continue
            dinner_used.add(d["name"])
            load[d["name"]] += cl["workers"]
            task_count[d["name"]] += 1
            for j in cl["jobs"]:
                assignment[j["site_label"]] = {"dinner": d["name"], "pickup": d["name"]}
            cluster_notes.append(
                f"[OT] {d['name']} ({d['vehicle']}, {d['type']}, cap {d['cap']}) → "
                + ", ".join(j["site_label"] for j in cl["jobs"])
                + f"  [{cl['workers']} pax food+pickup]"
            )
            return True
        return False

    for cl in clusters:
        if try_food_cluster(cl, ot_list):
            continue
        # split if combined fails
        if len(cl["jobs"]) > 1:
            cluster_notes.append(
                f"ℹ️ Split {cl['workers']} pax food cluster (combined route not feasible)"
            )
            for j in cl["jobs"]:
                sub = {"jobs": [j], "workers": j["workers"], "route_time": 0}
                if not try_food_cluster(sub, ot_list):
                    cluster_notes.append(
                        f"⚠️ NO OT for food {j['site_label']} ({j['workers']} pax)"
                    )
        else:
            cluster_notes.append(
                f"⚠️ NO OT for food cluster {cl['workers']} pax"
            )

    # ---------- Phase B: SHIFTS before 7pm ----------
    # Try to put ALL shifts on ONE free OT (no food) so other OT stay free for 7PM.
    free_ot = [d for d in ot_list if d["name"] not in dinner_used]
    free_ot.sort(key=lambda d: (task_count[d["name"]], load[d["name"]]))
    remaining_shifts = list(shifts)
    if free_ot and remaining_shifts:
        for d in free_ot:
            trial_sa = [
                {"from": s["from"], "to": s["to"], "driver": d["name"]}
                for s in remaining_shifts
            ]
            if can_take(d["name"], trial_shifts=trial_sa):
                for s in remaining_shifts:
                    shift_assignment.append(
                        {"from": s["from"], "to": s["to"], "driver": d["name"]}
                    )
                    cluster_notes.append(
                        f"Shift {s['from']} → {s['to']} → {d['name']}"
                    )
                load[d["name"]] += 2 * len(remaining_shifts)
                task_count[d["name"]] += len(remaining_shifts)
                remaining_shifts = []
                break
    # Leftover shifts one-by-one
    for s in remaining_shifts:
        avoided = avoid_for_job.get(f"SHIFT:{s['from']}", set())
        placed = False
        for pool in (
            [d for d in ot_list if d["name"] not in dinner_used],
            ot_list,
            staff_list,
        ):
            cands = [d for d in pool if d["name"] not in avoided]
            cands.sort(key=lambda d: (task_count[d["name"]], load[d["name"]]))
            for d in cands:
                trial_sa = shift_assignment + [
                    {"from": s["from"], "to": s["to"], "driver": d["name"]}
                ]
                if not can_take(d["name"], trial_shifts=trial_sa):
                    continue
                shift_assignment.append(
                    {"from": s["from"], "to": s["to"], "driver": d["name"]}
                )
                load[d["name"]] += 2
                task_count[d["name"]] += 1
                placed = True
                cluster_notes.append(
                    f"Shift {s['from']} → {s['to']} → {d['name']}"
                )
                break
            if placed:
                break
        if not placed:
            cluster_notes.append(
                f"⚠️ NO DRIVER for shift {s['from']} → {s['to']}"
            )

    # ---------- Phase C: remaining pickups — balance OT ----------
    # Jobs that still need a pickup driver
    pending = []
    for j in jobs:
        if j["end_min"] is None:
            continue
        a = assignment[j["site_label"]]
        if not a.get("pickup"):
            pending.append(j)
        # dinner-only already set pickup with dinner; skip

    # Sort: latest end first, then more workers (harder jobs first)
    pending.sort(key=lambda j: (-(j["end_min"] or 0), -(j["workers"] or 0)))

    for j in pending:
        avoided = avoid_for_job.get(j["site_label"], set())
        placed = False
        # OT first, balanced; then staff
        for pool, tag in ((ot_list, "OT"), (staff_list, "STAFF")):
            cands = [
                d for d in pool
                if d["name"] not in avoided and d["cap"] >= (j["workers"] or 0)
            ]
            cands.sort(key=ot_balance_key)
            for d in cands:
                trial = {k: dict(v) for k, v in assignment.items()}
                trial[j["site_label"]] = {
                    "dinner": trial[j["site_label"]].get("dinner"),
                    "pickup": d["name"],
                }
                if not can_take(d["name"], trial_assignment=trial):
                    continue
                assignment[j["site_label"]]["pickup"] = d["name"]
                load[d["name"]] += j["workers"] or 0
                task_count[d["name"]] += 1
                placed = True
                break
            if placed:
                break
        if not placed:
            cluster_notes.append(
                f"⚠️ NO DRIVER for pickup {j['site_label']} ({j['workers']} pax)"
            )

    # ---------- Phase D: fill idle OT with any staff-held job they can take ----------
    # Move work from staff → idle/light OT when feasible (maximise OT)
    staff_names = {d["name"] for d in staff_list}
    for j in jobs:
        a = assignment.get(j["site_label"]) or {}
        pk = a.get("pickup")
        if not pk or pk not in staff_names:
            continue
        # try lightest OT
        cands = [d for d in ot_list if d["cap"] >= (j["workers"] or 0)]
        cands.sort(key=ot_balance_key)
        for d in cands:
            trial = {k: dict(v) for k, v in assignment.items()}
            trial[j["site_label"]] = {
                "dinner": trial[j["site_label"]].get("dinner"),
                "pickup": d["name"],
            }
            if not can_take(d["name"], trial_assignment=trial):
                continue
            # also check staff is ok without this job (always ok)
            assignment[j["site_label"]]["pickup"] = d["name"]
            load[d["name"]] += j["workers"] or 0
            task_count[d["name"]] += 1
            load[pk] = max(0, load[pk] - (j["workers"] or 0))
            task_count[pk] = max(0, task_count[pk] - 1)
            cluster_notes.append(
                f"↩️ Moved {j['site_label']} from {pk} → OT {d['name']} (maximise OT)"
            )
            break

    # Summary note
    ot_summary = ", ".join(
        f"{d['name']}={task_count[d['name']]} jobs/{load[d['name']]} pax"
        for d in ot_list
    )
    cluster_notes.append(f"OT balance: {ot_summary}")
    idle = [d["name"] for d in ot_list if task_count[d["name"]] == 0]
    if idle:
        cluster_notes.append(f"ℹ️ Idle OT (no feasible slot): {', '.join(idle)}")

    return assignment, shift_assignment, cluster_notes, load


def assign_and_verify(
    jobs: List[dict],
    shifts: List[dict],
    fleet: List[dict],
    max_repairs: int = 12,
) -> Tuple[Dict[str, dict], List[dict], List[str], Dict[str, int], Dict[str, dict], List[str]]:
    """Assign then repair: move failing jobs off overloaded drivers and retry."""
    avoid: Dict[str, Set[str]] = {}
    log: List[str] = []
    assignment: Dict[str, dict] = {}
    shift_assignment: List[dict] = []
    cluster_notes: List[str] = []
    load: Dict[str, int] = {}
    results: Dict[str, dict] = {}

    for attempt in range(1, max_repairs + 1):
        assignment, shift_assignment, cluster_notes, load = assign_drivers(
            jobs, shifts, fleet, avoid_for_job=avoid
        )
        results = verify_schedule(
            jobs, shifts, assignment, shift_assignment, fleet=fleet
        )
        failing = [n for n, r in results.items() if r.get("fail")]
        if not failing:
            log.append(f"Attempt {attempt}: all clear — verified feasible.")
            break
        log.append(
            f"Attempt {attempt}: conflict on {', '.join(failing)} — "
            "moving failing job(s) off that driver and retrying."
        )
        # Mark jobs on failing drivers as avoid for them
        for j in jobs:
            a = assignment.get(j["site_label"]) or {}
            for role in ("dinner", "pickup"):
                dn = a.get(role)
                if dn in failing:
                    avoid.setdefault(j["site_label"], set()).add(dn)
        for s in shift_assignment:
            if s["driver"] in failing:
                avoid.setdefault(f"SHIFT:{s['from']}", set()).add(s["driver"])
        if attempt == max_repairs:
            log.append("Could not fully clear after repairs — see conflicts.")

    return assignment, shift_assignment, cluster_notes, load, results, log
