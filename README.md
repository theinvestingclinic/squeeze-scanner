# Squeeze Scanner — The Investing Clinic

Answers one question: **Where is market structure pressure building?**

## What it does

| Feature | How |
|---|---|
| Ticker scanner | Call-volume/open-interest activity proxy across the watchlist |
| Gamma map | Options-open-interest gamma proxy, call wall, put wall, and zero-gamma estimate |
| Squeeze score | 0–100 model: short interest + float + gamma + options fuel + confirmation |
| Volume zones | 30-day volume profile clusters (dark pool proxy until UW API added) |
| Discord alerts | One capped digest for calibrated, material state transitions |

## Quick start

```bash
cd backend
cp .env.example .env         # fill in your Discord webhook + Reddit API keys
pip install -r requirements.txt
uvicorn main:app --reload
```

Open `http://localhost:8000` — the dashboard is served from the same process.

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `DISCORD_WEBHOOK_URL` | Optional | Discord channel webhook for squeeze alerts; preferred |
| `DISCORD_BOT_TOKEN` | Optional | Bot token fallback when no webhook is configured |
| `DISCORD_CHANNEL_ID` | Optional | Bot-token target channel; defaults to `1505287069512237177` |
| `REDDIT_CLIENT_ID` | Optional | Reddit app client ID (free at reddit.com/prefs/apps) |
| `REDDIT_CLIENT_SECRET` | Optional | Reddit app secret |
| `ADMIN_TOKEN` | Optional | Enables mutation endpoints; if blank, all manual POST endpoints return 503 |
| `ALERT_THRESHOLD` | No (default 75) | Hot-tier squeeze score to fire a Discord alert |
| `ALERT_POTENTIAL_THRESHOLD` | No (default 50) | Secondary potential-squeeze score gate |
| `ALERT_MIN_SETUP_SCORE` | No (default 20) | Minimum setup score required for alerts |
| `ALERT_MIN_TRIGGER_SCORE` | No (default 20) | Minimum trigger score required for alerts |
| `ALERT_MIN_SHORT_INTEREST_PCT` | No (default 20) | Minimum short interest required for potential-squeeze alerts |
| `ALERT_MIN_RELATIVE_VOLUME` | No (default 2) | Minimum relative volume required for potential-squeeze alerts |
| `ALERT_REQUIRE_CALIBRATION` | No (default true) | Blocks alerts until at least five prior observations exist |
| `ALERT_DIGEST_MAX_NAMES` | No (default 5) | Maximum names in one transition digest |
| `SCAN_HISTORY_DAYS` | No (default 35) | Local history retained for 30-day calibration |
| `ENABLE_REDDIT_SIGNAL` | No (default false) | Enables the experimental Reddit penalty when credentials exist |
| `SCAN_INTERVAL_MINUTES` | No (default 30) | How often to scan during market hours |
| `ALLOWED_ORIGIN` | No | CORS origin for your domain |

Scanner runs without Discord or Reddit configured — those features just silently skip.

Alerts fire only after calibration is ready and a candidate enters a higher
signal tier or improves materially. Names from the same scan are grouped into
one capped digest. Stable readings do not repeat merely because 24 hours have
elapsed. `DISCORD_WEBHOOK_URL` posts directly to its channel. If no webhook is
set, `DISCORD_BOT_TOKEN` posts to `DISCORD_CHANNEL_ID`.

## API endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/scan` | Latest results, sorted by score |
| GET | `/api/ticker/:symbol` | Detail for one ticker |
| POST | `/api/scan/run` | Trigger a manual scan; requires `X-Admin-Token` |
| POST | `/api/scan/ticker/:symbol` | Scan one ticker on demand; requires `X-Admin-Token` |
| GET | `/api/alerts` | Recent Discord alerts sent |

## Scoring model

| Signal | Max pts | Source |
|---|---|---|
| Short interest % float | 20 | Yahoo Finance (bi-weekly) |
| Float size | 10 | Yahoo Finance |
| Price trend | 10 | yfinance price history |
| Call-volume/OI proxy | 15 | yfinance options |
| Options-OI gamma proxy | 12 | Modelled from the options chain |
| Call OI buildup | 10 | yfinance options |
| IV term-structure/history proxy | 8 | yfinance options plus accumulated local history |
| Breaking key level | 8 | yfinance price history |
| Time-adjusted relative volume | 7 | yfinance volume |
| Reddit saturation | −15 | Optional/experimental; disabled by default |

## Data limitations

- Short interest normally updates twice monthly.
- Call activity is compared with open interest until enough local observations
  exist for a ticker-specific baseline.
- Gamma and zero-gamma values are modelled proxies; they do not reveal actual
  dealer books.
- Volume zones are ordinary price-volume clusters, not dark-pool prints.
- Results are research candidates, not recommendations.

## Running on an always-on Mac

`scripts/run-macos.sh` starts the API on localhost and stores SQLite data in
the ignored `data/` directory. Install `deploy/macos/com.theinvestingclinic.squeeze-scanner.plist`
in `~/Library/LaunchAgents/` to start it at login and restart it after failures.
Use a named Cloudflare Tunnel to publish `http://127.0.0.1:8000` without opening
a router port. The production tunnel publishes
`https://scanner-api.theinvestingclinic.com`.

On this desktop, the startup wrapper reads the scanner's Discord webhook from
the macOS Keychain item
`com.theinvestingclinic.squeeze-scanner.discord-webhook`. The webhook is never
copied into this repository or a launch-agent plist.

The service scans from 9:40 a.m. through 4:00 p.m. Eastern on open U.S. equity
market days, respects common holidays/early closes, writes rotating application
logs, and has a separate daily SQLite backup launch agent. Install both
`deploy/macos/com.theinvestingclinic.squeeze-scanner.plist` and
`deploy/macos/com.theinvestingclinic.squeeze-scanner-backup.plist`.
