"""Train, evaluate and export the October LightGBM crowding model.

python train.py --cells work/cells.sqlite --output-dir artifacts
"""
import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from scipy.stats import spearmanr

from common import iter_routes


FIRST = date(2026, 10, 1)
DAY_NAMES = ("weekday", "saturday", "sunday")
DAY_TYPE = np.array([max(0, (FIRST + timedelta(days=i)).weekday() - 4)
                     for i in range(31)], dtype=np.int8)
LABELS = ("Low", "Medium", "High", "Very High")
MIN_TICKETS = 10
MIN_DATES = 3
QUANTILES = (.40, .75, .92)
FEATURES = ["half_hour", "day_type", "route_edges", "edge_fraction", "offset_min",
            "scheduled_traversals", "network_time_rate", "route_time_rate", "edge_all_time_rate",
            "edge_time_rate", "edge_history_exposure"]
PARAMETERS = dict(objective="poisson", metric="poisson", learning_rate=.065, num_leaves=31,
                  min_data_in_leaf=180, feature_fraction=.9, lambda_l2=8., max_bin=63,
                  seed=42, deterministic=True, force_col_wise=True, verbosity=-1)


def prefixes(daily):
    """Calendar-day index k stores only observations on dates strictly before k."""
    output = np.zeros((32, 3, *daily.shape[1:]), dtype=np.int32)
    mask_shape = (31,) + (1,) * (daily.ndim - 1)
    for dt in range(3):
        mask = (DAY_TYPE == dt).reshape(mask_shape)
        np.cumsum(daily * mask, axis=0, dtype=np.int32, out=output[1:, dt])
    return output


def ratio(y, exposure, fallback=0.0):
    y, exposure = np.broadcast_arrays(y, exposure)
    out = np.broadcast_to(fallback, y.shape).astype(np.float32, copy=True)
    np.divide(y, exposure, where=exposure > 0, out=out)
    return out


def network_profile(path):
    y = np.zeros((31, 48), dtype=np.int64)
    exposure = np.zeros_like(y)
    counts = np.zeros(31, dtype=np.int64)
    unscheduled = 0
    for route in iter_routes(path):
        t = route["exposure"]
        positive = t > 0
        y += np.where(positive, route["passengers"], 0).sum(axis=2)
        exposure += t.sum(axis=2)
        counts += positive.sum(axis=(1, 2))
        unscheduled += int(route["passengers"][~positive].sum())
    return prefixes(y), prefixes(exposure), counts, unscheduled


class History:
    def __init__(self, route, network):
        self.route = route
        self.t = np.asarray(route["exposure"])
        self.y = np.where(self.t > 0, route["passengers"], 0)
        self.tickets = np.where(self.t > 0, route["tickets"], 0)
        self.yh, self.th = prefixes(self.y), prefixes(self.t)
        self.yr, self.tr = self.yh.sum(axis=3), self.th.sum(axis=3)
        self.ye, self.te = self.yh.sum(axis=(1, 2)), self.th.sum(axis=(1, 2))
        self.gy, self.gt = network

    def features(self, cutoff, dt, half, edge, scheduled):
        gy, gt = self.gy[cutoff, dt, half], self.gt[cutoff, dt, half]
        network_rate = ratio(gy, gt)
        route_rate = ratio(self.yr[cutoff, dt, half], self.tr[cutoff, dt, half], network_rate)
        edge_rate = ratio(self.ye[cutoff, edge], self.te[cutoff, edge], route_rate)
        past_y, past_t = self.yh[cutoff, dt, half, edge], self.th[cutoff, dt, half, edge]
        exact = ratio(past_y, past_t, route_rate)
        out = np.column_stack((half, np.broadcast_to(dt, half.shape),
                               np.full_like(half, len(self.route["edges"])),
                               np.asarray(self.route["seg_frac"])[edge],
                               np.asarray(self.route["offsets"])[edge] / 60,
                               scheduled, network_rate, route_rate, edge_rate, exact,
                               np.log1p(past_t)))
        return out.astype(np.float32, copy=False)


def sample_rows(cells, network, counts, first, end, maximum, frozen=None):
    """Sample active cell-days uniformly, independently of tickets and labels."""
    rng = np.random.default_rng(731 + first + end)
    probability = min(1., maximum / max(1, counts[first:end].sum()))
    blocks, targets, weights = [], [], []
    for route in iter_routes(cells):
        t = route["exposure"]
        active = np.flatnonzero(t[first:end].ravel())
        n = rng.binomial(len(active), probability)
        if not n:
            continue
        sample = active if n == len(active) else rng.choice(active, n, replace=False)
        day, half, edge = np.unravel_index(sample, t[first:end].shape)
        day += first
        scheduled = t[day, half, edge]
        h = History(route, network)
        blocks.append(h.features(day if frozen is None else frozen, DAY_TYPE[day], half, edge, scheduled))
        targets.append((h.y[day, half, edge] / scheduled).astype(np.float32))
        weights.append(scheduled.astype(np.float32))
    if not blocks:
        raise ValueError("No scheduled training/validation cells in the supplied date range.")
    return np.concatenate(blocks), np.concatenate(targets), np.concatenate(weights)


def fit(cells, network, counts, config, *, final_rounds=None):
    end = 31 if final_rounds else 18
    x, y, w = sample_rows(cells, network, counts, 0, end, config.train_rows)
    n_train = len(y)
    print(f"Fitting days 1–{end} on {n_train:,} sampled cell-days", flush=True)
    training = lgb.Dataset(x, label=y, weight=w, feature_name=FEATURES)
    valid = []
    callbacks = [lgb.log_evaluation(25)]
    n_val = 0
    if final_rounds is None:
        vx, vy, vw = sample_rows(cells, network, counts, 18, 21, config.validation_rows, frozen=18)
        n_val = len(vy)
        valid = [lgb.Dataset(vx, label=vy, weight=vw, reference=training)]
        callbacks.append(lgb.early_stopping(18, verbose=False))
    booster = lgb.train(dict(PARAMETERS, num_threads=config.threads), training,
                        num_boost_round=final_rounds or config.rounds, valid_sets=valid,
                        callbacks=callbacks)
    return booster, n_train, n_val


class Metrics:
    def __init__(self):
        self.totals = Counter()
        self.by_route = defaultdict(dict)
        self.weekday = defaultdict(lambda: np.zeros((3,48), dtype=np.float64))

    def update(self, method, prediction, route, dt, half, target, t):
        if not len(t):
            return
        mu = np.maximum(prediction.astype(np.float64) * t, 1e-12)
        y = target.astype(np.float64)
        positive = y > 0
        dev = mu - y
        dev[positive] += y[positive] * np.log(y[positive] / mu[positive])
        for key, value in (("n", len(t)), ("t", t.sum()), ("dev", 2*dev.sum()),
                           ("abs", np.abs(y - mu).sum())):
            self.totals[method, key] += value
        group = dt.astype(np.int32)*48 + half
        sums = np.vstack([np.bincount(group, weights=a, minlength=144) for a in (y, mu, t)])
        self.by_route[method][route] = sums
        self.weekday[method] += sums[:, :48]

    def result(self):
        out = {}
        for method, groups in self.by_route.items():
            arr = np.concatenate(list(groups.values()), axis=1)
            y, mu, exposure = arr[:, arr[2] >= 20]
            selection = self.weekday[method]
            mask = selection[2] > 0
            profile = selection[:2, mask] / selection[2, mask]
            observed = y / exposure
            predicted = mu / exposure
            corr = spearmanr(observed, predicted).statistic if len(observed) >= 2 else np.nan
            profile_corr = np.corrcoef(profile)[0, 1] if profile.shape[1] >= 2 else np.nan
            n = int(self.totals[method, "n"])
            out[method] = {
                "cell_days": n, "scheduled_traversals": int(self.totals[method, "t"]),
                "poisson_deviance_per_cell": float(self.totals[method, "dev"] / n),
                "mae_ticketed_passengers_per_cell": float(self.totals[method, "abs"] / n),
                "exposure_weighted_mae_rate": float(self.totals[method, "abs"] / self.totals[method,"t"]),
                "route_time_groups_min_20_traversals": len(observed),
                "route_time_spearman": float(corr) if np.isfinite(corr) else None,
                "route_time_weighted_mae_rate": float(np.abs(y-mu).sum()/exposure.sum()) if len(y) else None,
                "weekday_profile_correlation": float(profile_corr) if np.isfinite(profile_corr) else None}
        return out

    def weekday_profile(self):
        curves = []
        for half in range(48):
            row = {"bin": half, "local_time": f"{half // 2:02d}:{(half % 2)*30:02d}"}
            for method, totals in self.weekday.items():
                observed, predicted, exposure = totals[:, half]
                row["scheduled_traversals"] = int(exposure)
                row["observed"] = float(observed / exposure) if exposure else None
                row[method] = float(predicted / exposure) if exposure else None
            curves.append(row)
        return curves


def evidence(h, cutoff, dt):
    dates = DAY_TYPE[:cutoff] == dt
    ticket = h.tickets[:cutoff][dates]
    return ticket.sum(axis=0), (ticket > 0).sum(axis=0)


def evaluate(cells, network, model, threads):
    all_cells, supported_cells = Metrics(), Metrics()
    for route in iter_routes(cells):
        h = History(route, network)
        day, half, edge = np.nonzero(h.t[21:] > 0)
        if not len(day):
            continue
        day += 21
        dt = DAY_TYPE[day]
        t = h.t[day, half, edge]
        y = h.y[day, half, edge]
        # The frozen history and features are identical for all held-out days
        # sharing (day type, half-hour, edge, scheduled-traversal count).
        stride = int(t.max()) + 1
        key = ((dt.astype(np.int64)*48 + half)*len(route["edges"]) + edge)*stride + t
        _, first, inverse = np.unique(key, return_index=True, return_inverse=True)
        x = h.features(18, dt[first], half[first], edge[first], t[first])
        predictions = {"global_bin_profile":x[:,6], "route_bin_mean":x[:,7],
                       "route_edge_bin_mean":x[:,9],
                       "lightgbm":model.predict(x, num_threads=threads)}
        support = np.zeros(len(t), dtype=bool)
        for daytype in np.unique(dt):
            tickets, dates = evidence(h, 18, daytype)
            mask = dt == daytype
            support[mask] = ((tickets[half[mask], edge[mask]] >= MIN_TICKETS)
                             & (dates[half[mask], edge[mask]] >= MIN_DATES))
        for method, compact in predictions.items():
            pred = compact[inverse]
            all_cells.update(method, pred, route["route"], dt, half, y, t)
            supported_cells.update(method, pred[support], route["route"], dt[support], half[support],
                                   y[support], t[support])
    return {"all_active_test_cells": all_cells.result(), "training_supported_test_cells": supported_cells.result(),
            "heldout_weekday_half_hour_profile": all_cells.weekday_profile()}


def quantiles(values, weights):
    order = np.argsort(values, kind="stable")
    w = np.cumsum(weights[order], dtype=np.float64)
    ix = np.searchsorted(w, w[-1] * np.array(QUANTILES))
    return [float(v) for v in values[order[ix]]]


def flush(blocks, writer):
    if blocks:
        writer.write_table(pa.concat_tables(blocks), row_group_size=65536)
        blocks.clear()


def export_grid(cells, network, model, output, threads):
    schema = pa.schema([("route_id",pa.int32()), ("edge_id",pa.int32()), ("route_short_name",pa.string()),
                        ("from_stop_id",pa.string()), ("to_stop_id",pa.string()), ("daytype",pa.string()),
                        ("bin",pa.int8()), ("scheduled_traversals",pa.int32()), ("scheduled_dates",pa.int8()),
                        ("tickets",pa.int32()), ("observed_dates",pa.int8()), ("rate",pa.float32())])
    parts, supported_rates, supported_weights = [], [], []
    active_dates = 0
    with tempfile.TemporaryDirectory(dir=output) as temp:
        stage = Path(temp) / "rates.parquet"
        with pq.ParquetWriter(stage, schema, compression="zstd") as writer:
            for route in iter_routes(cells):
                h = History(route, network)
                endpoints = np.array(route["edges"], dtype=str)
                for dt, name in enumerate(DAY_NAMES):
                    days = DAY_TYPE == dt
                    calendar = h.t[days]
                    exposure = calendar.sum(axis=0)
                    half, edge = np.nonzero(exposure > 0)
                    if not len(half):
                        continue
                    t = exposure[half, edge]
                    scheduled_dates = (calendar > 0).sum(axis=0)[half, edge]
                    tickets, dates = evidence(h, 31, dt)
                    tic, observed = tickets[half,edge], dates[half,edge]
                    ok = (tic >= MIN_TICKETS) & (observed >= MIN_DATES)
                    rates = np.zeros(len(t), dtype=np.float32)
                    if ok.any():
                        # Average frequency on days the slot operates. The supplied
                        # feed has one daily service; same-daytype active exposures
                        # are identical for an individual October slot.
                        x = h.features(31, dt, half[ok], edge[ok], t[ok]/scheduled_dates[ok])
                        rates[ok] = model.predict(x, num_threads=threads)
                        supported_rates.append(rates[ok])
                        supported_weights.append(t[ok])
                    arrays = [np.full(len(t), route["route_id"]), edge, [route["route"]]*len(t),
                              endpoints[edge,0].tolist(), endpoints[edge,1].tolist(), [name]*len(t), half, t,
                              scheduled_dates, pa.array(tic, mask=~ok), pa.array(observed, mask=~ok),
                              pa.array(rates, mask=~ok)]
                    parts.append(pa.Table.from_arrays([pa.array(a, type=f.type) for a,f in zip(arrays,schema)], schema=schema))
                    active_dates += len(t)
                    if active_dates >= 65536:
                        flush(parts, writer)
                        active_dates = 0
            flush(parts, writer)
        if not supported_rates:
            raise ValueError("No grid cell meets the ticket and date support thresholds.")
        thresholds = quantiles(np.concatenate(supported_rates), np.concatenate(supported_weights))
        counts = Counter()
        dest = output / "crowd_grid.parquet"
        final_schema = schema.append(pa.field("crowd_class",pa.string()))
        with pq.ParquetWriter(dest, final_schema, compression="zstd") as writer:
            for batch in pq.ParquetFile(stage).iter_batches(batch_size=65536):
                table = pa.Table.from_batches([batch])
                prediction = table["rate"].to_numpy()
                labels = np.array((*LABELS, "Unknown"))[
                    np.where(np.isnan(prediction), 4, np.searchsorted(thresholds, prediction))]
                uniques, totals = np.unique(labels, return_counts=True)
                counts.update({str(k):int(v) for k,v in zip(uniques,totals)})
                writer.write_table(table.append_column("crowd_class", pa.array(labels.tolist())))
    return thresholds, dict(counts)


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--cells", required=True, type=Path)
    cli.add_argument("--output-dir", required=True, type=Path)
    cli.add_argument("--train-rows", type=int, default=1000000, help="Expected uniformly sampled training cell-days per fit.")
    cli.add_argument("--validation-rows", type=int, default=250000)
    cli.add_argument("--rounds", type=int, default=180, help="Maximum boosting rounds; validation selects the actual count.")
    cli.add_argument("--threads", type=int, default=min(4,os.cpu_count() or 1))
    args = cli.parse_args()
    if min(args.train_rows, args.validation_rows, args.rounds, args.threads) < 1:
        cli.error("Sample sizes, rounds and threads must be positive.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    print("Computing prefix-only network history", flush=True)
    gy, gt, counts, unscheduled = network_profile(args.cells)
    network = (gy, gt)
    trial, n_train, n_val = fit(args.cells, network, counts, args)
    best = trial.best_iteration or trial.current_iteration()
    print(f"Scoring every scheduled cell-day on October 22–31 using {best} rounds", flush=True)
    results = evaluate(args.cells, network, trial, args.threads)
    del trial
    final, n_final, _ = fit(args.cells, network, counts, args, final_rounds=best)
    with tempfile.TemporaryDirectory(dir=args.output_dir) as tmp:
        out = Path(tmp)
        model_path = out / "crowd_model.lgb.txt"
        final.save_model(str(model_path))
        print("Exporting the support-filtered, exact-stop grid", flush=True)
        thresholds, counts_by_label = export_grid(args.cells, network, final, out, args.threads)
        eval_data = {
            "target": "Matched ticketed passengers on a directed GTFS route edge per scheduled traversal.",
            "train": ["2026-10-01","2026-10-18"], "validation": ["2026-10-19","2026-10-21"],
            "test": ["2026-10-22","2026-10-31"], "best_iteration": best,
            "history": "Training and final-fit rows use only preceding calendar dates. Validation and test use a single history frozen at October 18. Day type is derived solely from the calendar.",
            "evaluation": "All positive-exposure held-out cell-days, including zeros. All methods use identical rows and scheduled traversals. The supported subset uses only ticket and date counts available by October 18. The exact edge/time baseline backs off to route/time, then network/time.",
            "metrics": "Predict rate per scheduled traversal. Cell count prediction equals rate times that date's scheduled traversals. Poisson deviance uses a 1e-12 floor; aggregate rank and MAE use route/daytype/half-hour groups with >=20 scheduled traversals.",
            "sampling": {"method":"Deterministic uniform sampling without replacement inside each route, independent of target.",
                         "eligible_train":int(counts[:18].sum()), "sampled_train":n_train,
                         "eligible_validation":int(counts[18:21].sum()), "sampled_validation":n_val,
                         "eligible_test":int(counts[21:].sum()), "sampled_test":False,
                         "eligible_full_month":int(counts.sum()), "sampled_final_fit":n_final},
            "additional_zero_exposure_passenger_crossings_found_in_staged_cells":unscheduled,
            "staging_exclusions":"The builder removes matched passenger crossings without scheduled exposure before training. Its totals are recorded in build_report.json.",
            "results":results}
        write_json(out / "eval.json", eval_data)
        with model_path.open("rb") as stream:
            digest = hashlib.file_digest(stream,"sha256").hexdigest()
        write_json(out / "metadata.json", {
            "model":"LightGBM Poisson on per-traversal rate with scheduled traversal weights",
            "model_sha256":digest, "lightgbm_version":lgb.__version__, "features":FEATURES,
            "parameters":dict(PARAMETERS, num_threads=args.threads), "rounds":best,
            "final_fit_period":["2026-10-01","2026-10-31"], "timezone":"Asia/Kolkata",
            "bin_minutes":30, "daytypes":list(DAY_NAMES),
            "grid_key":["route_short_name","from_stop_id","to_stop_id","daytype","bin"],
            "class_names":list(LABELS), "class_quantiles":list(QUANTILES), "class_thresholds_rate":thresholds,
            "threshold_population":"All published supported rates, weighted by their full-month scheduled traversal counts. Equality goes in the lower band.",
            "counts_by_class":counts_by_label, "n_grid_rows":sum(counts_by_label.values()),
            "support":{"minimum_ticket_crossings":MIN_TICKETS,"minimum_contributing_dates":MIN_DATES,
                       "unknown":"Rate and private support counts are null on a scheduled slot below either floor. Unscheduled slots are absent."},
            "limitation":"Relative historical ticketed demand per scheduled bus. October ticket coverage, actual arrivals, vehicle capacity, and true onboard occupancy are unknown."})
        for name in ("crowd_model.lgb.txt","crowd_grid.parquet","eval.json","metadata.json"):
            os.replace(out / name, args.output_dir / name)
    print(json.dumps({"best_iteration":best,"grid_classes":counts_by_label, "test":results["all_active_test_cells"]},indent=2))


if __name__ == "__main__":
    main()
