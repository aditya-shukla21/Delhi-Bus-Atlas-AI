"""Rebuild compact, population-wide demand checks from the supplied October ZIP."""
import argparse
import csv
import hashlib
import io
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from zipfile import ZipFile


def audit(source, destination):
    daily = defaultdict(Counter)
    hours = {group: Counter() for group in ("weekday", "weekend")}
    routes, starts, vehicles, types, group_sizes = set(), set(), set(), Counter(), Counter()
    days = {}
    rejected = Counter()
    raw_rows = 0
    with ZipFile(source) as archive:
        name, = [n for n in archive.namelist() if n.endswith("/October-Delhi.csv") and "__MACOSX" not in n]
        with archive.open(name) as raw:
            fingerprint = hashlib.file_digest(raw, "sha256").hexdigest()
        with archive.open(name) as raw:
            for row in csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")):
                raw_rows += 1
                stamp = row["created_at"]
                try:
                    count = int(row["passenger_count"])
                    if count < 1:
                        raise ValueError
                    if not stamp.endswith("+05:30"):
                        rejected["Unexpected UTC offset"] += 1
                        continue
                    day = stamp[:10]
                    hour = int(stamp[11:13])
                    if not 0 <= hour <= 23:
                        raise ValueError
                    if day not in days:
                        days[day] = "weekday" if date.fromisoformat(day).weekday() < 5 else "weekend"
                except ValueError:
                    rejected["Invalid count or timestamp"] += 1
                    continue
                profile = daily[day]
                profile["tickets"] += 1
                profile["passengers"] += count
                vehicle = row["vehicle_number"].strip()
                if vehicle.upper() in {"", "NULL"}:
                    profile["missing_vehicle"] += 1
                else:
                    vehicles.add(vehicle)
                routes.add(row["route"])
                starts.add(row["start_stop_name"])
                types[row["ticket_type_id"]] += 1
                group_sizes[count] += 1
                hours[days[day]][hour] += count
    day_counts = Counter(days.values())
    per_day = {
        group: [round(hours[group][hour] / day_counts[group], 2) for hour in range(24)]
        for group in day_counts
    }
    result = {
        "ticket_csv_sha256": fingerprint,
        "rows_read": raw_rows,
        "rejected_for_demand_profile": rejected,
        "route_labels_including_null": len(routes),
        "boarding_names_including_null": len(starts),
        "distinct_nonmissing_vehicle_labels": len(vehicles),
        "ticket_type_counts": types,
        "passenger_count_frequencies": group_sizes,
        "daily": dict(sorted(daily.items())),
        "days_by_type": day_counts,
        "mean_passengers_ticketed_per_day_by_ist_hour": per_day,
        "meaning": "Network-wide passenger counts by ticket issue time. These measure ticketing activity and do not identify individual bus loads.",
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"{raw_rows:,} rows checked across {len(days)} dates. Saved {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "data" / "demand_checks.json")
    args = parser.parse_args()
    audit(args.archive, args.out)
