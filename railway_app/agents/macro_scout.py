"""
Agent 1 — Macro Scout
Model: anthropic/claude-sonnet-4-6  |  Web search: on  |  Temp: 0.1
"""

import json
from utils.openrouter import call_openrouter

MODEL = "anthropic/claude-sonnet-4-6"

_SYSTEM_TEMPLATE = """You are a senior gold market macro analyst with 20 years of experience.
Your ONLY job: determine today's directional bias for XAUUSD.

GOLD PRICE DRIVERS TO ANALYZE:
1. US Dollar Index (DXY) — inverse correlation with gold
   - DXY falling = BULLISH gold
   - DXY rising = BEARISH gold
2. US 10-Year Treasury Yields — inverse correlation
   - Yields falling = BULLISH gold
   - Yields rising = BEARISH gold
3. Federal Reserve — policy stance, recent speeches
   - Dovish = BULLISH gold
   - Hawkish = BEARISH gold
4. Geopolitical events — wars, sanctions, crises
   - Tension rising = BULLISH gold (safe haven)
5. Inflation data (CPI, PCE, PPI)
   - Higher than expected = BULLISH gold
6. Risk sentiment (VIX, equity futures)
   - Risk-off / fear = BULLISH gold
   - Risk-on / greed = BEARISH gold
7. Central bank gold purchases/sales
8. Scheduled high-impact news TODAY

MEMORY CONTEXT: {memory_context}
(Learn from past: which macro conditions led to wins/losses)

Respond ONLY in valid JSON — no markdown, no explanation outside JSON:
{{
  "bias": "BULLISH|BEARISH|NEUTRAL",
  "strength": 1-10,
  "key_drivers": ["driver1", "driver2", "driver3"],
  "risk_events_today": [{{"event": "name", "time_gmt": "HH:MM", "impact": "HIGH|MEDIUM"}}],
  "news_blackout_windows": ["HH:MM-HH:MM GMT"],
  "dxy_direction": "FALLING|RISING|FLAT",
  "yields_direction": "FALLING|RISING|FLAT",
  "risk_sentiment": "RISK_OFF|RISK_ON|NEUTRAL",
  "confidence": "HIGH|MEDIUM|LOW",
  "summary": "2-3 sentence macro context for today",
  "agent": "MACRO_SCOUT",
  "vote": "GREEN|YELLOW|RED"
}}

Vote GREEN = clear bias, HIGH confidence, no dangerous news imminent
Vote YELLOW = NEUTRAL bias or MEDIUM confidence
Vote RED = major news within 2 hours OR completely conflicting signals"""


async def run_macro_scout(market_data: dict, memory_context: str) -> dict:
    """Run Macro Scout — returns directional bias JSON."""
    system = _SYSTEM_TEMPLATE.replace("{memory_context}", memory_context)

    user_message = (
        f"Current XAUUSD market data:\n"
        f"Price: ${market_data['current_price']}\n"
        f"DateTime (UTC): {market_data['timestamp']}\n"
        f"H4 Trend: {market_data['h4_trend']}\n"
        f"Day High: ${market_data.get('day_high', 'N/A')}\n"
        f"Day Low:  ${market_data.get('day_low', 'N/A')}\n\n"
        f"Asian Range:\n"
        f"  High: ${market_data['asian_range']['high']}\n"
        f"  Low:  ${market_data['asian_range']['low']}\n"
        f"  Size: {market_data['asian_range']['size_pips']} pips\n\n"
        f"H1 Indicators:\n"
        f"  EMA9:           {market_data['indicators']['ema9']}\n"
        f"  EMA21:          {market_data['indicators']['ema21']}\n"
        f"  EMA50:          {market_data['indicators']['ema50']}\n"
        f"  RSI14:          {market_data['indicators']['rsi_14']}\n"
        f"  ATR14:          {market_data['indicators']['atr_14']}\n"
        f"  MACD Histogram: {market_data['indicators']['macd_histogram']}\n\n"
        f"Analyze current macro conditions and provide directional bias for XAUUSD today.\n"
        f"Consider DXY, yields, Fed stance, geopolitics, and scheduled news events."
    )

    try:
        result = await call_openrouter(
            model=MODEL,
            system_prompt=system,
            user_message=user_message,
            temperature=0.1,
        )
        result.setdefault("agent", "MACRO_SCOUT")
        return result
    except Exception as e:
        print(f"[MacroScout] Error: {e}")
        return {
            "bias": "NEUTRAL",
            "strength": 3,
            "key_drivers": [f"Agent error: {str(e)[:100]}"],
            "risk_events_today": [],
            "news_blackout_windows": [],
            "dxy_direction": "FLAT",
            "yields_direction": "FLAT",
            "risk_sentiment": "NEUTRAL",
            "confidence": "LOW",
            "summary": f"Macro Scout failed: {str(e)[:200]}",
            "agent": "MACRO_SCOUT",
            "vote": "RED",
        }
