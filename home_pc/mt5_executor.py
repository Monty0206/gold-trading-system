"""
MT5 EXECUTOR — Runs on your Home PC (Windows 24/7)
Watches Supabase for new EXECUTE signals.
Places trades on Deriv MT5 automatically.
Reports outcomes back to Supabase.
"""

import os
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
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# ============================================================
# TELEGRAM ALERTS (sync — uses httpx sync client)
# ============================================================

def send_telegram(text: str) -> None:
    """Send a Markdown-formatted Telegram alert. Silent if no token configured."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        with httpx.Client(timeout=15.0) as client:
            client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": text,
                    "parse_mode": "Markdown",
                },
            )
    except Exception as e:
        print(f"[Telegram] Failed: {e}")


def send_daily_stop_alert(daily_loss_usd: float, daily_stop: float) -> None:
    """Alert: daily loss limit reached, executor refusing new signals."""
    msg = (
        f"🛑 *DAILY STOP HIT*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Daily loss: `${daily_loss_usd:.2f}`\n"
        f"Daily stop: `${daily_stop:.2f}`\n"
        f"_Executor is refusing new signals for the rest of the day._"
    )
    send_telegram(msg)


def send_session_close_alert(session_name: str) -> None:
    """Alert: session ending — closing all open positions."""
    msg = (
        f"⏰ *SESSION ENDING — {session_name}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Closing all open XAUUSD positions before session end."
    )
    send_telegram(msg)


def send_be_move_alert(ticket: int, entry_price: float) -> None:
    """Alert: TP1 hit, SL moved to breakeven."""
    msg = (
        f"🟢 *SL MOVED TO BREAKEVEN*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Ticket: `#{ticket}`\n"
        f"New SL: `${entry_price:.2f}` _(entry)_\n"
        f"Trade is now risk-free."
    )
    send_telegram(msg)

# ============================================================
# MT5 CONNECTION
# ============================================================

def connect_mt5() -> bool:
    if not mt5.initialize():
        print(f"MT5 initialize failed: {mt5.last_error()}")
        return False

    login = int(os.getenv("MT5_LOGIN"))
    password = os.getenv("MT5_PASSWORD")
    server = os.getenv("MT5_SERVER", "Deriv-Server")

    authorized = mt5.login(login, password=password, server=server)
    if not authorized:
        print(f"MT5 login failed: {mt5.last_error()}")
        return False

    info = mt5.account_info()
    print(f"MT5 Connected: {info.name} | Balance: ${info.balance:.2f}")
    return True


# ============================================================
# PLACE TRADE
# ============================================================

def place_trade(signal: dict) -> dict:
    symbol = "XAUUSD"
    direction = signal.get("direction", "")
    lot = float(signal.get("lot_size", 0.01))
    sl = float(signal.get("stop_loss", 0))
    tp1 = float(signal.get("take_profit_1", 0))
    signal_entry = float(signal.get("entry_price", 0))

    # Get live tick
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return {"success": False, "error": "Could not get tick data for XAUUSD"}

    if direction == "LONG":
        order_type = mt5.ORDER_TYPE_BUY
        price = tick.ask
    elif direction == "SHORT":
        order_type = mt5.ORDER_TYPE_SELL
        price = tick.bid
    else:
        return {"success": False, "error": f"Unknown direction: {direction}"}

    # Slippage guard (max 50 pips from signal price)
    slippage_pips = abs(price - signal_entry) * 10
    if slippage_pips > 50:
        return {
            "success": False,
            "error": (
                f"Price slipped too far: signal={signal_entry}, "
                f"current={price}, slippage={slippage_pips:.1f} pips"
            ),
        }

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp1,
        "deviation": 20,
        "magic": 20260101,
        "comment": f"GoldSniper|{str(signal.get('id', ''))[:8]}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)

    if result.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"TRADE PLACED: Ticket #{result.order}")
        print(f"   {direction} {lot} lots XAUUSD @ {price}")
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

    from_date = datetime(2020, 1, 1, tzinfo=timezone.utc)
    to_date = datetime.now(timezone.utc)
    history = mt5.history_deals_get(from_date, to_date)

    if not history:
        return None

    entry_deal_time = None
    for deal in history:
        if deal.order == ticket and deal.entry == mt5.DEAL_ENTRY_IN:
            entry_deal_time = deal.time
            break

    for deal in history:
        if deal.order == ticket and deal.entry == mt5.DEAL_ENTRY_OUT:
            profit = deal.profit
            exit_price = deal.price
            entry_price = float(signal.get("entry_price", 0))
            pips = abs(exit_price - entry_price) * 10

            outcome = "WIN" if profit > 0 else "LOSS" if profit < 0 else "BREAKEVEN"

            sl = float(signal.get("stop_loss", 0))
            tp1 = float(signal.get("take_profit_1", 0))
            direction = signal.get("direction", "")

            if direction == "LONG":
                if exit_price >= tp1 - 0.5:
                    exit_reason = "TP1"
                elif exit_price <= sl + 0.5:
                    exit_reason = "SL"
                else:
                    exit_reason = "MANUAL"
            else:
                if exit_price <= tp1 + 0.5:
                    exit_reason = "TP1"
                elif exit_price >= sl - 0.5:
                    exit_reason = "SL"
                else:
                    exit_reason = "MANUAL"

            duration_minutes = None
            if entry_deal_time and deal.time:
                duration_minutes = max(0, int((deal.time - entry_deal_time) / 60))

            return {
                "signal_id": signal_id,
                "outcome": outcome,
                "exit_reason": exit_reason,
                "entry_price": float(entry_price),
                "exit_price": float(exit_price),
                "profit_usd": float(profit),
                "profit_pips": round(float(pips), 1),
                "duration_minutes": duration_minutes,
                "account_balance_after": float(mt5.account_info().balance),
            }
    return None


# ============================================================
# MOVE STOP LOSS TO BREAKEVEN
# ============================================================

def move_sl_to_breakeven(position) -> bool:
    """
    Modify a position's SL to its entry price using TRADE_ACTION_SLTP.
    Returns True on success.
    """
    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "symbol": position.symbol,
        "position": position.ticket,
        "sl": float(position.price_open),
        "tp": float(position.tp),
        "magic": position.magic,
    }
    result = mt5.order_send(request)
    if result is None:
        print(f"   [BE] order_send returned None for ticket #{position.ticket}")
        return False
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"   [BE] SL moved to breakeven (${position.price_open:.2f}) for #{position.ticket}")
        return True
    print(f"   [BE] Failed to modify SL: retcode={result.retcode}, comment={result.comment}")
    return False


# ============================================================
# CLOSE A POSITION (market order opposite side)
# ============================================================

def close_position(position) -> bool:
    """Close a position with a market deal in the opposite direction."""
    tick = mt5.symbol_info_tick(position.symbol)
    if not tick:
        return False
    if position.type == mt5.ORDER_TYPE_BUY:
        order_type = mt5.ORDER_TYPE_SELL
        price = tick.bid
    else:
        order_type = mt5.ORDER_TYPE_BUY
        price = tick.ask

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": position.symbol,
        "volume": float(position.volume),
        "type": order_type,
        "position": position.ticket,
        "price": price,
        "deviation": 20,
        "magic": position.magic,
        "comment": "GoldSniper|SessionEnd",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result is None:
        print(f"   [Close] order_send returned None for #{position.ticket}")
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
    print("MT5 EXECUTOR — Home PC")
    print("Connecting to MT5...")

    if not connect_mt5():
        print("Failed to connect to MT5. Retrying in 60s...")
        time.sleep(60)
        return

    print("Watching Supabase for signals...\n")

    open_trades: dict = {}  # {signal_id: {"ticket": int, "signal": dict}}
    be_moved_trades: set = set()  # tickets already moved to breakeven
    session_closed_today: set = set()  # session names already closed today (e.g. "LONDON|2026-04-30")
    daily_loss_usd = 0.0
    daily_stop = float(os.getenv("ACCOUNT_BALANCE", "20.00")) * 0.03
    daily_stop_alerted = False
    last_loss_reset_date = datetime.now(timezone.utc).date()

    while True:
        try:
            now_utc = datetime.now(timezone.utc)
            today = now_utc.date()

            # Reset daily counters at UTC midnight
            if today != last_loss_reset_date:
                daily_loss_usd = 0.0
                daily_stop_alerted = False
                last_loss_reset_date = today

            # Compute "stale" cutoff — ignore signals older than 30 minutes
            stale_cutoff = now_utc - timedelta(minutes=30)

            # 1. CHECK FOR NEW EXECUTE SIGNALS
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

            # Also flag any older unexecuted signals as expired
            try:
                stale_signals = (
                    supabase.table("trade_signals")
                    .select("id, created_at")
                    .in_("decision", ["EXECUTE_BUY", "EXECUTE_SELL"])
                    .eq("executed", False)
                    .is_("execution_error", "null")
                    .lt("created_at", stale_cutoff.isoformat())
                    .execute()
                )
                for stale in (stale_signals.data or []):
                    print(f"Signal {stale['id'][:8]} expired (>30 min old) — flagging.")
                    supabase.table("trade_signals").update(
                        {"execution_error": "Signal expired (>30 min old)"}
                    ).eq("id", stale["id"]).execute()
            except Exception as e:
                print(f"Stale-signal scan error: {e}")

            for signal in (new_signals.data or []):
                signal_id = signal["id"]

                # Daily loss circuit breaker
                if daily_loss_usd >= daily_stop:
                    print(
                        f"DAILY STOP HIT (${daily_loss_usd:.2f} loss). "
                        f"Refusing new signals."
                    )
                    if not daily_stop_alerted:
                        send_daily_stop_alert(daily_loss_usd, daily_stop)
                        daily_stop_alerted = True
                    supabase.table("trade_signals").update(
                        {"execution_error": "Daily stop loss limit reached"}
                    ).eq("id", signal_id).execute()
                    continue

                print(
                    f"\nNEW SIGNAL: {signal['decision']} @ {signal.get('entry_price')}"
                )

                result = place_trade(signal)

                if result["success"]:
                    supabase.table("trade_signals").update(
                        {
                            "executed": True,
                            "execution_price": result["execution_price"],
                            "execution_time": result["execution_time"],
                            "mt5_ticket": result["ticket"],
                        }
                    ).eq("id", signal_id).execute()
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

            # 2. MOVE SL TO BREAKEVEN AFTER TP1 HIT
            for signal_id, trade_info in list(open_trades.items()):
                ticket = trade_info["ticket"]
                if ticket in be_moved_trades:
                    continue
                positions = mt5.positions_get(ticket=ticket)
                if not positions:
                    continue
                pos = positions[0]
                signal = trade_info["signal"]
                tp1 = float(signal.get("take_profit_1", 0) or 0)
                if tp1 <= 0:
                    continue
                tick = mt5.symbol_info_tick(pos.symbol)
                if not tick:
                    continue

                hit_tp1 = False
                if pos.type == mt5.ORDER_TYPE_BUY and tick.bid >= tp1:
                    hit_tp1 = True
                elif pos.type == mt5.ORDER_TYPE_SELL and tick.ask <= tp1:
                    hit_tp1 = True

                if hit_tp1:
                    if move_sl_to_breakeven(pos):
                        be_moved_trades.add(ticket)
                        send_be_move_alert(ticket, float(pos.price_open))

            # 3. SESSION-END FORCED CLOSE
            # London close 12:00 UTC -> trigger at 11:55
            # NY close 17:00 UTC -> trigger at 16:55
            current_hm = now_utc.hour * 60 + now_utc.minute
            for session_name, trigger_min, end_min in [
                ("LONDON", 11 * 60 + 55, 12 * 60),
                ("NEW_YORK", 16 * 60 + 55, 17 * 60),
            ]:
                key = f"{session_name}|{today.isoformat()}"
                if trigger_min <= current_hm < end_min and key not in session_closed_today:
                    positions = mt5.positions_get(symbol="XAUUSD") or []
                    if positions:
                        print(f"\nSession {session_name} ending — closing {len(positions)} positions.")
                        send_session_close_alert(session_name)
                        for pos in positions:
                            close_position(pos)
                    session_closed_today.add(key)

            # 4. MONITOR OPEN TRADES FOR OUTCOMES
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
                    print(f"   Exit reason: {outcome['exit_reason']}")
                    print(f"   P&L: ${outcome['profit_usd']:.2f}")
                    print(f"   Balance: ${outcome['account_balance_after']:.2f}")
                    print(f"{'='*40}\n")

                    # Track daily loss
                    if outcome["profit_usd"] < 0:
                        daily_loss_usd += abs(outcome["profit_usd"])
                        if daily_loss_usd >= daily_stop and not daily_stop_alerted:
                            send_daily_stop_alert(daily_loss_usd, daily_stop)
                            daily_stop_alerted = True

                    try:
                        supabase.table("trade_outcomes").insert(outcome).execute()
                        new_balance = outcome["account_balance_after"]
                        os.environ["ACCOUNT_BALANCE"] = str(new_balance)
                    except Exception as e:
                        print(f"Failed to log outcome to Supabase: {e}")

                    closed_trades.append(signal_id)

            for sid in closed_trades:
                del open_trades[sid]

            # 5. KEEP MT5 CONNECTION ALIVE
            if not mt5.terminal_info():
                print("MT5 disconnected. Reconnecting...")
                connect_mt5()

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
