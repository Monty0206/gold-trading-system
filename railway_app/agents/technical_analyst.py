"""
Agent 2 — Technical Analyst
Model: config.MODELS["technical_analyst"]  |  Temp: 0.1
"""

import json

from config import MODELS
from utils.openrouter import call_openrouter

MODEL = MODELS["technical_analyst"]

_SYSTEM_TEMPLATE = """You are a professional XAUUSD technical analyst specializing in
Smart Money Concepts (SMC) and institutional price action.
Pure technical analysis only. No opinions. Only rules.

MARKET DATA PROVIDED: {market_data}
MEMORY CONTEXT: {memory_context}

ANALYSIS FRAMEWORK:

1. MARKET STRUCTURE (H4 and H1)
   - Identify: Higher Highs/Higher Lows (bullish) or Lower Highs/Lower Lows (bearish)
   - Use the swing_highs and swing_lows arrays provided — they are pre-computed.

2. ASIAN SESSION RANGE (23:00 UTC previous day → 07:00 UTC today)
   - The asian_range.high and asian_range.low are pre-computed from the 23:00-07:00 UTC window.
   - This is the compression zone London will break.
   - Direction of break = intraday trade direction.

3. SMART MONEY CONCEPTS
   - Order Blocks: Last bearish candle before bullish move (support)
   - Fair Value Gaps: Imbalances to be filled
   - Liquidity Pools: Swing highs/lows that will be swept before real move
   - Breaker Blocks: Failed order blocks that flip

4. EMA ALIGNMENT (H1) — pre-computed flags provided:
   - ema_aligned_bullish = EMA9 > EMA21 > EMA50
   - ema_aligned_bearish = EMA9 < EMA21 < EMA50

5. RSI 14 (H1, Wilder's smoothing — matches MT5):
   - rsi_above_50 = RSI > 50
   - Above 50 + rising = bullish momentum

6. ATR 14 (H1, Wilder's smoothing):
   - SL = beyond swing high/low + (ATR × 0.5)

7. SETUP GRADING:
   A-Grade: 6/6 confluence, clear structure, obvious entry
   B-Grade: 4-5/6 confluence, good structure, clear entry
   C-Grade: 3/6 confluence — WAIT for better setup
   NO_SETUP: Less than 3 — DO NOT TRADE

CONFLUENCE CHECKLIST:
[1] H4 trend aligned with direction
[2] H1 trend aligned with direction
[3] EMA 9/21 aligned on H1
[4] RSI above/below 50 aligned
[5] MACD histogram momentum aligned
[6] Price at key level (OB, FVG, S/R, Asian range retest)

Respond ONLY in valid JSON:
{{
  "h4_trend": "BULLISH|BEARISH|RANGING",
  "h1_trend": "BULLISH|BEARISH|RANGING",
  "m15_trend": "BULLISH|BEARISH|RANGING",
  "asian_range_high": 0.00,
  "asian_range_low": 0.00,
  "asian_range_size_pips": 0.0,
  "expected_breakout_direction": "UP|DOWN|UNCLEAR",
  "entry_type": "LIMIT|MARKET|STOP",
  "entry_zone_from": 0.00,
  "entry_zone_to": 0.00,
  "stop_loss": 0.00,
  "stop_loss_pips": 0.0,
  "take_profit_1": 0.00,
  "take_profit_2": 0.00,
  "rr_ratio_tp1": 0.0,
  "rr_ratio_tp2": 0.0,
  "confluence_score": 0,
  "confluence_details": {{
    "h4_aligned": true,
    "h1_aligned": true,
    "ema_aligned": true,
    "rsi_aligned": true,
    "macd_aligned": true,
    "key_level": true
  }},
  "key_levels": [{{"level": 0.00, "type": "SUPPORT|RESISTANCE|OB|FVG"}}],
  "order_blocks": [{{"level": 0.00, "direction": "BULLISH|BEARISH"}}],
  "setup_grade": "A|B|C|NO_SETUP",
  "atr_value": 0.00,
  "invalidation_level": 0.00,
  "invalidation_reason": "description",
  "agent": "TECHNICAL_ANALYST",
  "vote": "GREEN|YELLOW|RED"
}}

Vote GREEN = A or B grade, 4+ confluence
Vote YELLOW = C grade or 3 confluence
Vote RED = NO_SETUP or confluence below 3"""


async def run_technical_analyst(market_data: dict, memory_context: str) -> dict:
    """Run Technical Analyst — returns SMC chart analysis JSON."""
    market_data_str = json.dumps(market_data, indent=2)

    system = (
        _SYSTEM_TEMPLATE
        .replace("{market_data}", market_data_str)
        .replace("{memory_context}", memory_context)
    )

    user_message = (
        f"Analyze the XAUUSD chart data provided in your system prompt.\n"
        f"Current price: ${market_data['current_price']}\n"
        f"Data source: {market_data.get('data_source', 'N/A')}\n"
        f"Asian Range: ${market_data['asian_range']['low']} — ${market_data['asian_range']['high']} "
        f"({market_data['asian_range']['size_pips']} pips)\n"
        f"EMA Bullish Stack: {market_data['ema_aligned_bullish']}\n"
        f"EMA Bearish Stack: {market_data['ema_aligned_bearish']}\n"
        f"RSI above 50: {market_data['rsi_above_50']}\n"
        f"MACD Bullish: {market_data['macd_bullish']}\n"
        f"Swing Highs (recent): {market_data.get('swing_highs', [])}\n"
        f"Swing Lows  (recent): {market_data.get('swing_lows', [])}\n\n"
        f"Grade this setup and provide full technical analysis with entry, SL, TP1, TP2."
    )

    try:
        result = await call_openrouter(
            model=MODEL,
            system_prompt=system,
            user_message=user_message,
            temperature=0.1,
        )
        result.setdefault("agent", "TECHNICAL_ANALYST")

        # Verify LLM-reported confluence_score matches actual flags
        if "confluence_details" in result and "confluence_score" in result:
            details = result.get("confluence_details") or {}
            if isinstance(details, dict):
                actual_score = sum(1 for v in details.values() if v)
                reported_score = result.get("confluence_score", 0)
                try:
                    reported_score = int(reported_score)
                except (TypeError, ValueError):
                    reported_score = 0
                if abs(actual_score - reported_score) > 1:
                    print(
                        f"[TechnicalAnalyst] Confluence score mismatch: "
                        f"reported={reported_score}, actual={actual_score}. Using actual."
                    )
                    result["confluence_score"] = actual_score
        return result
    except Exception as e:
        print(f"[TechnicalAnalyst] Error: {e}")
        return {
            "h4_trend": "RANGING",
            "h1_trend": "RANGING",
            "m15_trend": "RANGING",
            "asian_range_high": market_data["asian_range"]["high"],
            "asian_range_low": market_data["asian_range"]["low"],
            "asian_range_size_pips": market_data["asian_range"]["size_pips"],
            "expected_breakout_direction": "UNCLEAR",
            "entry_type": "MARKET",
            "entry_zone_from": 0.0,
            "entry_zone_to": 0.0,
            "stop_loss": 0.0,
            "stop_loss_pips": 0.0,
            "take_profit_1": 0.0,
            "take_profit_2": 0.0,
            "rr_ratio_tp1": 0.0,
            "rr_ratio_tp2": 0.0,
            "confluence_score": 0,
            "confluence_details": {
                "h4_aligned": False, "h1_aligned": False, "ema_aligned": False,
                "rsi_aligned": False, "macd_aligned": False, "key_level": False,
            },
            "key_levels": [],
            "order_blocks": [],
            "setup_grade": "NO_SETUP",
            "atr_value": market_data["indicators"]["atr_14"],
            "invalidation_level": 0.0,
            "invalidation_reason": f"Agent error: {str(e)[:200]}",
            "agent": "TECHNICAL_ANALYST",
            "vote": "RED",
        }
