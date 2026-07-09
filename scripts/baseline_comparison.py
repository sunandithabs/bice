#!/usr/bin/env python3
"""
baseline_comparison.py

Runs BICE alongside sklearn's IsolationForest and OneClassSVM on the *same*
per-device N-BaIoT data, using the same baseline / evaluation split
BICE itself uses. Produces:

  1. A real TPR/FPR comparison table (BICE vs IF vs OC-SVM), replacing the
     "contextual comparison" table in the paper that currently cites other
     papers' numbers on different datasets.
  2. A theta-sensitivity sweep for BICE, free of extra cost, since drift is
     computed once per tick and re-thresholding it for different theta values
     needs no re-run.

Usage:
    python3 scripts/baseline_comparison.py --dataset /path/to/n-baiot

Output:
    Prints a summary table to stdout and writes results/baseline_comparison.json
"""
import argparse
import json
import os
import random
import sys
import time

random.seed(42)  # deterministic: DatasetDevice itself has no RNG, but this
# keeps behavior reproducible if invoked alongside other seeded code paths.

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.dataset import create_dataset_devices  # noqa: E402

EVAL_TICKS = 400  # 60 burn-in + 300-row baseline + 40-tick held-out test window
WARMUP = 300  # matches DatasetDevice's baseline window (engine/dataset.py)
THETA_SWEEP = [2.0, 2.5, 3.0, 3.5, 4.0]


def device_id_of(dev):
    """Recover the physical device id ("1".."9") from the CSV filename,
    mirroring the grouping logic in engine/dataset.py::create_dataset_devices."""
    base = os.path.splitext(os.path.basename(dev.row_file_path))[0]
    return base.split('.')[0]


def top_drift_feature(dev):
    """After a device has been ticked, recompute per-feature z at the final
    test window and return the feature name/z with the largest magnitude —
    for diagnosing which feature is driving a saturated drift score."""
    if dev.baseline is None or len(dev.history) < 300:
        return None
    test = list(dev.history)[-20:]
    best = None
    for i, (mean, sigma) in enumerate(dev.baseline):
        tv = [t[i] for t in test]
        obs_mean = sum(tv) / len(tv)
        se = sigma
        z = (obs_mean - mean) / se
        if best is None or abs(z) > abs(best[1]):
            best = (dev.feature_names[i], z, mean, sigma)
    return best


def collect_profile(dev):
    """Tick a DatasetDevice for EVAL_TICKS ticks, returning:
      - baseline_rows: raw feature vectors from the first WARMUP ticks, for sklearn training
      - raw_rows: raw feature vectors (post-warmup), for sklearn scoring
      - drift_trace: BICE's own per-tick mean-abs-Z drift values (post-warmup)
    """
    baseline_rows = []
    raw_rows = []
    drift_trace = []

    for i in range(EVAL_TICKS):
        dev.tick()
        if i < WARMUP:
            baseline_rows.append([dev.current[k] for k in dev.feature_names])
            continue
        raw_rows.append([dev.current[k] for k in dev.feature_names])
        s = dev.state()
        if s is not None:
            drift_trace.append(float(s["drift"]))

    return baseline_rows, raw_rows, drift_trace


def bice_alert_at_theta(drift_trace, theta):
    """A profile is flagged if its BICE drift crosses theta on any post-warmup
    tick — matches the alert condition Delta > theta used throughout the paper."""
    return any(d > theta for d in drift_trace)


def sklearn_alert(model, scaler, rows):
    """A profile is flagged if the majority of its post-warmup ticks are
    scored as outliers (-1) by the sklearn model. Majority vote keeps the
    decision rule symmetric with BICE's persistent-drift alert, rather than
    flagging on a single noisy tick."""
    if not rows:
        return False
    X = scaler.transform(rows)
    preds = model.predict(X)
    outlier_frac = (preds == -1).mean()
    return bool(outlier_frac > 0.5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, help="Path to N-BaIoT dataset folder")
    parser.add_argument("--out", default="results/baseline_comparison.json")
    args = parser.parse_args()

    from sklearn.ensemble import IsolationForest
    from sklearn.svm import OneClassSVM
    from sklearn.preprocessing import StandardScaler

    print(f"Loading device profiles from {args.dataset} ...")
    devices = create_dataset_devices(args.dataset, "n_baiot")
    print(f"Found {len(devices)} profiles.")

    by_physical_device = {}
    for dev in devices:
        by_physical_device.setdefault(device_id_of(dev), []).append(dev)

    results = []
    t0 = time.time()

    for phys_id, profiles in sorted(by_physical_device.items()):
        benign = next((d for d in profiles if not d.default_attacked), None)
        if benign is None:
            print(f"  [device {phys_id}] no benign profile found, skipping device")
            continue

        print(f"[device {phys_id}] establishing baseline from {benign.name} ...")
        baseline_rows, benign_test_rows, benign_drift = collect_profile(benign)

        scaler = StandardScaler().fit(baseline_rows)
        X_train = scaler.transform(baseline_rows)

        iso = IsolationForest(contamination=0.1, random_state=42).fit(X_train)
        ocsvm = OneClassSVM(nu=0.1, kernel="rbf", gamma="scale").fit(X_train)

        results.append({
            "device": phys_id,
            "profile": benign.name,
            "label": "benign",
            "bice_drift_trace": benign_drift,
            "bice_alert": {str(t): bice_alert_at_theta(benign_drift, t) for t in THETA_SWEEP},
            "iforest_alert": sklearn_alert(iso, scaler, benign_test_rows),
            "ocsvm_alert": sklearn_alert(ocsvm, scaler, benign_test_rows),
        })
        if benign_drift:
            print(f"    drift: min={min(benign_drift):.1f} mean={sum(benign_drift)/len(benign_drift):.1f} max={max(benign_drift):.1f}")
            top = top_drift_feature(benign)
            if top:
                print(f"    top feature: {top[0]} z={top[1]:.1f} baseline_mean={top[2]:.4g} baseline_sigma={top[3]:.4g}")

        for dev in profiles:
            if dev is benign:
                continue
            print(f"[device {phys_id}] scoring {dev.name} ...")
            _, attack_rows, attack_drift = collect_profile(dev)
            results.append({
                "device": phys_id,
                "profile": dev.name,
                "label": "attack",
                "bice_drift_trace": attack_drift,
                "bice_alert": {str(t): bice_alert_at_theta(attack_drift, t) for t in THETA_SWEEP},
                "iforest_alert": sklearn_alert(iso, scaler, attack_rows),
                "ocsvm_alert": sklearn_alert(ocsvm, scaler, attack_rows),
            })

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s. Computing summary ...")

    def confusion(method_key, theta=None):
        tp = fp = tn = fn = 0
        for r in results:
            if method_key == "bice":
                alert = r["bice_alert"][str(theta)]
            else:
                alert = r[method_key]
            if r["label"] == "attack":
                tp += alert
                fn += not alert
            else:
                fp += alert
                tn += not alert
        return tp, fp, tn, fn

    def full_metrics(tp, fp, tn, fn):
        precision = tp / (tp + fp) if (tp + fp) else float("nan")
        recall = tp / (tp + fn) if (tp + fn) else float("nan")  # TPR
        f1 = (2 * precision * recall / (precision + recall)
              if precision == precision and recall == recall and (precision + recall) else float("nan"))
        accuracy = (tp + tn) / (tp + fp + tn + fn) if (tp + fp + tn + fn) else float("nan")
        tnr = tn / (tn + fp) if (tn + fp) else float("nan")
        balanced_accuracy = (recall + tnr) / 2
        fpr = fp / (fp + tn) if (fp + tn) else float("nan")
        return {"precision": precision, "recall_tpr": recall, "f1": f1, "accuracy": accuracy,
                "balanced_accuracy": balanced_accuracy, "fpr": fpr, "tp": tp, "fn": fn, "fp": fp, "tn": tn}

    summary = {"n_profiles": len(results), "runtime_sec": round(elapsed, 1), "comparison": {}, "theta_sweep": {}}

    print("\n=== Method comparison (BICE @ theta=3.0) ===")
    print(f"{'Method':<16} {'Prec':>7} {'Recall':>7} {'F1':>7} {'Acc':>7} {'BalAcc':>7} {'FPR':>7}")
    for key, label in [("bice", "BICE"), ("iforest_alert", "IsolationForest"), ("ocsvm_alert", "OC-SVM")]:
        theta = 3.0 if key == "bice" else None
        m = full_metrics(*confusion(key, theta))
        print(f"{label:<16} {m['precision']*100:>6.1f}% {m['recall_tpr']*100:>6.1f}% {m['f1']*100:>6.1f}% "
              f"{m['accuracy']*100:>6.1f}% {m['balanced_accuracy']*100:>6.1f}% {m['fpr']*100:>6.1f}%   "
              f"(TP={m['tp']} FN={m['fn']} FP={m['fp']} TN={m['tn']})")
        summary["comparison"][label] = m

    print("\n=== BICE theta sensitivity sweep ===")
    print(f"{'Theta':<8} {'Prec':>7} {'Recall':>7} {'F1':>7} {'Acc':>7} {'BalAcc':>7} {'FPR':>7}")
    for theta in THETA_SWEEP:
        m = full_metrics(*confusion("bice", theta))
        print(f"{theta:<8} {m['precision']*100:>6.1f}% {m['recall_tpr']*100:>6.1f}% {m['f1']*100:>6.1f}% "
              f"{m['accuracy']*100:>6.1f}% {m['balanced_accuracy']*100:>6.1f}% {m['fpr']*100:>6.1f}%")
        summary["theta_sweep"][str(theta)] = m

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump({"summary": summary, "per_profile": results}, f, indent=2)
    print(f"\nFull results written to {args.out}")
    print("Paste the two tables above back into chat and I'll drop them into the paper.")


if __name__ == "__main__":
    main()
