# End-to-end system workflow

This project has two distinct workflows: an offline data/model build and the online (local) application workflow. The first creates the data consumed by the second.

## A. Offline build workflow

1. Provide the original October ticket CSV and DTC/DIMTS static GTFS archive to the build environment.
2. Build the GTFS timetable database and route geometry.
3. Run pattern/data checks.
4. Run the AI pipeline: stop matching, cell construction, chronological training/validation/test, model evaluation and production grid export.
5. Import the exported grid into `data/crowding.sqlite`.
6. Regenerate the operator hotspot index and saved demo data.
7. Run integration checks and AI verification.

The top-level `rebuild.py` orchestrates these steps. It takes the source archive path as its command-line argument; the ticket CSV is expected in the source data location configured by the AI package. See [Installation](INSTALLATION.md) and [AI pipeline](AI_PIPELINE.md) before rebuilding.

## B. App runtime workflow

1. Start `server.py` (or double-click `Start planner.cmd`).
2. The server restores the crowd database from its ZIP if needed.
3. The browser loads the local HTML, CSS and JavaScript.
4. The user searches for an origin and destination; stop search is served by `/v1/stops/search`.
5. The browser requests `/v1/plan` with stop IDs, date, time and preference.
6. The routing engine searches scheduled patterns for direct and one-transfer options.
7. Each ridden edge is looked up in the crowd database at its scheduled traversal day type and half-hour.
8. The server returns the options; the browser displays timings, transfers, crowd bands, evidence coverage and map geometry.
9. Optional features call `/v1/advice` for later-departure comparisons and `/v1/hotspots` for operator high-load stretches. Journey questions are classified locally in the browser.

## Key safeguards

- A transfer is only considered at the same GTFS stop ID.
- The planner considers a first departure within 60 minutes and a transfer wait from 2 to 45 minutes.
- A crowd rate is published only with at least 10 supporting ticket crossings over at least 3 distinct dates.
- Missing or unsupported crowd cells remain Unknown; they are not silently treated as low crowd.
- The app does not provide live vehicle tracking, real-time traffic or seat availability.

See [workflow diagram](diagrams/system-workflow.mmd) and [journey planning flow](diagrams/journey-planning.mmd).
