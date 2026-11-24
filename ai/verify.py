"""Verify chronology, EVERY published grid key and support mask, and replay real predictions."""
import argparse
import json
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from common import iter_routes, readonly
from train import DAY_NAMES, DAY_TYPE, LABELS, MIN_DATES, MIN_TICKETS, History, evidence, network_profile, prefixes


def check_chronology():
    shape = (31,48,2)
    exposure = np.ones(shape, dtype=np.int32)
    y = np.arange(np.prod(shape), dtype=np.int32).reshape(shape) % 7
    route = dict(edges=[("A","B"),("B","C")], seg_frac=[0,1], offsets=[0,120],
                 exposure=exposure, passengers=y, tickets=y)

    def snapshot(labels, cutoff):
        network = prefixes(labels.sum(axis=2)), prefixes(exposure.sum(axis=2))
        h = History(dict(route, passengers=labels, tickets=labels), network)
        return h.features(cutoff, np.array([0,1,2]), np.array([12,12,12]), np.array([0,1,0]), np.ones(3))

    for cutoff in (1,9,18):
        changed = y.copy()
        changed[cutoff:] += 10000
        np.testing.assert_array_equal(snapshot(y, cutoff), snapshot(changed, cutoff))


def read_grid(artifacts):
    meta = json.loads((artifacts/"metadata.json").read_text())
    with closing(readonly(artifacts/"segments.sqlite")) as db:
        mapping = {(r,e):(name,a,b) for r,e,name,a,b in db.execute(
            "select route_id,edge_id,route_short_name,from_stop_id,to_stop_id from edges join routes using(route_id)")}
    seen = Counter()
    replay = defaultdict(list)
    prev = -1
    for batch in pq.ParquetFile(artifacts/"crowd_grid.parquet").iter_batches(batch_size=65536):
        table = pa.Table.from_batches([batch])
        ids = ["route_id","edge_id","route_short_name","from_stop_id","to_stop_id"]
        for row in table.select(ids).group_by(ids).aggregate([]).to_pylist():
            key = row["route_id"],row["edge_id"]
            assert mapping[key] == (row["route_short_name"],row["from_stop_id"],row["to_stop_id"])
        def column(name):
            return table[name].to_numpy()
        dt = pc.index_in(table["daytype"], value_set=pa.array(DAY_NAMES)).to_numpy()
        assert np.isfinite(dt).all()
        rid, edge, half = column("route_id"), column("edge_id"), column("bin")
        assert np.all((half >= 0) & (half < 48)) and np.all((edge>=0) & (edge < 2**20))
        key = (((rid.astype(np.int64)*3+dt)*48+half) << 20) + edge
        assert key[0] > prev and np.all(key[1:] > key[:-1]), "Duplicate or unsorted public key"
        prev = key[-1]
        rate, tickets, dates = column("rate"), column("tickets"), column("observed_dates")
        assert np.all(column("scheduled_traversals") > 0) and np.all(column("scheduled_dates") > 0)
        label = pc.index_in(table["crowd_class"], value_set=pa.array((*LABELS,"Unknown"))).to_numpy()
        assert np.isfinite(label).all()
        unknown = label == 4
        for values in (rate,tickets,dates):
            np.testing.assert_array_equal(np.isnan(values), unknown)
        assert np.all(tickets[~unknown] >= MIN_TICKETS) and np.all(dates[~unknown] >= MIN_DATES)
        assert np.isfinite(rate[~unknown]).all() and np.all(rate[~unknown] >= 0)
        np.testing.assert_array_equal(label[~unknown], np.searchsorted(meta["class_thresholds_rate"], rate[~unknown]))
        seen.update(dict(zip((*LABELS,"Unknown"), np.bincount(label, minlength=5).tolist())))
        for k in range(3):
            indices = np.flatnonzero((dt == k) & ~unknown)
            if len(replay[k]) < 5 and len(indices):
                i = indices[len(indices)//2]
                replay[k].append((int(rid[i]),int(edge[i]),k,int(half[i]),float(rate[i]),
                                  int(tickets[i]),int(dates[i])))
    assert dict(seen) == meta["counts_by_class"] and sum(seen.values()) == meta["n_grid_rows"]
    return replay


def check_saved_model(cells, artifacts, replay):
    gy, gt, _, _ = network_profile(cells)
    by_route = defaultdict(list)
    for rows in replay.values():
        for rid, *row in rows:
            by_route[rid].append(row)
    booster = lgb.Booster(model_file=str(artifacts/"crowd_model.lgb.txt"))
    n = 0
    for route in iter_routes(cells):
        if route["route_id"] not in by_route:
            continue
        h = History(route, (gy,gt))
        for edge, dt, half, published, tickets, observed in by_route.pop(route["route_id"]):
            scheduled = h.t[DAY_TYPE == dt,half,edge]
            freq = scheduled[scheduled > 0].mean()
            x = h.features(31,dt,np.array([half]),np.array([edge]),np.array([freq]))
            reconstructed = booster.predict(x,num_threads=1)[0]
            np.testing.assert_allclose(reconstructed,published,rtol=1e-6,atol=1e-8)
            counts, dates = evidence(h,31,dt)
            assert (counts[half,edge], dates[half,edge]) == (tickets,observed)
            n += 1
        if not by_route:
            break
    assert not by_route and n >= 3
    return n


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cells",required=True,type=Path)
    parser.add_argument("--artifacts",required=True,type=Path)
    args = parser.parse_args()
    check_chronology()
    items = read_grid(args.artifacts)
    count = check_saved_model(args.cells,args.artifacts,items)
    print(f"Chronology, all public grid keys, suppression and {count} saved-model prediction replays passed.")
