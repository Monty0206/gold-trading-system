"""
Agent 3 — Quant Reasoner
Model: deepseek/deepseek-r1  |  Temp: 0.1  |  Cost: FREE on OpenRouter
Runs in parallel with Agents 1 & 2 using market data; full macro/technical
verification is completed by the Final Executor after all outputs are available.
"""

import json
from utils.openrouter import call_openrouter

MODEL = "deepseek/deepseek-r1"

_SYSTEM_TEMPLATE = """You are a quantitative analyst. Pure mathematics and logic only.
No directional opinions. You verify numbers and find errors.

MACRO OUTPUT: {macro_output}
TECHNICAL OUTPUT: {technical_output}
ACCOUNT BALANCE: {account_balance}
RISK PCT: {risk_pct}
MEMORY CONTEXT: {memory_context}

YOUR CALCULATIONS:

1. VERIFY R:R RATIO
   rr = abs(tp1 - entry) / abs(entry - sl)
   Must be >= 2.0 to pass

2. CALCULATE CORRECT LOT SIZE
   risk_amount = account_balance * (risk_pct / 100)
   pip_risk = abs(entry - stop_loss) * 10  (for XAUUSD, 1 pip = $0.01)
   pip_value_per_001_lot = 0.10  (approximate for XAUUSD)
   lot_size = risk_amount / (pip_risk * pip_value_per_001_lot)
   NEVER exceed 0.01 lot for account below $50
   NEVER exceed 0.02 lot for account below $100

3. VERIFY MACRO-TECHNICAL AGREEMENT
   Macro BULLISH + Technical LONG = AGREE (trade valid)
   Macro BEARISH + Technical SHORT = AGREE (trade valid)
   Any mismatch = DISAGREE (do not trade)

4. PROBABILITY SCORING
   AGREE + 6/6 confluence = 85
   AGREE + 5/6 confluence = 78
   AGREE + 4/6 confluence = 70
   AGREE + 3/6 confluence = 55
   DISAGREE (any) = 30
   Score below 60 = do not trade

5. FIND MATH ERRORS
   Check entry/SL/TP levels are internally consistent
   Check direction matches (SL below entry for longs, above for shorts)
   Check TP above entry for longs, below for shorts

Respond ONLY in valid JSON:
{{
  "macro_technical_agree": true,
  "verified_rr_tp1": 0.0,
  "verified_rr_tp2": 0.0,
  "correct_lot_size": 0.00,
  "max_risk_usd": 0.00,
  "probability_score": 0,
  "math_errors": [],
  "levels_consistent": true,
  "edge_strength": "STRONG|MODERATE|WEAK|NO_EDGE",
  "calculation_notes": "step by step working",
  "agent": "QUANT_REASONER",
  "vote": "GREEN|YELLOW|RED"
}}

Vote GREEN = probability >= 70, no math errors, levels consistent
Vote YELLOW = probability 55-69
Vote RED = probability < 55 OR macro/technical disagree OR math errors"""


async def run_quant_reasoner(
    market_data: dict,
    memory_context: str,
    macro_output: dict = None,
    technical_output: dict = None,
) -> dict:
    """
    Run Quant Reasoner.
    When called in parallel (macro/technical not yet available), passes
    placeholder data; the Final Executor performs full cross-verification.
    """
    import os
    account_balance = float(os.getenv("ACCOUNT_BALANCE", "20.00"))
    risk_pct = float(os.getenv("RISK_PCT", "1.0"))

    macro_str = json.dumps(macro_output, indent=2) if macro_output else "Not available yet (parallel execution)"
    technical_str = json.dumps(technical_output, indent=2) if technical_output else "Not available yet (parallel execution)"

    system = (
        _SYSTEM_TEMPLATE
        .replace("{macro_output}", macro_str)
        .replace("{technical_output}", technical_str)
        .replace("{account_balance}", str(account_balance))
        .replace("{risk_pct}", str(risk_pct))
        .replace("{memory_context}", memory_context)
    )

    user_message = (
        f"Current XAUUSD price: ${market_data['current_price']}\n"
        f"Account balance: ${account_balance}\n"
        f"Risk per trade: {risk_pct}%\n"
        f"Max lot allowed: 0.01\n\n"
        f"ATR (H1): {market_data['indicators']['atr_14']}\n"
        f"Asian Range High: {market_data['asian_range']['high']}\n"
        f"Asian Range Low: {market_data['asian_range']['low']}\n\n"
        f"Using ATR of {market_data['indicators']['atr_14']} for stop calculations:\n"
        f"- For a LONG: SL ~= Asian Low - (ATR * 0.5) = "
        f"{round(market_data['asian_range']['low'] - market_data['indicators']['atr_14'] * 0.5, 2)}\n"
        f"- For a SHORT: SL ~= Asian High + (ATR * 0.5) = "
        f"{round(market_data['asian_range']['high'] + market_data['indicators']['atr_14'] * 0.5, 2)}\n\n"
        f"Calculate the correct lot size, verify R:R ratios, and score the probability.\n"
        f"If macro/technical data is not yet available, base probability on market structure only."
    )

    try:
        result = await call_openrouter(
            model=MODEL,
            system_prompt=system,
            user_message=user_message,
            temperature=0.1,
            max_tokens=8192,
        )
        result.setdefault("agent", "QUANT_REASONER")
        return result
    except Exception as e:
        print(f"[QuantReasoner] Error: {e}")
        risk_amount = account_balance * (risk_pct / 100)
        return {
            "macro_technical_agree": False,
            "verified_rr_tp1": 0.0,
            "verified_rr_tp2": 0.0,
            "correct_lot_size": 0.01,
            "max_risk_usd": round(risk_amount, 2),
            "probability_score": 30,
            "math_errors": [f"Agent error: {str(e)[:200]}"],
            "levels_consistent": False,
            "edge_strength": "NO_EDGE",
            "calculation_notes": f"Quant Reasoner failed: {str(e)[:200]}",
            "agent": "QUANT_REASONER",
            "vote": "RED",
        }
