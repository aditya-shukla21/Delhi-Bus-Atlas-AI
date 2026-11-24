# Delhi Bus Atlas — integrated AI planner

Delhi Bus Atlas is an offline-first, crowd-aware journey planner for Delhi buses. It combines static DTC/DIMTS GTFS schedules, historical ticket-derived crowd estimates and a local browser interface.

## Open the app

Extract the complete ZIP. On Windows, double-click **Start planner.cmd**. Python 3.11 or later is required. The browser opens locally; keep the terminal running. The supplied compiled databases mean no Python packages or internet access are needed to run the app. The large crowd database is stored as `data/crowding.sqlite.zip` for GitHub compatibility and is automatically extracted by `server.py` on first launch; allow extra disk space for the extracted database.

Alternatively run:

```shell
python server.py --open --port 0
```

**Journey demo.html** opens directly in a browser with a saved example. It supports the Comfort slider, maps, English/Hindi, operator periods, later-departure comparisons and journey questions. Stop/date changes require the full app.

## Main features

- Direct and one-transfer scheduled journey search.
- Crowd-aware ranking with a continuous comfort preference.
- Historical crowd bands and ticket/date evidence for each supported stretch.
- Evidence coverage, with unsupported cells shown as Unknown.
- Offline GTFS route geometry, English/Hindi interface and operator hotspot view.
- A limited bilingual journey-intent classifier that answers supported questions using planner results.

## What the estimates mean

Rates are predicted ticketed passengers crossing a stretch per scheduled bus traversal. Low / Medium / High / Very High are relative bands from the corrected model. They do not establish total occupancy or seat availability. Only cells with at least ten contributing tickets over three dates receive rates. Other scheduled cells show Unknown.

Evidence lists ticket crossings and contributing dates. Coverage is the proportion of scheduled riding time with supported estimates; it is not prediction accuracy. Overall journey bands require at least 50% coverage. Unknown time receives the highest penalty during comfort sorting. Dates outside October reuse October weekday, Saturday or Sunday patterns.

The model scored all 14,034,000 scheduled held-out cell-days on October 22–31. LightGBM improves Poisson deviance and rank correlation, while the historical edge baseline has lower MAE. See [ai/RESULTS.md](ai/RESULTS.md) and the [model card](docs/MODEL_CARD.md). Approximately 10% of scheduled grid combinations meet publication support.

## Journey search

First departures are within 60 minutes. Search supports direct journeys and one transfer at the same stop ID with 2–45 minutes to connect. It scores a bounded set of alternatives. Times include initial and transfer waiting. The slider blends normalized arrival and crowd penalties across the displayed alternatives.

The advisor evaluates three ten-minute windows starting 10, 20 and 30 minutes later. A recommendation requires a distinct later bus, a lower crowd band and score, at least 75% coverage on both journeys, and arrival no more than 15 minutes later than the current choice.

The offline map draws GTFS geometry where matched and identifies fallback stop connections. Stop names retain the source feed's spelling in both languages. The assistant classifies a limited set of question types locally and constructs answers from verified query results. It provides no live tracking, fare prediction or general conversation.

## Documentation

The full documentation and diagrams are in **[docs/](docs/README.md)**:

- [System architecture](docs/ARCHITECTURE.md)
- [End-to-end workflow](docs/SYSTEM_WORKFLOW.md)
- [AI pipeline](docs/AI_PIPELINE.md)
- [Data dictionary](docs/DATA_DICTIONARY.md)
- [HTTP API reference](docs/API_REFERENCE.md)
- [Installation and verification](docs/INSTALLATION.md)
- [Model card and limitations](docs/MODEL_CARD.md)

## Rebuild from the original data

Install Python 3.12 and the pinned training dependencies, then stop the running server and use a fresh extracted project copy:

```shell
python -m pip install -r ai/requirements.txt
python rebuild.py "path/to/TDH - RVSHH 2 (1).zip"
```

This recreates the timetable, route geometry, demand audit, corrected training data and model, imports the grid into SQLite, rebuilds operator rankings and the offline demo, and runs integration checks. Intermediate ticket data is stored in `ai/work` and must stay private. The raw source ZIP and ticket CSV are supplied separately. Check the source-data path configured in `ai/common.py` before rebuilding.

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

See [docs/API_REFERENCE.md](docs/API_REFERENCE.md) for full parameters and behavior. Main routes: `/health`, `/v1/example`, `/v1/stops/search`, `/v1/plan`, `/v1/advice` and `/v1/hotspots`.

## Data credits and privacy

The project uses user-supplied October-Delhi ticket data and the DTC/DIMTS static bus GTFS feed. Python, NumPy, LightGBM, SciPy and Apache Arrow support offline processing. Raw ticket and vehicle records are excluded from this distribution. Training sampling, source hashes, model parameters and scoring rules accompany the artifacts. Keep source ticket data and `ai/work/` intermediates private.
