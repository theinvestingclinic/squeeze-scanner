# Squeeze Scanner — The Investing Clinic

Answers one question: **Where is market structure pressure building?**

## What it does

| Feature | How |
|---|---|
| Ticker scanner | Unusual call volume ratio across watchlist |
| Gamma map | Call wall, put wall, zero-gamma level (Black-Scholes from yfinance) |
| Squeeze score | 0–100 model: short interest + float + gamma + options fuel + confirmation |
| Volume zones | 30-day volume profile clusters (dark pool proxy until UW API added) |
| Discord alerts | Fires when a stock reaches the potential-squeeze alert gate |

## Quick start

```bash
cd backend
cp .env.example .env         # fill in your Discord webhook + Reddit API keys
pip install -r requirements.txt
uvicorn main:app --reload
```

Open `http://localhost:8000` — the dashboard is served from the same process.

## Or with Docker

```bash
cp backend/.env.example backend/.env   # fill in keys
docker-compose up --build
```

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `DISCORD_WEBHOOK_URL` | Optional | Discord channel webhook for squeeze alerts; preferred |
| `DISCORD_BOT_TOKEN` | Optional | Bot token fallback when no webhook is configured |
| `DISCORD_CHANNEL_ID` | Optional | Bot-token target channel; defaults to `1505287069512237177` |
| `REDDIT_CLIENT_ID` | Optional | Reddit app client ID (free at reddit.com/prefs/apps) |
| `REDDIT_CLIENT_SECRET` | Optional | Reddit app secret |
| `ALERT_THRESHOLD` | No (default 75) | Minimum squeeze score to fire a Discord alert |
| `SCAN_INTERVAL_MINUTES` | No (default 30) | How often to scan during market hours |
| `ALLOWED_ORIGIN` | No | CORS origin for your domain |

Scanner runs without Discord or Reddit configured — those features just silently skip.

Alerts fire from the Short Squeeze Scanner itself after a scan result passes the alert gate: total score at or above `ALERT_THRESHOLD`, setup score at least 20, trigger score at least 20, valid common-stock eligibility, current short-interest data, and no already-squeezed penalty. `DISCORD_WEBHOOK_URL` posts directly to its channel. If no webhook is set, `DISCORD_BOT_TOKEN` posts to `DISCORD_CHANNEL_ID`.

## API endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/scan` | Latest results, sorted by score |
| GET | `/api/ticker/:symbol` | Detail for one ticker |
| POST | `/api/scan/run` | Trigger a manual scan |
| POST | `/api/scan/ticker/:symbol` | Scan one ticker on demand |
| GET | `/api/alerts` | Recent Discord alerts sent |

## Scoring model

| Signal | Max pts | Source |
|---|---|---|
| Short interest % float | 20 | Yahoo Finance (bi-weekly) |
| Float size | 10 | Yahoo Finance |
| Price trend | 10 | yfinance price history |
| Call volume ratio | 15 | yfinance options |
| Negative gamma | 12 | Calculated from options chain |
| Call OI buildup | 10 | yfinance options |
| IV expansion | 8 | yfinance options |
| Breaking key level | 8 | yfinance price history |
| Relative volume | 7 | yfinance volume |
| Reddit saturation | −15 | PRAW (Reddit API) |

## Upgrading to paid data

When ready to add real dark pool data and real-time short interest:
- Replace `short_data.py` with **Ortex API** (~$200/mo)
- Replace `volume_profile.py` with **Unusual Whales API** (~$150/mo)
- Add cost-to-borrow to scoring model (+18 pts available)

## Deploying to your site

The FastAPI backend serves the frontend at `/`. For theinvestingclinic.com:

**Option A — subdomain**: Deploy to `scanner.theinvestingclinic.com` via Railway or Render (free tier available), link from your site.

**Option B — embed**: Deploy backend, add `<iframe src="https://scanner.theinvestingclinic.com" />` to any page.

**Option C — same server**: Set `ALLOWED_ORIGIN=https://theinvestingclinic.com` and call the API from your existing frontend.
