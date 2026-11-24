# Installation, operation and verification

## Run the supplied application

### Windows (recommended)

1. Download or clone the repository and extract it fully.
2. Install Python 3.11 or later.
3. Double-click `Start planner.cmd`.
4. Keep the terminal window open while using the app. The browser opens locally.

The supplied compiled databases mean the normal app runtime does not need the AI training packages or an internet connection. On first launch, if `data/crowding.sqlite` is missing, `server.py` extracts it from `data/crowding.sqlite.zip`. Allow enough free disk space for both the archive and extracted database.

### Manual start

```shell
python server.py --open --port 0
```

> **Note:** Both startup methods launch the same Delhi Bus Atlas application. `Start planner.cmd` is the convenient Windows launcher: it locates an available Python executable and starts the local server automatically. The manual command is useful for developers who prefer to start the server from a terminal or a specific Python environment.

To stop the server, press Ctrl+C in the terminal.

## Run checks

From the repository root:

```shell
python checks.py
python test_route_map.py
python ai/test_data.py
```

The deeper AI artifact verification command requires the private rebuilt staging database:

```shell
python ai/verify.py --cells ai/work/cells.sqlite --artifacts ai/artifacts
```

That verification checks chronology, grid keys, suppression decisions and saved-model replay.

## Rebuild from original source data

A full rebuild is for maintainers who have the original source archive and ticket CSV. It is not needed to run the supplied application.

1. Use Python 3.12 for the AI build.
2. Keep the original ticket CSV and GTFS archive in a private local workspace.
3. Install pinned AI dependencies:

```shell
python -m pip install -r ai/requirements.txt
```

4. Run the top-level rebuild script with the GTFS archive path:

```shell
python rebuild.py "path/to/TDH - RVSHH 2 (1).zip"
```

The rebuild orchestrator runs timetable build, route geometry build, pattern checks, AI pipeline, crowd database import, demo export and integration checks. The AI package expects the ticket CSV in the source-data location configured in `ai/common.py`; inspect that configuration before starting. Intermediate ticket-derived files are written under `ai/work/` and must not be published.

To import an already generated AI grid and refresh the demo:

```shell
python import_ai.py
python export_demo.py
```

Restart the server after replacing runtime data so cached timetable/planner data is reloaded.

## Troubleshooting

- **Browser cannot connect:** confirm the terminal still shows the local server address and that the process is running.
- **Missing crowd database:** check that `data/crowding.sqlite.zip` exists and that there is disk space to extract it.
- **Missing timetable / geometry:** restore the complete repository data directory; the crowd archive alone is not enough to plan journeys.
- **Rebuild dependency errors:** use Python 3.12 and install `ai/requirements.txt` in the same interpreter used for the rebuild.
- **Different results after rebuild:** compare the generated metadata, source fingerprints, AI results and support counts. Retraining can change thresholds and predictions.

For endpoint parameters, see [API reference](API_REFERENCE.md).
