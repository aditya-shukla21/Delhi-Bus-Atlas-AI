"""Read the original ZIP directly and create the private matched-ticket staging database."""
import argparse
import csv
import datetime as dt
import hashlib
import io
import itertools
import json
import sqlite3
import tempfile
import zipfile
from collections import Counter, defaultdict
from contextlib import closing, contextmanager
from functools import lru_cache
from pathlib import Path

import numpy as np
from common import DAY, MONTH_START, ND, WORK
from matching import build_matcher, clean


@lru_cache(maxsize=150000)
def clock(text):
    h, m, s = map(int, text.split(':'))
    if h < 0 or not (0 <= m < 60 and 0 <= s < 60):
        raise ValueError('invalid clock')
    return h*3600+m*60+s


@contextmanager
def csvrows(archive, member):
    with archive.open(member) as raw, io.TextIOWrapper(raw,encoding='utf-8-sig',newline='') as text:
        yield csv.DictReader(text)


def ingest_feed(z, db):
    prefix, = [n[:-len('routes.txt')] for n in z.namelist() if n.endswith('/delhi_buses_static_gtfs_v1/routes.txt')]
    with csvrows(z,prefix+'stops.txt') as rows:
        stops = {r['stop_id']:(r['stop_name'],float(r['stop_lat']),float(r['stop_lon'])) for r in rows}
    db.executemany('INSERT INTO stops VALUES(?,?,?,?)',((s,*info) for s,info in stops.items()))
    with csvrows(z,prefix+'routes.txt') as rows:
        routes = {r['route_id']:r['route_short_name'] for r in rows if r['route_type']=='3'}
    with csvrows(z,prefix+'trips.txt') as rows:
        trips = {r['trip_id']:(routes[r['route_id']],r['service_id']) for r in rows if r['route_id'] in routes}
    with csvrows(z,prefix+'calendar.txt') as rows:
        for r in rows:
            days = ''.join(r[k] for k in 'monday tuesday wednesday thursday friday saturday sunday'.split())
            db.execute('INSERT INTO calendar VALUES(?,?,?,?)',(r['service_id'],days,r['start_date'],r['end_date']))
    if prefix+'calendar_dates.txt' in z.namelist():
        with csvrows(z,prefix+'calendar_dates.txt') as rows:
            db.executemany('INSERT INTO exception VALUES(?,?,?)',((r['service_id'],r['date'],int(r['exception_type'])) for r in rows))
    keys, offsets = {}, defaultdict(Counter)
    counts = Counter()
    with csvrows(z,prefix+'stop_times.txt') as rows:
        for trip, group in itertools.groupby(rows,key=lambda r:r['trip_id']):
            route, service = trips.pop(trip)
            seq = sorted((int(r['stop_sequence']),r['stop_id'],clock(r['departure_time'])) for r in group)
            if len(seq)<2 or any(s[2]>t[2] for s,t in zip(seq,seq[1:])):
                raise ValueError(f'Invalid scheduled trip {trip}')
            ids = tuple(r[1] for r in seq)
            times = tuple(r[2] for r in seq)
            p = keys.setdefault((route,ids),len(keys))
            offsets[p][tuple(t-times[0] for t in times)]+=1
            db.execute('INSERT INTO scheduled VALUES(?,?,?)',(p,service,np.asarray(times[:-1],dtype='<i4').tobytes()))
            counts['scheduled_trips']+=1
    if trips:
        raise ValueError('Some trips lack stop times')
    patterns, by_route = [], defaultdict(list)
    for (route,ids),p in keys.items():
        freq = offsets[p].total()
        by_name = defaultdict(list)
        for i,s in enumerate(ids):
            by_name[clean(stops[s][0])].append(i)
        off = offsets[p].most_common(1)[0][0]
        db.execute('INSERT INTO patterns VALUES(?,?,?,?,?)',(p,route,json.dumps(ids),json.dumps(off),freq))
        patterns.append((route,ids,off,by_name))
        by_route[clean(route)].append(p)
    for ids in by_route.values():
        ids.sort(key=lambda p:(-offsets[p].total(),p))
    counts.update(patterns=len(patterns), scheduled_routes=len(by_route))
    return build_matcher(patterns,by_route), counts


def ingest_tickets(z, db, resolve):
    filename, = [n for n in z.namelist() if n.endswith('/October-Delhi.csv')]
    counts = Counter()
    dates = {(MONTH_START+dt.timedelta(days=i)).isoformat():i for i in range(ND)}
    batch = []
    with csvrows(z,filename) as rows:
        for r in rows:
            counts['input_tickets']+=1
            try:
                n=int(r['passenger_count'])
                if n<=0:
                    raise ValueError
            except (TypeError,ValueError):
                counts['invalid_passengers']+=1
                continue
            counts['input_passengers']+=n
            stamp=r['created_at']
            try:
                if not stamp.endswith('+05:30'):
                    raise ValueError
                tod=clock(stamp[11:19])
                if tod>=DAY:
                    raise ValueError
                t=dates[stamp[:10]]*DAY+tod
            except (ValueError,KeyError):
                counts['invalid_ist_or_outside_october']+=1
                continue
            match=resolve(clean(r['route']),clean(r['start_stop_name']),clean(r['end_stop_name']))
            if isinstance(match,str):
                counts[match]+=1
                continue
            p,i,j,method=match
            counts[('matched_exact','matched_alias','matched_fuzzy')[method]]+=1
            batch.append((p,t,i,j,n))
            counts['matched_tickets']+=1
            counts['matched_passengers']+=n
            if len(batch)>=25000:
                db.executemany('INSERT INTO events VALUES(?,?,?,?,?)',batch)
                batch.clear()
    db.executemany('INSERT INTO events VALUES(?,?,?,?,?)',batch)
    with z.open(filename) as raw:
        counts['raw_csv_sha256']=hashlib.file_digest(raw,'sha256').hexdigest()
    return counts


def build(archive, work_dir):
    work_dir.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work_dir) as tmp, zipfile.ZipFile(archive) as z:
        staged=Path(tmp)/'matched.sqlite'
        with closing(sqlite3.connect(staged)) as db,db:
            db.executescript('''
                PRAGMA journal_mode=OFF;
                CREATE TABLE stops(id TEXT PRIMARY KEY,name TEXT,lat REAL,lon REAL);
                CREATE TABLE calendar(service TEXT,mask TEXT,start TEXT,end TEXT);
                CREATE TABLE exception(service TEXT,date TEXT,kind INTEGER);
                CREATE TABLE scheduled(pattern_id INTEGER,service TEXT,times BLOB);
                CREATE TABLE patterns(pattern_id INTEGER PRIMARY KEY,route TEXT,stops TEXT,offsets TEXT,trips INTEGER);
                CREATE TABLE events(pattern_id INTEGER,t INTEGER,si INTEGER,ei INTEGER,n INTEGER);
                CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
            ''')
            print('Reading full bus GTFS',flush=True)
            resolve,feed_stats=ingest_feed(z,db)
            stats=dict(feed_stats)
            print('Matching all fare records',flush=True)
            stats.update(ingest_tickets(z,db,resolve))
            with archive.open('rb') as f:
                stats['source_archive_sha256']=hashlib.file_digest(f,'sha256').hexdigest()
            db.execute('CREATE INDEX schedule_pattern ON scheduled(pattern_id)')
            db.execute('CREATE INDEX ticket_pattern ON events(pattern_id)')
            db.executemany('INSERT INTO metadata VALUES(?,?)',((k,json.dumps(v)) for k,v in stats.items()))
        staged.replace(work_dir/'matched.sqlite')
    print(json.dumps(stats,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--work-dir',type=Path,default=WORK)
    args=parser.parse_args()
    build(args.archive,args.work_dir)
