# AI crowd-estimation pipeline

The `ai/` package rebuilds a LightGBM model and exports a precomputed crowd grid. The integrated planner consumes that grid; it does not invoke LightGBM for every user query.

## Pipeline stages

1. **Stop matching** — normalize stop names and aliases, then match ticket stop pairs within route context. Only a unique forward path of GTFS stop IDs is accepted; ambiguous matches are audited.
2. **Scheduled exposure / cell construction** — build route-specific directed edges from actual GTFS trip patterns. Respect service calendars and exceptions. Shared edges pool only within the same directional route.
3. **Ticket timing propagation** — propagate ticketed demand along the matched path using scheduled offsets. Midnight crossings advance the calendar date and half-hour; out-of-month crossings are counted and excluded.
4. **Feature construction** — use calendar day type, half-hour, route/edge characteristics, scheduled exposure and historical network/route/edge rates.
5. **Chronological model selection** — train on October 1–18, validate on October 19–21 and test on October 22–31. Training histories use only earlier dates; validation/test histories are frozen at October 18.
6. **Evaluation** — compare LightGBM against global-bin, route-bin and directed-route-edge-bin historical baselines on the same held-out cells.
7. **Production refit and export** — refit the final model using October history and export `artifacts/crowd_grid.parquet`, metadata and supporting artifacts.
8. **Integration** — `import_ai.py` imports the Parquet grid into SQLite and rebuilds the operator index.

## Model target and lookup key

The target is matched ticketed passenger demand per scheduled bus traversal of a directed stop-to-stop stretch. The planner lookup key is:

`(route_short_name, from_stop_id, to_stop_id, daytype, bin)`

The half-hour bin is 0–47. For example, 18:20 maps to bin 36. Day type is weekday, Saturday or Sunday, based on the local traversal date (including after-midnight legs).

## Evidence policy

A cell requires at least 10 supporting ticket crossings on at least 3 distinct dates before its rate and crowd class are published. Unsupported scheduled cells retain a null rate and Unknown class. This is deliberate missing-evidence handling, not a prediction of low demand.

## Important implementation details

- The model uses a Poisson objective.
- The selected boosting round count recorded in the supplied results is 180; this reached the configured search limit, so further optimality beyond that limit was not established.
- The standalone model file is not sufficient by itself to reproduce predictions: feature preparation in `train.py` is also required.
- The exported grid is the planner's serving interface.

For exact parameters, commands and test procedures, see [ai/README.md](../ai/README.md), [ai/RESULTS.md](../ai/RESULTS.md) and [Model card](MODEL_CARD.md).
