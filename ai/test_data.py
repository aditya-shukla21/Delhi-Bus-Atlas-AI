"""Synthetic regressions for variant pooling, midnight travel and path ambiguity."""
import importlib
import sqlite3
import unittest
from collections import Counter, defaultdict

import numpy as np

from common import DAY, ND, NB
from matching import build_matcher

builder=importlib.import_module('01_build_cells')


class CellsTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript('''
            CREATE TABLE scheduled(pattern_id,service,times);
            CREATE TABLE calendar(service,mask,start,end);
            CREATE TABLE exception(service,date,kind);
            CREATE TABLE events(pattern_id,t,si,ei,n);
        ''')
        self.db.execute("INSERT INTO calendar VALUES('daily','1111111','20260101','20261231')")

    def test_short_trip_does_not_serve_full_route_tail(self):
        # A-B-C full service at 23:55; A-B short service at 23:57.
        self.db.executemany('INSERT INTO scheduled VALUES(?,?,?)',[
            (1,'daily',np.array([DAY-300,DAY+300],'<i4').tobytes()),
            (2,'daily',np.array([DAY-180],'<i4').tobytes())])
        self.db.execute("INSERT INTO exception VALUES('daily','20261002',2)")
        exposure=np.zeros((ND,NB,2),np.int32)
        sums,den,frac=(np.zeros(2) for _ in range(3))
        active=builder.active_dates(self.db)
        for p,ids in [(1,[0,1]),(2,[0])]:
            builder.add_schedule(self.db,p,np.array(ids),exposure,sums,den,frac,active)
        self.assertEqual(exposure[0,47,0],2)
        self.assertEqual(exposure[1,0,1],1)  # Oct 1 service after midnight.
        self.assertEqual(exposure[0,0,1],1)  # Incoming Sep 30 service.
        self.assertEqual(exposure[2,0,1],0)  # Oct 2 was canceled.
        self.assertEqual(exposure[1,47,0],0)
        self.assertEqual(exposure[:,:,1].max(),1)

    def test_ticket_passengers_and_ticket_support_roll_into_next_day(self):
        self.db.executemany('INSERT INTO events VALUES(?,?,?,?,?)',[(1,DAY-300,0,2,3),(1,31*DAY-300,0,2,2)])
        pax,tickets=(np.zeros((ND,NB,2),np.int32) for _ in range(2))
        audit=Counter()
        builder.add_tickets(self.db,1,np.array([0,1]),np.array([0,600,900]),pax,tickets,audit)
        self.assertEqual(pax[1,0,1],3)
        self.assertEqual(tickets[1,0,1],1)
        self.assertEqual(pax[0,0,1],0)
        self.assertEqual(audit['outside_month_ticket_traversals'],1)

    def test_repeat_traversal_has_one_ticket_for_publication_support(self):
        self.db.execute('INSERT INTO events VALUES(1,0,0,3,2)')
        pax,tickets=(np.zeros((ND,NB,2),np.int32) for _ in range(2))
        builder.add_tickets(self.db,1,np.array([0,1,0]),np.array([0,10,20,30]),pax,tickets,Counter())
        self.assertEqual((pax[0,0,0],tickets[0,0,0]),(4,1))

    def test_ambiguous_variants_and_loop_occurrences(self):
        def pattern(ids):
            names=defaultdict(list)
            for i,s in enumerate(ids):
                names[s].append(i)
            return ('R',tuple(ids),list(range(len(ids))),names)
        match=build_matcher([pattern('abc'),pattern('ab'),pattern('axc')],{'r':[0,1,2]})
        self.assertEqual(match('r','a','b'),(0,0,1,0))  # shared prefix
        self.assertEqual(match('r','a','c'),'ambiguous_path')
        match=build_matcher([pattern('ababc')],{'r':[0]})
        self.assertEqual(match('r','a','b'),'ambiguous_path')


if __name__=='__main__':
    unittest.main()
