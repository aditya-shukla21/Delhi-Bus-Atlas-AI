# Repaired Delhi crowd prediction model

This package rebuilds the supplied LightGBM approach from the original October ticket and full Delhi GTFS archive. Its target is matched ticketed passenger demand per scheduled bus traversal of a directed stop-to-stop stretch. Published crowd bands describe relative historical demand. Vehicle capacity and seat availability remain unmeasured.

## Run

Install Python 3.12, extract this package, and open a terminal in its directory.

```shell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python run_pipeline.py "C:\path\to\TDH - RVSHH 2 (1).zip"
```

On macOS/Linux use `.venv/bin/python` for the last two commands. All input paths are arguments. The pipeline builds intermediate data itself in `work/` and writes final artifacts in `artifacts/`. Intermediate data is private and must be excluded from a public deployment. Stop consumers of the artifacts while rebuilding.

## Changes

- Raw tickets are streamed, and matching uses route-local normalized names, slash aliases and conservative spelling matches. Only a unique forward path of GTFS stop IDs is accepted. Ambiguous records are counted in the audit.
- Every scheduled trip contributes only the actual edges that it traverses. Shared edges pool within the same directional route, including short-route variants. Calendar exceptions and service dates are respected.
- Ticket travel time is propagated along the matched path. A midnight crossing updates both the date and half-hour. Out-of-month crossings are counted and excluded.
- Training covers October 1–18, validation October 19–21 and testing October 22–31. Historical features for training rows use preceding dates only. Validation and test histories are frozen at October 18. The final production model is subsequently refitted using all October dates.
- Day types are weekday, Saturday and Sunday, derived from the calendar. No low-volume test dates are inferred as holidays.
- Each published rate requires at least ten supporting ticket crossings on three distinct dates. Scheduled slots below either threshold retain an Unknown class and a null rate.
- The exact route label and boarding/alighting stop IDs accompany every prediction. A separate SQLite mapping preserves the original pattern/segment sequence.
- Evaluation compares LightGBM with global, route/time and directed-edge/time historical baselines on the same held-out cells. Validation selects boosting rounds. See the rebuilt evaluation for which method performs best on each metric.

## Integrate into a journey planner

Use `artifacts/crowd_grid.parquet` for fast lookups. The key is
`(route_short_name, from_stop_id, to_stop_id, daytype, bin)`.
For a scheduled traversal at 18:20 IST, bin is 36. Derive the day type from the traversal's local calendar date, including after-midnight legs. Treat a null rate or missing lookup as Unknown.

`artifacts/segments.sqlite` contains `routes`, `edges`, `segments` and `stops` tables. Numeric route and edge IDs are local to this build. Match to an external planner using the explicit directional route label and original stop-ID pair.

The model file is useful for reproducibility and future retraining. A bare model cannot predict from route and time alone: it also needs the historical feature preparation in `train.py`. The precomputed grid already includes these features' predictions.

## Assumptions and limits

The ticket issue timestamp proxies boarding time, and scheduled offsets proxy movement along the ride. When equivalent paths occur in several patterns, the most frequent compatible pattern supplies the timing profile. Stop-name matching can still make mistakes. Completely missing tickets cannot be recovered.

Cells with recorded demand and zero scheduled exposure are excluded from the per-scheduled-bus target and counted in `build_report.json`. The supplied month contains no September tickets for passengers already aboard at its start. Neighboring segments are correlated, so millions of cell observations do not represent millions of independent journeys.

Crowd thresholds follow the uploaded model's exposure-weighted 40th, 75th and 92nd percentiles on supported production predictions. They are recomputed after retraining. They are different from the earlier planner's thresholds.

Sources are the user-provided October CSV and DTC/DIMTS GTFS archive. The package uses Python, NumPy, LightGBM, SciPy and Apache Arrow. Source and data fingerprints are recorded with the artifacts.

## Example lookup

After installing dependencies, query Lal Kuan to Prem Nagar on 525STLUP at 09:00 IST:

```shell
python query.py --route 525STLUP --from-stop 2821 --to-stop 2822 --date 2026-10-26 --time 09:00
```

The response contains the exact key, predicted rate, crowd class and evidence when supported. The route planner must apply this lookup separately to every ridden edge at that edge's traversal time.


## Verify a rebuilt package

```shell
python test_data.py
python verify.py --cells work/cells.sqlite --artifacts artifacts
```

The first command tests matching, variant exposure, service calendars and rollover on small controlled cases. The second perturbs later labels to check feature isolation, scans every grid key and suppression decision, checks duplicate keys, and reproduces saved predictions with the exported model.


# Rebuild results

The corrected model was trained and evaluated on the original October archive. The test comprises 14,034,000 scheduled edge/half-hour/day cells from October 22–31. Training uses October 1–18 and validation October 19–21. All test features use history frozen at October 18.

| Method | Cell MAE | Poisson deviance | Route/time rank correlation |
|---|---:|---:|---:|
| global_bin_profile | 0.6795 | 1.5859 | 0.3042 |
| route_bin_mean | 0.4958 | 1.2190 | 0.7103 |
| route_edge_bin_mean | 0.4179 | 2.2656 | 0.7103 |
| lightgbm | 0.4381 | 0.7564 | 0.7478 |

LightGBM improves deviance and rank correlation on this comparison. The directed-edge historical baseline retains lower cell MAE and lower aggregate rate MAE. These metrics use corrected targets and matching, so the original ZIP metrics are not a controlled before/after comparison.

The final grid has 4,210,200 scheduled keys. Of these, 421,209 meet the ticket/date support thresholds and 3,788,991 show Unknown. Thus about 10% of scheduled route-edge/day-type/half-hour combinations have published rates. The all-cell test scores do not establish equally reliable predictions for every exported slot.

Training and final refitting each used approximately one million uniformly sampled cell-days. Validation used 250,150 sampled cells. Every test cell was scored. The selected 180 rounds reached the configured search limit; optimality beyond that limit was not tested.

Four controlled data regression tests passed. The feature perturbation check, all 4,210,200 grid-key and support checks, and 15 saved-model prediction/evidence replays across day types passed. An actual lookup on 525STLUP, stop 2821 to 2822, weekday 09:00 returns Very High with 375 ticket crossings over 22 dates.

The integrated planner imports this corrected grid by exact directional route label and GTFS stop-ID pair. It uses the same thresholds and preserves Unknown cells and ticket/date evidence.
