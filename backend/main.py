import json
import logging
import asyncio
import hmac
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy.orm import Session
from sqlalchemy import desc

from config import settings
from database import create_tables, get_db, ScanResult, ScanRun, Alert, SessionLocal
from eligibility import ELIGIBLE_COMMON_STOCK
from scheduler import start_scheduler, stop_scheduler
from ticker_filters import EXCLUDED_ETF_TICKERS, is_excluded_ticker


class SensitiveUrlFilter(logging.Filter):
    """Prevent webhook credentials from ever being written by HTTP loggers."""

    WEBHOOK = re.compile(
        r"https://(?:discord(?:app)?\.com)/api(?:/v\d+)?/webhooks/"
        r"[^/\s]+/[^?\s]+"
    )

    def filter(self, record: logging.LogRecord) -> bool:
        rendered = record.getMessage()
        redacted = self.WEBHOOK.sub("https://discord.com/api/webhooks/[REDACTED]", rendered)
        if redacted != rendered:
            record.msg = redacted
            record.args = ()
        return True


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
root_logger = logging.getLogger()
redaction_filter = SensitiveUrlFilter()
for handler in root_logger.handlers:
    handler.addFilter(redaction_filter)

if os.environ.get("LOG_FILE"):
    rotating_handler = RotatingFileHandler(
        os.environ["LOG_FILE"],
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
    )
    rotating_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    rotating_handler.addFilter(redaction_filter)
    root_logger.addHandler(rotating_handler)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger(__name__)
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


async def _startup_scan():
    """Seed an empty database only during an open regular session."""
    import asyncio
    await asyncio.sleep(5)  # let the server finish starting
    try:
        from market_calendar import is_scan_window
        if not is_scan_window():
            log.info("Database seed scan deferred until the next open market session")
            return
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
    """Keep mutation endpoints closed unless an explicit admin token is configured."""
    if not settings.admin_token:
        raise HTTPException(status_code=503, detail="Admin endpoints are disabled")
    if not hmac.compare_digest(x_admin_token, settings.admin_token):
        raise HTTPException(status_code=401, detail="Invalid admin token")


# ── Helper ──────────────────────────────────────────────────────────────────

def _result_to_dict(r: ScanResult, include_detail: bool = True) -> dict:
    score_breakdown = json.loads(r.score_breakdown or "{}")
    eligibility = score_breakdown.get("_eligibility") or {}
    quality = score_breakdown.get("_data_quality") or {}
    reliable_base = (
        quality.get("signals_calibrated")
        and quality.get("has_short_data")
        and (r.setup_score or 0) >= settings.alert_min_setup_score
        and (r.trigger_score or 0) >= settings.alert_min_trigger_score
    )
    potential_base = (
        reliable_base
        and (r.short_interest_pct or 0) >= settings.alert_min_short_interest_pct
        and (r.relative_volume or 0) >= settings.alert_min_relative_volume
    )
    if reliable_base and r.score >= settings.alert_threshold:
        signal_state = "active_trigger"
    elif potential_base and r.score >= settings.alert_potential_threshold:
        signal_state = "setup_watch"
    else:
        signal_state = "monitor"

    payload = {
        "id": r.id,
        "ticker": r.ticker,
        "eligibility_status": eligibility.get("status", "legacy_unknown"),
        "eligibility": eligibility,
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
        "reddit_saturation": r.reddit_saturation,
        "reddit_data_available": bool(quality.get("has_reddit_data", False)),
        "price_change_30d": r.price_change_30d,
        "finra_short_vol_ratio": r.finra_short_vol_ratio,
        "data_quality": quality,
        "signal_state": signal_state,
        "scanned_at": r.scanned_at.isoformat() if r.scanned_at else None,
    }
    if include_detail:
        payload["volume_zones"] = json.loads(r.volume_zones or "[]")
        payload["score_breakdown"] = score_breakdown
    return payload


def _result_is_current_eligible(r: ScanResult) -> bool:
    if is_excluded_ticker(r.ticker):
        return False
    try:
        score_breakdown = json.loads(r.score_breakdown or "{}")
    except Exception:
        return False
    eligibility = score_breakdown.get("_eligibility") or {}
    return eligibility.get("status") == ELIGIBLE_COMMON_STOCK


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


@app.get("/api/scan")
def get_scan_results(
    request: Request,
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
        return JSONResponse(
            {"results": [], "count": 0, "total_scanned": 0},
            headers={"Cache-Control": "public, max-age=60"},
        )

    candidate_rows = (
        db.query(ScanResult)
        .filter(ScanResult.scan_run_id == latest_run.id)
        .filter(~ScanResult.ticker.in_(EXCLUDED_ETF_TICKERS))
        .order_by(desc(ScanResult.score))
        .all()
    )
    rows = [r for r in candidate_rows if _result_is_current_eligible(r)]
    filtered = [r for r in rows if r.score >= min_score]
    results = [_result_to_dict(r, include_detail=False) for r in filtered[: max(1, min(limit, 100))]]
    etag = f'W/"scan-{latest_run.id}-{limit}-{min_score:g}"'
    headers = {
        "Cache-Control": "public, max-age=120, stale-while-revalidate=300",
        "ETag": etag,
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)

    payload = {
        "results": results,
        "count": len(filtered),
        "eligible_count": len(rows),
        "total_scanned": latest_run.ticker_count or len(rows),
        "active_trigger_count": sum(
            1 for row in rows if _result_to_dict(row, include_detail=False)["signal_state"] == "active_trigger"
        ),
        "setup_watch_count": sum(
            1 for row in rows if _result_to_dict(row, include_detail=False)["signal_state"] == "setup_watch"
        ),
        "last_completed": latest_run.completed_at.isoformat() if latest_run.completed_at else None,
    }
    return JSONResponse(payload, headers=headers)


@app.get("/api/ticker/{symbol}")
def get_ticker_detail(symbol: str, db: Session = Depends(get_db)):
    """Latest scan data for a specific ticker."""
    if is_excluded_ticker(symbol):
        raise HTTPException(status_code=404, detail="Ticker is excluded from the squeeze scanner")

    r = (
        db.query(ScanResult)
        .filter(ScanResult.ticker == symbol.upper())
        .order_by(desc(ScanResult.scanned_at))
        .first()
    )
    if not r:
        raise HTTPException(status_code=404, detail="Ticker not found in scan results")
    if not _result_is_current_eligible(r):
        raise HTTPException(status_code=404, detail="Ticker is not eligible for current squeeze scanner")
    return _result_to_dict(r)


@app.get("/api/scan/status")
def scan_status(db: Session = Depends(get_db)):
    """Current scan state — used by the frontend to show progress."""
    from scanner import is_scan_running
    latest_run = (
        db.query(ScanRun)
        .order_by(desc(ScanRun.started_at))
        .first()
    )
    return {
        "scanning": is_scan_running(),
        "last_run_started": latest_run.started_at.isoformat() if latest_run else None,
        "last_run_completed": latest_run.completed_at.isoformat() if latest_run and latest_run.completed_at else None,
        "last_run_tickers": latest_run.ticker_count if latest_run else 0,
    }


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
    symbol = symbol.upper()
    if is_excluded_ticker(symbol):
        raise HTTPException(status_code=400, detail="ETFs and funds are excluded from the squeeze scanner")

    data = scan_ticker(symbol)
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
    rows = [r for r in rows if not is_excluded_ticker(r.ticker)]
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
            {
                "ticker": a.ticker,
                "score": a.score,
                "sent_at": a.sent_at.isoformat(),
                "return_1d": a.return_1d,
                "return_5d": a.return_5d,
                "max_favorable_5d": a.max_favorable_5d,
                "max_drawdown_5d": a.max_drawdown_5d,
            }
            for a in alerts
        ]
    }


# ── Serve frontend ────────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
def serve_frontend():
    return FileResponse(FRONTEND_DIR / "index.html")
