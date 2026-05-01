"""
MT5 EXECUTOR — Runs on your Home PC (Windows 24/7)
Watches Supabase for new EXECUTE signals.
Places trades on Deriv MT5 automatically.
Reports outcomes back to Supabase and triggers agent learning loop.
"""

import os
import signal
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx
import MetaTrader5 as mt5
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY"),
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")

# Auto-detected at startup
SYMBOL = "XAUUSD"
FILLING_MODE = None


# ============================================================
# GRACEFUL SHUTDOWN (SIGTERM from system restart / Task Scheduler)
# ============================================================

def _shutdown_handler(*_):
    print("\nSIGTERM received — shutting down cleanly.")
    mt5.shutdown()
    sys.exit(0)

signal.signal(signal.SIGTERM, _shutdown_handler)


# ============================================================
# TELEGRAM ALERTS (sync)
# ============================================================

def send_telegram(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"},
            )
            if resp.status_code != 200:
                print(f"[Telegram] HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"[Telegram] Failed: {e}")


def send_daily_stop_alert(daily_loss_usd: float, daily_stop: float) -> None:
    send_telegram(
        f"DAILY STOP HIT\n"
        f"Daily loss: `${daily_loss_usd:.2f}`\n"
        f"Daily stop: `${daily_stop:.2f}`\n"
        f"Refusing new signals for the rest of the day."
    )


def send_session_close_alert(session_name: str) -> None:
    send_telegram(
        f"SESSION ENDING — {session_name}\n"
        f"Closing all open XAUUSD positions before session end."
    )


def send_be_move_alert(ticket: int, entry_price: float) -> None:
    send_telegram(
        f"SL MOVED TO BREAKEVEN\n"
        f"Ticket: `#{ticket}`\n"
        f"New SL: `${entry_price:.2f}` (entry)\n"
        f"Trade is now risk-free."
    )


# ============================================================
# MT5 CONNECTION
# ============================================================

def connect_mt5() -> bool:
    if not mt5.initialize():
        print(f"MT5 initialize failed: {mt5.last_error()}")
        return False

    login_str = os.getenv("MT5_LOGIN")
    if not login_str:
        print("MT5_LOGIN env var not set")
        mt5.shutdown()
        return False
    try:
        login = int(login_str)
    except ValueError:
        print(f"MT5_LOGIN is not a valid integer: {login_str!r}")
        mt5.shutdown()
        return False

    password = os.getenv("MT5_PASSWORD")
    server   = os.getenv("MT5_SERVER", "Deriv-Server")

    if not mt5.login(login, password=password, server=server):
        print(f"MT5 login failed: {mt5.last_error()}")
        mt5.shutdown()
        return False

    info = mt5.account_info()
    print(f"MT5 Connected: {info.name} | Balance: ${info.balance:.2f}")
    return True


def detect_symbol() -> str:
    """Auto-detect the correct XAUUSD symbol name for this broker/account."""
    candidates = ["XAUUSD", "XAUUSD.", "XAUUSDm", "XAUUSDc", "XAUUSDi", "Gold", "GOLD"]
    for sym in candidates:
        info = mt5.symbol_info(sym)
        if info is not None:
            mt5.symbol_select(sym, True)
            print(f"Symbol detected: {sym}")
            return sym
    print("WARNING: Could not detect XAUUSD symbol. Defaulting to 'XAUUSD'.")
    return "XAUUSD"


def detect_filling_mode(symbol: str) -> int:
    """Probe the broker's supported filling mode for a symbol."""
    si = mt5.symbol_info(symbol)
    if si is None:
        return mt5.ORDER_FILLING_IOC
    fm = si.filling_mode
    if fm & 1:
        print(f"Filling mode: FOK (filling_mode={fm})")
        return mt5.ORDER_FILLING_FOK
    if fm & 2:
        print(f"Filling mode: IOC (filling_mode={fm})")
        return mt5.ORDER_FILLING_IOC
    print(f"Filling mode: RETURN (filling_mode={fm})")
    return mt5.ORDER_FILLING_RETURN


# ============================================================
# DAILY LOSS FROM SUPABASE (survives restarts)
# ============================================================

def get_daily_loss_from_supabase() -> float:
    """Sum today's net loss from Supabase trade_outcomes (survives restarts)."""
    try:
        today_iso = datetime.now(timezone.utc).date().isoformat()
        rows = (
            supabase.table("trade_outcomes")
            .select("profit_usd")
            .gte("created_at", f"{today_iso}T00:00:00")
            .execute()
        )
        net = sum(float(r.get("profit_usd") or 0) for r in (rows.data or []))
        return abs(net) if net < 0 else 0.0
    except Exception as e:
        print(f"[DailyLoss] Supabase read failed: {e}")
        return 0.0


# ============================================================
# PLACE TRADE (Fix #4: atomic PENDING claim, Fix #8: symbol/filling)
# ============================================================

def place_trade(signal: dict) -> dict:
    global SYMBOL, FILLING_MODE

    direction    = signal.get("direction", "")
    lot          = float(signal.get("lot_size", 0.01))
    sl           = float(signal.get("stop_loss", 0))
    tp1          = float(signal.get("take_profit_1", 0))
    signal_entry = float(signal.get("entry_price", 0))

    # Live tick
    tick = mt5.symbol_info_tick(SYMBOL)
    if not tick:
        return {"success": False, "error": f"Could not get tick data for {SYMBOL}"}

    if direction == "LONG":
        order_type = mt5.ORDER_TYPE_BUY
        price = tick.ask
    elif direction == "SHORT":
        order_type = mt5.ORDER_TYPE_SELL
        price = tick.bid
    else:
        return {"success": False, "error": f"Unknown direction: {direction}"}

    # Tighter slippage guard (15 pips — was 50, $0.50 was unacceptable on $20)
    slippage_pips = abs(price - signal_entry) * 10
    if slippage_pips > 15:
        return {
            "success": False,
            "error": (
                f"Price slipped {slippage_pips:.1f} pips (max 15): "
                f"signal={signal_entry}, current={price}"
            ),
        }

    # Stops level check — prevent INVALID_STOPS retcode 10016
    si = mt5.symbol_info(SYMBOL)
    if si:
        min_dist = si.trade_stops_level * si.point
        if min_dist > 0:
            if direction == "LONG" and sl > 0:
                sl = min(sl, price - min_dist)
            elif direction == "SHORT" and sl > 0:
                sl = max(sl, price + min_dist)

    request = {
        "action":      mt5.TRADE_ACTION_DEAL,
        "symbol":      SYMBOL,
        "volume":      lot,
        "type":        order_type,
        "price":       price,
        "sl":          sl,
        "tp":          tp1,
        "deviation":   20,
        "magic":       20260101,
        "comment":     f"GoldSniper|{str(signal.get('id',''))[:8]}",
        "type_time":   mt5.ORDER_TIME_GTC,
        "type_filling": FILLING_MODE,
    }

    result = mt5.order_send(request)
    if result is None:
        return {"success": False, "error": "order_send returned None"}

    if result.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"TRADE PLACED: Ticket #{result.order}")
        print(f"   {direction} {lot} lots {SYMBOL} @ {price}")
        print(f"   SL: {sl} | TP1: {tp1}")
        return {
            "success": True,
            "ticket": result.order,
            "execution_price": price,
            "execution_time": datetime.now(timezone.utc).isoformat(),
        }
    else:
        error = f"Order failed: retcode={result.retcode}, comment={result.comment}"
        print(f"ERROR: {error}")
        return {"success": False, "error": error}


# ============================================================
# MONITOR OPEN TRADES
# ============================================================

def check_trade_outcome(ticket: int, signal_id: str, signal: dict):
    """Return outcome dict if trade has closed, else None."""
    if mt5.positions_get(ticket=ticket):
        return None  # Still open

    # Only look back 7 days — avoids pulling years of history every 5s
    from_date = datetime.now(timezone.utc) - timedelta(days=7)
    to_date   = datetime.now(timezone.utc)
    history   = mt5.history_deals_get(from_date, to_date)
    if not history:
        return None

    entry_deal_time = None
    for deal in history:
        if deal.order == ticket and deal.entry == mt5.DEAL_ENTRY_IN:
            entry_deal_time = deal.time
            break

    for deal in history:
        if deal.order == ticket and deal.entry == mt5.DEAL_ENTRY_OUT:
            profit     = deal.profit
            exit_price = deal.price
            entry_price = float(signal.get("entry_price", 0))
            pips = abs(exit_price - entry_price) * 10

            outcome = "WIN" if profit > 0 else "LOSS" if profit < 0 else "BREAKEVEN"

            sl  = float(signal.get("stop_loss", 0))
            tp1 = float(signal.get("take_profit_1", 0))
            direction = signal.get("direction", "")

            if direction == "LONG":
                exit_reason = "TP1" if exit_price >= tp1 - 0.5 else "SL" if exit_price <= sl + 0.5 else "MANUAL"
            else:
                exit_reason = "TP1" if exit_price <= tp1 + 0.5 else "SL" if exit_price >= sl - 0.5 else "MANUAL"

            duration_minutes = None
            if entry_deal_time and deal.time:
                duration_minutes = max(0, int((deal.time - entry_deal_time) / 60))

            return {
                "signal_id":            signal_id,
                "outcome":              outcome,
                "exit_reason":          exit_reason,
                "entry_price":          float(entry_price),
                "exit_price":           float(exit_price),
                "profit_usd":           float(profit),
                "profit_pips":          round(float(pips), 1),
                "duration_minutes":     duration_minutes,
                "account_balance_after": float(mt5.account_info().balance),
            }
    return None


# ============================================================
# LEARNING LOOP — mark agents correct/incorrect (Fix #5)
# ============================================================

def trigger_learning_loop(signal_id: str, outcome: str) -> None:
    """Update agent_performance.was_correct and market_patterns after trade closes."""
    try:
        rows = (
            supabase.table("agent_performance")
            .select("id, vote")
            .eq("signal_id", signal_id)
            .execute()
        )
        for row in (rows.data or []):
            vote = row.get("vote", "")
            if vote == "YELLOW":
                continue
            if outcome == "WIN":
                was_correct = (vote == "GREEN")
            elif outcome == "LOSS":
                was_correct = (vote == "RED")
            else:
                continue  # BREAKEVEN — skip
            supabase.table("agent_performance").update(
                {"was_correct": was_correct, "outcome": outcome}
            ).eq("id", row["id"]).execute()
        print(f"[Learning] Agent performance updated for signal {signal_id[:8]}")
    except Exception as e:
        print(f"[Learning] agent_performance update failed: {e}")

    try:
        sig_row = (
            supabase.table("trade_signals")
            .select("macro_bias, technical_grade, session, direction")
            .eq("id", signal_id)
            .execute()
        )
        if not sig_row.data:
            return
        sig = sig_row.data[0]
        pattern_name = (
            f"{sig.get('session','UNKNOWN')}_"
            f"{sig.get('macro_bias','NEUTRAL')}_"
            f"{sig.get('technical_grade','C')}_"
            f"{sig.get('direction','UNKNOWN')}"
        )
        was_win = (outcome == "WIN")
        now_iso = datetime.now(timezone.utc).isoformat()

        existing = (
            supabase.table("market_patterns")
            .select("win_count, loss_count, sample_size")
            .eq("pattern_name", pattern_name)
            .execute()
        )
        if existing.data:
            p = existing.data[0]
            wins   = p["win_count"]  + (1 if was_win else 0)
            losses = p["loss_count"] + (0 if was_win else 1)
            total  = wins + losses
            supabase.table("market_patterns").update({
                "win_count":   wins,
                "loss_count":  losses,
                "sample_size": total,
                "win_rate":    round(wins / total * 100, 2),
                "last_seen":   now_iso,
            }).eq("pattern_name", pattern_name).execute()
        else:
            supabase.table("market_patterns").upsert({
                "pattern_name":        pattern_name,
                "description":         f"Auto: {pattern_name}",
                "session":             sig.get("session"),
                "macro_condition":     sig.get("macro_bias"),
                "technical_condition": sig.get("technical_grade"),
                "sample_size":         1,
                "win_count":           1 if was_win else 0,
                "loss_count":          0 if was_win else 1,
                "win_rate":            100.0 if was_win else 0.0,
                "last_seen":           now_iso,
            }, on_conflict="pattern_name").execute()
        print(f"[Learning] Pattern memory updated: {pattern_name}")
    except Exception as e:
        print(f"[Learning] Pattern memory update failed: {e}")


# ============================================================
# MOVE SL TO BREAKEVEN
# ============================================================

def move_sl_to_breakeven(position) -> bool:
    request = {
        "action":   mt5.TRADE_ACTION_SLTP,
        "symbol":   position.symbol,
        "position": position.ticket,
        "sl":       float(position.price_open),
        "tp":       float(position.tp),
        "magic":    position.magic,
    }
    result = mt5.order_send(request)
    if result is None:
        print(f"   [BE] order_send returned None for #{position.ticket}")
        return False
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"   [BE] SL moved to breakeven (${position.price_open:.2f}) for #{position.ticket}")
        return True
    print(f"   [BE] Failed: retcode={result.retcode}, comment={result.comment}")
    return False


# ============================================================
# CLOSE POSITION
# ============================================================

def close_position(position) -> bool:
    tick = mt5.symbol_info_tick(position.symbol)
    if not tick:
        return False
    order_type = mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
    price = tick.bid if position.type == mt5.ORDER_TYPE_BUY else tick.ask

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       position.symbol,
        "volume":       float(position.volume),
        "type":         order_type,
        "position":     position.ticket,
        "price":        price,
        "deviation":    20,
        "magic":        position.magic,
        "comment":      "GoldSniper|SessionEnd",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": FILLING_MODE,
    }
    result = mt5.order_send(request)
    if result is None:
        return False
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"   [Close] Closed #{position.ticket} @ {price}")
        return True
    print(f"   [Close] Failed: retcode={result.retcode}, comment={result.comment}")
    return False


# ============================================================
# MAIN EXECUTION LOOP
# ============================================================

def main():
    global SYMBOL, FILLING_MODE

    print("MT5 EXECUTOR — Home PC")
    print("Connecting to MT5...")

    reconnect_wait = 10
    while not connect_mt5():
        print(f"Failed to connect to MT5. Retrying in {reconnect_wait}s...")
        time.sleep(reconnect_wait)
        reconnect_wait = min(reconnect_wait * 2, 300)  # exponential backoff, cap 5 min

    # Detect correct symbol and filling mode once at startup
    SYMBOL       = detect_symbol()
    FILLING_MODE = detect_filling_mode(SYMBOL)

    # Load daily loss from Supabase (survives restarts)
    daily_loss_usd      = get_daily_loss_from_supabase()
    last_balance_check  = time.time()
    daily_stop          = float(mt5.account_info().balance) * 0.03
    daily_stop_alerted  = False
    last_loss_reset     = datetime.now(timezone.utc).date()

    open_trades: dict          = {}  # {signal_id: {"ticket": int, "signal": dict}}
    be_moved_trades: set       = set()
    session_closed_today: set  = set()

    print(f"Watching Supabase for signals...\n"
          f"Daily loss loaded from Supabase: ${daily_loss_usd:.2f}\n"
          f"Daily stop: ${daily_stop:.2f}\n")

    while True:
        try:
            now_utc = datetime.now(timezone.utc)
            today   = now_utc.date()

            # Reset daily counters at UTC midnight
            if today != last_loss_reset:
                daily_loss_usd     = get_daily_loss_from_supabase()
                daily_stop_alerted = False
                last_loss_reset    = today
                # Update daily_stop from live MT5 balance
                acct = mt5.account_info()
                if acct:
                    daily_stop = float(acct.balance) * 0.03

            # Refresh daily_loss from Supabase every 60s (in case other process updated it)
            if time.time() - last_balance_check > 60:
                daily_loss_usd     = get_daily_loss_from_supabase()
                last_balance_check = time.time()
                acct = mt5.account_info()
                if acct:
                    daily_stop = float(acct.balance) * 0.03

            # Friday 14:00 UTC — refuse new signals heading into weekend
            is_friday_cutoff = (
                now_utc.weekday() == 4
                and now_utc.hour * 60 + now_utc.minute >= 14 * 60
            )

            stale_cutoff = now_utc - timedelta(minutes=30)

            # ── 1. CHECK FOR NEW EXECUTE SIGNALS ────────────────────────────
            try:
                new_signals = (
                    supabase.table("trade_signals")
                    .select("*")
                    .in_("decision", ["EXECUTE_BUY", "EXECUTE_SELL"])
                    .eq("executed", False)
                    .is_("execution_error", "null")
                    .gte("created_at", stale_cutoff.isoformat())
                    .execute()
                )
            except Exception as e:
                print(f"Supabase poll error: {e}")
                time.sleep(10)
                continue

            # Flag stale unexecuted signals as expired
            try:
                stale = (
                    supabase.table("trade_signals")
                    .select("id")
                    .in_("decision", ["EXECUTE_BUY", "EXECUTE_SELL"])
                    .eq("executed", False)
                    .is_("execution_error", "null")
                    .lt("created_at", stale_cutoff.isoformat())
                    .execute()
                )
                for s in (stale.data or []):
                    print(f"Signal {s['id'][:8]} expired (>30 min old) — flagging.")
                    supabase.table("trade_signals").update(
                        {"execution_error": "Signal expired (>30 min old)"}
                    ).eq("id", s["id"]).execute()
            except Exception as e:
                print(f"Stale-signal scan error: {e}")

            for signal in (new_signals.data or []):
                signal_id = signal["id"]

                # Friday cutoff guard
                if is_friday_cutoff:
                    print(f"Friday 14:00 UTC cutoff — refusing signal {signal_id[:8]}")
                    supabase.table("trade_signals").update(
                        {"execution_error": "Friday 14:00 UTC cutoff — no new trades before weekend"}
                    ).eq("id", signal_id).execute()
                    continue

                # Daily loss circuit breaker
                if daily_loss_usd >= daily_stop:
                    print(f"DAILY STOP (${daily_loss_usd:.2f} loss). Refusing signal.")
                    if not daily_stop_alerted:
                        send_daily_stop_alert(daily_loss_usd, daily_stop)
                        daily_stop_alerted = True
                    supabase.table("trade_signals").update(
                        {"execution_error": "Daily stop loss limit reached"}
                    ).eq("id", signal_id).execute()
                    continue

                # EQUITY STOP — close all + refuse if floating loss > 5%
                acct = mt5.account_info()
                if acct and acct.equity < acct.balance * 0.95:
                    msg = (
                        f"EQUITY STOP: equity ${acct.equity:.2f} < "
                        f"95% of balance ${acct.balance:.2f}"
                    )
                    print(msg)
                    send_telegram(f"EQUITY STOP TRIGGERED\n{msg}\nClosing all positions.")
                    for pos in (mt5.positions_get(symbol=SYMBOL) or []):
                        close_position(pos)
                    supabase.table("trade_signals").update(
                        {"execution_error": msg}
                    ).eq("id", signal_id).execute()
                    continue

                print(f"\nNEW SIGNAL: {signal['decision']} @ {signal.get('entry_price')}")

                # ── ATOMIC CLAIM (Fix #4) ────────────────────────────────────
                # Mark as PENDING before placing trade — prevents double execution
                # if the loop overlaps (e.g. MT5 order_send takes >5s).
                try:
                    claimed = (
                        supabase.table("trade_signals")
                        .update({"execution_error": "PENDING_EXECUTION"})
                        .eq("id", signal_id)
                        .is_("execution_error", "null")
                        .execute()
                    )
                    if not claimed.data:
                        print(f"Signal {signal_id[:8]} already claimed — skipping.")
                        continue
                except Exception as e:
                    print(f"Claim failed for {signal_id[:8]}: {e}")
                    continue

                result = place_trade(signal)

                if result["success"]:
                    supabase.table("trade_signals").update({
                        "executed":        True,
                        "execution_price": result["execution_price"],
                        "execution_time":  result["execution_time"],
                        "mt5_ticket":      result["ticket"],
                        "execution_error": None,
                    }).eq("id", signal_id).execute()
                    open_trades[signal_id] = {
                        "ticket": result["ticket"],
                        "signal": signal,
                    }
                    print(f"Logged to Supabase. Monitoring trade...")
                else:
                    supabase.table("trade_signals").update(
                        {"execution_error": result["error"]}
                    ).eq("id", signal_id).execute()
                    print(f"Execution failed: {result['error']}")

            # ── 2. MOVE SL TO BREAKEVEN AFTER TP1 ───────────────────────────
            for signal_id, trade_info in list(open_trades.items()):
                ticket = trade_info["ticket"]
                if ticket in be_moved_trades:
                    continue
                positions = mt5.positions_get(ticket=ticket)
                if not positions:
                    continue
                pos    = positions[0]
                sig    = trade_info["signal"]
                tp1    = float(sig.get("take_profit_1", 0) or 0)
                if tp1 <= 0:
                    continue
                tick = mt5.symbol_info_tick(pos.symbol)
                if not tick:
                    continue
                hit_tp1 = (
                    (pos.type == mt5.ORDER_TYPE_BUY  and tick.bid >= tp1) or
                    (pos.type == mt5.ORDER_TYPE_SELL and tick.ask <= tp1)
                )
                if hit_tp1 and move_sl_to_breakeven(pos):
                    be_moved_trades.add(ticket)
                    send_be_move_alert(ticket, float(pos.price_open))

            # ── 3. SESSION-END FORCED CLOSE ──────────────────────────────────
            current_hm = now_utc.hour * 60 + now_utc.minute
            for session_name, trigger_min, end_min in [
                ("LONDON",   11 * 60 + 55, 12 * 60),
                ("NEW_YORK", 16 * 60 + 55, 17 * 60),
            ]:
                key = f"{session_name}|{today.isoformat()}"
                if trigger_min <= current_hm < end_min and key not in session_closed_today:
                    positions = mt5.positions_get(symbol=SYMBOL) or []
                    if positions:
                        print(f"\nSession {session_name} ending — closing {len(positions)} positions.")
                        send_session_close_alert(session_name)
                        for pos in positions:
                            close_position(pos)
                    session_closed_today.add(key)

            # ── 4. MONITOR OPEN TRADES FOR OUTCOMES ──────────────────────────
            closed_trades = []
            for signal_id, trade_info in open_trades.items():
                try:
                    outcome = check_trade_outcome(
                        trade_info["ticket"], signal_id, trade_info["signal"]
                    )
                except Exception as e:
                    print(f"Outcome check error for {signal_id}: {e}")
                    continue

                if outcome:
                    print(f"\n{'='*40}")
                    print(f"TRADE CLOSED: {outcome['outcome']}")
                    print(f"   Exit:    {outcome['exit_reason']}")
                    print(f"   P&L:     ${outcome['profit_usd']:.2f}")
                    print(f"   Balance: ${outcome['account_balance_after']:.2f}")
                    print(f"{'='*40}\n")

                    # Update daily loss counter
                    if outcome["profit_usd"] < 0:
                        daily_loss_usd += abs(outcome["profit_usd"])
                        if daily_loss_usd >= daily_stop and not daily_stop_alerted:
                            send_daily_stop_alert(daily_loss_usd, daily_stop)
                            daily_stop_alerted = True

                    # Log to Supabase
                    try:
                        supabase.table("trade_outcomes").insert(outcome).execute()
                    except Exception as e:
                        print(f"Failed to log outcome: {e}")

                    # Trigger agent learning loop (Fix #5)
                    trigger_learning_loop(signal_id, outcome["outcome"])

                    closed_trades.append(signal_id)

            for sid in closed_trades:
                del open_trades[sid]

            # ── 5. KEEP MT5 CONNECTION ALIVE ─────────────────────────────────
            if not mt5.terminal_info():
                print("MT5 disconnected. Reconnecting...")
                reconnect_wait = 10
                while not connect_mt5():
                    time.sleep(reconnect_wait)
                    reconnect_wait = min(reconnect_wait * 2, 300)
                    if reconnect_wait >= 300:
                        send_telegram("MT5 disconnected for 5+ minutes — check home PC!")

            time.sleep(5)

        except KeyboardInterrupt:
            print("\nExecutor stopped by user.")
            mt5.shutdown()
            break
        except Exception as e:
            print(f"Executor loop error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()
