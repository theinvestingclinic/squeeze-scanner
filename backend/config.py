from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = Path(__file__).resolve().with_name(".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE)

    discord_webhook_url: str = ""
    discord_bot_token: str = ""
    discord_channel_id: str = "1505287069512237177"
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "SqueezeScanner/1.0"
    admin_token: str = ""
    alert_threshold: int = 75
    alert_potential_threshold: int = 50
    alert_min_setup_score: float = 20
    alert_min_trigger_score: float = 20
    alert_min_short_interest_pct: float = 20
    alert_min_relative_volume: float = 2
    alert_require_calibration: bool = True
    alert_digest_max_names: int = 5
    alert_material_score_change: float = 10
    alert_material_trigger_change: float = 8
    scan_interval_minutes: int = 30
    scan_history_days: int = 35
    enable_reddit_signal: bool = False
    database_url: str = "sqlite:////data/scanner.db"
    allowed_origin: str = "https://theinvestingclinic.com"

settings = Settings()
