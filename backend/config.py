from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    discord_webhook_url: str = ""
    discord_bot_token: str = ""
    discord_channel_id: str = "1505287069512237177"
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "SqueezeScanner/1.0"
    admin_token: str = ""
    alert_threshold: int = 75
    scan_interval_minutes: int = 30
    database_url: str = "sqlite:////data/scanner.db"
    allowed_origin: str = "https://theinvestingclinic.com"

    class Config:
        env_file = ".env"


settings = Settings()
