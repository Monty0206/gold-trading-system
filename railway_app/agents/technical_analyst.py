"""
Agent 2 — Technical Analyst
Model: anthropic/claude-opus-4-6  |  Temp: 0.1
"""

import json
from utils.openrouter import call_openrouter

MODEL = "anthropic/claude-opus-4-6"

_SYSTEM_TEMPLATE = """You are a professional XAUUSD technical analyst specializing in
Smart Money Concepts (SMC) and institutional price action.
Pure technical analysis only. No opinions. Only rules.

MARKET DATA PROVIDED: {market_data}
MEMORY CONTEXT: {memory_context}

ANALYSIS FRAMEWORK:

1. MARKET STRUCTURE (H4 and H1)
   - Identify: Higher Highs/Higher Lows (bullish) or Lower Highs/Lower Lows (bearish)
   - Current trend per timeframe

2. ASIAN SESSION RANGE (00:00-07:00 GMT)
   - Mark the HIGH and LOW precisely
   - This is the compression zone London will break
   - Direction of break = intraday trade direction

3. SMART MONEY CONCEPTS
   - Order Blocks: Last bearish candle before bullish move (support)
   - Fair Value Gaps: Imbalances to be filled
   - Liquidity Pools: Highs/lows that will be swept before real move
   - Breaker Blocks: Failed order blocks that flip

4. EMA ALIGNMENT (H1)
   - EMA9 > EMA21 > EMA50 = Strong bullish trend
   - EMA9 < EMA21 < EMA50 = Strong bearish trend

5. RSI 14 (H1)
   - Above 50 + rising = bullish momentum
   - Below 50 + falling = bearish momentum
   - Divergence = potential reversal

6. ATR 14 (H1)
   - Used for stop loss sizing only
   - SL = beyond swing high/low + (ATR x 0.5)

7. SETUP GRADING
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
    import json as _json
    market_data_str = _json.dumps(market_data, indent=2)

    system = _SYSTEM_TEMPLATE.replace("{market_data}", market_data_str).replace(
        "{memory_context}", memory_context
    )

    user_message = (
        f"Analyze the XAUUSD chart data provided in your system prompt.\n"
        f"Current price: ${market_data['current_price']}\n"
        f"Asian Range: ${market_data['asian_range']['low']} — ${market_data['asian_range']['high']} "
        f"({market_data['asian_range']['size_pips']} pips)\n"
        f"EMA Bullish Stack: {market_data['ema_aligned_bullish']}\n"
        f"EMA Bearish Stack: {market_data['ema_aligned_bearish']}\n"
        f"RSI above 50: {market_data['rsi_above_50']}\n"
        f"MACD Bullish: {market_data['macd_bullish']}\n\n"
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
                "h4_aligned": False,
                "h1_aligned": False,
                "ema_aligned": False,
                "rsi_aligned": False,
                "macd_aligned": False,
                "key_level": False,
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
