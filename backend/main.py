import json
import logging
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc

from config import settings
from database import create_tables, get_db, ScanResult, ScanRun, Alert, SessionLocal
from scheduler import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


async def _startup_scan():
    """Run a scan on startup if the database is empty."""
    import asyncio
    await asyncio.sleep(5)  # let the server finish starting
    try:
        db = SessionLocal()
        count = db.query(ScanResult).count()
        db.close()
        if count == 0:
            log.info("Database empty on startup — running initial scan")
            from scanner import run_full_scan
            await run_full_scan()
    except Exception as e:
        log.warning(f"Startup scan failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    start_scheduler()
    import asyncio
    asyncio.create_task(_startup_scan())
    yield
    stop_scheduler()


app = FastAPI(title="Squeeze Scanner", version="1.0.0", lifespan=lifespan)

def _build_origins(origin: str) -> list[str]:
    """Always allow both www and non-www variants of the configured origin."""
    origins = {origin, "http://localhost:3000", "http://localhost:8080"}
    if origin.startswith("https://www."):
        origins.add(origin.replace("https://www.", "https://"))
    elif origin.startswith("https://"):
        origins.add(origin.replace("https://", "https://www."))
    return list(origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_build_origins(settings.allowed_origin),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Auth ─────────────────────────────────────────────────────────────────────

def require_admin(x_admin_token: str = Header(default="")):
    """Protect mutation endpoints. If ADMIN_TOKEN is set in env, enforce it."""
    if settings.admin_token and x_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Invalid admin token")


# ── Helper ──────────────────────────────────────────────────────────────────

def _result_to_dict(r: ScanResult) -> dict:
    return {
        "id": r.id,
        "ticker": r.ticker,
        "score": r.score,
        "setup_score": r.setup_score,
        "trigger_score": r.trigger_score,
        "price": r.price,
        "short_interest_pct": r.short_interest_pct,
        "float_shares_m": r.float_shares_m,
        "price_trend_score": r.price_trend_score,
        "call_volume_ratio": r.call_volume_ratio,
        "is_negative_gamma": r.is_negative_gamma,
        "call_oi_pct_change": r.call_oi_pct_change,
        "iv_percentile": r.iv_percentile,
        "breaking_key_level": r.breaking_key_level,
        "relative_volume": r.relative_volume,
        "call_wall": r.call_wall,
        "put_wall": r.put_wall,
        "zero_gamma": r.zero_gamma,
        "net_gex": r.net_gex,
        "volume_zones": json.loads(r.volume_zones or "[]"),
        "reddit_saturation": r.reddit_saturation,
        "price_change_30d": r.price_change_30d,
        "finra_short_vol_ratio": r.finra_short_vol_ratio,
        "score_breakdown": json.loads(r.score_breakdown or "{}"),
        "scanned_at": r.scanned_at.isoformat() if r.scanned_at else None,
    }


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


@app.get("/api/scan")
def get_scan_results(
    limit: int = 50,
    min_score: float = 0,
    db: Session = Depends(get_db),
):
    """Results from the latest completed scan run, sorted by score descending."""
    latest_run = (
        db.query(ScanRun)
        .filter(ScanRun.completed_at.isnot(None))
        .order_by(desc(ScanRun.completed_at))
        .first()
    )
    if not latest_run:
        return {"results": [], "count": 0}

    rows = (
        db.query(ScanResult)
        .filter(ScanResult.scan_run_id == latest_run.id, ScanResult.score >= min_score)
        .order_by(desc(ScanResult.score))
        .limit(limit)
        .all()
    )
    return {"results": [_result_to_dict(r) for r in rows], "count": len(rows)}


@app.get("/api/ticker/{symbol}")
def get_ticker_detail(symbol: str, db: Session = Depends(get_db)):
    """Latest scan data for a specific ticker."""
    r = (
        db.query(ScanResult)
        .filter(ScanResult.ticker == symbol.upper())
        .order_by(desc(ScanResult.scanned_at))
        .first()
    )
    if not r:
        raise HTTPException(status_code=404, detail="Ticker not found in scan results")
    return _result_to_dict(r)


@app.post("/api/scan/run")
async def trigger_scan(
    background_tasks: BackgroundTasks,
    _: None = Depends(require_admin),
):
    """Manually trigger a full scan (runs in background)."""
    from scanner import run_full_scan, is_scan_running
    if is_scan_running():
        return {"message": "Scan already running", "time": datetime.utcnow().isoformat()}
    background_tasks.add_task(run_full_scan, settings.alert_threshold)
    return {"message": "Scan started", "time": datetime.utcnow().isoformat()}


@app.post("/api/scan/ticker/{symbol}")
async def scan_single_ticker(
    symbol: str,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Scan a single ticker on demand."""
    from scanner import scan_ticker, save_result
    data = scan_ticker(symbol.upper())
    if not data:
        raise HTTPException(status_code=400, detail=f"Could not fetch data for {symbol}")
    save_result(db, data)
    return data


@app.post("/api/discovery/run")
async def trigger_discovery(
    background_tasks: BackgroundTasks,
    _: None = Depends(require_admin),
):
    """Manually trigger the FINRA ticker discovery sweep."""
    from ticker_discovery import run_discovery
    from database import SessionLocal

    async def _run():
        db = SessionLocal()
        try:
            await run_discovery(db)
        finally:
            db.close()

    background_tasks.add_task(_run)
    return {"message": "Discovery started", "time": datetime.utcnow().isoformat()}


@app.get("/api/discovery/tickers")
def get_discovered_tickers(db: Session = Depends(get_db)):
    """List all active tickers found via FINRA discovery."""
    from database import DiscoveredTicker
    rows = db.query(DiscoveredTicker).filter_by(is_active=True).order_by(
        DiscoveredTicker.last_seen_at.desc()
    ).all()
    return {
        "count": len(rows),
        "tickers": [
            {"ticker": r.ticker, "discovered_at": r.discovered_at.isoformat(),
             "last_seen_at": r.last_seen_at.isoformat()}
            for r in rows
        ]
    }


@app.get("/api/alerts")
def get_alerts(limit: int = 20, db: Session = Depends(get_db)):
    """Recent Discord alerts that were sent."""
    alerts = (
        db.query(Alert)
        .order_by(desc(Alert.sent_at))
        .limit(limit)
        .all()
    )
    return {
        "alerts": [
            {"ticker": a.ticker, "score": a.score, "sent_at": a.sent_at.isoformat()}
            for a in alerts
        ]
    }


# ── Serve frontend ────────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory="../frontend"), name="static")


@app.get("/")
def serve_frontend():
    return FileResponse("../frontend/index.html")
