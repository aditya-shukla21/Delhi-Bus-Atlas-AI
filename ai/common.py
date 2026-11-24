"""Shared calendar, schema and tensor reader for the Delhi October 2026 pipeline."""
import datetime as dt
import json
import sqlite3
import zlib
from contextlib import closing
from pathlib import Path

import numpy as np


MONTH_START = dt.date(2026, 10, 1)
ND, NB, BINSEC, DAY = 31, 48, 1800, 86400
ROOT = Path(__file__).resolve().parent
WORK = ROOT / 'work'
OUT = ROOT / 'artifacts'


def readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)


def encode(array):
    return zlib.compress(np.ascontiguousarray(array, dtype='<i4').tobytes(), level=1)


def decode(blob, shape):
    return np.frombuffer(zlib.decompress(blob), dtype='<i4').reshape(shape)


def iter_routes(db_path):
    """Yield a single route at a time. Daily tensors are [October day index, bin, edge]."""
    with closing(readonly(db_path)) as db:
        for rid, route, edges, off, frac, trips, pax, count in db.execute('SELECT * FROM cells ORDER BY route_id'):
            pairs = [tuple(pair) for pair in json.loads(edges)]
            shape = (ND, NB, len(pairs))
            yield dict(route_id=rid, route=route, edges=pairs, offsets=np.array(json.loads(off),np.float32),
                       seg_frac=np.array(json.loads(frac),np.float32), exposure=decode(trips,shape),
                       passengers=decode(pax,shape),tickets=decode(count,shape))
