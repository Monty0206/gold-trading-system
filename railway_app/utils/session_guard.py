from datetime import datetime, timezone

from config import HARD_RULES


def get_current_session() -> str:
    """Return the current trading session name based on UTC clock."""
    now = datetime.now(timezone.utc)
    hm = now.hour * 60 + now.minute

    if hm < 7 * 60:
        return "ASIAN"
    if 7 * 60 + 45 <= hm < 12 * 60:
        return "LONDON"
    if 12 * 60 <= hm < 12 * 60 + 45:
        return "GAP"
    if 12 * 60 + 45 <= hm < 17 * 60:
        return "NEW_YORK"
    return "CLOSED"


def is_valid_trading_time() -> bool:
    """Return True only during London or NY open windows on weekdays,
    with a Friday 14:00 UTC hard cutoff to avoid weekend gap risk."""
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    # Friday 14:00 UTC cutoff — no new trades heading into weekend
    if now.weekday() == 4:  # Friday
        hm = now.hour * 60 + now.minute
        if hm >= HARD_RULES["no_trade_friday_after_hm"]:
            return False
    return get_current_session() in ("LONDON", "NEW_YORK")


def get_minutes_until_news(news_events: list) -> int:
    """Return minutes until the next HIGH-impact event, or -1 if none found."""
    now = datetime.now(timezone.utc)
    min_minutes = float("inf")

    for event in news_events:
        if event.get("impact") != "HIGH":
            continue
        time_str = event.get("time_gmt", "")
        if not time_str:
            continue
        try:
            h, m = map(int, time_str.split(":"))
            today = now.date()
            event_dt = datetime(
                today.year, today.month, today.day, h, m, tzinfo=timezone.utc
            )
            diff = (event_dt - now).total_seconds() / 60
            if 0 < diff < min_minutes:
                min_minutes = diff
        except (ValueError, TypeError, AttributeError):
            continue

    return int(min_minutes) if min_minutes != float("inf") else -1


def is_in_news_blackout(news_events: list, blackout_minutes: int = 30) -> bool:
    """Return True if a HIGH-impact news event is within blackout_minutes."""
    mins = get_minutes_until_news(news_events)
    return 0 <= mins <= blackout_minutes
