# Rebuild results

The corrected model was trained and evaluated on the original October archive. The test comprises 14,034,000 scheduled edge/half-hour/day cells from October 22â€“31. Training uses October 1â€“18 and validation October 19â€“21. All test features use history frozen at October 18.

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
