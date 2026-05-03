"""
Agent 1 — Macro Scout
Model: config.MODELS["macro_scout"]  |  Temp: 0.1
Receives real DXY, 10Y yields, VIX, and FMP economic calendar from market_data.
"""

import json

from config import MODELS
from utils.openrouter import call_openrouter

MODEL = MODELS["macro_scout"]

_SYSTEM_TEMPLATE = """You are a senior gold market macro analyst with 20 years of experience.
Your ONLY job: determine today's directional bias for XAUUSD.

You have live web search capability. Before forming your bias, search for:
1. Latest Federal Reserve speaker statements (last 48 hours)
2. Breaking geopolitical events (wars, sanctions, central bank gold buying)
3. Current gold market sentiment from financial news (Kitco, Reuters, Bloomberg)
Use this real-time information to supplement the provided macro data.

LIVE MACRO DATA (real-time, not your training data):
- DXY (US Dollar Index): {dxy_current} | 24h direction: {dxy_direction} | Change: {dxy_change}%
- US 10Y Yield (^TNX): {tnx_current}% | 24h direction: {tnx_direction} | Change: {tnx_change}%
- VIX (Fear Index): {vix_current} | 24h direction: {vix_direction} | Change: {vix_change}%
- GVZ (Gold Volatility Index): {gvz_current} | 24h direction: {gvz_direction} | Change: {gvz_change}%
- Crude Oil (CL=F, inflation proxy): {oil_current} | 24h direction: {oil_direction} | Change: {oil_change}%
- Bitcoin (BTC-USD, risk-on/safe-haven proxy): {btc_current} | 24h direction: {btc_direction} | Change: {btc_change}%

GOLD PRICE DRIVERS — APPLY THESE RULES:
1. DXY FALLING = BULLISH gold | DXY RISING = BEARISH gold (strong inverse correlation)
2. YIELDS FALLING = BULLISH gold | YIELDS RISING = BEARISH gold (inverse correlation)
3. VIX RISING = BULLISH gold (risk-off / safe haven demand)
4. VIX FALLING = BEARISH gold (risk-on, less safe haven demand)
5. Fed policy: Dovish = BULLISH | Hawkish = BEARISH
6. Geopolitical tension = BULLISH (safe haven)
7. Inflation surprise (CPI/PCE above estimate) = BULLISH

TODAY'S ECONOMIC CALENDAR (HIGH-impact events — real data):
{economic_calendar}

MEMORY CONTEXT: {memory_context}
(Learn from past: which macro conditions led to wins/losses)

INSTRUCTIONS:
- Use the LIVE MACRO DATA above as your primary source. Do NOT rely on training data for current DXY/yield/VIX levels.
- Flag any HIGH-impact event within 2 hours as a news blackout risk.
- Your bias must be consistent with DXY/yield/VIX directions.

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
  "summary": "2-3 sentence macro context for today referencing the live DXY/yield/VIX readings",
  "agent": "MACRO_SCOUT",
  "vote": "GREEN|YELLOW|RED"
}}

Vote GREEN = clear bias, HIGH confidence, no dangerous news within 2h
Vote YELLOW = NEUTRAL bias or MEDIUM confidence or conflicting signals
Vote RED = major HIGH-impact news within 2h OR completely conflicting signals"""


async def run_macro_scout(market_data: dict, memory_context: str) -> dict:
    """Run Macro Scout — returns directional bias JSON with real macro data."""
    macro = market_data.get("macro", {})
    dxy    = macro.get("dxy", {})
    tnx    = macro.get("tnx_10y", {})
    vix    = macro.get("vix", {})
    gvz    = macro.get("gvz", {})
    oil    = macro.get("oil", {})
    btc    = macro.get("btc", {})
    cal    = market_data.get("economic_calendar", [])

    cal_str = (
        "\n".join(
            f"  {e['time_gmt']} GMT — {e['event']} ({e['country']}) [{e['impact']}]"
            for e in cal
        )
        if cal
        else "  No economic events fetched (set FMP_API_KEY for real calendar)."
    )

    system = (
        _SYSTEM_TEMPLATE
        .replace("{dxy_current}",   str(dxy.get("current",     "N/A")))
        .replace("{dxy_direction}", str(dxy.get("direction",   "UNKNOWN")))
        .replace("{dxy_change}",    str(dxy.get("change_pct",  "N/A")))
        .replace("{tnx_current}",   str(tnx.get("current",     "N/A")))
        .replace("{tnx_direction}", str(tnx.get("direction",   "UNKNOWN")))
        .replace("{tnx_change}",    str(tnx.get("change_pct",  "N/A")))
        .replace("{vix_current}",   str(vix.get("current",     "N/A")))
        .replace("{vix_direction}", str(vix.get("direction",   "UNKNOWN")))
        .replace("{vix_change}",    str(vix.get("change_pct",  "N/A")))
        .replace("{gvz_current}",   str(gvz.get("current",     "N/A")))
        .replace("{gvz_direction}", str(gvz.get("direction",   "UNKNOWN")))
        .replace("{gvz_change}",    str(gvz.get("change_pct",  "N/A")))
        .replace("{oil_current}",   str(oil.get("current",     "N/A")))
        .replace("{oil_direction}", str(oil.get("direction",   "UNKNOWN")))
        .replace("{oil_change}",    str(oil.get("change_pct",  "N/A")))
        .replace("{btc_current}",   str(btc.get("current",     "N/A")))
        .replace("{btc_direction}", str(btc.get("direction",   "UNKNOWN")))
        .replace("{btc_change}",    str(btc.get("change_pct",  "N/A")))
        .replace("{economic_calendar}", cal_str)
        .replace("{memory_context}", memory_context)
    )

    user_message = (
        f"Current XAUUSD market data:\n"
        f"Price: ${market_data['current_price']}\n"
        f"Data source: {market_data.get('data_source', 'N/A')}\n"
        f"DateTime (UTC): {market_data['timestamp']}\n"
        f"H4 Trend: {market_data['h4_trend']}\n"
        f"Day High: ${market_data.get('day_high', 'N/A')}\n"
        f"Day Low:  ${market_data.get('day_low', 'N/A')}\n\n"
        f"Asian Range:\n"
        f"  High: ${market_data['asian_range']['high']}\n"
        f"  Low:  ${market_data['asian_range']['low']}\n"
        f"  Size: {market_data['asian_range']['size_pips']} pips\n\n"
        f"Live macro readings are in your system prompt above.\n"
        f"Use DXY={dxy.get('current','N/A')} ({dxy.get('direction','?')}), "
        f"10Y={tnx.get('current','N/A')}% ({tnx.get('direction','?')}), "
        f"VIX={vix.get('current','N/A')} ({vix.get('direction','?')}) "
        f"to determine directional bias."
    )

    try:
        result = await call_openrouter(
            model=MODEL,
            system_prompt=system,
            user_message=user_message,
            temperature=0.1,
        )
        # Merge real calendar into risk_events if agent returned empty
        if not result.get("risk_events_today") and cal:
            result["risk_events_today"] = [
                e for e in cal if e.get("impact") == "HIGH"
            ]
        result.setdefault("agent", "MACRO_SCOUT")
        return result
    except Exception as e:
        print(f"[MacroScout] Error: {e}")
        return {
            "bias": "NEUTRAL",
            "strength": 3,
            "key_drivers": [f"Agent error: {str(e)[:100]}"],
            "risk_events_today": cal,
            "news_blackout_windows": [],
            "dxy_direction": dxy.get("direction", "FLAT"),
            "yields_direction": tnx.get("direction", "FLAT"),
            "risk_sentiment": "NEUTRAL",
            "confidence": "LOW",
            "summary": f"Macro Scout failed: {str(e)[:200]}",
            "agent": "MACRO_SCOUT",
            "vote": "RED",
        }
