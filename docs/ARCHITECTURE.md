# System architecture

Delhi Bus Atlas is an offline-first web application. A local Python HTTP server serves the browser UI and answers planner requests from prebuilt SQLite data. Crowd estimates are prepared offline by a separate LightGBM pipeline and imported into the runtime crowd database.

## Component layers

### 1. Browser interface
- `index.html` defines the application structure.
- `style.css` provides presentation and responsive styling.
- `app.js` handles stop selection, requests, journey cards, crowd evidence, map display, comfort preference, language and operator view.
- `journey_ai.js` classifies a limited set of journey-question intents locally. It uses planner results for travel facts; it is not a general-purpose chatbot.
- `Journey demo.html` is a standalone saved-example demonstration and is not the full interactive planner.

### 2. Local HTTP server
- `server.py` binds to `127.0.0.1`, serves the UI assets and exposes JSON endpoints.
- `routing.py` searches GTFS timetable patterns and scores direct / one-transfer journey options using crowd data.
- `route_map.py` provides offline route geometry lookup and builds the geometry database.
- `operator_view.py` reads the imported crowd database's precomputed hotspot index.

The server restores `data/crowding.sqlite` from `data/crowding.sqlite.zip` on first launch when the extracted database is absent. The extracted database is a runtime file, not the distributed compressed source.

### 3. Runtime data
- `data/timetable.sqlite`: stop names/coordinates, service calendars and scheduled route patterns.
- `data/crowding.sqlite`: crowd estimates keyed by directional route edge, day type and half-hour bin, plus provenance.
- `data/geometry.sqlite`: GTFS shapes and their stop alignments, used for clipped route polylines.
- `data/hotspots.json`: precomputed operator-view results.
- `data/example.json`: saved example payload used by the demo endpoint.

### 4. Offline model build
The `ai/` package matches ticket records to GTFS journeys, builds scheduled edge/time cells, trains and evaluates LightGBM, then exports a Parquet grid and supporting artifacts. `import_ai.py` imports the grid into the runtime crowd database. `rebuild.py` orchestrates the full source-to-runtime rebuild.

## Data flow and boundaries

- Raw October ticket records and the original GTFS archive are build inputs; they are not part of the normal browser request path.
- The browser sends stop IDs, date, time and preference to the local server.
- The server reads local SQLite/JSON data and returns computed journey or hotspot results.
- Crowd estimates are historical ticket-demand estimates per scheduled traversal. They are not vehicle telemetry or measured occupancy.
- The browser-side intent classifier categorizes supported questions; answers are grounded in the journey result already returned by the planner.

## Design choices

- **Offline runtime:** after the supplied data files are present and the crowd archive is extracted, the app does not require a remote prediction service.
- **Exact join keys:** crowd estimates are joined using directional route label, from-stop ID, to-stop ID, day type and half-hour bin.
- **Conservative evidence:** cells below ticket/date support thresholds remain Unknown.
- **Separate build and runtime:** expensive data preparation is not performed during a normal journey search.

See [the architecture diagram](diagrams/architecture.mmd) and [the end-to-end workflow](SYSTEM_WORKFLOW.md).
