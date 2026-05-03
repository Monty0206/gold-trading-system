"""
Agent 5 — Risk Manager (PURE PYTHON, NO LLM)
Hard rules only. If all pass: GREEN. If any fails: RED with reason.
Includes: daily loss, max trades, equity stop proxy, lot sanity, news blackout, kill switch.
"""

import logging
from datetime import date

from config import HARD_RULES, MODELS  # noqa: F401  (kept for compatibility/lookup)
from utils.session_guard import is_in_news_blackout

logger = logging.getLogger(__name__)


def _count_executed_trades_today(supabase) -> int:
    """Count trades executed today (max trades per day)."""
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
    """Sum today's net loss (positive = net loss) from trade_outcomes."""
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
        net = sum(float(r.get("profit_usd") or 0) for r in (rows.data or []))
        return abs(net) if net < 0 else 0.0
    except Exception:
        return 0.0


def _count_consecutive_losses(supabase) -> int:
    """Most recent streak of consecutive LOSS outcomes."""
    if supabase is None:
        return 0
    try:
        rows = (
            supabase.table("trade_outcomes")
            .select("outcome")
            .order("created_at", desc=True)
            .limit(HARD_RULES["max_consecutive_losses"] + 1)
            .execute()
        )
        count = 0
        for r in (rows.data or []):
            if r.get("outcome") == "LOSS":
                count += 1
            else:
                break
        return count
    except Exception:
        return 0


def _get_account_equity_pct(supabase, account_balance: float) -> float:
    """Get a proxy for current equity vs balance using last outcome.
    Returns a ratio (1.0 = at balance, < 1.0 = drawdown).
    Without live MT5 access from Railway, we approximate by checking if today's
    cumulative P&L would put equity below 95% of balance."""
    if supabase is None or account_balance <= 0:
        return 1.0
    try:
        today_iso = date.today().isoformat()
        rows = (
            supabase.table("trade_outcomes")
            .select("profit_usd")
            .gte("created_at", f"{today_iso}T00:00:00")
            .execute()
        )
        net = sum(float(r.get("profit_usd") or 0) for r in (rows.data or []))
        # equity proxy = balance + net P&L today
        equity_proxy = account_balance + net
        return max(0.0, equity_proxy / account_balance)
    except Exception:
        return 1.0


def _check_python_hard_rules(
    all_votes: list,
    green_count: int,
    account_state: dict,
    technical_output: dict,
    quant_output: dict,
    news_events: list,
    session: str,
    supabase=None,
    min_confluence_override: int | None = None,
) -> dict:
    """Enforce non-negotiable hard rules in pure Python."""
    failed = []

    # Min green votes
    if green_count < HARD_RULES["min_green_votes"]:
        failed.append(
            f"Only {green_count} GREEN votes — need {HARD_RULES['min_green_votes']}"
        )

    # Confluence (with optional dynamic regime override)
    confluence = int(technical_output.get("confluence_score", 0) or 0)
    confluence_min = int(min_confluence_override or HARD_RULES["min_confluence"])
    if confluence < confluence_min:
        failed.append(
            f"Confluence {confluence} < required {confluence_min}"
        )

    # No setup
    if technical_output.get("setup_grade") == "NO_SETUP":
        failed.append("Technical grade is NO_SETUP")

    # Unclear breakout direction
    breakout_dir = technical_output.get("expected_breakout_direction", "UNCLEAR")
    if breakout_dir not in ("UP", "DOWN"):
        failed.append(f"Breakout direction is {breakout_dir!r} — must be UP or DOWN")

    # Min probability
    probability = quant_output.get("probability_score", 0)
    if probability < HARD_RULES["min_probability"]:
        failed.append(
            f"Probability {probability}% < minimum {HARD_RULES['min_probability']}%"
        )

    # Min R:R
    rr = quant_output.get("verified_rr_tp1", 0.0)
    if rr <= 0:
        failed.append(f"R:R is {rr} — no valid R:R data")
    elif rr < HARD_RULES["min_rr_ratio"]:
        failed.append(f"R:R {rr:.2f} < minimum {HARD_RULES['min_rr_ratio']}")

    # Lot size sanity check
    proposed_lot = quant_output.get("correct_lot_size", 0.01)
    if proposed_lot <= 0:
        failed.append(f"Lot size {proposed_lot} — quant rejected the trade")
    elif proposed_lot > HARD_RULES["max_lot_size"]:
        failed.append(f"Lot size {proposed_lot} > max {HARD_RULES['max_lot_size']}")

    # Max risk pct (use actual_risk_usd if available, else target)
    balance = float(account_state.get("balance", 20.0))
    actual_risk = quant_output.get("actual_risk_usd")
    proposed_risk_usd = float(actual_risk if actual_risk is not None else quant_output.get("max_risk_usd", 0.0))
    proposed_risk_pct = (proposed_risk_usd / balance * 100) if balance > 0 else 0
    # Allow up to 2x the configured pct (to match quant's 2x rejection rule)
    max_pct_allowed = HARD_RULES["max_risk_pct"] * 2.0
    if proposed_risk_pct > max_pct_allowed:
        failed.append(
            f"Risk {proposed_risk_pct:.2f}% > max {max_pct_allowed}% (2x override cap)"
        )

    # Max trades executed today
    executed_today = _count_executed_trades_today(supabase)
    if executed_today >= HARD_RULES["max_open_trades"]:
        failed.append(
            f"Already {executed_today} executed trades today — max {HARD_RULES['max_open_trades']}"
        )

    # Daily loss circuit breaker
    daily_loss = _sum_daily_loss(supabase)
    daily_loss_pct = (daily_loss / balance * 100) if balance > 0 else 0
    if daily_loss_pct >= HARD_RULES["max_daily_loss_pct"]:
        failed.append(
            f"Daily loss ${daily_loss:.2f} ({daily_loss_pct:.2f}%) >= "
            f"max {HARD_RULES['max_daily_loss_pct']}% — DAILY STOP HIT"
        )

    # Equity stop proxy (approximate from today's cumulative P&L)
    equity_ratio = _get_account_equity_pct(supabase, balance)
    if equity_ratio < 0.95:
        failed.append(
            f"Equity ratio {equity_ratio:.2%} below 95% — equity stop"
        )

    # Consecutive losses kill switch
    consecutive = _count_consecutive_losses(supabase)
    if consecutive >= HARD_RULES["max_consecutive_losses"]:
        failed.append(
            f"{consecutive} consecutive losses — strategy pause (kill switch)"
        )

    # Session blackouts
    if session == "ASIAN" and HARD_RULES["no_trade_asian_session"]:
        failed.append("Asian session — no trading 00:00-07:00 GMT")
    if session == "GAP" and HARD_RULES["no_trade_gap_session"]:
        failed.append("Gap session — no trading 12:00-12:45 GMT")

    # News blackout (uses tightened blackout — both HIGH and MEDIUM impact)
    if is_in_news_blackout(news_events, HARD_RULES["no_trade_mins_before_news"]):
        failed.append(
            f"HIGH/MEDIUM-impact news within {HARD_RULES['no_trade_mins_before_news']} minutes"
        )

    # Math errors from quant
    if quant_output.get("math_errors"):
        failed.append(f"Math errors detected: {quant_output['math_errors']}")

    # Quant abort flag
    if quant_output.get("abort"):
        failed.append("Quant Reasoner aborted (lot too small or invalid inputs)")

    return {"passed": len(failed) == 0, "failed_rules": failed}


async def run_risk_manager(
    market_data: dict,
    all_votes: list,
    green_count: int,
    account_state: dict,
    memory_context: str,
    supabase=None,
    min_confluence_override: int | None = None,
) -> dict:
    """Pure Python Risk Manager — no LLM call.
    GREEN if all hard rules pass, RED with reason if any fail."""
    technical_output = next(
        (v for v in all_votes if v.get("agent") == "TECHNICAL_ANALYST"), {}
    )
    quant_output = next(
        (v for v in all_votes if v.get("agent") == "QUANT_REASONER"), {}
    )
    macro_output = next(
        (v for v in all_votes if v.get("agent") == "MACRO_SCOUT"), {}
    )

    calendar_events = market_data.get("economic_calendar") or []
    news_events = calendar_events if calendar_events else macro_output.get("risk_events_today", [])
    session = account_state.get("session", "UNKNOWN")

    # Run hard rules
    hard_rules_result = _check_python_hard_rules(
        all_votes=all_votes,
        green_count=green_count,
        account_state=account_state,
        technical_output=technical_output,
        quant_output=quant_output,
        news_events=news_events,
        session=session,
        supabase=supabase,
        min_confluence_override=min_confluence_override,
    )

    # Build trade proposal
    zone_from = float(technical_output.get("entry_zone_from") or 0)
    zone_to   = float(technical_output.get("entry_zone_to") or 0)
    if zone_from > 0 and zone_to > 0:
        entry = round((zone_from + zone_to) / 2, 2)
    else:
        entry = zone_from or zone_to

    breakout_dir = technical_output.get("expected_breakout_direction", "UNCLEAR")
    if breakout_dir == "UP":
        direction = "LONG"
    elif breakout_dir == "DOWN":
        direction = "SHORT"
    else:
        direction = "NONE"

    if hard_rules_result["passed"]:
        logger.info(f"Risk Manager: GREEN — all hard rules passed (green={green_count})")
        return {
            "hard_rules_passed": True,
            "failed_rules": [],
            "sanity_check_passed": True,
            "sanity_concerns": [],
            "risk_assessment": "APPROVED",
            "rejection_reason": None,
            "approved_lot_size":  quant_output.get("correct_lot_size", 0.01),
            "approved_risk_usd":  quant_output.get("actual_risk_usd",
                                                    quant_output.get("max_risk_usd", 0.20)),
            "approved_entry":     entry,
            "approved_sl":        technical_output.get("stop_loss", 0),
            "approved_tp1":       technical_output.get("take_profit_1", 0),
            "approved_tp2":       technical_output.get("take_profit_2", 0),
            "risk_notes": f"Pure Python rules — APPROVED. Direction: {direction}",
            "agent": "RISK_MANAGER",
            "vote": "GREEN",
        }

    # Failed
    logger.warning(f"Risk Manager: RED — {hard_rules_result['failed_rules']}")
    return {
        "hard_rules_passed": False,
        "failed_rules": hard_rules_result["failed_rules"],
        "sanity_check_passed": False,
        "sanity_concerns": [],
        "risk_assessment": "REJECTED",
        "rejection_reason": "; ".join(hard_rules_result["failed_rules"]),
        "approved_lot_size":  quant_output.get("correct_lot_size", 0.01),
        "approved_risk_usd":  quant_output.get("max_risk_usd", 0.20),
        "approved_entry":     entry,
        "approved_sl":        technical_output.get("stop_loss", 0),
        "approved_tp1":       technical_output.get("take_profit_1", 0),
        "approved_tp2":       technical_output.get("take_profit_2", 0),
        "risk_notes": "Hard rules failed.",
        "agent": "RISK_MANAGER",
        "vote": "RED",
    }
