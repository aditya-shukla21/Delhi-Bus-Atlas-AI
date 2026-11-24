"""Offline route shape builder and map lookup. Uses only the Python standard library."""
import argparse
import csv
import io
import itertools
import json
import math
import sqlite3
import struct
import tempfile
import zipfile
import zlib
from bisect import bisect_left
from collections import Counter, defaultdict
from contextlib import closing, contextmanager
from pathlib import Path


DATA = Path(__file__).resolve().parent / 'data'
SNAP_METRES = 200
# Local east/north units at Delhi's latitude; projection is used only for snapping.
LAT_METRES = 111200
LON_METRES = LAT_METRES * math.cos(math.radians(28.6))


@contextmanager
def feed_rows(archive, prefix, file):
    with archive.open(prefix + file + '.txt') as raw:
        with io.TextIOWrapper(raw, encoding='utf-8-sig', newline='') as text:
            yield csv.DictReader(text)


def pack(points):
    return zlib.compress(b''.join(struct.pack('<ii', round(lat * 1e6), round(lon * 1e6))
                                 for lat, lon in points), level=6)


def unpack(blob):
    return [(a / 1e6, b / 1e6) for a, b in struct.iter_unpack('<ii', zlib.decompress(blob))]


def projections(points, stop_coords):
    """Project stops onto every nearby segment, including competing branches of a loop."""
    xy = [(lon * LON_METRES, lat * LAT_METRES) for lat, lon in points]
    grid = defaultdict(list)
    for i, ((x, y), (u, v)) in enumerate(zip(xy, xy[1:])):
        if x == u and y == v:
            continue
        gx = int(min(x, u) // SNAP_METRES), int(max(x, u) // SNAP_METRES)
        gy = int(min(y, v) // SNAP_METRES), int(max(y, v) // SNAP_METRES)
        for ix in range(gx[0], gx[1] + 1):
            for iy in range(gy[0], gy[1] + 1):
                grid[ix, iy].append(i)
    result = []
    for lat, lon in stop_coords:
        sx, sy = lon * LON_METRES, lat * LAT_METRES
        gx, gy = int(sx // SNAP_METRES), int(sy // SNAP_METRES)
        indices = set(itertools.chain.from_iterable(
            grid.get((i, j), ()) for i in range(gx-1, gx+2) for j in range(gy-1, gy+2)))
        options = {}
        for i in indices:
            x, y = xy[i]
            u, v = xy[i+1]
            dx, dy = u-x, v-y
            t = max(0.0, min(1.0, ((sx-x) * dx + (sy-y) * dy) / (dx*dx + dy*dy)))
            d2 = (x + t*dx - sx)**2 + (y + t*dy - sy)**2
            if d2 <= SNAP_METRES * SNAP_METRES:
                options[i+t] = d2
        result.append(options)
    return result


def align(options, last, reverse=False):
    """Find the longest ordered alignment, then minimize total squared snap error.

    A prefix-minimum tree handles skipped stops and repeated passages near a stop.
    Each state links to its predecessor, so the selected positions can be recovered.
    """
    positions = sorted({(last-p if reverse else p) for group in options for p in group})
    tree = [None] * (len(positions) + 1)
    nodes = []

    def best_prefix(k):
        best = (0, 0.0, -1)
        while k:
            if tree[k] is not None:
                best = min(best, tree[k])
            k -= k & -k
        return best

    for stop, group in enumerate(options):
        updates = []
        for pos, d2 in sorted(group.items()):
            coord = last-pos if reverse else pos
            ix = bisect_left(positions, coord) + 1
            count, cost, parent = best_prefix(ix)
            state = (count-1, cost+d2, len(nodes))
            nodes.append((stop, pos, parent))
            updates.append((ix, state))
        for ix, state in updates:
            while ix < len(tree):
                tree[ix] = state if tree[ix] is None else min(tree[ix], state)
                ix += ix & -ix
    count, cost, parent = best_prefix(len(positions))
    aligned = [None] * len(options)
    while parent >= 0:
        stop, position, parent = nodes[parent]
        aligned[stop] = round(position, 7)
    return (count, cost), aligned


def build(archive_path, output_dir=DATA):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output_dir) as scratch, zipfile.ZipFile(archive_path) as archive:
        dest = Path(scratch) / 'geometry.sqlite'
        with closing(sqlite3.connect(dest)) as db, db:
            db.executescript('''
                CREATE TABLE shape(id TEXT PRIMARY KEY, points BLOB NOT NULL);
                CREATE TABLE pattern(route TEXT, shape TEXT, stops TEXT, locations TEXT, trips INTEGER);
                CREATE INDEX by_route ON pattern(route);
                CREATE TABLE stops(id TEXT PRIMARY KEY, lat REAL, lon REAL);
                CREATE TABLE metadata(key TEXT PRIMARY KEY, value INTEGER);
            ''')
            prefix, = [n[:-len('shapes.txt')] for n in archive.namelist()
                       if n.endswith('/delhi_buses_static_gtfs_v1/shapes.txt')]
            with feed_rows(archive, prefix, 'stops') as rows:
                stops = {r['stop_id']: (float(r['stop_lat']), float(r['stop_lon'])) for r in rows}
                db.executemany('INSERT INTO stops VALUES (?,?,?)', ((s,*coords) for s,coords in stops.items()))
            with feed_rows(archive, prefix, 'routes') as rows:
                routes = {r['route_id']: r['route_short_name'] for r in rows if r['route_type'] == '3'}
            with feed_rows(archive, prefix, 'trips') as rows:
                trips = {r['trip_id']: (routes[r['route_id']], r['shape_id'])
                         for r in rows if r['route_id'] in routes}
            counts = Counter()
            patterns = Counter()
            with feed_rows(archive, prefix, 'stop_times') as rows:
                for trip, group in itertools.groupby(rows, key=lambda r: r['trip_id']):
                    route, shape = trips.pop(trip)
                    seq = tuple(s for _, s in sorted((int(r['stop_sequence']), r['stop_id']) for r in group))
                    patterns[shape, route, seq] += 1
            if trips:
                raise ValueError('Missing scheduled stop times')
            by_shape = defaultdict(list)
            for (shape, route, ids), frequency in patterns.items():
                by_shape[shape].append((route, ids, frequency))
            with feed_rows(archive, prefix, 'shapes') as rows:
                for sid, group in itertools.groupby(rows, key=lambda r:r['shape_id']):
                    vertices = sorted((int(r['shape_pt_sequence']), float(r['shape_pt_lat']),
                                       float(r['shape_pt_lon'])) for r in group)
                    points = [(a,b) for _,a,b in vertices]
                    db.execute('INSERT INTO shape VALUES (?,?)', (sid, pack(points)))
                    counts['shapes'] += 1
                    counts['points'] += len(points)
                    for route, ids, frequency in by_shape.pop(sid, []):
                        options = projections(points, [stops[s] for s in ids])
                        forward = align(options, len(points)-1)
                        backward = align(options, len(points)-1, reverse=True)
                        quality, locations = min((forward, backward), key=lambda item:item[0])
                        db.execute('INSERT INTO pattern VALUES (?,?,?,?,?)', (route, sid,
                                   json.dumps(ids, separators=(',',':')),
                                   json.dumps(locations, separators=(',',':')), frequency))
                        counts['patterns'] += 1
                        counts['pattern_stops'] += len(ids)
                        counts['aligned_stops'] += -quality[0]
            counts['patterns_without_shape'] = sum(len(items) for items in by_shape.values())
            db.executemany('INSERT INTO metadata VALUES (?,?)', counts.items())
        dest.replace(output_dir / 'geometry.sqlite')
    return dict(counts)


def readonly(path):
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)


def interpolate(points, position):
    i = int(position)
    a, b = points[i]
    c, d = points[min(i+1,len(points)-1)]
    t = position-i
    return (round(a+(c-a)*t, 6), round(b+(d-b)*t, 6))


def trim(points, start, end):
    low, high = sorted((start, end))
    vertices = [interpolate(points, low), *points[math.floor(low)+1:math.ceil(high)], interpolate(points, high)]
    result = [list(p) for p, _ in itertools.groupby(vertices)]
    return result if start <= end else result[::-1]


def stop_chain(db, ids):
    found = dict((sid,[lat,lon]) for sid,lat,lon in db.execute(
        'SELECT id,lat,lon FROM stops WHERE id IN (' + ','.join('?' for _ in ids) + ')',ids))
    return {'source': 'stop_chain', 'points': [found[s] for s in ids if s in found]}


def leg_geometry(route, ordered_stop_ids, data_dir=DATA):
    """Return the clipped GTFS polyline or the ordered coordinates of the leg's stops."""
    ids = tuple(map(str, ordered_stop_ids))
    base = Path(data_dir)
    path = base / 'geometry.sqlite'
    if not ids:
        return {'source':'stop_chain', 'points':[]}
    if not path.is_file():
        with closing(readonly(base / 'timetable.sqlite')) as db:
            return stop_chain(db, ids)
    with closing(readonly(path)) as db:
        candidates = []
        for shape, stops, locations, trips in db.execute(
                'SELECT shape,stops,locations,trips FROM pattern WHERE route=? ORDER BY trips DESC,shape', (route,)):
            seq = tuple(json.loads(stops))
            positions = json.loads(locations)
            matches = [(positions[i], positions[i+len(ids)-1]) for i,s in enumerate(seq)
                       if s==ids[0] and seq[i:i+len(ids)]==ids and None not in positions[i:i+len(ids)]]
            # Repeated identical subsequences can denote different branches of a loop.
            if len(matches)==1 and matches[0][0]!=matches[0][1]:
                candidates.append((trips, shape, *matches[0]))
        if candidates:
            _, shape, start, end = max(candidates, key=lambda c:c[0])
            blob, = db.execute('SELECT points FROM shape WHERE id=?', (shape,)).fetchone()
            result = trim(unpack(blob), start, end)
            if len(result)>=2:
                return {'source':'gtfs_shape','points':result}
        return stop_chain(db, ids)


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('input_zip', type=Path)
    cli.add_argument('--output-dir', type=Path, default=DATA)
    args = cli.parse_args()
    print(json.dumps(build(args.input_zip, args.output_dir), indent=2))
