"""Integrated planner, model and operator regression checks."""
import json,sqlite3,unittest
from pathlib import Path
import routing,operator_view
ROOT=Path(__file__).resolve().parent
class Checks(unittest.TestCase):
 def test_model_import(self):
  meta=json.loads((ROOT/"ai/artifacts/metadata.json").read_text())
  with sqlite3.connect(ROOT/"data/crowding.sqlite") as db:
   self.assertEqual(dict(db.execute("select level,count(*) from crowd group by level")),meta["counts_by_class"])
   self.assertEqual(db.execute("select count(*) from crowd where load is not null and (tickets<10 or days<3)").fetchone()[0],0)
   self.assertEqual(db.execute("select count(*) from crowd where level='Unknown' and load is not null").fetchone()[0],0)
 def test_slider_and_evidence(self):
  args=("2821","2773","2026-10-26","09:00")
  for pref in (0,50,100):
   result=routing.plan(*args,pref)["options"]
   self.assertTrue(1<=len(result)<=3)
   for o in result:
    self.assertTrue(0<=o["coverage"]<=1)
    self.assertGreaterEqual(o["duration_min"],o["wait_min"])
    for leg in o["legs"]:
     self.assertTrue(leg["geometry"]["points"])
     for s in leg["segments"]:
      if s["level"]=="Unknown": self.assertIsNone(s["load"])
      else:
       self.assertGreaterEqual(s["tickets"],10)
       self.assertGreaterEqual(s["days"],3)
 def test_calendar(self):
  self.assertEqual(routing.crowd_period(4,86400+1800),("saturday",1))
  self.assertFalse(routing.plan("2821","2773","2041-01-01","09:00")["options"])
 def test_operator(self):
  for day in ("weekday","saturday","sunday"):
   rows=operator_view.hotspots(day,18)
   self.assertEqual(len(rows),len({r["route"] for r in rows}))
   self.assertTrue(all(r["tickets"]>=10 and r["days"]>=3 for r in rows))
 def test_advisor(self):
  a=routing.advice("2821","2773","2026-10-26","09:00",0)
  for w in a["windows"]:
   if w["qualifies"]:
    self.assertLessEqual(w["arrival_delta_min"],15)
    self.assertGreaterEqual(w["alternative"]["coverage"],.75)
    self.assertGreater(w["alternative"]["departure_iso"],a["baseline"]["departure_iso"])
if __name__=="__main__":unittest.main()
