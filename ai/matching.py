"""Route-local conservative ticket matcher. Returns an unambiguous forward stop-ID path."""
import html
import itertools
import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from functools import lru_cache

def clean(value):
    return ' '.join(value.strip().casefold().split())


@lru_cache(maxsize=65536)
def stop_key(name):
    name = unicodedata.normalize('NFKC', html.unescape(name)).casefold()
    name = re.sub(r'\bx-?ing\b', 'crossing', name)
    name = re.sub(r'\bextn\b', 'extension', name)
    name = re.sub(r'\bsec\b', 'sector', name)
    return ''.join(c for c in name if c.isalnum())


def build_matcher(patterns, by_route):
    lexicons = {}
    for route, ids in by_route.items():
        full, alias = defaultdict(set), defaultdict(set)
        for p in ids:
            for name in patterns[p][3]:
                full[stop_key(name)].add(name)
                for part in name.split('/'):
                    key = stop_key(part)
                    if len(key) >= 3 and any(c.isalpha() for c in key):
                        alias[key].add(name)
        lexicons[route] = (full, alias)

    @lru_cache(maxsize=262144)
    def candidates(route, label):
        full, aliases = lexicons[route]
        key = stop_key(label)
        if not key or key == 'null':
            return (), 0
        if key in full:
            return full[key], 0
        if key in aliases:
            return aliases[key], 1
        # Compare against whole GTFS names. A strong match must also be
        # separated from the runner-up; never change sector/stop numbers.
        if len(key) >= 6:
            numbers = re.findall(r'\d+', key)
            scores = []
            for candidate in full:
                if abs(len(candidate) - len(key)) > 0.22 * max(len(key), len(candidate)):
                    continue
                if re.findall(r'\d+', candidate) != numbers:
                    continue
                score = SequenceMatcher(None, key, candidate, autojunk=False).ratio()
                if score >= 0.85:
                    scores.append((score, candidate))
            scores.sort(reverse=True)
            if scores and scores[0][0] >= 0.90 and (len(scores) == 1 or scores[0][0] - scores[1][0] >= 0.05):
                return full[scores[0][1]], 2
        return (), 0

    @lru_cache(maxsize=262144)
    def resolve(route, start, end):
        if route not in by_route:
            return 'route_unmatched'
        starts, sm = candidates(route, start)
        ends, em = candidates(route, end)
        if not starts or not ends:
            return 'stops_unmatched_or_wrong_order'
        chosen = None
        chosen_path = None
        for p in by_route[route]:
            _, stops, _, locations = patterns[p]
            for i in itertools.chain.from_iterable(locations.get(name, ()) for name in starts):
                for j in itertools.chain.from_iterable(locations.get(name, ()) for name in ends):
                    if j <= i:
                        continue
                    path = stops[i:j + 1]
                    if chosen is None:
                        chosen, chosen_path = (p, i, j), path
                    elif path != chosen_path or (p == chosen[0] and (i, j) != chosen[1:]):
                        return 'ambiguous_path'
        return (*chosen, max(sm, em)) if chosen else 'stops_unmatched_or_wrong_order'

    return resolve
