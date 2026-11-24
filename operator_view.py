"""One supported high-load stretch per route and half-hour."""
import json
import sqlite3
from pathlib import Path
DATA=Path(__file__).resolve().parent/"data"
def build():
    with sqlite3.connect((DATA/"timetable.sqlite").as_uri()+"?mode=ro",uri=True) as db:
        names=dict(db.execute("select id,name from stops"))
    with sqlite3.connect((DATA/"crowding.sqlite").as_uri()+"?mode=ro",uri=True) as db:
        rows=db.execute("""
        with route_rank as (
         select *,row_number() over(partition by route,day,bin order by load desc,days desc,tickets desc,a,b) as r
         from crowd where load is not null and tickets>=10 and days>=3
        ), period_rank as (
         select *,row_number() over(partition by day,bin order by load desc,route) as n
         from route_rank where r=1
        ) select route,a,b,day,bin,load,level,tickets,days from period_rank where n<=12 order by day,bin,n
        """)
        result={}
        for route,a,b,day,bin_no,load,level,tickets,days in rows:
            result.setdefault(f"{day}/{bin_no}",[]).append(dict(route=route,from_name=names[a],to_name=names[b],load=load,level=level,tickets=tickets,days=days))
    (DATA/"hotspots.json").write_text(json.dumps(result,ensure_ascii=False),encoding="utf-8")
def hotspots(day,hour):
    if day not in ("weekday","saturday","sunday") or not 0<=int(hour)<48: raise ValueError("Invalid day or half-hour bin")
    return json.loads((DATA/"hotspots.json").read_text(encoding="utf-8")).get(f"{day}/{int(hour)}",[])
if __name__=="__main__": build()
