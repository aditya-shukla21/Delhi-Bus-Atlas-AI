# Local HTTP API reference

The Python server in `server.py` listens on loopback (`127.0.0.1`) and returns JSON for API routes. It also serves the browser assets. The default port is 8000; use `--port 0` to let the operating system choose a free port.

## Endpoints

### `GET /health`

Health response:

```json
{"status":"ok"}
```

### `GET /v1/example`

Returns the saved example payload from `data/example.json`. Used by the standalone demo workflow.

### `GET /v1/stops/search?q=<text>`

Searches stops that occur in the timetable. Returns up to 25 matches with stop ID, name and coordinates. The query must be non-empty.

Example:

```text
/v1/stops/search?q=Lal%20Kuan
```

### `GET /v1/plan`

Builds journey options.

Required query parameters:

| Parameter | Meaning |
|---|---|
| `from` | Origin GTFS stop ID |
| `to` | Destination GTFS stop ID |
| `date` | Local date, `YYYY-MM-DD` |
| `time` | Departure time, 24-hour `HH:MM` |
| `preference` | `0`–`100`, or supported named value `fast` / `comfort` |

Example:

```text
/v1/plan?from=2821&to=2773&date=2026-10-26&time=09%3A00&preference=50
```

The server also accepts the legacy parameter name `comfort` when `preference` is absent. The routing layer searches direct and one-transfer options; the first departure search window is 60 minutes. Transfers must use the same GTFS stop ID and allow 2–45 minutes to connect.

### `GET /v1/advice`

Uses the same required query parameters as `/v1/plan`. Evaluates later departure windows and may recommend leaving later when the implemented crowd, evidence-coverage and arrival-time conditions are met. It does not guarantee that a later option exists.

### `GET /v1/hotspots?day=<day>&bin=<n>`

Returns precomputed high-load stretches for a day type and half-hour bin.

- `day`: `weekday`, `saturday` or `sunday`
- `bin`: integer 0–47

The legacy parameter name `hour` is also accepted, but it represents a half-hour bin, not a clock-hour number. For example, bin 36 represents 18:00–18:29.

## Errors and validation

- Unknown paths return HTTP 404 with a JSON error.
- Invalid/missing parameters return HTTP 400.
- Unexpected local data/runtime errors return HTTP 500 with a generic JSON error.
- Request paths longer than 2048 characters are rejected with HTTP 414.

The server intentionally avoids logging request paths because journey queries contain origin and destination selections.

## Browser assets

The server serves `/`, `/index.html`, `/app.js`, `/journey_ai.js` and `/style.css`.

This is a local application API, not a hosted public API. Keep the server on loopback unless you intentionally redesign its security and deployment model.
