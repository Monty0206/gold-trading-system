"""
GOLD SESSION SNIPER v2.0 — Railway Orchestrator
Runs on cron schedule. Fires all agents. Logs to Supabase. Sends Telegram alert. Exits cleanly.
"""

import asyncio
import json
import os
import sys

# Add railway_app/ to path so all module imports resolve correctly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timezone

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

from agents.macro_scout import run_macro_scout
from agents.technical_analyst import run_technical_analyst
from agents.quant_reasoner import run_quant_reasoner
from agents.bull_bear_debate import run_bull_bear_debate
from agents.risk_manager import run_risk_manager
from agents.final_executor import run_final_executor
from memory.supabase_memory import (
    get_agent_memory,
    get_system_memory,
    log_signal,
    log_agent_votes,
)
from utils.market_data import fetch_market_data
from utils.openrouter import get_credits_info
from utils.telegram_alerts import send_signal_alert, send_cost_alert, send_error_alert
from utils.session_guard import get_current_session, is_valid_trading_time

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY"),
)


async def run_gold_sniper() -> None:
    start_time = datetime.now(timezone.utc)
    print(f"\n{'='*60}")
    print(f"GOLD SESSION SNIPER v2.0")
    print(f"  {start_time.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}")

    # 1. CHECK SESSION VALIDITY
    session = get_current_session()
    if not is_valid_trading_time():
        print(f"Outside trading hours ({session}). Exiting.")
        sys.exit(0)
    print(f"Session: {session}")

    # 2. SNAPSHOT OPENROUTER USAGE (before any agent calls)
    print("Snapshotting OpenRouter usage...")
    credits_before = await get_credits_info()
    if credits_before["error"]:
        print(f"   WARNING: credits snapshot failed — {credits_before['error']}")
    else:
        print(f"   Usage so far: ${credits_before['usage_total']:.4f}")

    # 3. FETCH LIVE MARKET DATA
    print("Fetching XAUUSD market data...")
    try:
        market_data = await fetch_market_data()
        print(f"   Price: ${market_data['current_price']}")
        print(f"   ATR:   {market_data['indicators']['atr_14']}")
        print(
            f"   Asian: {market_data['asian_range']['high']} / "
            f"{market_data['asian_range']['low']}"
        )
    except Exception as e:
        err = f"Market data failed: {e}"
        print(f"ERROR: {err}")
        await send_error_alert(err)
        sys.exit(1)

    # 4. FETCH AGENT MEMORIES FROM SUPABASE
    print("Loading agent memories from Supabase...")
    memories = {}
    for agent in [
        "MACRO_SCOUT",
        "TECHNICAL_ANALYST",
        "QUANT_REASONER",
        "BULL_BEAR_DEBATE",
        "RISK_MANAGER",
    ]:
        memories[agent] = await get_agent_memory(agent, supabase)
    system_memory = await get_system_memory(supabase)

    # 5. RUN AGENTS 1, 2, 3 IN PARALLEL
    print("Running parallel analysis agents...")
    try:
        macro, technical, quant = await asyncio.gather(
            run_macro_scout(market_data, memories["MACRO_SCOUT"]),
            run_technical_analyst(market_data, memories["TECHNICAL_ANALYST"]),
            run_quant_reasoner(market_data, memories["QUANT_REASONER"]),
        )
        print(f"   Macro:     {macro.get('vote')} — {macro.get('bias')}")
        print(
            f"   Technical: {technical.get('vote')} — "
            f"Grade {technical.get('setup_grade')}"
        )
        print(
            f"   Quant:     {quant.get('vote')} — "
            f"Probability {quant.get('probability_score')}%"
        )
    except Exception as e:
        err = f"Agent 1-3 failed: {e}"
        print(f"ERROR: {err}")
        await send_error_alert(err)
        sys.exit(1)

    # 6. BULL vs BEAR DEBATE
    print("Running Bull vs Bear debate...")
    try:
        debate = await run_bull_bear_debate(
            market_data, macro, technical, quant, memories["BULL_BEAR_DEBATE"]
        )
        print(
            f"   Debate:    {debate.get('vote')} — "
            f"{debate.get('winner')} wins ({debate.get('conviction')})"
        )
    except Exception as e:
        print(f"WARNING: Debate agent failed: {e}")
        debate = {
            "vote": "YELLOW",
            "winner": "DRAW",
            "conviction": "LOW",
            "agent": "BULL_BEAR_DEBATE",
        }

    # 7. RISK MANAGER
    print("Risk Manager evaluating...")
    account_state = {
        "balance": float(os.getenv("ACCOUNT_BALANCE", "20.00")),
        "session": session,
        "risk_pct": float(os.getenv("RISK_PCT", "1.0")),
        "max_lot": float(os.getenv("MAX_LOT", "0.01")),
    }
    all_votes = [macro, technical, quant, debate]
    green_count = sum(1 for v in all_votes if v.get("vote") == "GREEN")

    risk = await run_risk_manager(
        market_data, all_votes, green_count, account_state, memories["RISK_MANAGER"]
    )
    print(f"   Risk:      {risk.get('vote')} — {risk.get('risk_assessment')}")
    if risk.get("rejection_reason"):
        print(f"   Reason:    {risk.get('rejection_reason')}")

    # 8. FINAL EXECUTOR
    print("Final Executor synthesizing...")
    all_outputs = {
        "macro_scout": macro,
        "technical_analyst": technical,
        "quant_reasoner": quant,
        "bull_bear_debate": debate,
        "risk_manager": risk,
    }
    final = await run_final_executor(all_outputs, system_memory, account_state)

    # 9. LOG TO SUPABASE
    print("Logging to Supabase...")
    total_green = green_count + (1 if risk.get("vote") == "GREEN" else 0)
    signal_data = {
        "session": session,
        "decision": final.get("decision"),
        "direction": final.get("direction"),
        "entry_price": final.get("entry_price"),
        "stop_loss": final.get("stop_loss"),
        "take_profit_1": final.get("take_profit_1"),
        "take_profit_2": final.get("take_profit_2"),
        "lot_size": final.get("lot_size"),
        "risk_usd": final.get("risk_usd"),
        "rr_ratio": final.get("rr_tp1"),
        "confidence_score": final.get("confidence_score"),
        "green_votes": total_green,
        "agent_votes": all_outputs,
        "macro_bias": macro.get("bias"),
        "technical_grade": technical.get("setup_grade"),
        "asian_range_high": market_data["asian_range"]["high"],
        "asian_range_low": market_data["asian_range"]["low"],
        "executed": False,
    }
    try:
        signal_id = await log_signal(signal_data, supabase)
        await log_agent_votes(signal_id, all_outputs, supabase)
        print(f"   Signal ID: {signal_id}")
    except Exception as e:
        signal_id = "logging-failed"
        print(f"WARNING: Supabase logging failed: {e}")

    # 10. SEND TELEGRAM SIGNAL ALERT
    print("Sending Telegram signal alert...")
    await send_signal_alert(final, signal_id, total_green, session)

    # 11. SEND TELEGRAM COST SUMMARY
    print("Calculating session cost...")
    credits_after = await get_credits_info()

    session_cost = 0.0
    if not credits_before["error"] and not credits_after["error"]:
        session_cost = max(0.0, credits_after["usage_total"] - credits_before["usage_total"])

    # Count how many signals ran today (to approximate total daily spend)
    today_session_count = 1
    try:
        from datetime import date
        today_iso = date.today().isoformat()
        today_rows = (
            supabase.table("trade_signals")
            .select("id", count="exact")
            .gte("created_at", f"{today_iso}T00:00:00")
            .execute()
        )
        today_session_count = max(1, today_rows.count or 1)
    except Exception:
        pass  # Fall back to 1 session

    total_today = session_cost * today_session_count

    # Days remaining: credits_remaining / projected daily cost (2 sessions/day)
    days_remaining = None
    if credits_after["credits_remaining"] is not None and session_cost > 0:
        daily_rate = session_cost * 2
        days_remaining = credits_after["credits_remaining"] / daily_rate

    print(
        f"   Session cost: ${session_cost:.4f} | "
        f"Credits remaining: "
        + (f"${credits_after['credits_remaining']:.4f}" if credits_after["credits_remaining"] is not None else "N/A")
    )
    await send_cost_alert(
        session_cost=session_cost,
        total_today=total_today,
        credits_remaining=credits_after["credits_remaining"],
        days_remaining=days_remaining,
        session=session,
        today_session_count=today_session_count,
    )

    # 13. TERMINAL SUMMARY
    elapsed = (datetime.now(timezone.utc) - start_time).seconds
    print(f"\n{'='*60}")
    print(f"FINAL DECISION")
    print(f"{'='*60}")
    print(f"Decision:    {final.get('decision')}")
    print(f"Direction:   {final.get('direction')}")
    print(f"Entry:       ${final.get('entry_price', 'N/A')}")
    print(f"Stop Loss:   ${final.get('stop_loss', 'N/A')}")
    print(
        f"TP1:         ${final.get('take_profit_1', 'N/A')} "
        f"(R:R {final.get('rr_tp1', 'N/A')})"
    )
    print(
        f"TP2:         ${final.get('take_profit_2', 'N/A')} "
        f"(R:R {final.get('rr_tp2', 'N/A')})"
    )
    print(f"Lot Size:    {final.get('lot_size', 'N/A')}")
    print(f"Risk:        ${final.get('risk_usd', 'N/A')}")
    print(f"Confidence:  {final.get('confidence_score', 'N/A')}%")
    print(f"Green Votes: {total_green}/6")
    print(f"Signal ID:   {signal_id}")
    print(f"Runtime:     {elapsed}s")
    print(f"{'='*60}\n")

    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(run_gold_sniper())
