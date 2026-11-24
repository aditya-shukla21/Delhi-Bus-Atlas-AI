"""Offline Delhi bus routing. Rebuild with: python routing.py build SOURCE.zip"""
import argparse
import csv
import io
import itertools
import json
import math
import os
import sqlite3
import tempfile
import threading
import zipfile
from bisect import bisect_left, bisect_right
from collections import defaultdict
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import date as Date, timedelta
from functools import lru_cache
from pathlib import Path


DATA = Path(__file__).resolve().parent / "data"
TIMETABLE = DATA / "timetable.sqlite"
CROWDING = DATA / "crowding.sqlite"
DAY = 86400
DEPART_WINDOW = 3600
MAX_TRANSFER_WAIT = 45 * 60
MIN_TRANSFER_WAIT = 2 * 60


@lru_cache(maxsize=150000)
def clock_seconds(text):
    h, m, s = map(int, text.split(":"))
    if h < 0 or not (0 <= m < 60 and 0 <= s < 60):
        raise ValueError(f"Invalid GTFS clock {text!r}")
    return h * 3600 + m * 60 + s


def load_feed(db, archive):
    with zipfile.ZipFile(archive) as source:
        prefix, = [n[:-len("calendar.txt")] for n in source.namelist()
                   if n.endswith("delhi_buses_static_gtfs_v1/calendar.txt")]

        @contextmanager
        def rows(name):
            with source.open(prefix + name + ".txt") as member:
                with io.TextIOWrapper(member, encoding="utf-8-sig", newline="") as stream:
                    yield csv.DictReader(stream)

        db.executescript("""
            CREATE TABLE stops(id TEXT PRIMARY KEY, name TEXT, lat REAL, lon REAL);
            CREATE TABLE calendar(service TEXT PRIMARY KEY, mask TEXT, start TEXT, end TEXT);
            CREATE TABLE patterns(route TEXT, agency TEXT, service TEXT, headsign TEXT,
                stops TEXT, arrivals TEXT, departures TEXT, starts TEXT);
            CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
        """)
        with rows("stops") as stops:
            db.executemany("INSERT INTO stops VALUES (?,?,?,?)", (
                (r["stop_id"], r["stop_name"], r["stop_lat"], r["stop_lon"]) for r in stops))
        with rows("calendar") as services:
            weekdays = "monday tuesday wednesday thursday friday saturday sunday".split()
            db.executemany("INSERT INTO calendar VALUES (?,?,?,?)", (
                (r["service_id"], "".join(r[d] for d in weekdays), r["start_date"], r["end_date"])
                for r in services))
        with rows("routes") as routes:
            buses = {r["route_id"]: (r["route_short_name"], r["agency_id"])
                     for r in routes if r["route_type"] == "3"}
        with rows("trips") as trips:
            trips_by_id = {r["trip_id"]: (*buses[r["route_id"]], r["service_id"], r["trip_headsign"])
                           for r in trips if r["route_id"] in buses}
        profiles = defaultdict(list)
        stop_times = 0
        with rows("stop_times") as times:
            for trip_id, group in itertools.groupby(times, lambda row: row["trip_id"]):
                # The supplied full feed groups all records for each trip contiguously.
                # pop detects an unexpected second block rather than splitting that trip.
                trip = trips_by_id.pop(trip_id)
                ordered = sorted(group, key=lambda row: int(row["stop_sequence"]))
                ids = tuple(row["stop_id"] for row in ordered)
                base = clock_seconds(ordered[0]["departure_time"])
                arrivals = tuple(clock_seconds(row["arrival_time"]) - base for row in ordered)
                departures = tuple(clock_seconds(row["departure_time"]) - base for row in ordered)
                if any(x > y for x, y in zip(arrivals, departures)) or any(
                        x > y for x, y in zip(departures, arrivals[1:])):
                    raise ValueError(f"Invalid chronological order for {trip_id}")
                profiles[(*trip, ids, arrivals, departures)].append(base)
                stop_times += len(ordered)
        if trips_by_id:
            raise ValueError(f"{len(trips_by_id)} bus trips lack stop times")
        for (route, agency, service, headsign, ids, arr, dep), starts in profiles.items():
            blobs = [json.dumps(seq, separators=(",", ":")) for seq in (ids, arr, dep, sorted(starts))]
            db.execute("INSERT INTO patterns VALUES (?,?,?,?,?,?,?,?)",
                       (route, agency, service, headsign, *blobs))
        counts = {"stop_times": stop_times, "patterns": len(profiles), "bus_routes": len(buses),
                  "bus_trips": sum(map(len, profiles.values()))}
        db.executemany("INSERT INTO metadata VALUES (?,?)", counts.items())
        return counts


def build(archive):
    DATA.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=DATA, delete=False) as scratch:
        path = Path(scratch.name)
    try:
        with closing(sqlite3.connect(path)) as db, db:
            counts = load_feed(db, archive)
        os.replace(path, TIMETABLE)
        return counts
    finally:
        path.unlink(missing_ok=True)


@dataclass
class Pattern:
    route: str
    agency: str
    service: str
    headsign: str
    stops: list
    arr: list
    dep: list
    starts: list


def read_only(path):
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


@lru_cache(maxsize=1)
def timetable():
    with closing(read_only(TIMETABLE)) as db:
        stops = {i: dict(id=i, name=n, lat=a, lon=b)
                 for i, n, a, b in db.execute("SELECT id,name,lat,lon FROM stops")}
        services = list(db.execute("SELECT service,mask,start,end FROM calendar"))
        by_stop = defaultdict(list)
        patterns = []
        last_clock = 0
        for route, agency, service, head, ids, arr, dep, starts in db.execute("SELECT * FROM patterns"):
            p = Pattern(route, agency, service, head, *map(json.loads, (ids, arr, dep, starts)))
            for i, stop in enumerate(p.stops):
                by_stop[stop].append((len(patterns), i))
            last_clock = max(last_clock, p.starts[-1] + p.arr[-1])
            patterns.append(p)
    return stops, services, patterns, by_stop, last_clock


def search_stops(query):
    text = str(query).strip().casefold()[:120]
    if not text:
        return []
    stops, _, _, by_stop, _ = timetable()
    matches = [s for s in stops.values() if s["id"] in by_stop and
               (s["id"] == text or text in s["name"].casefold())]
    matches.sort(key=lambda s: (s["id"] != text, s["name"].casefold() != text,
                                not s["name"].casefold().startswith(text), s["name"], s["id"]))
    return matches[:25]


def service_offsets(services, when, first_offset, last_offset):
    active = defaultdict(list)
    for shift in range(first_offset, last_offset + 1):
        try:
            day = when + timedelta(days=shift)
        except OverflowError:
            continue
        key = day.strftime("%Y%m%d")
        for service, mask, first, last in services:
            if first <= key <= last and mask[day.weekday()] == "1":
                active[service].append(shift * DAY)
    return active


def trip_starts(p, board, first, last, offsets):
    for offset in offsets:
        adjustment = p.dep[board] + offset
        lo = bisect_left(p.starts, first - adjustment)
        hi = bisect_right(p.starts, last - adjustment)
        for i in range(lo, hi):
            yield p.starts[i] + offset


def candidates(origin, destination, when, requested, window=DEPART_WINDOW):
    _, services, patterns, index, max_clock = timetable()
    active = service_offsets(services, when, -(max_clock // DAY),
                             (requested + window + max_clock + MAX_TRANSFER_WAIT) // DAY)
    # Only board the second bus at the very same GTFS stop ID.
    connections = defaultdict(list)
    for second_id, end in index[destination]:
        p = patterns[second_id]
        if not active[p.service]:
            continue
        for board in range(end):
            connections[p.stops[board]].append((second_id, board, end))

    # Retain the earliest arrival for a route sequence and boarding-time bucket.
    # This bounds repeated near-identical departures on frequent corridors.
    best = {}

    def keep(key, legs, arrival, departure):
        old = best.get(key)
        if old is None or (arrival, -departure) < old[:2]:
            best[key] = (arrival, -departure, legs)

    for first_id, board in index[origin]:
        p = patterns[first_id]
        for start in trip_starts(p, board, requested, requested + window, active[p.service]):
            departure = start + p.dep[board]
            bucket = departure // 900
            for end in range(board + 1, len(p.stops)):
                meet = p.stops[end]
                arrival = start + p.arr[end]
                leg = (first_id, board, end, start)
                if meet == destination:
                    keep((p.route, bucket), (leg,), arrival, departure)
                    break
                if meet == origin:
                    break
                for second_id, second_board, last in connections.get(meet, ()):
                    q = patterns[second_id]
                    # Some short workings of the same line can connect to a
                    # longer variant. Avoid a redundant reboarding only when
                    # the first bus itself continues to the destination.
                    if p.route == q.route and destination in p.stops[end:]:
                        continue
                    # A later departure on the same pattern can use another crowd bin.
                    # Keep the earliest connection in each 15-minute interval.
                    last_bucket = None
                    for second_start in trip_starts(q, second_board, arrival + MIN_TRANSFER_WAIT,
                                                   arrival + MAX_TRANSFER_WAIT, active[q.service]):
                        second_bucket = (second_start + q.dep[second_board]) // 900
                        if second_bucket == last_bucket:
                            continue
                        last_bucket = second_bucket
                        finish = second_start + q.arr[last]
                        keep((p.route, q.route, bucket, second_bucket),
                             (leg, (second_id, second_board, last, second_start)), finish, departure)
    direct, transfers = [], []
    for arrival, neg_departure, legs in sorted(best.values()):
        target = direct if len(legs) == 1 else transfers
        target.append((arrival, legs))
    # Score a range of route combinations before filling spare slots with other times.
    def shortlist(rows, limit):
        unique, repeats = [], []
        seen = set()
        for row in rows:
            routes = tuple(patterns[leg[0]].route for leg in row[1])
            (repeats if routes in seen else unique).append(row)
            seen.add(routes)
        return (unique + repeats)[:limit]
    return shortlist(direct, 160) + shortlist(transfers, 240)


_local = threading.local()


@lru_cache(maxsize=1024)
def crowd_profile(route, day, half_hour):
    if not hasattr(_local, "crowd"):
        _local.crowd = read_only(CROWDING)
    rows = _local.crowd.execute(
        """SELECT a,b,level,load,tickets,days,scheduled FROM crowd
           WHERE route=? AND day=? AND bin=? AND load IS NOT NULL
             AND tickets>=10 AND days>=3 AND scheduled>0
             AND level IN ('Low','Medium','High','Very High')""",
        (route, day, half_hour))
    return {(a, b): (level, load, tickets, dates, scheduled)
            for a, b, level, load, tickets, dates, scheduled in rows}


def show_time(seconds, *, round_up=False):
    if round_up:
        seconds = (seconds + 59) // 60 * 60
    day, clock = divmod(seconds, DAY)
    return f"{clock // 3600:02d}:{clock // 60 % 60:02d}" + (f" (+{day})" if day else "")


LEVELS = ("Low", "Medium", "High", "Very High")
DAY_TYPES = ("weekday",) * 5 + ("saturday", "sunday")


def crowd_period(weekday, seconds):
    day_offset, clock = divmod(seconds, DAY)
    return DAY_TYPES[(weekday + day_offset) % 7], clock // 1800


def score(legs, weekday, model_ready):
    _, _, patterns, _, _ = timetable()
    total = known = value = 0
    for pid, board, end, start in legs:
        p = patterns[pid]
        for j in range(board, end):
            depart = start + p.dep[j]
            weight = max(1, p.arr[j + 1] - p.dep[j])
            total += weight
            if not model_ready:
                continue
            day, half_hour = crowd_period(weekday, depart)
            row = crowd_profile(p.route, day, half_hour).get((p.stops[j], p.stops[j + 1]))
            if row:
                known += weight
                value += LEVELS.index(row[0]) * weight
    coverage = known / total
    # Ranking assumes the highest observed category on every unsupported segment.
    highest = len(LEVELS) - 1
    cost = (value + (total - known) * highest) / total
    level = LEVELS[min(highest, int(value / known + 0.5))] if coverage >= 0.5 else "Unknown"
    return cost, coverage, level


def render(legs, requested, arrival, weekday, coverage, level, model_ready):
    from route_map import leg_geometry
    stops, _, patterns, _, _ = timetable()
    details = []
    wait = 0
    previous = requested
    for pid, board, end, start in legs:
        p = patterns[pid]
        depart = start + p.dep[board]
        wait += depart - previous
        previous = start + p.arr[end]
        segments = []
        for j in range(board, end):
            a, b = p.stops[j:j + 2]
            seconds = start + p.dep[j]
            day, half_hour = crowd_period(weekday, seconds)
            profile = crowd_profile(p.route, day, half_hour) if model_ready else {}
            category, load, tickets, days, scheduled = profile.get((a, b), ("Unknown", None, None, None, None))
            segments.append(dict(a=a, b=b, from_name=stops[a]["name"], to_name=stops[b]["name"],
                                 level=category, load=load, tickets=tickets, days=days, scheduled=scheduled,
                                 day_type=day, bin=half_hour,
                                 departure=show_time(seconds)))
        details.append(dict(route=p.route, agency=p.agency, headsign=p.headsign,
                            origin=stops[p.stops[board]]["name"], destination=stops[p.stops[end]]["name"],
                            origin_id=p.stops[board], destination_id=p.stops[end],
                            departure=show_time(depart), arrival=show_time(previous, round_up=True),
                            geometry=leg_geometry(p.route, p.stops[board:end + 1], data_dir=DATA),
                            stops=end - board, segments=segments))
    return dict(departure=details[0]["departure"], arrival=show_time(arrival, round_up=True),
                duration_min=math.ceil((arrival - requested) / 60), wait_min=math.ceil(wait / 60),
                transfers=len(legs) - 1, level=level, coverage=coverage, legs=details)


@dataclass
class Choice:
    arrival: int
    legs: tuple
    routes: tuple
    cost: float
    coverage: float
    level: str

    def departure(self):
        pid, board, _, start = self.legs[0]
        return start + timetable()[2][pid].dep[board]

    def fast_key(self):
        return self.arrival, len(self.legs), self.cost, -self.coverage, self.legs

    def comfort_key(self):
        return self.coverage < 0.5, self.cost, -self.coverage, self.arrival, len(self.legs), self.legs


def comparisons(choices):
    if not choices:
        return []
    fastest = min(choices, key=Choice.fast_key)
    comfortable = min(choices, key=Choice.comfort_key)
    selected = [fastest]
    if comfortable != fastest:
        selected.append(comfortable)
    # Balance the remaining time and crowd penalties relative to the two
    # endpoints. Floors also give a stable ordering when the endpoints tie.
    time_span = max(60, comfortable.arrival - fastest.arrival)
    cost_span = max(0.1, abs(fastest.cost - comfortable.cost))

    def middle_key(option):
        extra_time = (option.arrival - fastest.arrival) / time_span
        extra_cost = max(0, option.cost - comfortable.cost) / cost_span
        return (option.coverage < 0.5, max(extra_time, extra_cost), extra_time + extra_cost,
                len(option.legs), option.fast_key())

    for option in sorted(choices, key=middle_key):
        if any((option.routes, option.level) == (prior.routes, prior.level) for prior in selected):
            continue
        selected.append(option)
        if len(selected) == 3:
            break
    return selected


def inputs(origin, destination, date, time, preference):
    stops = timetable()[0]
    origin, destination = str(origin), str(destination)
    if origin not in stops or destination not in stops:
        raise ValueError("Select both stops from the timetable.")
    if origin == destination:
        raise ValueError("Choose two different stops.")
    when = Date.fromisoformat(date)
    if len(time) != 5 or time[2] != ":" or not (time[:2] + time[3:]).isdigit():
        raise ValueError("Use a 24-hour time such as 08:30.")
    requested = clock_seconds(time + ":00")
    if requested >= DAY:
        raise ValueError("Hour must be between 00 and 23.")
    value = {"fast": "0", "comfort": "100"}.get(str(preference), str(preference))
    if not value.isascii() or not value.isdigit() or len(value) > 3 or int(value) > 100:
        raise ValueError("Choose a comfort preference from 0 to 100.")
    return origin, destination, when, requested, int(value)


@lru_cache(maxsize=32)
def choices_at(origin, destination, when, requested, window):
    rows = candidates(origin, destination, when, requested, window)
    patterns = timetable()[2]
    model_ready = CROWDING.is_file()
    choices = []
    weekday = when.weekday()
    for arrival, legs in rows:
        cost, coverage, level = score(legs, weekday, model_ready)
        routes = tuple(patterns[leg[0]].route for leg in legs)
        choices.append(Choice(arrival, legs, routes, cost, coverage, level))
    return choices


def ranked_comparisons(choices, preference):
    selected = comparisons(choices)
    if not selected:
        return []
    fast = sorted(selected, key=Choice.fast_key)
    comfortable = sorted(selected, key=Choice.comfort_key)
    # A four-point penalty places every option below 50% coverage behind
    # supported options when the slider is set to maximum comfort.
    costs = [c.cost + (4 if c.coverage < .5 else 0) for c in selected]
    duration_span = max(1, fast[-1].arrival - fast[0].arrival)
    cost_span = max(1e-9, max(costs) - min(costs))
    weight = preference / 100
    ranked = []
    for choice, cost in zip(selected, costs):
        t = (choice.arrival - fast[0].arrival) / duration_span
        c = (cost - min(costs)) / cost_span
        ranks = dict(crowd_cost=choice.cost, time_score=t, comfort_score=c,
                     time_rank=fast.index(choice), comfort_rank=comfortable.index(choice))
        tie = ranks["time_rank" if preference < 50 else "comfort_rank"]
        ranked.append(((1 - weight) * t + weight * c, tie, choice, ranks))
    return [(choice, ranks) for _, _, choice, ranks in sorted(ranked, key=lambda row: row[:2])]


def plan(origin, destination, date, time, preference="fast"):
    a, b, when, requested, value = inputs(origin, destination, date, time, preference)
    model_ready = CROWDING.is_file()
    options = []
    for c, ranks in ranked_comparisons(choices_at(a, b, when, requested, DEPART_WINDOW), value):
        option = render(c.legs, requested, c.arrival, when.weekday(), c.coverage, c.level, model_ready)
        options.append({**option, **ranks})
    message = ""
    if not options:
        message = ("No direct or same-stop one-transfer option departs within the next hour. "
                   "Check the stop direction, departure time or service date.")
    elif not model_ready:
        message = "Crowding estimates are unavailable."
    return dict(options=options, message=message)


def local_iso(when, seconds):
    days, clock = divmod(seconds, DAY)
    adjusted = when + timedelta(days=days)
    return f"{adjusted.isoformat()}T{clock // 3600:02d}:{clock // 60 % 60:02d}:{clock % 60:02d}+05:30"


def summary(choice, when, requested):
    return dict(routes=list(choice.routes), departure=show_time(choice.departure()),
                arrival=show_time(choice.arrival, round_up=True),
                duration_min=math.ceil((choice.arrival - requested) / 60),
                level=choice.level, coverage=choice.coverage, crowd_cost=choice.cost,
                departure_iso=local_iso(when, choice.departure()), arrival_iso=local_iso(when, choice.arrival))


def advice(origin, destination, date, time, preference="fast"):
    a, b, when, requested, value = inputs(origin, destination, date, time, preference)
    base = ranked_comparisons(choices_at(a, b, when, requested, DEPART_WINDOW), value)
    if not base:
        return dict(baseline=None, windows=[], recommendation=None, message="No baseline journey is available.")
    baseline = base[0][0]
    windows = []
    first_pattern, _, _, first_start = baseline.legs[0]
    for offset in (10, 20, 30):
        start = requested + offset * 60
        candidates_later = [c for c in choices_at(a, b, when, start, 599)
                            if c.departure() > baseline.departure()
                            and (c.legs[0][0], c.legs[0][3]) != (first_pattern, first_start)]
        qualifying = [c for c in candidates_later if baseline.coverage >= 0.75 and c.coverage >= 0.75
                      and LEVELS.index(c.level) < LEVELS.index(baseline.level)
                      and c.cost < baseline.cost and c.arrival <= baseline.arrival + 15 * 60]
        selected = ranked_comparisons(qualifying or candidates_later, value)
        alternative = selected[0][0] if selected else None
        if alternative is None:
            reason = "No distinct later departure in this ten-minute window."
        elif min(baseline.coverage, alternative.coverage) < .75:
            reason = "Crowding coverage is below 75% on at least one journey."
        elif qualifying:
            reason = "Lower predicted crowd band with at least 75% coverage on both journeys."
        else:
            reason = "No supported lower crowd band within 15 minutes of the original arrival."
        day_offset, clock = divmod(start, DAY)
        windows.append(dict(offset_min=offset, date=(when + timedelta(days=day_offset)).isoformat(),
                            time=show_time(clock), alternative=summary(alternative, when, start) if alternative else None,
                            arrival_delta_min=(math.ceil(alternative.arrival / 60) - math.ceil(baseline.arrival / 60)
                                               if alternative else None),
                            qualifies=bool(qualifying), reason=reason))
    recommendation = min((w for w in windows if w["qualifies"]),
                         key=lambda w: (w["alternative"]["arrival_iso"], w["alternative"]["crowd_cost"]), default=None)
    message = "A later departure has a lower estimated crowd band." if recommendation else "No supported leave-later improvement in the three windows."
    return dict(baseline=summary(baseline, when, requested), windows=windows,
                recommendation=recommendation, message=message)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build"])
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.archive), indent=2))
