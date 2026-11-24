"""Import the verified AI grid and regenerate the operator index."""
import json
import sqlite3
from pathlib import Path
import pyarrow.parquet as pq
ROOT = Path(__file__).resolve().parent
def build():
    target = ROOT / "data/crowding.sqlite"
    stage = target.with_suffix(".tmp")
    stage.unlink(missing_ok=True)
    with sqlite3.connect(stage) as db:
        db.execute("CREATE TABLE crowd(route TEXT,a TEXT,b TEXT,day TEXT,bin INT,load REAL,level TEXT,tickets INT,days INT,scheduled INT,PRIMARY KEY(route,a,b,day,bin)) WITHOUT ROWID")
        for batch in pq.ParquetFile(ROOT/"ai/artifacts/crowd_grid.parquet").iter_batches(batch_size=65536):
            cols=batch.to_pydict()
            names=["route_short_name","from_stop_id","to_stop_id","daytype","bin","rate","crowd_class","tickets","observed_dates","scheduled_traversals"]
            db.executemany("INSERT INTO crowd VALUES(?,?,?,?,?,?,?,?,?,?)",zip(*(cols[n] for n in names)))
        db.execute("CREATE INDEX crowd_time ON crowd(day,bin,route)")
        db.execute("CREATE TABLE provenance(key TEXT PRIMARY KEY,value TEXT)")
        meta=json.loads((ROOT/"ai/artifacts/metadata.json").read_text())
        db.executemany("INSERT INTO provenance VALUES(?,?)",((k,json.dumps(v)) for k,v in meta.items()))
    db.close()
    stage.replace(target)
    from operator_view import build as index
    index()
if __name__=="__main__": build()
