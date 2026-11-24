# Model card: Delhi bus crowd estimates

## Summary

The project uses a LightGBM model with a Poisson objective to estimate historical ticketed passenger demand per scheduled bus traversal of a directed stop-to-stop stretch. Predictions are exported to a Parquet grid and imported into the local planner's SQLite database.

## Intended use

- Compare relative historical demand across supported route stretches and time windows.
- Add a crowd-aware signal to scheduled journey options.
- Show evidence coverage and supporting ticket/date counts.
- Provide an operator-oriented view of historically higher-load stretches.

## Not intended for

- Live or real-time crowd measurement.
- Exact vehicle occupancy or passenger counts on a particular bus.
- Seat availability, capacity, standing-room or safety guarantees.
- Live GPS, traffic-aware arrival prediction or fare prediction.
- Predictions for every scheduled cell: unsupported cells are intentionally Unknown.

## Data and target

Inputs are user-supplied October ticketing records and the DTC/DIMTS static GTFS feed. Ticket issue timestamp is used as a proxy for boarding time; scheduled offsets are used to propagate ticket demand along the ride. Stop-name matching can be imperfect and passengers already aboard before the supplied month cannot be recovered from that month alone.

The target is matched ticketed passenger demand per scheduled traversal of a directed edge. The output is a relative historical crowd band, not occupancy.

## Training and evaluation design

- Training: October 1–18, 2026.
- Validation: October 19–21, 2026.
- Held-out test: October 22–31, 2026.
- Training features use only preceding dates; validation and test histories are frozen at October 18.
- Final production model is subsequently refitted using all October dates.
- Selected LightGBM iteration: 180 (the configured search limit was reached).

## Recorded test metrics

The held-out evaluation covers 14,034,000 scheduled edge/half-hour/day cells.

| Method | Cell MAE | Poisson deviance | Route/time rank correlation |
|---|---:|---:|---:|
| Global bin profile | 0.6795 | 1.5859 | 0.3042 |
| Route/bin mean | 0.4958 | 1.2190 | 0.7103 |
| Route/edge/bin mean | 0.4179 | 2.2656 | 0.7103 |
| LightGBM | 0.4381 | 0.7564 | 0.7478 |

LightGBM performs best on Poisson deviance and route/time rank correlation in this comparison. The directed-edge historical baseline has lower cell MAE; therefore the model should not be described as best on every metric. See [AI results](../ai/RESULTS.md) for additional evaluation notes.

## Publication threshold and coverage

A grid slot is published only if it has at least 10 ticket crossings across at least 3 distinct dates. The exported grid has 4,210,200 scheduled keys: 421,209 supported and 3,788,991 Unknown (approximately 10% supported). The test scores over all active held-out cells do not imply equal reliability for every exported slot.

Crowd labels use exposure-weighted 40th, 75th and 92nd percentiles of supported production predictions. These are relative bands, not universal passenger-count or vehicle-capacity thresholds.

## Known limitations and risks

- Ticket issue time is only a proxy for boarding time.
- GTFS scheduled offsets proxy movement along the trip; actual delays are not observed.
- Name matching may be wrong; ambiguous matches are excluded.
- Completely missing ticket records cannot be recovered.
- The supplied month lacks preceding September tickets for passengers already aboard at the beginning of October.
- Neighboring edge observations are correlated; millions of cell observations are not millions of independent journeys.
- Only a minority of scheduled slots meet the evidence threshold.
- A selected 180 rounds reached the configured search limit; optimality beyond it was not tested.

## Responsible interpretation

Treat crowd bands as historical guidance, not a promise about the next bus. Read the evidence counts and coverage alongside each estimate. Unknown means insufficient qualifying evidence, not low demand.
