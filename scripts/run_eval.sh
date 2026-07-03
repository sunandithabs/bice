pkill -f "uvicorn main:app"
sleep 2
cd ~/projects/bice && BICE_DATASET_PATH=/home/smtx724/Downloads/archive python3 -m uvicorn main:app --port 8000 &
sleep 120 && python3 test_metrics.py && curl -s http://127.0.0.1:8000/api/state | python3 -c "
import sys,json,statistics
assets=[a for a in json.load(sys.stdin).get('assets',[]) if a]
drifts=[a['drift'] for a in assets]
trust=[a['trust'] for a in assets]
print('total:', len(assets))
print('attacked:', sum(1 for a in assets if a.get('attacked')))
print('benign:', sum(1 for a in assets if not a.get('attacked')))
print('mean_drift:', round(statistics.mean(drifts),1))
print('median_drift:', round(statistics.median(drifts),1))
print('min_drift:', round(min(drifts),2))
print('max_drift:', round(max(drifts),1))
print('mean_trust:', round(statistics.mean(trust),1))
print('min_trust:', min(trust))
print('max_trust:', max(trust))
for a in sorted(assets, key=lambda x: x.get('drift',0), reverse=True)[:20]:
    print(f'  {a[\"name\"]}: drift={a[\"drift\"]:.2f} trust={a[\"trust\"]} attacked={a[\"attacked\"]} alert={a[\"alert\"]}')
"
