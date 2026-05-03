"""
News & Sentiment Agent — fetches live gold market headlines via Perplexity
and scores current sentiment to supplement macro analysis.
"""
import json
import logging
from datetime import datetime, timezone

from config import MODELS
from utils.openrouter import call_openrouter

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a gold market news analyst. Using your live web search capability:

1. Search for gold (XAUUSD) news from the last 6 hours
2. Check for Federal Reserve or central bank announcements
3. Look for geopolitical events (wars, sanctions, elections, inflation data)
4. Find any surprise economic data releases affecting precious metals

Return ONLY valid JSON:
{
  "sentiment_score": <0-100, where 0=extreme fear/bearish, 50=neutral, 100=extreme greed/bullish>,
  "sentiment_label": "<VERY_BEARISH|BEARISH|NEUTRAL|BULLISH|VERY_BULLISH>",
  "breaking_events": ["<event1>", "<event2>"],
  "fed_tone": "<DOVISH|NEUTRAL|HAWKISH|NO_DATA>",
  "geopolitical_risk": "<LOW|MEDIUM|HIGH|EXTREME>",
  "news_bias": "<BEARISH|NEUTRAL|BULLISH>",
  "key_headline": "<most important headline>",
  "trade_caution": <true if breaking news warrants extra caution, else false>,
  "caution_reason": "<reason or null>"
}"""


async def run(current_price: float, session: str) -> dict:
    """Async runner for news sentiment agent."""
    prompt = f"""Current gold price: ${current_price:.2f}
Current session: {session}
Current UTC time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}

Search for the latest gold market news and sentiment. Focus on news from the last 6 hours."""

    try:
        model = MODELS.get("news_sentiment")
        if not model:
            return _neutral_sentiment()

        result = await call_openrouter(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            user_message=prompt,
            temperature=0.1,
        )
        if isinstance(result, str):
            result = json.loads(result)

        # Validate required fields
        required = ["sentiment_score", "sentiment_label", "news_bias", "trade_caution"]
        if not all(k in result for k in required):
            logger.warning("News sentiment missing required fields, using neutral")
            return _neutral_sentiment()

        result["agent"] = "news_sentiment"
        result["vote"] = _sentiment_to_vote(result["sentiment_label"], result["trade_caution"])
        logger.info(
            f"News sentiment: {result['sentiment_label']} "
            f"(score={result['sentiment_score']}, caution={result['trade_caution']})"
        )
        return result
    except Exception as e:
        logger.error(f"News sentiment agent error: {e}")
        return _neutral_sentiment()


def _sentiment_to_vote(label: str, caution: bool) -> str:
    if caution:
        return "YELLOW"
    if label in ("VERY_BULLISH", "BULLISH"):
        return "GREEN"
    if label in ("VERY_BEARISH", "BEARISH"):
        return "RED"
    return "YELLOW"


def _neutral_sentiment() -> dict:
    return {
        "agent": "news_sentiment",
        "vote": "YELLOW",
        "sentiment_score": 50,
        "sentiment_label": "NEUTRAL",
        "breaking_events": [],
        "fed_tone": "NO_DATA",
        "geopolitical_risk": "LOW",
        "news_bias": "NEUTRAL",
        "key_headline": "No data available",
        "trade_caution": False,
        "caution_reason": None,
    }
