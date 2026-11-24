"""Look up a route's directed edge by local traversal date and time."""
import argparse
import datetime as dt
import json
from pathlib import Path
import pyarrow.dataset as ds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route", required=True)
    parser.add_argument("--from-stop", required=True)
    parser.add_argument("--to-stop", required=True)
    parser.add_argument("--date", required=True, type=dt.date.fromisoformat)
    parser.add_argument("--time", required=True, type=dt.time.fromisoformat)
    parser.add_argument("--grid", type=Path, default=Path(__file__).parent / "artifacts" / "crowd_grid.parquet")
    args = parser.parse_args()
    daytype = ("weekday", "saturday", "sunday")[max(0, args.date.weekday()-4)]
    half = args.time.hour*2 + args.time.minute//30
    filters = ((ds.field("route_short_name") == args.route) &
               (ds.field("from_stop_id") == args.from_stop) &
               (ds.field("to_stop_id") == args.to_stop) &
               (ds.field("daytype") == daytype) &
               (ds.field("bin") == half))
    rows = ds.dataset(args.grid, format="parquet").to_table(filter=filters).to_pylist()
    print(json.dumps(rows[0] if rows else {"crowd_class":"Unknown", "rate":None,
                     "reason":"No scheduled model slot for this route, edge and time."},
                     ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
