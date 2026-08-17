"""
dispatch_engine.py - pure, testable scheduling logic.
No Streamlit, no gspread here - just real geography and real time math,
so it can be unit-tested without a live Google Sheets connection.
"""
import json
import math

with open("config.json", "r") as f:
    config = json.load(f)

HQ_LAT = config.get("hq_lat", 1.2947675)
HQ_LON = config.get("hq_lon", 103.6345739)
EVENING_BUFFER_MIN = config.get("traffic_buffer_mins", 15)
DINNER_TARGET_MIN = 18 * 60 + 30
DINNER_HARD_CUTOFF_MIN = 19 * 60
PICKUP_BUFFER_MIN = 10
COMBINE_KM = 7.0
CLUSTER_KM = 8.0
ROUTE_TIME_BUDGET_MIN = 120

STAFF_POOL = [
    {"name": "Saravanan", "vehicle": "5546", "type": "10ft", "cap": 14},
    {"name": "Tianwei",   "vehicle": "3576", "type": "14ft", "cap": 25},
    {"name": "Ramesh",    "vehicle": "6897", "type": "10ft", "cap": 14},
]

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


def _to_minutes(t):
    """Accepts '22:00', '21:00:00', '10:00 PM', or similar; returns minutes
    since midnight."""
    t = str(t).strip()
    if not t:
        return None
    t = t.upper().replace(" ", "")
    pm = "PM" in t
    am = "AM" in t
    t = t.replace("PM", "").replace("AM", "")
    if ":" not in t:
        return None
    try:
        parts = t.split(":")
        h, m = int(parts[0]), int(parts[1])  # ignore seconds if present
    except Exception:
        return None
    if pm and h != 12:
        h += 12
    if am and h == 12:
        h = 0
    return h * 60 + m


def parse_site_database(raw_rows):
    """Site_Database sheet layout (as built): row1=title, row2=note, row3=headers,
    row4+=data. Columns: A=Code B=Company C=SiteName D=Address E=Driver
    F=VehCode G=Lorry H=TravelMin I=TravelSource J=Lat K=Lon L=MapsLink
    M=Confidence N=DisplayLabel
    """
    header_idx = None
    for i, row in enumerate(raw_rows):
        if len(row) > 0 and row[0].strip() == "PJC Code":
            header_idx = i
            break
    if header_idx is None:
        return {}
    sites = {}
    for row in raw_rows[header_idx + 1:]:
        if not row or not row[0].strip():
            continue
        row = row + [""] * (14 - len(row))
        code = row[0].strip()
        lat = _to_float(row[9])
        lon = _to_float(row[10])
        travel_min = _to_float(row[7])
        sites[code] = {
            "code": code,
            "company": row[1].strip(),
            "name": row[2].strip(),
            "address": row[3].strip(),
            "driver": row[4].strip(),
            "vehicle": row[5].strip(),
            "lorry": row[6].strip(),
            "travel_hq_min": travel_min,
            "lat": lat,
            "lon": lon,
            "label": row[13].strip() or (row[2].strip() + " [" + code + "]"),
        }
    return sites


def parse_fleet(raw_rows):
    header_idx = None
    for i, row in enumerate(raw_rows):
        if len(row) > 0 and row[0].strip() == "Driver No.":
            header_idx = i
            break
    if header_idx is None:
        return []
    fleet = []
    for row in raw_rows[header_idx + 1:]:
        if not row or not row[0].strip():
            continue
        row = row + [""] * (6 - len(row))
        cap = _to_int(row[4], 14)
        vehicle = str(row[1]).strip()
        if vehicle.endswith(".0"):
            vehicle = vehicle[:-2]
        fleet.append({
            "name": row[0].strip(),
            "vehicle": vehicle,
            "plate": row[2].strip(),
            "type": row[3].strip() or "10ft",
            "cap": cap,
        })
    existing_vehicles = {d["vehicle"] for d in fleet}
    for s in STAFF_POOL:
        if s["vehicle"] not in existing_vehicles:
            fleet.append({
                "name": s["name"], "vehicle": s["vehicle"], "plate": "",
                "type": s["type"], "cap": s["cap"],
            })
    return fleet


def parse_daily_ops(raw_rows, site_lookup):
    """Finds the 'Site / Shift End Time / Workers / ...' table and the
    'From Site / To Site / Driver' shifting table."""
    sec1_start = None
    sec2_start = None
    for i, row in enumerate(raw_rows):
        if len(row) > 1 and row[0].strip() == "Site" and row[1].strip() == "Shift End Time":
            sec1_start = i + 1
        if len(row) > 1 and row[0].strip() == "From Site" and row[1].strip() == "To Site":
            sec2_start = i + 1

    jobs = []
    if sec1_start is not None:
        for row in raw_rows[sec1_start:]:
            if not row or not row[0].strip():
                break
            if row[0].strip().startswith("SHIFTING") or row[0].strip().startswith("Click here"):
                break
            site_label = row[0].strip()
            end_min = _to_minutes(row[1]) if len(row) > 1 else None
            workers = _to_int(row[2]) if len(row) > 2 else 0
            info = resolve_site(site_label, site_lookup)
            jobs.append({
                "site_label": site_label,
                "end_min": end_min,
                "workers": workers,
                "info": info,
                "is_dinner": end_min is not None and end_min >= 21 * 60 + 30,
            })

    shifts = []
    if sec2_start is not None:
        for row in raw_rows[sec2_start:]:
            if not row or not row[0].strip():
                break
            if row[0].strip().startswith("Click here"):
                break
            frm = row[0].strip()
            to = row[1].strip() if len(row) > 1 else ""
            frm_info = resolve_site(frm, site_lookup)
            to_info = resolve_site(to, site_lookup)
            if frm_info and to_info:
                shifts.append({"from": frm, "to": to, "from_info": frm_info, "to_info": to_info})
    return jobs, shifts


def resolve_site(label, site_lookup):
    """Flexible match: exact display label, exact code, code substring,
    then fuzzy name substring - mirrors the Apps Script _lookupSite logic."""
    label = label.strip()
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


# =====================================================================
# REAL GEOGRAPHY / TIME ENGINE
# =====================================================================
def haversine_km(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return None
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def travel_min(dist_km, evening=True):
    if dist_km is None:
        return None
    base = dist_km * 2 + 10
    return round(base + EVENING_BUFFER_MIN) if evening else round(base)


def fmt_time(m):
    m = int(m) % 1440
    h, mi = divmod(m, 60)
    ap = "PM" if h >= 12 else "AM"
    h12 = h % 12 or 12
    return f"{h12}:{mi:02d} {ap}"


def route_time(points):
    """Nearest-neighbour route from HQ through all (lat,lon) points,
    including a 5-min unload per stop. Real drive-time estimate."""
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


# =====================================================================
# SCHEDULING ENGINE (deterministic - this is the actual "brain")
# =====================================================================
def cluster_dinner_jobs(dinner_jobs):
    """Union-find clustering of 10PM sites: merge only if within CLUSTER_KM,
    combined workers fit a 25-seat lorry, AND the real nearest-neighbour
    route time stays inside ROUTE_TIME_BUDGET_MIN. This is the fix for
    clusters that look fine on distance/capacity alone but are physically
    undriveable in the food-delivery window."""
    idxs = list(range(len(dinner_jobs)))
    parent = {i: i for i in idxs}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def members(root):
        return [i for i in idxs if find(i) == root]

    for a in range(len(dinner_jobs)):
        for b in range(a + 1, len(dinner_jobs)):
            ja, jb = dinner_jobs[a], dinner_jobs[b]
            if not ja["info"] or not jb["info"]:
                continue
            d = haversine_km(ja["info"]["lat"], ja["info"]["lon"], jb["info"]["lat"], jb["info"]["lon"])
            if d is None or d > CLUSTER_KM:
                continue
            ra, rb = find(a), find(b)
            if ra == rb:
                continue
            merged_idx = members(ra) + members(rb)
            total_workers = sum(dinner_jobs[i]["workers"] for i in merged_idx)
            if total_workers > 25:
                continue
            pts = [(dinner_jobs[i]["info"]["lat"], dinner_jobs[i]["info"]["lon"]) for i in merged_idx]
            if route_time(pts) > ROUTE_TIME_BUDGET_MIN:
                continue
            parent[rb] = ra

    groups = {}
    for i in idxs:
        r = find(i)
        groups.setdefault(r, []).append(i)

    clusters = []
    for members_idx in groups.values():
        jobs = [dinner_jobs[i] for i in members_idx]
        pts = [(j["info"]["lat"], j["info"]["lon"]) for j in jobs]
        clusters.append({
            "jobs": jobs,
            "workers": sum(j["workers"] for j in jobs),
            "route_time": route_time(pts),
        })
    clusters.sort(key=lambda c: -c["workers"])
    return clusters


def assign_drivers(jobs, shifts, fleet, avoid_for_job=None):
    """Balances load across the fleet - prefers each site's historical
    driver when capacity AND current load allow, otherwise picks whichever
    eligible driver currently has the LEAST load (so the same driver isn't
    hammered every night), and only reaches into the staff/backup pool if
    the primary roster genuinely can't cover a job.

    avoid_for_job: optional {site_label: set(driver_names_to_avoid)} used by
    the repair loop in assign_and_verify() to steer a specific conflicting
    job away from an overloaded driver on the next attempt.
    """
    avoid_for_job = avoid_for_job or {}

    def driver_for_history(hist_str):
        if not hist_str:
            return None
        for d in fleet:
            if d["vehicle"] and d["vehicle"] in hist_str:
                return d
            if d["name"] and d["name"].lower() in hist_str.lower():
                return d
        return None

    load = {d["name"]: 0 for d in fleet}
    dinner_used = set()
    assignment = {}

    dinner_jobs = [j for j in jobs if j["is_dinner"]]
    other_jobs = [j for j in jobs if not j["is_dinner"]]

    clusters = cluster_dinner_jobs(dinner_jobs)
    cluster_notes = []

    for cl in clusters:
        avoided = set()
        for j in cl["jobs"]:
            avoided |= avoid_for_job.get(j["site_label"], set())

        pref = None
        for j in cl["jobs"]:
            hist = driver_for_history(j["info"]["driver"] if j["info"] else "")
            if (hist and hist["cap"] >= cl["workers"] and hist["name"] not in dinner_used
                    and hist["name"] not in avoided):
                pref = hist
                break
        if pref:
            chosen = pref
        else:
            candidates = [d for d in fleet if d["cap"] >= cl["workers"]
                          and d["name"] not in dinner_used and d["name"] not in avoided]
            candidates.sort(key=lambda d: load[d["name"]])
            chosen = candidates[0] if candidates else None

        if not chosen:
            cluster_notes.append(f"⚠️ NO DRIVER AVAILABLE for {cl['workers']}-person cluster: "
                                  + ", ".join(j["site_label"] for j in cl["jobs"]))
            continue

        dinner_used.add(chosen["name"])
        load[chosen["name"]] += cl["workers"]
        tight = " (tight - lands close to 7PM cutoff)" if cl["route_time"] > 90 else ""
        cluster_notes.append(
            f"{chosen['name']} ({chosen['vehicle']}, {chosen['type']}) -> "
            + ", ".join(j["site_label"] for j in cl["jobs"])
            + f" [{cl['workers']} pax, {cl['route_time']}min route{tight}]"
        )
        for j in cl["jobs"]:
            assignment[j["site_label"]] = {"dinner": chosen["name"], "pickup": chosen["name"]}

    # LOAD-AWARE task limit: a driver already carrying 2+ pickup jobs is
    # skipped for historical preference (this is what prevents one driver
    # silently absorbing every job that happens to be "their" territory -
    # the exact overload pattern this engine exists to catch).
    task_count = {d["name"]: 0 for d in fleet}
    for j in other_jobs:
        avoided = avoid_for_job.get(j["site_label"], set())
        hist = driver_for_history(j["info"]["driver"] if j["info"] else "")
        use_hist = (hist and hist["cap"] >= j["workers"] and hist["name"] not in avoided
                    and task_count[hist["name"]] < 2)
        if use_hist:
            chosen = hist
        else:
            candidates = [d for d in fleet if d["cap"] >= j["workers"] and d["name"] not in avoided]
            candidates.sort(key=lambda d: (task_count[d["name"]], load[d["name"]]))
            chosen = candidates[0] if candidates else fleet[0]
        load[chosen["name"]] += j["workers"]
        task_count[chosen["name"]] += 1
        assignment[j["site_label"]] = {"dinner": None, "pickup": chosen["name"]}

    shift_assignment = []
    for s in shifts:
        avoided = avoid_for_job.get(f"SHIFT:{s['from']}", set())
        candidates = [d for d in fleet if d["name"] not in avoided]
        candidates.sort(key=lambda d: load[d["name"]])
        chosen = candidates[0] if candidates else fleet[0]
        load[chosen["name"]] += 2
        shift_assignment.append({"from": s["from"], "to": s["to"], "driver": chosen["name"]})

    return assignment, shift_assignment, cluster_notes, load


def assign_and_verify(jobs, shifts, fleet, max_iterations=6):
    """Runs assign_drivers(), verifies the result, and if any driver comes
    back with a real conflict, steers the specific failing job away from
    that driver and tries again - this is the actual 'try a different
    driver, or fall back to a staff driver' behaviour, done automatically
    instead of just reporting a broken schedule."""
    avoid_for_job = {}
    iteration_log = []

    for attempt in range(max_iterations):
        assignment, shift_assignment, cluster_notes, load = assign_drivers(
            jobs, shifts, fleet, avoid_for_job=avoid_for_job
        )
        results = verify_schedule(jobs, shifts, assignment, shift_assignment)
        failing = {d: r for d, r in results.items() if r["fail"]}

        if not failing:
            iteration_log.append(f"Attempt {attempt + 1}: all clear.")
            return assignment, shift_assignment, cluster_notes, load, results, iteration_log

        moved_any = False
        for driver, res in failing.items():
            for task, timing, ok in res["log"]:
                if ok:
                    continue
                # task looks like "Pickup SITE_LABEL" / "Dinner SITE_LABEL" / "Shift A -> B"
                if task.startswith("Shift "):
                    frm = task[len("Shift "):].split(" -> ")[0]
                    key = f"SHIFT:{frm}"
                elif task.startswith("Pickup "):
                    key = task[len("Pickup "):]
                elif task.startswith("Dinner "):
                    key = task[len("Dinner "):]
                else:
                    continue
                avoid_for_job.setdefault(key, set()).add(driver)
                moved_any = True
        iteration_log.append(
            f"Attempt {attempt + 1}: conflict on {', '.join(failing.keys())} - "
            f"steering the offending job(s) to a different driver and retrying."
        )
        if not moved_any:
            break

    # Ran out of attempts - return the last result honestly, don't hide it
    iteration_log.append(f"Could not fully resolve after {max_iterations} attempts - "
                          "see remaining conflicts below.")
    return assignment, shift_assignment, cluster_notes, load, results, iteration_log


def verify_schedule(jobs, shifts, assignment, shift_assignment):
    """The real safety net: simulate every driver's whole evening with real
    travel times and flag anything that doesn't physically fit."""
    driver_tasks = {}
    for j in jobs:
        a = assignment.get(j["site_label"])
        if not a or not j["info"]:
            continue
        if a["dinner"]:
            driver_tasks.setdefault(a["dinner"], []).append(
                {"type": "Dinner", "label": j["site_label"], "info": j["info"],
                 "deadline": DINNER_TARGET_MIN, "hard": DINNER_HARD_CUTOFF_MIN})
        if a["pickup"] and j["end_min"] is not None:
            driver_tasks.setdefault(a["pickup"], []).append(
                {"type": "Pickup", "label": j["site_label"], "info": j["info"],
                 "deadline": j["end_min"] + PICKUP_BUFFER_MIN,
                 "hard": j["end_min"] + PICKUP_BUFFER_MIN + 15})

    shift_lookup = {s["from"]: s for s in shifts}
    for s in shift_assignment:
        sinfo = shift_lookup.get(s["from"])
        driver_tasks.setdefault(s["driver"], []).append({
            "type": "Shift", "label": f"{s['from']} -> {s['to']}",
            "from_info": sinfo["from_info"] if sinfo else None,
            "to_info": sinfo["to_info"] if sinfo else None,
            "deadline": 19 * 60, "hard": 19 * 60 + 15,
        })

    results = {}
    for driver, tasks in driver_tasks.items():
        tasks.sort(key=lambda t: t["deadline"])
        cur = (HQ_LAT, HQ_LON)
        clock = 17 * 60
        log = []
        fail = False
        for i, t in enumerate(tasks):
            if t["type"] == "Shift":
                fi, ti = t.get("from_info"), t.get("to_info")
                if not fi or not ti:
                    log.append((t["label"], "site not found", False))
                    fail = True
                    continue
                d1 = haversine_km(cur[0], cur[1], fi["lat"], fi["lon"])
                clock += (travel_min(d1) or 0) + 5
                d2 = haversine_km(fi["lat"], fi["lon"], ti["lat"], ti["lon"])
                clock += (travel_min(d2) or 0)
                arrival = clock
                clock += 5
                cur = (ti["lat"], ti["lon"])
                ok = arrival <= t["deadline"]
                if arrival > t["hard"]:
                    fail = True
                log.append((f"Shift {t['label']}", f"arrive {fmt_time(arrival)} (need {fmt_time(t['deadline'])})", ok))
                continue

            info = t["info"]
            if not info or info["lat"] is None:
                log.append((t["label"], "site coordinates missing", False))
                fail = True
                continue
            d = haversine_km(cur[0], cur[1], info["lat"], info["lon"])
            trav = travel_min(d)
            arrival = clock + trav
            ok = arrival <= t["deadline"]
            if arrival > t["hard"]:
                fail = True
            log.append((f"{t['type']} {t['label']}", f"arrive {fmt_time(arrival)} (need {fmt_time(t['deadline'])})", ok))

            if t["type"] == "Dinner":
                clock = arrival + 10
                cur = (info["lat"], info["lon"])
            else:
                nxt = tasks[i + 1] if i + 1 < len(tasks) else None
                combine = False
                if nxt and nxt["type"] == "Pickup" and nxt.get("info"):
                    dd = haversine_km(info["lat"], info["lon"], nxt["info"]["lat"], nxt["info"]["lon"])
                    if dd is not None and dd <= COMBINE_KM:
                        combine = True
                if combine:
                    clock = arrival + 10
                    cur = (info["lat"], info["lon"])
                else:
                    back = travel_min(haversine_km(info["lat"], info["lon"], HQ_LAT, HQ_LON))
                    clock = arrival + 10 + (back or 0)
                    cur = (HQ_LAT, HQ_LON)

        results[driver] = {"fail": fail, "log": log}
    return results


