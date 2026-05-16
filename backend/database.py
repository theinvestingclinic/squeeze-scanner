from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
from config import settings

engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class ScanResult(Base):
    __tablename__ = "scan_results"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String, index=True)
    score = Column(Float, default=0)
    price = Column(Float, default=0)

    # Foundation
    short_interest_pct = Column(Float, default=0)
    float_shares_m = Column(Float, default=0)
    price_trend_score = Column(Float, default=0)

    # Options fuel
    call_volume_ratio = Column(Float, default=0)
    is_negative_gamma = Column(Boolean, default=False)
    call_oi_pct_change = Column(Float, default=0)
    iv_percentile = Column(Float, default=0)

    # Confirmation
    breaking_key_level = Column(Boolean, default=False)
    relative_volume = Column(Float, default=0)

    # Gamma map
    call_wall = Column(Float, nullable=True)
    put_wall = Column(Float, nullable=True)
    zero_gamma = Column(Float, nullable=True)
    net_gex = Column(Float, default=0)

    # Volume zones (JSON list)
    volume_zones = Column(Text, default="[]")

    # Danger
    reddit_saturation = Column(Float, default=0)
    price_change_30d = Column(Float, default=0)

    # Score breakdown (JSON)
    score_breakdown = Column(Text, default="{}")

    alert_sent = Column(Boolean, default=False)
    scanned_at = Column(DateTime, default=datetime.utcnow)


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String, index=True)
    score = Column(Float)
    message = Column(Text)
    sent_at = Column(DateTime, default=datetime.utcnow)


def create_tables():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
