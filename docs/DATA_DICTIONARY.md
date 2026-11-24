# Data dictionary and storage guide

This guide describes the principal files and tables visible in the current project code. It is not a dump of every column in every build artifact.

## Runtime files

| File | Purpose | Main contents |
|---|---|---|
| `data/timetable.sqlite` | Journey search | `stops`, `calendar`, `patterns`, `metadata` |
| `data/crowding.sqlite` | Crowd lookup | `crowd`, `provenance` |
| `data/geometry.sqlite` | Offline route map | `shape`, `pattern`, `stops`, `metadata` |
| `data/hotspots.json` | Operator view | High-load stretches indexed by day type and half-hour bin |
| `data/example.json` | Saved demo | Example journey payload |

### Timetable database

- `stops`: GTFS stop ID (primary key), stop name, latitude and longitude.
- `calendar`: service ID, weekly service mask, start date and end date.
- `patterns`: route label, agency, service, headsign, ordered stop IDs, arrival offsets, departure offsets and scheduled start times.
- `metadata`: build counts such as stop times, patterns, bus routes and trips.

### Crowd database

The `crowd` table is created by `import_ai.py` with this logical schema:

| Field | Meaning |
|---|---|
| `route` | Directional route short name |
| `a` | From-stop GTFS ID |
| `b` | To-stop GTFS ID |
| `day` | `weekday`, `saturday` or `sunday` |
| `bin` | Half-hour bin, 0–47 |
| `load` | Predicted ticketed passengers per scheduled bus traversal; null if unsupported |
| `level` | Relative crowd class; Unknown when unsupported |
| `tickets` | Supporting ticket crossings; null for unsupported cells |
| `days` | Distinct dates with supporting tickets; null for unsupported cells |
| `scheduled` | Scheduled traversals used for the exported slot |

The primary key is `(route, a, b, day, bin)`. An index supports day/bin/route hotspot queries. The `provenance` table stores build metadata from the model artifact metadata file.

### Geometry database

- `shape`: GTFS shape ID and compressed coordinate sequence.
- `pattern`: route, shape ID, ordered stop IDs, aligned positions and trip frequency.
- `stops`: stop ID and coordinates.
- `metadata`: shape/pattern/alignment counts.

## AI artifacts

The `ai/artifacts/` directory contains the exported prediction grid, model and metadata/evaluation outputs from the build. The Parquet grid includes route and edge identifiers, route label, from/to stop IDs, day type, half-hour bin, scheduled exposure, evidence counts, rate and crowd class. Consult the generated metadata and [AI package README](../ai/README.md) for the exact artifact set produced by a given rebuild.

## Private build intermediates and source inputs

The original ticket CSV, original GTFS archive and `ai/work/` intermediate data are build inputs/intermediates, not required for normal app runtime. Keep raw ticket-level records and intermediate data private. The repository distributes the compressed crowding database; the server extracts it on first launch.

For the model's interpretation and support policy, see [Model card](MODEL_CARD.md).
