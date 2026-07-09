import asyncio, random, math, sqlite3, json, os
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
import io
from engine.engine import devices, device_map, DATASET_MODE

try:
    from engine.dataset import cleanup_dataset_dirs
except ImportError:
    def cleanup_dataset_dirs():
        pass

DB_PATH = "results/bice.db"

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                device TEXT,
                drift REAL,
                trust INTEGER,
                metrics TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                device TEXT,
                drift REAL,
                explanation TEXT
            )
        """)
        conn.commit()

def log_telemetry(device_name, state):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO telemetry (timestamp, device, drift, trust, metrics) VALUES (?, ?, ?, ?, ?)",
            (datetime.now().isoformat(), device_name, state["drift"], state["trust"], json.dumps(state["features"]))
        )
        if state["alert"]:
            conn.execute(
                "INSERT INTO alerts (timestamp, device, drift, explanation) VALUES (?, ?, ?, ?)",
                (datetime.now().isoformat(), device_name, state["drift"], state["explanation"])
            )
        conn.commit()

alerts_cache = [] # Keep recent in memory for quick UI access
calibrated = set()  # Track which devices have been calibrated
calibration_log = []  # Log calibration events

async def telemetry_loop():
    prev_alert = {d.name: False for d in devices}
    while True:
        for d in devices:
            d.tick()
            d.adapt_baseline() # Gated learning
            s = d.state()
            if s:
                log_telemetry(d.name, s)
                
                # Calibrate theta for benign devices (one-time, when they have enough data)
                if d.name not in calibrated and not d.attacked and getattr(d, "drift_history", None) and len(d.drift_history) > 100:
                    old_theta = d.calibrated_theta
                    d.calibrate_theta()
                    calibrated.add(d.name)
                    log_entry = f"[{datetime.now().strftime('%H:%M:%S')}] Calibrated {d.name}: theta={d.calibrated_theta} (was {old_theta})"
                    calibration_log.append(log_entry)
                    if len(calibration_log) > 50:
                        calibration_log.pop(0)
                
                if s["alert"] and not prev_alert[d.name]:
                    alerts_cache.insert(0, {
                        "device":  d.name, 
                        "drift":   s["drift"], 
                        "time":    datetime.now().strftime("%H:%M:%S"),
                        "msg":     s["explanation"]
                    })
                    if len(alerts_cache) > 20: alerts_cache.pop()
                prev_alert[d.name] = s["alert"]
            else:
                prev_alert[d.name] = False
        await asyncio.sleep(0)

async def attack_simulator():
    while True:
        # Randomly inject attacks if no one is currently being attacked
        if not any(d.attacked for d in devices):
            await asyncio.sleep(random.randint(15, 30))
            target = random.choice(devices)
            target.attacked = True
            await asyncio.sleep(random.randint(20, 40))
            target.attacked = False
        await asyncio.sleep(5)

@asynccontextmanager
async def lifespan(_):
    init_db()
    asyncio.create_task(telemetry_loop())
    if not DATASET_MODE:
        asyncio.create_task(attack_simulator())
    yield
    cleanup_dataset_dirs()

app = FastAPI(lifespan=lifespan)

DASHBOARD_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard", "index.html")

@app.get("/")
def index(): return FileResponse(DASHBOARD_PATH)

@app.get("/api/calibration")
def get_calibration():
    return {"calibrated_count": len(calibrated), "logs": calibration_log}

@app.get("/api/state")
def get_state():
    assets = []
    for d in devices:
        s = d.state()
        if not s:
            continue
        # Build recent snapshots for UI sparklines
        # Use the feature keys from the state response for consistency
        feature_keys = list(s.get('features', {}).keys())
        if not feature_keys and hasattr(d, 'feature_names'):
            feature_keys = list(d.feature_names)[:5]  # Limit to first 5 for display
        
        recent = []
        for row in list(getattr(d, 'history', []))[-16:]:
            try:
                if isinstance(row, dict):
                    # Row is already a dict (synthetic devices)
                    rec = {k: round(float(row.get(k)), 2) if row.get(k) is not None else None for k in feature_keys}
                elif isinstance(row, (list, tuple)):
                    # Row is a list/tuple (dataset devices) - map indices to feature names
                    feature_names = getattr(d, 'feature_names', []) or feature_keys
                    rec = {}
                    for i, k in enumerate(feature_names[:5]):  # Limit to first 5
                        if i < len(row):
                            v = row[i]
                            rec[k] = round(float(v), 2) if v is not None else None
                else:
                    rec = {}
            except Exception:
                rec = {}
            recent.append(rec)

        s['recent'] = recent
        assets.append(s)

    if len(assets) < len(devices) * 0.9:
        return {"ready": False}

    return {
        "ready": True,
        "assets": assets,
        "alerts": alerts_cache,
    }


@app.get('/api/export')
def export_telemetry(format: str = 'csv', device: str = None, limit: int = 10000):
    """Export telemetry rows. `format` can be `csv` or `json`. Optional `device` filter and `limit`.
    Streams results to avoid loading large DB into memory.
    """
    def iter_json(rows):
        yield '['
        first = True
        for r in rows:
            if not first: yield ','
            first = False
            yield json.dumps({
                'id': r[0], 'timestamp': r[1], 'device': r[2], 'drift': r[3], 'trust': r[4], 'metrics': json.loads(r[5] or '{}')
            })
        yield ']'

    def iter_csv(rows):
        buf = io.StringIO()
        writer_header = 'id,timestamp,device,drift,trust,metrics\n'
        yield writer_header
        for r in rows:
            # metrics as JSON string escaped
            metrics = r[5].replace('"', '""') if r[5] else ''
            line = f'{r[0]},{r[1]},{r[2]},{r[3]},{r[4]},"{metrics}"\n'
            yield line

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    q = "SELECT id,timestamp,device,drift,trust,metrics FROM telemetry"
    params = []
    if device:
        q += " WHERE device = ?"
        params.append(device)
    q += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    cur.execute(q, params)
    rows = cur.fetchall()
    conn.close()

    # we fetched descending; reverse to chronological
    rows = list(reversed(rows))

    if format == 'json':
        return StreamingResponse(iter_json(rows), media_type='application/json')
    else:
        return StreamingResponse(iter_csv(rows), media_type='text/csv')

@app.post("/api/attack/{name}")
def toggle_attack(name: str):
    d = device_map.get(name)
    if not d: return {"error": "not found"}
    d.attacked = not d.attacked
    return {"device": name, "attacked": d.attacked}

@app.post("/api/quarantine/{name}")
def toggle_quarantine(name: str):
    d = device_map.get(name)
    if not d: return {"error": "not found"}
    d.quarantine = not d.quarantine
    return {"device": name, "quarantine": d.quarantine}

@app.post("/api/reset")
def reset_run():
    """Resets all devices for a clean second (or Nth) run.
    Rewinds CSVs to row 0, clears all statistical state and calibration."""
    global calibrated, calibration_log
    for d in devices:
        if hasattr(d, 'reset'):
            d.reset()
    calibrated = set()
    calibration_log = []
    alerts_cache.clear()
    return {"status": "reset", "devices": len(devices)}
