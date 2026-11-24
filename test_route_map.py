"""Regression checks for loop direction, clipping and geometry fallbacks."""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import route_map as maps


class GeometryTests(unittest.TestCase):
    def test_loop_and_reversed_sequence(self):
        # The route passes A twice. B and C determine which passage to use.
        a, b, c = (28.5, 77.1), (28.51, 77.1), (28.5, 77.11)
        vertices = [a, b, c, a]
        groups = maps.projections(vertices, [a, b, c, a])
        score, positions = maps.align(groups, len(vertices)-1)
        self.assertEqual(score, (-4, 0.0))
        self.assertEqual(positions, [0, 1, 2, 3])
        score, positions = maps.align(list(reversed(groups)), len(vertices)-1, reverse=True)
        self.assertEqual(score, (-4, 0.0))
        self.assertEqual(positions, [3, 2, 1, 0])

    def test_partial_geometry_trims_both_ends(self):
        points = [(28.1,77.1),(28.2,77.2),(28.3,77.3),(28.4,77.4)]
        expected = [[28.15,77.15],[28.2,77.2],[28.3,77.3],[28.325,77.325]]
        self.assertEqual(maps.trim(points, 0.5, 2.25), expected)
        self.assertEqual(maps.trim(points, 2.25, 0.5), expected[::-1])

    def test_far_stop_stays_unaligned(self):
        a, b = (28.5,77.1), (28.52,77.1)
        groups = maps.projections([a,b], [a,(28.51,78.1),b])
        self.assertEqual(maps.align(groups, 1)[1], [0,None,1])

    def test_missing_shape_and_missing_archive_use_timetable_order(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for artifact in ['timetable.sqlite','geometry.sqlite']:
                with closing(sqlite3.connect(base / artifact)) as db, db:
                    db.execute('CREATE TABLE stops(id TEXT, lat REAL, lon REAL)')
                    db.executemany('INSERT INTO stops VALUES (?,?,?)', [('b',28.2,77.2),('a',28.1,77.1)])
                    db.execute('CREATE TABLE pattern(route,shape,stops,locations,trips)')
                self.assertEqual(maps.leg_geometry('missing',['a','b'],base),
                                 {'source':'stop_chain','points':[[28.1,77.1],[28.2,77.2]]})


if __name__ == '__main__':
    unittest.main()
