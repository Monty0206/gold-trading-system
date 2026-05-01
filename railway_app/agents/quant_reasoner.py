"""
Agent 3 — Quant Reasoner
Model: config.MODELS["quant_reasoner"]  |  Temp: 0.1
Runs SEQUENTIALLY after macro + technical agents (not in parallel).
Receives actual macro and technical outputs for real cross-verification.
Python computes canonical lot size and R:R — LLM verifies and scores probability.
"""

import json
import os

from config import MODELS
from utils.openrouter import call_openrouter

MODEL = MODELS["quant_reasoner"]

_SYSTEM_TEMPLATE = """You are a quantitative analyst. Pure mathematics and logic only.
No directional opinions. You verify numbers and find errors.

MACRO OUTPUT: {macro_output}
TECHNICAL OUTPUT: {technical_output}
ACCOUNT BALANCE: ${account_balance}
RISK PCT: {risk_pct}%
MEMORY CONTEXT: {memory_context}

PYTHON PRE-COMPUTED VALUES (use these as ground truth):
  Lot size:     {py_lot_size} lots
  Max risk USD: ${py_risk_usd}
  R:R TP1:      {py_rr_tp1}
  R:R TP2:      {py_rr_tp2}

YOUR TASKS:

1. VERIFY MACRO-TECHNICAL AGREEMENT
   Macro BULLISH + Technical expects UP breakout = AGREE
   Macro BEARISH + Technical expects DOWN breakout = AGREE
   Any mismatch = DISAGREE

2. PROBABILITY SCORING
   AGREE + 6/6 confluence = 85
   AGREE + 5/6 confluence = 78
   AGREE + 4/6 confluence = 70
   AGREE + 3/6 confluence = 55
   DISAGREE = 30
   Score below 60 = do not trade

3. FIND MATH ERRORS in the technical output
   - SL must be below entry for LONG, above for SHORT
   - TP must be above entry for LONG, below for SHORT
   - R:R must be >= 2.0

4. CONFIRM or OVERRIDE Python lot size
   Confirm the pre-computed lot size is correct for the given risk/balance.
   Only override if you find an error in the Python calculation.

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


def _python_calculations(
    technical: dict,
    account_balance: float,
    risk_pct: float,
) -> dict:
    """Deterministic Python lot/RR calculations. These are the ground truth."""
    # Use midpoint of entry zone — avoids using wrong end for SHORT vs LONG
    zone_from = float(technical.get("entry_zone_from") or 0)
    zone_to   = float(technical.get("entry_zone_to") or 0)
    if zone_from > 0 and zone_to > 0:
        entry = round((zone_from + zone_to) / 2, 2)
    else:
        entry = zone_from or zone_to

    sl  = float(technical.get("stop_loss", 0) or 0)
    tp1 = float(technical.get("take_profit_1", 0) or 0)
    tp2 = float(technical.get("take_profit_2", 0) or 0)

    target_risk_usd = round(account_balance * (risk_pct / 100), 2)

    # XAUUSD canonical lot sizing:
    #   contract_size = 100 oz
    #   P&L per lot   = price_distance_dollars * 100
    #   lot_size      = risk_usd / (price_distance_dollars * 100)
    # On a $20 account with a $2 stop: raw_lot = 0.20 / (2.00 * 100) = 0.001
    # Deriv minimum lot is 0.01 — the cap always applies at this account size.
    # risk_usd stays as TARGET (not actual) so the risk-manager gate is consistent.
    max_lot = float(os.getenv("MAX_LOT", "0.01"))
    min_lot = 0.01
    price_distance = abs(entry - sl) if sl and entry else 0
    if price_distance > 0:
        raw_lot  = target_risk_usd / (price_distance * 100)
        lot_size = max(min_lot, min(max_lot, round(raw_lot, 3)))
    else:
        lot_size = min_lot

    rr_tp1 = (
        round(abs(tp1 - entry) / abs(entry - sl), 2)
        if sl and entry and tp1 and abs(entry - sl) > 0
        else 0.0
    )
    rr_tp2 = (
        round(abs(tp2 - entry) / abs(entry - sl), 2)
        if sl and entry and tp2 and abs(entry - sl) > 0
        else 0.0
    )

    return {
        "lot_size":   lot_size,
        "risk_usd":   target_risk_usd,  # target risk for risk-manager gate
        "rr_tp1":     rr_tp1,
        "rr_tp2":     rr_tp2,
    }


async def run_quant_reasoner(
    market_data: dict,
    memory_context: str,
    macro_output: dict,
    technical_output: dict,
    account_balance: float,
) -> dict:
    """Run Quant Reasoner sequentially after macro + technical agents."""
    risk_pct = float(os.getenv("RISK_PCT", "1.0"))

    # Python ground-truth calculations
    py = _python_calculations(technical_output, account_balance, risk_pct)

    macro_str    = json.dumps(macro_output,    indent=2)
    technical_str = json.dumps(technical_output, indent=2)

    system = (
        _SYSTEM_TEMPLATE
        .replace("{macro_output}",    macro_str[:2000])
        .replace("{technical_output}", technical_str[:2000])
        .replace("{account_balance}", str(account_balance))
        .replace("{risk_pct}",        str(risk_pct))
        .replace("{memory_context}",  memory_context)
        .replace("{py_lot_size}",     str(py["lot_size"]))
        .replace("{py_risk_usd}",     str(py["risk_usd"]))
        .replace("{py_rr_tp1}",       str(py["rr_tp1"]))
        .replace("{py_rr_tp2}",       str(py["rr_tp2"]))
    )

    user_message = (
        f"Current XAUUSD price: ${market_data['current_price']}\n"
        f"Account balance: ${account_balance}\n"
        f"Risk per trade: {risk_pct}%\n"
        f"Max lot allowed: 0.01\n\n"
        f"ATR (H1, Wilder): {market_data['indicators']['atr_14']}\n"
        f"Asian Range High: {market_data['asian_range']['high']}\n"
        f"Asian Range Low:  {market_data['asian_range']['low']}\n\n"
        f"Macro bias: {macro_output.get('bias','?')} ({macro_output.get('confidence','?')} confidence)\n"
        f"Technical breakout expected: {technical_output.get('expected_breakout_direction','?')}\n"
        f"Confluence score: {technical_output.get('confluence_score', 0)}/6\n"
        f"Setup grade: {technical_output.get('setup_grade','?')}\n\n"
        f"Verify macro/technical agreement, check math errors, and score probability.\n"
        f"The Python pre-computed values are your ground truth for lot size and R:R."
    )

    try:
        result = await call_openrouter(
            model=MODEL,
            system_prompt=system,
            user_message=user_message,
            temperature=0.1,
            max_tokens=4096,
        )
        # Always use Python calculations for safety-critical fields
        result["correct_lot_size"] = py["lot_size"]
        result["max_risk_usd"]     = py["risk_usd"]
        result.setdefault("verified_rr_tp1", py["rr_tp1"])
        result.setdefault("verified_rr_tp2", py["rr_tp2"])
        result.setdefault("agent", "QUANT_REASONER")
        return result
    except Exception as e:
        print(f"[QuantReasoner] Error: {e}")
        return {
            "macro_technical_agree": False,
            "verified_rr_tp1": py["rr_tp1"],
            "verified_rr_tp2": py["rr_tp2"],
            "correct_lot_size": py["lot_size"],
            "max_risk_usd": py["risk_usd"],
            "probability_score": 30,
            "math_errors": [f"Agent error: {str(e)[:200]}"],
            "levels_consistent": False,
            "edge_strength": "NO_EDGE",
            "calculation_notes": f"Quant Reasoner failed: {str(e)[:200]}",
            "agent": "QUANT_REASONER",
            "vote": "RED",
        }
