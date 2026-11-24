"""Pool ticket demand and scheduled traversals on exactly the same directed GTFS edges."""
import argparse
import datetime as dt
import itertools
import json
import sqlite3
import tempfile
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path

import numpy as np
from common import BINSEC, DAY, MONTH_START, NB, ND, OUT, WORK, encode, readonly


def active_dates(db):
    calendars = {s:(mask,lo,hi) for s,mask,lo,hi in db.execute('SELECT * FROM calendar')}
    exceptions = {(s,d):v for s,d,v in db.execute('SELECT * FROM exception')}
    cache = {}

    def active(service, spill):
        key = (service,spill)
        if key not in cache:
            selected = []
            for actual in range(ND):
                service_date = MONTH_START+dt.timedelta(days=actual-int(spill))
                stamp = service_date.strftime('%Y%m%d')
                mask,lo,hi = calendars.get(service,('0000000','',''))
                ordinary = lo<=stamp<=hi and mask[service_date.weekday()]=='1'
                if exceptions.get((service,stamp),1 if ordinary else 2)==1:
                    selected.append(actual)
            cache[key] = np.array(selected,dtype=int)
        return cache[key]
    return active


def add_schedule(db,p,local_edges,exposure,offset_sums,edge_counts,frac_sums,active):
    nedge=exposure.shape[-1]
    by_service=defaultdict(list)
    for service,blob in db.execute('SELECT service,times FROM scheduled WHERE pattern_id=?',(p,)):
        by_service[service].append(np.frombuffer(blob,dtype='<i4'))
    for service,rows in by_service.items():
        times=np.stack(rows)
        np.add.at(offset_sums,local_edges,(times-times[:,[0]]).sum(axis=0))
        np.add.at(edge_counts,local_edges,len(rows))
        np.add.at(frac_sums,local_edges,len(rows)*np.arange(len(local_edges))/max(1,len(local_edges)-1))
        spill, bin_in_day=np.divmod(times//BINSEC,NB)
        cell=bin_in_day*nedge+local_edges[None,:]
        for shift in np.unique(spill):
            increments=np.bincount(cell[spill==shift],minlength=NB*nedge).reshape(NB,nedge)
            exposure[active(service,shift)]+=increments.astype(np.int32)


def add_tickets(db,p,local_edges,offsets,pax,tickets,counts):
    nedge=pax.shape[-1]
    events=db.execute('SELECT t,si,ei,n FROM events WHERE pattern_id=?',(p,))
    loops=len(set(local_edges.tolist()))!=len(local_edges)
    while block:=events.fetchmany(4096):
        t,si,ei,n=np.asarray(block,dtype=np.int64).T
        lengths=ei-si
        ids=np.repeat(np.arange(len(block)),lengths)
        seg=np.arange(lengths.sum())-np.repeat(np.cumsum(lengths)-lengths,lengths)+si[ids]
        # Transaction timestamps are local civil times. The GTFS elapsed time
        # from boarding to each segment carries into the following civil day.
        shifted=t[ids]+offsets[seg]-offsets[si[ids]]
        counts['ticket_segment_traversals']+=len(shifted)
        counts['cross_midnight_ticket_traversals']+=int(np.count_nonzero(shifted//DAY!=t[ids]//DAY))
        valid=(shifted>=0)&(shifted<ND*DAY)
        counts['outside_month_ticket_traversals']+=int(np.count_nonzero(~valid))
        flat=(shifted[valid]//BINSEC)*nedge+local_edges[seg[valid]]
        np.add.at(pax.ravel(),flat,n[ids[valid]])
        if loops:
            # Same ticket, same edge and same bin counts once for privacy
            # support; repeat traversals still contribute to demand/exposure.
            distinct=np.unique(ids[valid]*pax.size+flat)
            np.add.at(tickets.ravel(),distinct%pax.size,1)
        else:
            np.add.at(tickets.ravel(),flat,1)


def build(work_dir,output_dir):
    output_dir.mkdir(parents=True,exist_ok=True)
    source=work_dir/'matched.sqlite'
    if not source.is_file():
        raise SystemExit('Run 00_match_stops.py with this --work-dir first.')
    with tempfile.TemporaryDirectory(dir=work_dir) as scratch, tempfile.TemporaryDirectory(dir=output_dir) as public:
        cell_path=Path(scratch)/'cells.sqlite'
        map_path=Path(public)/'segments.sqlite'
        with closing(readonly(source)) as db, closing(sqlite3.connect(cell_path)) as cells, closing(sqlite3.connect(map_path)) as mapping, cells, mapping:
            cells.execute('CREATE TABLE cells(route_id INTEGER PRIMARY KEY,route TEXT,edges TEXT,offsets TEXT,seg_frac TEXT,exposure BLOB,passengers BLOB,tickets BLOB)')
            mapping.executescript('''
                CREATE TABLE stops(stop_id TEXT PRIMARY KEY,name TEXT,lat REAL,lon REAL);
                CREATE TABLE routes(route_id INTEGER PRIMARY KEY,route_short_name TEXT UNIQUE);
                CREATE TABLE edges(route_id INTEGER,edge_id INTEGER,from_stop_id TEXT,to_stop_id TEXT,
                    PRIMARY KEY(route_id,edge_id),UNIQUE(route_id,from_stop_id,to_stop_id)) WITHOUT ROWID;
                CREATE TABLE segments(pattern_id INTEGER,seg INTEGER,route_id INTEGER,edge_id INTEGER,from_stop_id TEXT,to_stop_id TEXT,
                    PRIMARY KEY(pattern_id,seg)) WITHOUT ROWID;
                CREATE INDEX segments_route ON segments(route_id,edge_id);
            ''')
            mapping.executemany('INSERT INTO stops VALUES(?,?,?,?)',db.execute('SELECT * FROM stops'))
            counts=Counter()
            active=active_dates(db)
            patterns=db.execute('SELECT pattern_id,route,stops,offsets,trips FROM patterns ORDER BY route,pattern_id')
            for rid,(route,items) in enumerate(itertools.groupby(patterns,key=lambda r:r[1])):
                variants=[(p,json.loads(ids),np.array(json.loads(off),dtype=np.int64)) for p,_,ids,off,_ in items]
                edges=sorted({ab for _,ids,_ in variants for ab in zip(ids,ids[1:])})
                ei={ab:i for i,ab in enumerate(edges)}
                nedge=len(edges)
                mapping.execute('INSERT INTO routes VALUES(?,?)',(rid,route))
                mapping.executemany('INSERT INTO edges VALUES(?,?,?,?)',((rid,i,a,b) for i,(a,b) in enumerate(edges)))
                shape=(ND,NB,nedge)
                exposure,pax,tickets=(np.zeros(shape,np.int32) for _ in range(3))
                sums,den,frac=(np.zeros(nedge,np.float64) for _ in range(3))
                for p,ids,off in variants:
                    local=np.array([ei[ab] for ab in zip(ids,ids[1:])])
                    mapping.executemany('INSERT INTO segments VALUES(?,?,?,?,?,?)',((p,i,rid,int(k),*edges[k]) for i,k in enumerate(local)))
                    add_schedule(db,p,local,exposure,sums,den,frac,active)
                    add_tickets(db,p,local,off,pax,tickets,counts)
                no_service=exposure==0
                counts['no_scheduled_exposure_ticket_contributions']+=int(tickets[no_service].sum())
                counts['no_scheduled_exposure_passenger_traversals']+=int(pax[no_service].sum())
                counts['no_scheduled_exposure_nonempty_cells']+=int(np.count_nonzero(tickets[no_service]))
                pax[no_service]=tickets[no_service]=0
                counts['eligible_schedule_cells']+=int(np.count_nonzero(exposure))
                counts['eligible_ticket_contributions']+=int(tickets.sum())
                counts['eligible_passenger_traversals']+=int(pax.sum())
                counts['scheduled_bus_edge_traversals']+=int(exposure.sum())
                counts['distinct_route_edges']+=nedge
                cells.execute('INSERT INTO cells VALUES(?,?,?,?,?,?,?,?)',(rid,route,json.dumps(edges),
                              json.dumps((sums/den).tolist()),json.dumps((frac/den).tolist()),
                              encode(exposure),encode(pax),encode(tickets)))
                if rid%500==0:
                    print(f'Pooled {rid+1} routes',flush=True)
            report={k:json.loads(v) for k,v in db.execute('SELECT * FROM metadata')}
            report.update(counts)
            report.update(timezone='Asia/Kolkata', dates=['2026-10-01','2026-10-31'],
                exposure='Each actual trip contributes once to each edge it traverses, in its scheduled segment-departure half-hour, conditional on service calendar and service date. Shared edges pool across variants of the same directional route. Repeated traversals count repeatedly.',
                matches='All tickets are eligible regardless of vehicle_id. Route-local normalized full names take priority over slash aliases and high-margin 0.90 similarity with identical numbers. Only a unique forward sequence of exact GTFS stop IDs is accepted. For shared equivalent paths, the most frequent matching pattern supplies the modal relative timing profile only. Ticket demand is counted once per actual traversal of the shared route edge.',
                limitations='Tickets proxy recorded demand at issue time. Missing capture, unscheduled buses and delays are unobserved. The start of October has no incoming September fare records. Cells with tickets but no scheduled exposure are excluded from the per-scheduled-bus target.')
        cell_path.replace(work_dir/'cells.sqlite')
        map_path.replace(output_dir/'segments.sqlite')
        report_path=Path(public)/'build_report.json'
        report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
        report_path.replace(output_dir/'build_report.json')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir',type=Path,default=WORK)
    parser.add_argument('--output-dir',type=Path,default=OUT)
    args=parser.parse_args()
    build(args.work_dir,args.output_dir)
