import praw
from datetime import datetime, timedelta
from config import settings

_reddit = None


def _get_reddit():
    global _reddit
    if _reddit is None and settings.reddit_client_id:
        _reddit = praw.Reddit(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret,
            user_agent=settings.reddit_user_agent,
        )
    return _reddit


# Rolling 24h mention counts per ticker (simple in-memory cache)
_mention_cache: dict[str, tuple[int, datetime]] = {}


def get_reddit_saturation(ticker: str) -> float:
    """
    Returns 0.0–1.0 saturation score.
    0 = no one talking about it, 1 = everyone knows the trade.

    Thresholds (calibrated for WSB/options subs):
      < 5 mentions/24h  → 0.0
      5–20              → 0.2
      20–50             → 0.4
      50–100            → 0.6
      100–300           → 0.8
      300+              → 1.0
    """
    cached = _mention_cache.get(ticker)
    if cached and (datetime.utcnow() - cached[1]).seconds < 1800:
        mentions = cached[0]
    else:
        mentions = _count_mentions(ticker)
        _mention_cache[ticker] = (mentions, datetime.utcnow())

    if mentions < 5:
        return 0.0
    elif mentions < 20:
        return 0.2
    elif mentions < 50:
        return 0.4
    elif mentions < 100:
        return 0.6
    elif mentions < 300:
        return 0.8
    else:
        return 1.0


def _count_mentions(ticker: str) -> int:
    reddit = _get_reddit()
    if not reddit:
        return 0

    subreddits = ["wallstreetbets", "stocks", "options", "shortsqueeze"]
    cutoff = datetime.utcnow() - timedelta(hours=24)
    count = 0
    search_term = f"${ticker}"

    try:
        for sub_name in subreddits:
            sub = reddit.subreddit(sub_name)
            for post in sub.search(search_term, sort="new", time_filter="day", limit=50):
                if datetime.utcfromtimestamp(post.created_utc) >= cutoff:
                    count += 1
    except Exception:
        pass

    return count
