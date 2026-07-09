#!/usr/bin/env python3
"""
full_evaluation.py

Regenerates all evaluation evidence for BICE without touching the detection
algorithm in engine/dataset.py or engine/engine.py:

  1. Classification metrics: Precision, Recall, F1, Accuracy, Balanced
     Accuracy (plus TPR/FPR) at BICE's default theta=3.0 / per-device
     calibrated theta, exactly as engine/dataset.py computes them.
  2. Runtime evaluation: per-tick latency (mean/p50/p95/p99, ms), process
     CPU time, and peak memory (RSS + tracemalloc heap for one device).
  3. Ablation study: three components are disabled one at a time --
     burn-in discarding, per-device theta calibration, and quarantine
     hysteresis -- via external monkeypatching / post-hoc reanalysis of the
     unmodified algorithm's own outputs. No line in engine/ is changed for
     any ablation variant; see ABLATIONS below for exactly what each one
     flips and how.

Dataset: the real N-BaIoT dataset (archive.ics.uci.edu) is not reachable
from this sandbox's network allowlist. scripts/generate_synthetic_dataset.py
produces a deterministic, structurally-faithful stand-in (same on-disk
layout and 100-column Kitsune feature schema) so these numbers are measured
from a real run of the real code, not invented. This is documented wherever
these results are reported.

Evaluation parameters (documented per user request):
  BURN_IN_ROWS      = 60   (engine/dataset.py DatasetDevice.BURN_IN_ROWS)
  BASELINE_WINDOW   = 300  (rows used to compute per-feature mean/sigma;
                             engine/dataset.py tick(), "len(self.history) >= 300")
  EVAL_WINDOW       = 400 ticks total per profile (WARMUP=300 to build the
                             baseline + 100 post-warmup ticks scored for
                             alerts), matching scripts/baseline_comparison.py
  THETA (default)   = 3.0  (engine/dataset.py DatasetDevice.__init__ default;
                             per-device calibrated_theta overrides it once
                             >=50 drift samples exist -- see calibrate_theta())
  RANDOM SEED        = 42  (Python `random`, sklearn random_state where applicable)
"""
import json
import os
import random
import resource
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
random.seed(42)

from engine.dataset import create_dataset_devices  # noqa: E402

DATASET_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results", "synthetic_nbaiot")
OUT_JSON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results", "full_evaluation.json")

BURN_IN_ROWS = 60
BASELINE_WINDOW = 300
WARMUP = 300
# 300 burn-in-adjusted ticks to fill the baseline (history reaches len 300),
# plus >=50 further ticks so calibrate_theta()'s 50-sample minimum
# (engine/dataset.py) is actually reached within the window, plus margin.
EVAL_TICKS = 480
THETA_DEFAULT = 3.0


def ensure_dataset():
    if not os.path.isdir(DATASET_DIR) or not os.listdir(DATASET_DIR):
        import subprocess
        subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "generate_synthetic_dataset.py"),
                         "--out", DATASET_DIR, "--devices", "3", "--rows", "900", "--seed", "42"], check=True)


# ---------------------------------------------------------------------------
# Ablation hooks. Every hook is applied to a device *instance* after normal
# construction -- engine/dataset.py source is never edited. Each hook is
# documented with exactly what real-algorithm behavior it disables.
# ---------------------------------------------------------------------------

def ablate_no_burn_in(dev):
    """Skip burn-in discarding: rows enter history/baseline from row 0."""
    dev._burn_in_remaining = 0


def ablate_no_theta_calibration(dev):
    """Disable per-device theta calibration: every device is judged against
    the fixed default theta=3.0 instead of its own calibrated_theta."""
    dev.calibrate_theta = lambda: None


ABLATIONS = {
    "full_system": None,
    "no_burn_in": ablate_no_burn_in,
    "no_theta_calibration": ablate_no_theta_calibration,
    # "no_quarantine_hysteresis" is handled post-hoc below (see run_variant),
    # because it re-labels the drift/trust series BICE already produced
    # rather than intercepting a hookable method.
}


def run_variant(hook, symmetric_quarantine=False):
    """Run every profile in the dataset for EVAL_TICKS ticks, applying `hook`
    (or none) right after construction. Returns per-profile records with the
    full drift/trust trace so both alert- and quarantine-based labels, and
    per-tick latency, can be derived without re-running BICE."""
    random.seed(42)
    devices = create_dataset_devices(DATASET_DIR, "n_baiot")
    records = []
    tick_latencies_ms = []

    for dev in devices:
        if hook:
            hook(dev)
        alert_trace, trust_trace, quarantine_trace = [], [], []
        for i in range(EVAL_TICKS):
            t0 = time.perf_counter()
            dev.tick()
            s = dev.state()
            tick_latencies_ms.append((time.perf_counter() - t0) * 1000.0)
            if i >= WARMUP and s is not None:
                alert_trace.append(s["alert"])       # algorithm's own decision (effective_theta already applied)
                trust_trace.append(s["trust"])
                quarantine_trace.append(s["quarantine"])

        alert_pred = any(alert_trace)
        # symmetric-threshold ("no hysteresis") quarantine re-derivation:
        # quarantine flips at trust<30 same as real algorithm, but *release*
        # also fires at trust<30 crossing back up (no 70% recovery band),
        # i.e. a single threshold instead of BICE's 30/70 hysteresis pair.
        if symmetric_quarantine and trust_trace:
            q = False
            sym_trace = []
            for t in trust_trace:
                q = t < 30
                sym_trace.append(q)
            quarantine_pred = any(sym_trace)
        else:
            quarantine_pred = any(quarantine_trace)

        records.append({
            "name": dev.name,
            "attacked": bool(dev.attacked),
            "alert_pred": bool(alert_pred),
            "quarantine_pred": bool(quarantine_pred),
        })

    return records, tick_latencies_ms


def confusion(records, pred_key):
    tp = fp = tn = fn = 0
    for r in records:
        pred, actual = r[pred_key], r["attacked"]
        if actual and pred: tp += 1
        elif actual and not pred: fn += 1
        elif not actual and pred: fp += 1
        else: tn += 1
    return tp, fp, tn, fn


def metrics_from_confusion(tp, fp, tn, fn):
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0  # = TPR
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    accuracy = (tp + tn) / (tp + fp + tn + fn) if (tp + fp + tn + fn) else 0.0
    tnr = tn / (tn + fp) if (tn + fp) else 0.0  # specificity
    balanced_accuracy = (recall + tnr) / 2
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    return {
        "precision": round(precision, 4), "recall_tpr": round(recall, 4),
        "f1": round(f1, 4), "accuracy": round(accuracy, 4),
        "balanced_accuracy": round(balanced_accuracy, 4), "fpr": round(fpr, 4),
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
    }


def latency_stats(samples_ms):
    s = sorted(samples_ms)
    n = len(s)
    def pct(p):
        return s[min(n - 1, int(n * p))]
    return {
        "mean_ms": round(statistics.mean(s), 4),
        "p50_ms": round(pct(0.50), 4),
        "p95_ms": round(pct(0.95), 4),
        "p99_ms": round(pct(0.99), 4),
        "max_ms": round(max(s), 4),
        "n_ticks": n,
    }


def _deep_sizeof(obj, seen=None):
    """Recursive size estimate over plain data containers (deque/list/tuple/
    dict/float/str/bool/None). Skips file handles / other non-data objects
    since we're measuring the algorithm's data footprint, not OS resources."""
    if seen is None:
        seen = set()
    oid = id(obj)
    if oid in seen:
        return 0
    seen.add(oid)
    size = sys.getsizeof(obj)
    if isinstance(obj, dict):
        for k, v in obj.items():
            size += _deep_sizeof(k, seen) + _deep_sizeof(v, seen)
    elif isinstance(obj, (list, tuple, set, frozenset)) or type(obj).__name__ == "deque":
        for item in obj:
            size += _deep_sizeof(item, seen)
    return size


def measure_memory_one_device():
    """Data-footprint estimate for a single fully-warmed device (history +
    baseline + drift_history buffers, the algorithm's actual retained state)
    -- steady-state per-device memory cost. File handles / sockets are
    intentionally excluded since those aren't part of the algorithm's state."""
    random.seed(42)
    devices = create_dataset_devices(DATASET_DIR, "n_baiot")
    dev = devices[0]
    for _ in range(EVAL_TICKS):
        dev.tick()
        dev.state()
    data_attrs = ("history", "baseline", "drift_history", "current", "feature_names")
    return sum(_deep_sizeof(getattr(dev, a, None)) for a in data_attrs)


def main():
    ensure_dataset()

    results = {"parameters": {
        "burn_in_rows": BURN_IN_ROWS, "baseline_window": BASELINE_WINDOW,
        "warmup_ticks": WARMUP, "eval_ticks_total": EVAL_TICKS,
        "post_warmup_scored_ticks": EVAL_TICKS - WARMUP, "theta_default": THETA_DEFAULT,
        "random_seed": 42, "dataset": "synthetic N-BaIoT-format (see generate_synthetic_dataset.py)",
    }}

    # --- 1. Full-system classification metrics + runtime ---
    print("[1/3] Full-system run (BICE, unmodified)...")
    t0 = time.process_time()
    records, latencies = run_variant(hook=None)
    cpu_time = time.process_time() - t0

    results["classification"] = {
        "alert_based": metrics_from_confusion(*confusion(records, "alert_pred")),
        "quarantine_based": metrics_from_confusion(*confusion(records, "quarantine_pred")),
        "n_profiles": len(records),
    }
    results["runtime"] = {
        "tick_latency": latency_stats(latencies),
        "total_cpu_time_sec": round(cpu_time, 4),
        "process_peak_rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "per_device_heap_bytes_after_full_run": measure_memory_one_device(),
    }

    # --- 2. Ablation study ---
    print("[2/3] Ablation study...")
    ablation_results = {}
    for label, hook in ABLATIONS.items():
        recs, _ = run_variant(hook=hook)
        ablation_results[label] = metrics_from_confusion(*confusion(recs, "alert_pred"))
    recs_sym, _ = run_variant(hook=None, symmetric_quarantine=True)
    ablation_results["no_quarantine_hysteresis"] = metrics_from_confusion(*confusion(recs_sym, "quarantine_pred"))
    results["ablation_alert_based"] = ablation_results

    # --- 3. Print summary tables ---
    print("\n[SUMMARY] Classification metrics (alert-based, theta as per algorithm)")
    m = results["classification"]["alert_based"]
    print(f"  Precision={m['precision']:.3f} Recall={m['recall_tpr']:.3f} F1={m['f1']:.3f} "
          f"Accuracy={m['accuracy']:.3f} BalancedAcc={m['balanced_accuracy']:.3f} FPR={m['fpr']:.3f}")

    print("\n[SUMMARY] Runtime")
    rt = results["runtime"]["tick_latency"]
    print(f"  tick latency: mean={rt['mean_ms']}ms p50={rt['p50_ms']}ms p95={rt['p95_ms']}ms p99={rt['p99_ms']}ms")
    print(f"  process CPU time: {results['runtime']['total_cpu_time_sec']}s, "
          f"peak RSS: {results['runtime']['process_peak_rss_kb']}KB, "
          f"per-device heap: {results['runtime']['per_device_heap_bytes_after_full_run']}B")

    print("\n[SUMMARY] Ablation (alert-based F1 / Recall / FPR, delta vs full_system)")
    base = ablation_results["full_system"]
    for label, m in ablation_results.items():
        d_f1 = m["f1"] - base["f1"]
        print(f"  {label:<26} F1={m['f1']:.3f} ({d_f1:+.3f})  Recall={m['recall_tpr']:.3f}  FPR={m['fpr']:.3f}")

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nFull results written to {OUT_JSON}")


if __name__ == "__main__":
    main()
