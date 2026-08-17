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
ROUTE_TIME_BUDGET = 100         # max minutes for a dinner multi-stop loop from HQ

# OT drivers — preferred order (must work continuously)
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
    """Build fleet: OT drivers from sheet first (ordered), then Staff Driver N."""
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
            cap = _to_int(row[4], 14)
            sheet_drivers.append(
                {
                    "name": name,
                    "vehicle": vehicle,
                    "plate": str(row[2]).strip(),
                    "type": str(row[3]).strip() or "10ft",
                    "cap": cap,
                    "is_ot": name in OT_ORDER,
                }
            )

    # Order OT drivers as specified
    by_name = {d["name"]: d for d in sheet_drivers}
    fleet: List[dict] = []
    for ot_name in OT_ORDER:
        if ot_name in by_name:
            d = by_name[ot_name]
            d["is_ot"] = True
            fleet.append(d)
        else:
            # placeholder if missing from sheet — still prefer OT slot
            fleet.append(
                {
                    "name": ot_name,
                    "vehicle": "",
                    "plate": "",
                    "type": "14ft",
                    "cap": 25 if ot_name != "Senthil" else 14,
                    "is_ot": True,
                }
            )

    # Any other sheet drivers that are not OT -> treat as staff later
    used = {d["name"] for d in fleet}
    staff_n = 1
    for d in sheet_drivers:
        if d["name"] in used:
            continue
        # Rename historical staff names to Staff Driver N
        fleet.append(
            {
                "name": f"Staff Driver {staff_n}",
                "vehicle": d["vehicle"],
                "plate": d["plate"],
                "type": d["type"],
                "cap": d["cap"],
                "is_ot": False,
                "original_name": d["name"],
            }
        )
        staff_n += 1
        used.add(d["name"])

    # Fill remaining staff slots from defaults if needed
    existing_veh = {d["vehicle"] for d in fleet if d["vehicle"]}
    for s in DEFAULT_STAFF:
        if s["vehicle"] in existing_veh:
            continue
        if any(d["name"] == s["name"] for d in fleet):
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

def _ot_first(fleet: List[dict]) -> List[dict]:
    ot = [d for d in fleet if d.get("is_ot")]
    staff = [d for d in fleet if not d.get("is_ot")]
    # Keep OT in OT_ORDER
    ot_sorted = sorted(
        ot,
        key=lambda d: OT_ORDER.index(d["name"]) if d["name"] in OT_ORDER else 99,
    )
    return ot_sorted + staff


def assign_drivers(
    jobs: List[dict],
    shifts: List[dict],
    fleet: List[dict],
    avoid_for_job: Optional[Dict[str, Set[str]]] = None,
):
    avoid_for_job = avoid_for_job or {}
    ordered = _ot_first(fleet)
    load = {d["name"]: 0 for d in ordered}
    dinner_used: Set[str] = set()
    task_count = {d["name"]: 0 for d in ordered}
    assignment: Dict[str, dict] = {}
    cluster_notes: List[str] = []

    dinner_jobs = [j for j in jobs if j["is_dinner"]]
    other_jobs = [j for j in jobs if not j["is_dinner"]]
    clusters = cluster_dinner_jobs(dinner_jobs)

    def pick(
        need_cap: int,
        preferred_hist: Optional[str],
        avoided: Set[str],
        for_dinner: bool,
    ) -> Optional[dict]:
        """Prefer OT, then staff. Historical preference only if OT and free."""
        def ok(d):
            if d["name"] in avoided:
                return False
            if d["cap"] < need_cap:
                return False
            if for_dinner and d["name"] in dinner_used:
                return False
            return True

        # 1) historical driver if OT and eligible
        if preferred_hist:
            for d in ordered:
                if d["name"] == preferred_hist or (
                    preferred_hist and d["vehicle"] and d["vehicle"] in preferred_hist
                ):
                    if ok(d) and d.get("is_ot"):
                        return d

        # 2) lightest-load OT that fits
        ots = [d for d in ordered if d.get("is_ot") and ok(d)]
        if ots:
            ots.sort(key=lambda d: (task_count[d["name"]], load[d["name"]]))
            return ots[0]

        # 3) staff only if OT cannot cover
        staff = [d for d in ordered if not d.get("is_ot") and ok(d)]
        if staff:
            staff.sort(key=lambda d: (task_count[d["name"]], load[d["name"]]))
            return staff[0]
        return None

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

    # --- Dinner clusters (one driver per cluster) ---
    for cl in clusters:
        avoided: Set[str] = set()
        for j in cl["jobs"]:
            avoided |= avoid_for_job.get(j["site_label"], set())
        pref = None
        for j in cl["jobs"]:
            pref = hist_name(j)
            if pref:
                break
        chosen = pick(cl["workers"], pref, avoided, for_dinner=True)
        if not chosen:
            cluster_notes.append(
                "⚠️ NO DRIVER for "
                + f"{cl['workers']}-person cluster: "
                + ", ".join(j["site_label"] for j in cl["jobs"])
                + " (need capacity >= "
                + str(cl["workers"])
                + ")"
            )
            continue
        dinner_used.add(chosen["name"])
        load[chosen["name"]] += cl["workers"]
        task_count[chosen["name"]] += 1
        tag = "OT" if chosen.get("is_ot") else "STAFF"
        cluster_notes.append(
            f"[{tag}] {chosen['name']} ({chosen['vehicle']}, {chosen['type']}, "
            f"cap {chosen['cap']}) → "
            + ", ".join(j["site_label"] for j in cl["jobs"])
            + f"  [{cl['workers']} pax, ~{cl['route_time']} min food route]"
        )
        for j in cl["jobs"]:
            assignment[j["site_label"]] = {
                "dinner": chosen["name"],
                "pickup": chosen["name"],
            }

    # --- Non-dinner pickups (7PM / 9PM) ---
    # Sort: later ends first so tight windows get attention; group by area later in verify
    other_jobs_sorted = sorted(
        other_jobs, key=lambda j: -(j["end_min"] or 0)
    )
    for j in other_jobs_sorted:
        avoided = avoid_for_job.get(j["site_label"], set())
        pref = hist_name(j)
        chosen = pick(j["workers"], pref, avoided, for_dinner=False)
        if not chosen:
            chosen = ordered[-1]  # last resort
        load[chosen["name"]] += j["workers"]
        task_count[chosen["name"]] += 1
        assignment[j["site_label"]] = {"dinner": None, "pickup": chosen["name"]}

    # --- Shifts (before 7PM) — prefer staff / light OT ---
    shift_assignment = []
    for s in shifts:
        avoided = avoid_for_job.get(f"SHIFT:{s['from']}", set())
        # Prefer staff for shifts so OT stay free for evening pickups
        staff = [d for d in ordered if not d.get("is_ot") and d["name"] not in avoided]
        if staff:
            staff.sort(key=lambda d: load[d["name"]])
            chosen = staff[0]
        else:
            chosen = pick(1, None, avoided, for_dinner=False) or ordered[0]
        load[chosen["name"]] += 2
        shift_assignment.append(
            {"from": s["from"], "to": s["to"], "driver": chosen["name"]}
        )

    return assignment, shift_assignment, cluster_notes, load


# ---------------------------------------------------------------------------
# Verification — simulate with WAIT until pickup window
# ---------------------------------------------------------------------------

def verify_schedule(
    jobs: List[dict],
    shifts: List[dict],
    assignment: Dict[str, dict],
    shift_assignment: List[dict],
) -> Dict[str, dict]:
    """
    Simulate each driver's evening.

    Critical fix vs old engine:
      - Pickup: if the driver arrives early, they WAIT until end_time
        (workers are still working / scanning). "Arrive early" is OK;
        the timeline shows leave-HQ and planned pickup window.
      - Food still must arrive by 18:30.
    """
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
        # Sort: food first, then shifts, then pickups by end time
        def sort_key(t):
            if t["type"] == "Dinner":
                return (0, t["deadline"])
            if t["type"] == "Shift":
                return (1, t["deadline"])
            return (2, t["deadline"])

        tasks.sort(key=sort_key)
        cur = (HQ_LAT, HQ_LON)
        clock = 17 * 60  # earliest leave HQ ~ 5:00 PM
        log = []
        fail = False

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
                ok = arrival <= t["deadline"]
                if arrival > t["hard"]:
                    fail = True
                status = "OK" if ok else f"LATE by {arrival - t['deadline']}min"
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

            # Travel to site
            from_hq = (
                abs(cur[0] - HQ_LAT) < 0.001 and abs(cur[1] - HQ_LON) < 0.001
            )
            if from_hq:
                trav = travel_from_hq(info, evening=True)
            else:
                d = haversine_km(cur[0], cur[1], info["lat"], info["lon"])
                trav = travel_min(d, evening=True) or 40

            arrival = clock + trav

            if t["type"] == "Dinner":
                ok = arrival <= t["deadline"]
                if arrival > t["hard"]:
                    fail = True
                status = "OK" if ok else f"LATE by {arrival - t['deadline']}min"
                log.append(
                    (
                        f"FOOD {t['label']}",
                        f"leave ~{fmt_time(clock)} → arrive {fmt_time(arrival)} "
                        f"(need by {fmt_time(t['deadline'])}) [{status}]",
                        ok,
                    )
                )
                clock = arrival + 10
                cur = (info["lat"], info["lon"])
                continue

            # PICKUP — workers free only at end_min; driver waits if early
            end_min = t.get("end_min") or t["deadline"] - PICKUP_AFTER_END
            service_start = max(arrival, end_min)  # wait for workers if early
            pickup_done = service_start + PICKUP_AFTER_END  # scan + load
            ok = arrival <= t["deadline"]
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

            log.append((f"PICKUP {t['label']} ({t.get('workers', '?')} pax)", timing, ok))

            # After pickup: chain nearby same-band pickup, else return HQ
            nxt = tasks[i + 1] if i + 1 < len(tasks) else None
            chain = False
            if nxt and nxt["type"] == "Pickup" and nxt.get("info"):
                dd = haversine_km(
                    info["lat"], info["lon"], nxt["info"]["lat"], nxt["info"]["lon"]
                )
                if dd is not None and dd <= COMBINE_PICKUP_KM:
                    chain = True
            if chain:
                clock = pickup_done
                cur = (info["lat"], info["lon"])
            else:
                back = travel_from_hq(info, evening=True)
                clock = pickup_done + back
                cur = (HQ_LAT, HQ_LON)

        results[driver] = {"fail": fail, "log": log}
    return results


def assign_and_verify(
    jobs: List[dict],
    shifts: List[dict],
    fleet: List[dict],
    max_iterations: int = 8,
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
        results = verify_schedule(jobs, shifts, assignment, shift_assignment)
        failing = {d: r for d, r in results.items() if r["fail"]}

        if not failing:
            iteration_log.append(f"Attempt {attempt + 1}: all clear.")
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
                    # "PICKUP Label (N pax)"
                    key = task[len("PICKUP ") :].rsplit(" (", 1)[0]
                elif task.startswith("FOOD "):
                    key = task[len("FOOD ") :]
                else:
                    continue
                avoid_for_job.setdefault(key, set()).add(driver)
                moved = True
        iteration_log.append(
            f"Attempt {attempt + 1}: conflict on {', '.join(failing)} — "
            "moving failing job(s) off that driver and retrying."
        )
        if not moved:
            break

    iteration_log.append(
        f"Could not fully clear after {max_iterations} attempts — see conflicts."
    )
    return assignment, shift_assignment, cluster_notes, load, results, iteration_log
