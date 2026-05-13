#!/usr/bin/env python3
import json, time, requests

def get_state():
    try:
        r = requests.get('http://localhost:8000/api/state', timeout=10)
        return r.json() if r.status_code == 200 else None
    except:
        return None

def classify_device(name):
    if "(Normal)" in name:
        return "benign"
    elif any(x in name for x in ["Gafgyt", "Mirai"]):
        return "attack"
    return "unknown"

def evaluate_once(devices):
    tp = fp = tn = fn = 0
    for d in devices:
        expected = classify_device(d["name"])
        is_attacked = d["quarantine"]
        if expected == "benign":
            if is_attacked: fp += 1
            else: tn += 1
        elif expected == "attack":
            if is_attacked: tp += 1
            else: fn += 1
    
    total_a = tp + fn
    total_b = tn + fp
    total_p = tp + fp
    
    tpr = (tp / total_a * 100) if total_a > 0 else 0
    fpr = (fp / total_b * 100) if total_b > 0 else 0
    prec = (tp / total_p * 100) if total_p > 0 else 0
    f1 = (2 * prec * tpr / (prec + tpr)) if (prec + tpr) > 0 else 0
    
    return {"tpr": tpr, "fpr": fpr, "precision": prec, "f1": f1, "tp": tp, "fp": fp, "tn": tn, "fn": fn, "ta": total_a, "tb": total_b}

print("=" * 70)
print("N-BaIoT Optimization Evaluation")
print("=" * 70)
print()
print("Waiting for stabilization (baseline + 200 ticks)...")
time.sleep(220)

results = []
for it in range(10):
    state = get_state()
    if not state:
        print(f"[{it}] API unreachable")
        continue
    
    devices = state.get("assets", [])
    m = evaluate_once(devices)
    results.append(m)
    print(f"[{it}] TPR={m['tpr']:6.1f}% FPR={m['fpr']:6.1f}% Prec={m['precision']:6.1f}% F1={m['f1']:6.1f}% (TP={m['tp']} FP={m['fp']} TN={m['tn']} FN={m['fn']})")
    
    if it < 9:
        time.sleep(30)

print()
print("=" * 70)
print("SUMMARY")
print("=" * 70)

avg_tpr = sum(r["tpr"] for r in results) / len(results)
avg_fpr = sum(r["fpr"] for r in results) / len(results)
avg_prec = sum(r["precision"] for r in results) / len(results)
avg_f1 = sum(r["f1"] for r in results) / len(results)

print(f"TPR (True Positive Rate):  {avg_tpr:6.1f}%")
print(f"FPR (False Positive Rate): {avg_fpr:6.1f}%")
print(f"Precision:                 {avg_prec:6.1f}%")
print(f"F1-Score:                  {avg_f1:6.1f}%")
print()
print(f"✓ Improvement from 50% baseline: +{(avg_tpr - 50):.1f} pp")
