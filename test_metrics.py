#!/usr/bin/env python3
# Run this AFTER server is already up:
#   BICE_DATASET_PATH=/home/smtx724/Downloads/archive_mini python3 -m uvicorn main:app --host 0.0.0.0 --port 8000

import sys
import time
import json
import urllib.request

def get_state():
    try:
        resp = urllib.request.urlopen('http://localhost:8000/api/state', timeout=5)
        return json.load(resp)
    except Exception:
        return None

# Wait for server + baselines
print("Waiting for server and baselines...")
for i in range(150):
    state = get_state()
    if state is None:
        print(f"  {i*5}s: server not up yet")
        time.sleep(5)
        continue

    assets = state.get('assets', [])
    if state.get('ready'):
        print(f"✓ Ready after {i*5}s — {len(assets)} devices")
        break

    print(f"  {i*5}s: {len(assets)} devices seen, not ready yet")
    time.sleep(5)
else:
    print("Timeout — server never became ready")
    sys.exit(1)

# Grab metrics
state = get_state()
assets = state.get('assets', [])

if not assets:
    print("ERROR: no assets")
    sys.exit(1)

tp  = sum(1 for a in assets if a.get('attacked') and a.get('alert'))
fp  = sum(1 for a in assets if not a.get('attacked') and a.get('alert'))
fn  = sum(1 for a in assets if a.get('attacked') and not a.get('alert'))
tn  = sum(1 for a in assets if not a.get('attacked') and not a.get('alert'))
att = sum(1 for a in assets if a.get('attacked'))
ben = sum(1 for a in assets if not a.get('attacked'))

print(f"\nTP={tp}  FP={fp}  FN={fn}  TN={tn}")
print(f"TPR={tp}/{att} ({100*tp/att if att else 0:.1f}%)")
print(f"FPR={fp}/{ben} ({100*fp/ben if ben else 0:.1f}%)")
print()

# Top 20 by drift
for a in sorted(assets, key=lambda x: x.get('drift', 0), reverse=True)[:20]:
    print(f"{a.get('name')}: drift={a.get('drift'):.2f} trust={a.get('trust')}% attacked={a.get('attacked')} alert={a.get('alert')}")
