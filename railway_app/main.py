"""
GOLD SESSION SNIPER v2.0 — Railway Orchestrator
Runs on cron schedule. Fires all agents. Logs to Supabase. Sends Telegram alert. Exits cleanly.

Execution order (Fix #2):
  1. macro + technical run in PARALLEL
  2. quant runs SEQUENTIALLY with macro+technical outputs
  3. debate runs with all three
  4. risk manager
  5. final executor
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import date, datetime, timezone

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

from agents.bull_bear_debate import run_bull_bear_debate
from agents.final_executor import run_final_executor
from agents.macro_scout import run_macro_scout
from agents.quant_reasoner import run_quant_reasoner
from agents.risk_manager import run_risk_manager
from agents.technical_analyst import run_technical_analyst
from agents import news_sentiment as news_agent
from agents import volatility_regime as regime_agent
from agents import correlation_agent as corr_agent
from memory.supabase_memory import (
    get_agent_memory,
    get_balance_from_supabase,
    get_system_memory,
    log_agent_votes,
    log_signal,
)
from utils.market_data import fetch_market_data
from utils.openrouter import get_credits_info
from utils.session_guard import get_current_session, is_valid_trading_time
from utils.telegram_alerts import send_cost_alert, send_error_alert, send_signal_alert

# ── Env var validation — fail fast with clear message ────────────────────────
_REQUIRED_ENV = [
    "OPENROUTER_API_KEY",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
]
_missing = [v for v in _REQUIRED_ENV if not os.getenv(v)]
if _missing:
    raise RuntimeError(f"Missing required environment variables: {_missing}")

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

    # 2. READ ACCOUNT BALANCE FROM SUPABASE (Fix #7)
    env_balance = float(os.getenv("ACCOUNT_BALANCE", "20.00"))
    try:
        bal_row = (
            supabase.table("trade_outcomes")
            .select("account_balance_after")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if bal_row.data and bal_row.data[0].get("account_balance_after"):
            account_balance = float(bal_row.data[0]["account_balance_after"])
            print(f"Balance (from Supabase): ${account_balance:.2f}")
        else:
            account_balance = env_balance
            print(f"Balance (from env var):  ${account_balance:.2f}")
    except Exception as e:
        account_balance = env_balance
        print(f"Balance read failed ({e}) — using env var: ${account_balance:.2f}")

    # 3. DAILY LOSS CIRCUIT BREAKER — abort before any agent runs
    try:
        daily_stop_pct = 3.0
        today_iso = date.today().isoformat()
        loss_rows = (
            supabase.table("trade_outcomes")
            .select("profit_usd")
            .gte("created_at", f"{today_iso}T00:00:00")
            .execute()
        )
        net_today = sum(
            float(r.get("profit_usd") or 0) for r in (loss_rows.data or [])
        )
        daily_loss_usd = abs(net_today) if net_today < 0 else 0.0
        daily_loss_pct = (daily_loss_usd / account_balance * 100) if account_balance > 0 else 0
        if daily_loss_pct >= daily_stop_pct:
            msg = (
                f"DAILY STOP HIT — net loss ${daily_loss_usd:.2f} "
                f"({daily_loss_pct:.2f}%) >= {daily_stop_pct}%. Aborting."
            )
            print(msg)
            await send_error_alert(
                f"DAILY STOP HIT\nNet loss today: ${daily_loss_usd:.2f} "
                f"({daily_loss_pct:.2f}% of ${account_balance:.2f})\n"
                f"Aborting {session} session."
            )
            sys.exit(0)
    except SystemExit:
        raise
    except Exception as e:
        print(f"WARNING: Daily-loss check failed (continuing): {e}")

    # 4. SNAPSHOT OPENROUTER USAGE
    print("Snapshotting OpenRouter usage...")
    credits_before = await get_credits_info()
    if credits_before["error"]:
        print(f"   WARNING: credits snapshot failed — {credits_before['error']}")
    else:
        print(f"   Usage so far: ${credits_before['usage_total']:.4f}")

    # 5. FETCH LIVE MARKET DATA (MT5 via Supabase → yfinance fallback)
    print("Fetching XAUUSD market data...")
    try:
        market_data = await fetch_market_data(supabase=supabase)
        print(f"   Source: {market_data.get('data_source','?')}")
        print(f"   Price: ${market_data['current_price']}")
        print(f"   ATR:   {market_data['indicators']['atr_14']}")
        print(f"   Asian: {market_data['asian_range']['high']} / {market_data['asian_range']['low']}")
        print(f"   DXY:   {market_data['macro']['dxy'].get('current','?')} ({market_data['macro']['dxy'].get('direction','?')})")
        print(f"   10Y:   {market_data['macro']['tnx_10y'].get('current','?')}% ({market_data['macro']['tnx_10y'].get('direction','?')})")
        print(f"   VIX:   {market_data['macro']['vix'].get('current','?')} ({market_data['macro']['vix'].get('direction','?')})")
        cal_count = len(market_data.get("economic_calendar", []))
        print(f"   Calendar: {cal_count} events today")
    except Exception as e:
        err = f"Market data failed: {e}"
        print(f"ERROR: {err}")
        await send_error_alert(err)
        sys.exit(1)

    # 6. FETCH AGENT MEMORIES
    print("Loading agent memories from Supabase...")
    memories = {}
    for agent in ["MACRO_SCOUT", "TECHNICAL_ANALYST", "QUANT_REASONER", "BULL_BEAR_DEBATE", "RISK_MANAGER"]:
        memories[agent] = await get_agent_memory(agent, supabase)
    system_memory = await get_system_memory(supabase)

    # ── Pre-initialise all agent outputs with RED/ABORT safe defaults.
    # These are used by the logging section even if the agent phase times out.
    account_state = {
        "balance":  account_balance,
        "session":  session,
        "risk_pct": float(os.getenv("RISK_PCT", "1.0")),
        "max_lot":  float(os.getenv("MAX_LOT", "0.01")),
    }
    macro     = {"vote": "RED",  "agent": "MACRO_SCOUT",       "bias": "UNKNOWN"}
    technical = {"vote": "RED",  "agent": "TECHNICAL_ANALYST",  "setup_grade": "NO_SETUP"}
    quant     = {"vote": "RED",  "agent": "QUANT_REASONER",    "probability_score": 0,
                 "correct_lot_size": 0.01, "max_risk_usd": 0.20, "verified_rr_tp1": 0}
    debate    = {"vote": "RED",  "agent": "BULL_BEAR_DEBATE",  "winner": "BEAR", "conviction": "LOW"}
    risk      = {"vote": "RED",  "agent": "RISK_MANAGER",
                 "risk_assessment": "REJECTED", "rejection_reason": "Agent phase incomplete"}
    all_outputs: dict = {}
    green_count = 0
    total_green = 0
    final: dict = {
        "decision": "ABORT", "direction": "NONE",
        "entry_price": 0, "stop_loss": 0, "take_profit_1": 0, "take_profit_2": 0,
        "lot_size": 0, "risk_usd": 0, "rr_tp1": 0, "rr_tp2": 0,
        "confidence_score": 0,
        "abort_reason": "Agent phase did not complete",
        "agent": "FINAL_EXECUTOR",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # ── 7-11. AGENT PHASE — 240s budget (was 150s); logging still has time within global budget
    regime_result: dict = {}
    news_result: dict = {}
    corr_result: dict = {}

    async def _run_agents() -> None:
        nonlocal macro, technical, quant, debate, risk, all_outputs, final, green_count, total_green
        nonlocal regime_result, news_result, corr_result

        # 7a. Pre-checks — Volatility regime + News sentiment (run first, in parallel)
        print("Running pre-checks (volatility regime + news sentiment)...")
        candles_m15 = market_data.get("candles_m15") or market_data.get("recent_candles_1h", [])
        atr_pips_in = None
        try:
            atr_val = market_data.get("indicators", {}).get("atr_14")
            if atr_val is not None:
                # ATR is in price units (XAUUSD: 1 pip = 0.10), convert to pips
                atr_pips_in = float(atr_val) * 10
        except Exception:
            atr_pips_in = None

        try:
            regime_result = regime_agent.run(
                candles_m15=candles_m15,
                current_atr=atr_pips_in,
            )
        except Exception as exc:
            print(f"   Regime agent error: {exc}")
            regime_result = {"agent": "volatility_regime", "vote": "GREEN",
                             "regime": "NORMAL", "min_confluence": 4,
                             "lot_multiplier": 1.0, "sl_multiplier": 1.0,
                             "atr_pips": 15.0, "note": "Default (error)"}

        try:
            news_result = await news_agent.run(
                current_price=market_data.get("current_price", 0.0),
                session=session,
            )
        except Exception as exc:
            print(f"   News agent error: {exc}")
            news_result = {"agent": "news_sentiment", "vote": "YELLOW",
                           "sentiment_label": "NEUTRAL", "trade_caution": False,
                           "caution_reason": None}

        print(f"   Regime: {regime_result.get('regime')} (ATR {regime_result.get('atr_pips')} pips, "
              f"min_conf={regime_result.get('min_confluence')}, lot_mult={regime_result.get('lot_multiplier')})")
        print(f"   News:   {news_result.get('sentiment_label')} caution={news_result.get('trade_caution')}")

        # Skip if breaking news warrants caution AND vote is RED
        if news_result.get("trade_caution") and news_result.get("vote") == "RED":
            print("WARNING: News agent flagged trade_caution=True with RED vote — aborting trade")
            final["decision"] = "ABORT"
            final["abort_reason"] = (
                f"News blackout: {news_result.get('caution_reason') or news_result.get('key_headline') or 'breaking news'}"
            )

        # 7. Macro + Technical in parallel
        print("Running macro + technical agents in parallel...")
        macro, technical = await asyncio.gather(
            run_macro_scout(market_data, memories["MACRO_SCOUT"]),
            run_technical_analyst(market_data, memories["TECHNICAL_ANALYST"]),
        )
        print(f"   Macro:     {macro.get('vote')} — {macro.get('bias')} "
              f"(DXY {macro.get('dxy_direction','?')}, Yields {macro.get('yields_direction','?')})")
        print(f"   Technical: {technical.get('vote')} — Grade {technical.get('setup_grade')}")

        # CHANGE 8 — verify confluence score arithmetic
        if isinstance(technical, dict) and "confluence_details" in technical and "confluence_score" in technical:
            details = technical.get("confluence_details") or {}
            if isinstance(details, dict):
                actual_score = sum(1 for v in details.values() if v)
                try:
                    reported = int(technical.get("confluence_score", 0) or 0)
                except (TypeError, ValueError):
                    reported = 0
                if abs(actual_score - reported) > 1:
                    print(f"   WARNING: Confluence mismatch reported={reported} actual={actual_score}. Using actual.")
                    technical["confluence_score"] = actual_score

        # 7b. Correlation agent — run AFTER macro_scout (needs macro_bias)
        try:
            corr_result = corr_agent.run(
                macro_data=market_data.get("macro", {}),
                macro_bias=macro.get("bias", "NEUTRAL"),
            )
        except Exception as exc:
            print(f"   Correlation agent error: {exc}")
            corr_result = {"agent": "correlation", "vote": "YELLOW",
                           "aligned_count": 0, "total_signals": 0,
                           "confidence_modifier": 0.0, "note": "Error"}
        print(f"   Corr:      {corr_result.get('vote')} — "
              f"{corr_result.get('aligned_count')}/{corr_result.get('total_signals')} aligned "
              f"(modifier {corr_result.get('confidence_modifier')})")

        # 8. Quant sequentially (needs macro+technical+regime outputs)
        print("Running quant reasoner (sequential — has macro+technical+regime context)...")
        quant = await run_quant_reasoner(
            market_data,
            memories["QUANT_REASONER"],
            macro_output=macro,
            technical_output=technical,
            account_balance=account_balance,
            regime_result=regime_result,
        )
        print(f"   Quant:     {quant.get('vote')} — "
              f"Probability {quant.get('probability_score')}% | "
              f"Lot {quant.get('correct_lot_size')} | R:R {quant.get('verified_rr_tp1')}")

        # CHANGE 8 — abort if quant rejected the trade (lot_size==0)
        if quant.get("correct_lot_size") in (0, 0.0) and quant.get("abort"):
            print(f"   ABORT: Quant rejected — {quant.get('calculation_notes', 'unknown reason')}")
            final["abort_reason"] = (
                f"Quant rejected: {quant.get('calculation_notes', 'lot too small')}"
            )

        # 9. Bull vs Bear debate
        print("Running Bull vs Bear debate...")
        try:
            debate_result = await run_bull_bear_debate(
                market_data, macro, technical, quant, memories["BULL_BEAR_DEBATE"]
            )
        except Exception as e:
            print(f"WARNING: Debate agent failed: {e}")
            debate_result = {"vote": "RED", "winner": "DRAW", "conviction": "LOW",
                             "agent": "BULL_BEAR_DEBATE"}
        debate.update(debate_result)
        print(f"   Debate:    {debate.get('vote')} — "
              f"{debate.get('winner')} wins ({debate.get('conviction')})")

        # 10. Risk Manager (with dynamic regime confluence min)
        print("Risk Manager evaluating...")
        all_votes = [macro, technical, quant, debate]
        green_count = sum(1 for v in all_votes if v.get("vote") == "GREEN")

        risk_result = await run_risk_manager(
            market_data, all_votes, green_count, account_state,
            memories["RISK_MANAGER"], supabase=supabase,
            min_confluence_override=regime_result.get("min_confluence"),
        )
        risk.update(risk_result)
        print(f"   Risk:      {risk.get('vote')} — {risk.get('risk_assessment')}")
        if risk.get("rejection_reason"):
            print(f"   Reason:    {risk.get('rejection_reason')}")

        # 11. Final Executor — include regime/news/correlation in context
        print("Final Executor synthesizing...")
        all_outputs.update({
            "macro_scout":       macro,
            "technical_analyst": technical,
            "quant_reasoner":    quant,
            "bull_bear_debate":  debate,
            "risk_manager":      risk,
            "volatility_regime": regime_result,
            "news_sentiment":    news_result,
            "correlation":       corr_result,
        })
        final_result = await run_final_executor(all_outputs, system_memory, account_state)
        final.update(final_result)
        total_green = green_count + (1 if risk.get("vote") == "GREEN" else 0)

    try:
        await asyncio.wait_for(_run_agents(), timeout=240)
    except asyncio.TimeoutError:
        print("ERROR: Agent phase timed out (>240s) — logging ABORT signal")
        await send_error_alert("Agent pipeline timed out after 240s — ABORT logged, no trade placed")
        total_green = green_count + (1 if risk.get("vote") == "GREEN" else 0)
        final["abort_reason"] = "Agent pipeline timed out (>240s)"
    except SystemExit:
        raise
    except Exception as e:
        err = f"Agent phase error: {e}"
        print(f"ERROR: {err}")
        await send_error_alert(err)
        total_green = 0
        final["abort_reason"] = str(e)[:300]

    # ── 12. LOG TO SUPABASE (always runs — even on agent timeout) ─────────────
    print("Logging to Supabase...")
    total_green = green_count + (1 if risk.get("vote") == "GREEN" else 0)
    if not all_outputs:
        all_outputs = {
            "macro_scout":       macro,
            "technical_analyst": technical,
            "quant_reasoner":    quant,
            "bull_bear_debate":  debate,
            "risk_manager":      risk,
        }
    signal_data = {
        "session":           session,
        "decision":          final.get("decision"),
        "direction":         final.get("direction"),
        "entry_price":       final.get("entry_price"),
        "stop_loss":         final.get("stop_loss"),
        "take_profit_1":     final.get("take_profit_1"),
        "take_profit_2":     final.get("take_profit_2"),
        "lot_size":          final.get("lot_size"),
        "risk_usd":          final.get("risk_usd"),
        "rr_ratio":          final.get("rr_tp1"),
        "confidence_score":  final.get("confidence_score"),
        "green_votes":       total_green,
        "agent_votes":       all_outputs,
        "macro_bias":        macro.get("bias"),
        "technical_grade":   technical.get("setup_grade"),
        "asian_range_high":  market_data["asian_range"]["high"],
        "asian_range_low":   market_data["asian_range"]["low"],
        "executed":          False,
    }
    try:
        signal_id = await log_signal(signal_data, supabase)
        await log_agent_votes(signal_id, all_outputs, supabase)
        print(f"   Signal ID: {signal_id}")
    except Exception as e:
        signal_id = "logging-failed"
        print(f"WARNING: Supabase logging failed: {e}")

    # ── 13. SEND TELEGRAM ALERTS ──────────────────────────────────────────────
    print("Sending Telegram alerts...")
    await send_signal_alert(final, signal_id, total_green, session)

    credits_after = await get_credits_info()
    session_cost = 0.0
    if not credits_before["error"] and not credits_after["error"]:
        session_cost = max(0.0, credits_after["usage_total"] - credits_before["usage_total"])

    today_session_count = 1
    try:
        today_iso = date.today().isoformat()
        today_rows = (
            supabase.table("trade_signals")
            .select("id", count="exact")
            .gte("created_at", f"{today_iso}T00:00:00")
            .execute()
        )
        today_session_count = max(1, today_rows.count or 1)
    except Exception:
        pass

    total_today = session_cost * today_session_count
    days_remaining = None
    if credits_after["credits_remaining"] is not None and session_cost > 0:
        days_remaining = credits_after["credits_remaining"] / (session_cost * 2)

    print(f"   Session cost: ${session_cost:.4f}")
    await send_cost_alert(
        session_cost=session_cost,
        total_today=total_today,
        credits_remaining=credits_after["credits_remaining"],
        days_remaining=days_remaining,
        session=session,
        today_session_count=today_session_count,
    )

    # ── 14. TERMINAL SUMMARY ──────────────────────────────────────────────────
    elapsed = (datetime.now(timezone.utc) - start_time).seconds
    print(f"\n{'='*60}")
    print(f"FINAL DECISION")
    print(f"{'='*60}")
    print(f"Decision:    {final.get('decision')}")
    print(f"Direction:   {final.get('direction')}")
    print(f"Entry:       ${final.get('entry_price','N/A')}")
    print(f"Stop Loss:   ${final.get('stop_loss','N/A')}")
    print(f"TP1:         ${final.get('take_profit_1','N/A')} (R:R {final.get('rr_tp1','N/A')})")
    print(f"TP2:         ${final.get('take_profit_2','N/A')} (R:R {final.get('rr_tp2','N/A')})")
    print(f"Lot Size:    {final.get('lot_size','N/A')}")
    print(f"Risk:        ${final.get('risk_usd','N/A')}")
    print(f"Confidence:  {final.get('confidence_score','N/A')}%")
    print(f"Green Votes: {total_green}/5")
    print(f"Signal ID:   {signal_id}")
    print(f"Runtime:     {elapsed}s")
    print(f"{'='*60}\n")

    sys.exit(0)


if __name__ == "__main__":
    try:
        # Global 6-minute budget — agent phase is now 240s, leaves 120s for logging/alerts
        asyncio.run(asyncio.wait_for(run_gold_sniper(), timeout=360))
    except asyncio.TimeoutError:
        print("ERROR: Session run exceeded 6-minute budget")
        try:
            asyncio.run(send_error_alert("Session timed out after 6 minutes — no signal generated"))
        except Exception:
            pass
        sys.exit(1)
    except SystemExit:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            asyncio.run(send_error_alert(f"FATAL ERROR: {e}"))
        except Exception:
            pass
        sys.exit(1)
