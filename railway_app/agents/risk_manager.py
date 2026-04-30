"""
Agent 5 — Risk Manager
Model: deepseek/deepseek-chat  |  Temp: 0.0
Python hard rules are checked FIRST. AI does final sanity check second.
"""

import json
import os
from datetime import date, datetime, timezone

from config import HARD_RULES
from utils.openrouter import call_openrouter
from utils.session_guard import is_in_news_blackout

MODEL = "deepseek/deepseek-chat"

_SYSTEM_TEMPLATE = """You are the Risk Manager and final gatekeeper.
You protect the account above everything else.
A missed trade is fine. A blown account is not.

TRADE PROPOSAL: {trade_proposal}
PYTHON RULES RESULT: {hard_rules_result}
ACCOUNT STATE: {account_state}
ALL AGENT VOTES: {all_votes}

If Python hard rules already REJECTED this trade → confirm REJECTED.
If Python hard rules PASSED → do a final sanity check:
- Does anything feel wrong that the rules didn't catch?
- Is there unusual market context that increases risk?
- Is the setup rushed or forced?

Respond ONLY in valid JSON:
{{
  "hard_rules_passed": true,
  "failed_rules": [],
  "sanity_check_passed": true,
  "sanity_concerns": [],
  "risk_assessment": "APPROVED|REJECTED",
  "rejection_reason": null,
  "approved_lot_size": 0.00,
  "approved_risk_usd": 0.00,
  "approved_entry": 0.00,
  "approved_sl": 0.00,
  "approved_tp1": 0.00,
  "approved_tp2": 0.00,
  "risk_notes": "any important risk context",
  "agent": "RISK_MANAGER",
  "vote": "GREEN|RED"
}}

Only GREEN if APPROVED. RED if any concern. No exceptions."""


def _count_open_trades_today(supabase) -> int:
    """Count signals already executed today (proxy for open trades)."""
    if supabase is None:
        return 0
    try:
        today_iso = date.today().isoformat()
        rows = (
            supabase.table("trade_signals")
            .select("id")
            .eq("executed", True)
            .gte("created_at", f"{today_iso}T00:00:00")
            .execute()
        )
        return len(rows.data or [])
    except Exception:
        return 0


def _sum_daily_loss(supabase) -> float:
    """Sum today's losses (positive number) from trade_outcomes."""
    if supabase is None:
        return 0.0
    try:
        today_iso = date.today().isoformat()
        rows = (
            supabase.table("trade_outcomes")
            .select("profit_usd")
            .gte("created_at", f"{today_iso}T00:00:00")
            .execute()
        )
        total_loss = 0.0
        for r in rows.data or []:
            p = float(r.get("profit_usd") or 0)
            if p < 0:
                total_loss += abs(p)
        return total_loss
    except Exception:
        return 0.0


def _check_python_hard_rules(
    all_votes: list,
    green_count: int,
    account_state: dict,
    technical_output: dict,
    quant_output: dict,
    news_events: list,
    session: str,
    supabase=None,
) -> dict:
    """Enforce hard rules in Python. Returns {passed, failed_rules}."""
    failed = []

    # Rule: Min green votes
    if green_count < HARD_RULES["min_green_votes"]:
        failed.append(
            f"Only {green_count} GREEN votes — need {HARD_RULES['min_green_votes']}"
        )

    # Rule: Min confluence score
    confluence = technical_output.get("confluence_score", 0)
    if confluence < HARD_RULES["min_confluence"]:
        failed.append(
            f"Confluence {confluence} < minimum {HARD_RULES['min_confluence']}"
        )

    # Rule: No setup
    if technical_output.get("setup_grade") == "NO_SETUP":
        failed.append("Technical grade is NO_SETUP")

    # Rule: Min probability
    probability = quant_output.get("probability_score", 0)
    if probability < HARD_RULES["min_probability"]:
        failed.append(
            f"Probability {probability}% < minimum {HARD_RULES['min_probability']}%"
        )

    # Rule: Min R:R
    rr = quant_output.get("verified_rr_tp1", 0.0)
    if 0 < rr < HARD_RULES["min_rr_ratio"]:
        failed.append(f"R:R {rr:.2f} < minimum {HARD_RULES['min_rr_ratio']}")

    # Rule: Max lot size
    proposed_lot = quant_output.get("correct_lot_size", 0.01)
    if proposed_lot > HARD_RULES["max_lot_size"]:
        failed.append(
            f"Lot size {proposed_lot} > max {HARD_RULES['max_lot_size']}"
        )

    # Rule: Max risk pct (proposed risk_usd vs account balance)
    balance = float(account_state.get("balance", 20.0))
    proposed_risk_usd = float(quant_output.get("max_risk_usd", 0.0))
    proposed_risk_pct = (proposed_risk_usd / balance * 100) if balance > 0 else 0
    if proposed_risk_pct > HARD_RULES["max_risk_pct"]:
        failed.append(
            f"Risk {proposed_risk_pct:.2f}% > max {HARD_RULES['max_risk_pct']}%"
        )

    # Rule: Max open trades today
    open_today = _count_open_trades_today(supabase)
    if open_today >= HARD_RULES["max_open_trades"]:
        failed.append(
            f"Already {open_today} executed trades today — max {HARD_RULES['max_open_trades']}"
        )

    # Rule: Max daily loss pct — circuit breaker
    daily_loss = _sum_daily_loss(supabase)
    daily_loss_pct = (daily_loss / balance * 100) if balance > 0 else 0
    if daily_loss_pct >= HARD_RULES["max_daily_loss_pct"]:
        failed.append(
            f"Daily loss ${daily_loss:.2f} ({daily_loss_pct:.2f}%) >= "
            f"max {HARD_RULES['max_daily_loss_pct']}% — DAILY STOP HIT"
        )

    # Rule: Asian session blackout
    if session == "ASIAN" and HARD_RULES["no_trade_asian_session"]:
        failed.append("Asian session — no trading 00:00-07:00 GMT")

    # Rule: Gap session blackout
    if session == "GAP" and HARD_RULES["no_trade_gap_session"]:
        failed.append("Gap session — no trading 12:00-12:45 GMT")

    # Rule: News blackout (30 min before HIGH-impact events)
    if is_in_news_blackout(news_events, HARD_RULES["no_trade_mins_before_news"]):
        failed.append(
            f"HIGH-impact news within {HARD_RULES['no_trade_mins_before_news']} minutes"
        )

    # Rule: Math errors from quant
    if quant_output.get("math_errors"):
        failed.append(f"Math errors detected: {quant_output['math_errors']}")

    return {"passed": len(failed) == 0, "failed_rules": failed}


async def run_risk_manager(
    market_data: dict,
    all_votes: list,
    green_count: int,
    account_state: dict,
    memory_context: str,
    supabase=None,
) -> dict:
    """Run Risk Manager — Python rules first, then AI sanity check."""
    # Extract individual agent outputs from the votes list
    technical_output = next(
        (v for v in all_votes if v.get("agent") == "TECHNICAL_ANALYST"), {}
    )
    quant_output = next(
        (v for v in all_votes if v.get("agent") == "QUANT_REASONER"), {}
    )
    macro_output = next(
        (v for v in all_votes if v.get("agent") == "MACRO_SCOUT"), {}
    )

    news_events = macro_output.get("risk_events_today", [])
    session = account_state.get("session", "UNKNOWN")

    # 1. Python hard rules — non-negotiable, run BEFORE any AI call
    hard_rules_result = _check_python_hard_rules(
        all_votes=all_votes,
        green_count=green_count,
        account_state=account_state,
        technical_output=technical_output,
        quant_output=quant_output,
        news_events=news_events,
        session=session,
        supabase=supabase,
    )

    # Build trade proposal summary
    entry = technical_output.get("entry_zone_from") or technical_output.get("entry_zone_to") or 0
    trade_proposal = {
        "direction": "LONG" if technical_output.get("expected_breakout_direction") == "UP" else "SHORT",
        "entry_price": entry,
        "stop_loss": technical_output.get("stop_loss", 0),
        "take_profit_1": technical_output.get("take_profit_1", 0),
        "take_profit_2": technical_output.get("take_profit_2", 0),
        "lot_size": quant_output.get("correct_lot_size", 0.01),
        "risk_usd": quant_output.get("max_risk_usd", 0.20),
        "rr_ratio": quant_output.get("verified_rr_tp1", 0),
        "setup_grade": technical_output.get("setup_grade", "NO_SETUP"),
    }

    system = (
        _SYSTEM_TEMPLATE
        .replace("{trade_proposal}", json.dumps(trade_proposal, indent=2))
        .replace("{hard_rules_result}", json.dumps(hard_rules_result, indent=2))
        .replace("{account_state}", json.dumps(account_state, indent=2))
        .replace("{all_votes}", json.dumps(
            [{"agent": v.get("agent"), "vote": v.get("vote")} for v in all_votes],
            indent=2,
        ))
    )

    system = system + f"\n\nMEMORY CONTEXT: {memory_context}"

    user_message = (
        f"Python hard rules {'PASSED' if hard_rules_result['passed'] else 'FAILED'}.\n"
        f"Failed rules: {hard_rules_result['failed_rules']}\n"
        f"Green votes: {green_count}/5 (before your vote)\n"
        f"Session: {session}\n"
        f"Balance: ${account_state.get('balance', 20)}\n\n"
        f"{'Confirm APPROVED with full sanity check.' if hard_rules_result['passed'] else 'Confirm REJECTED.'}"
    )

    try:
        result = await call_openrouter(
            model=MODEL,
            system_prompt=system,
            user_message=user_message,
            temperature=0.0,
        )
        # Always honour Python hard rules — override AI if it contradicts
        if not hard_rules_result["passed"]:
            result["hard_rules_passed"] = False
            result["failed_rules"] = hard_rules_result["failed_rules"]
            result["risk_assessment"] = "REJECTED"
            result["rejection_reason"] = "; ".join(hard_rules_result["failed_rules"])
            result["vote"] = "RED"
        result.setdefault("agent", "RISK_MANAGER")
        return result
    except Exception as e:
        print(f"[RiskManager] Error: {e}")
        # Fall back to Python rules only
        return {
            "hard_rules_passed": hard_rules_result["passed"],
            "failed_rules": hard_rules_result["failed_rules"],
            "sanity_check_passed": hard_rules_result["passed"],
            "sanity_concerns": [f"AI sanity check failed: {str(e)[:100]}"],
            "risk_assessment": "APPROVED" if hard_rules_result["passed"] else "REJECTED",
            "rejection_reason": "; ".join(hard_rules_result["failed_rules"]) if not hard_rules_result["passed"] else None,
            "approved_lot_size": trade_proposal["lot_size"],
            "approved_risk_usd": trade_proposal["risk_usd"],
            "approved_entry": trade_proposal["entry_price"],
            "approved_sl": trade_proposal["stop_loss"],
            "approved_tp1": trade_proposal["take_profit_1"],
            "approved_tp2": trade_proposal["take_profit_2"],
            "risk_notes": f"AI sanity check unavailable: {str(e)[:200]}",
            "agent": "RISK_MANAGER",
            "vote": "GREEN" if hard_rules_result["passed"] else "RED",
        }
