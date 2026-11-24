# Delhi Bus Atlas — integrated AI planner

## Open the app

Extract the complete ZIP. On Windows, double-click **Start planner.cmd**. Python 3.11 or later is required. The browser opens locally; keep the terminal running. The supplied compiled databases mean no Python packages or internet access are needed to run the app. The large crowd database is stored as `data/crowding.sqlite.zip` for GitHub compatibility and is automatically extracted by `server.py` on first launch; allow a little extra disk space for the extracted database.

Alternatively run:

```shell
python server.py --open --port 0
```

**Journey demo.html** opens directly in a browser with a saved example. It supports the Comfort slider, maps, English/Hindi, operator periods, later-departure comparisons and journey questions. Stop/date changes require the full app.

## Included

- Local planner and API, GTFS timetable, clipped geographic route shapes.
- Corrected LightGBM model, Parquet grid, exact GTFS mapping, metadata and held-out evaluation in ai/artifacts.
- SQLite crowd database imported directly from that grid, with preserved sparse-data support.
- English/Hindi interface, continuous comfort preference, historical crowd bands, leave-later checks.
- A local bilingual intent classifier answering journey questions from the planner's computed results.
- Rebuild scripts, dependencies, verification tests, technical note and demo walkthrough.

## What the estimates mean

Rates are predicted ticketed passengers crossing a stretch per scheduled bus traversal. Low / Medium / High / Very High are relative bands from the corrected model. They do not establish total occupancy or seat availability. Only cells with at least ten contributing tickets over three dates receive rates. Other scheduled cells show Unknown.

Evidence lists ticket crossings and contributing dates. Coverage is the proportion of scheduled riding time with supported estimates; it is not prediction accuracy. Overall journey bands require at least 50% coverage. Unknown time receives the highest penalty during comfort sorting. Dates outside October reuse October weekday, Saturday or Sunday patterns.

The model scored all 14,034,000 scheduled held-out cell-days on October 22–31. LightGBM improves Poisson deviance and rank correlation, while the historical edge baseline has lower MAE. See ai/RESULTS.md for exact values and limitations. Approximately 10% of scheduled grid combinations meet publication support.

## Journey search

First departures are within 60 minutes. Search supports direct journeys and one transfer at the same stop ID with 2–45 minutes to connect. It scores a bounded set of alternatives. Times include initial and transfer waiting. The slider blends normalized arrival and crowd penalties across the displayed alternatives.

The advisor evaluates three ten-minute windows starting 10, 20 and 30 minutes later. A recommendation requires a distinct later bus, a lower crowd band and score, at least 75% coverage on both journeys, and arrival no more than 15 minutes later than the current choice.

The offline map draws GTFS geometry where matched and identifies fallback stop connections. Stop names retain the source feed's spelling in both languages. The assistant classifies a limited set of question types locally and constructs answers from verified query results. It provides no live tracking, fare prediction or general conversation.

## Rebuild from the original data

Install Python 3.12 and the pinned training dependencies, then stop the running server and use a fresh extracted project copy:

```shell
python -m pip install -r ai/requirements.txt
python rebuild.py "path/to/TDH - RVSHH 2 (1).zip"
```

This recreates the timetable, route geometry, demand audit, corrected training data and model, imports the grid into SQLite, rebuilds operator rankings and the offline demo, and runs integration checks. Intermediate ticket data is stored in ai/work and must stay private. The raw source ZIP is supplied separately.

To refresh the runtime database from an already built model:

```shell
python import_ai.py
python export_demo.py
```

Restart the server after any data change so caches use the new build.

## Verify

```shell
python checks.py
python test_route_map.py
python ai/test_data.py
python ai/verify.py --cells ai/work/cells.sqlite --artifacts ai/artifacts
```

The last command requires rebuilt private staging. It checks chronology, every public grid key, sparse-field suppression and saved-model replay.

## HTTP interface

- /health
- /v1/stops/search?q=Lal%20Kuan
- /v1/plan?from=2821&to=2773&date=2026-10-26&time=09%3A00&preference=50
- /v1/advice with the same query fields
- /v1/hotspots?day=weekday&hour=18

Preference is 0–100. For hotspots, day is weekday/saturday/sunday and the legacy hour parameter holds a half-hour bin, 0–47. The browser runs journey-question classification locally. Runtime SQLite contains exact route labels and directed stop IDs.

## Data credits

The user supplied October-Delhi.csv and the full DTC/DIMTS static bus GTFS feed. Python, NumPy, LightGBM, SciPy and Apache Arrow support offline processing. The app uses standard browser APIs and a local Python server. Raw ticket and vehicle records are excluded from this distribution. Training sampling, source hashes, model parameters and scoring rules accompany the artifacts.
