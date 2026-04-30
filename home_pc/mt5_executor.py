"""
MT5 EXECUTOR — Runs on your Home PC (Windows 24/7)
Watches Supabase for new EXECUTE signals.
Places trades on Deriv MT5 automatically.
Reports outcomes back to Supabase.
"""

import os
import time
from datetime import datetime, timezone

import MetaTrader5 as mt5
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY"),
)

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

            return {
                "signal_id": signal_id,
                "outcome": outcome,
                "exit_reason": exit_reason,
                "entry_price": float(entry_price),
                "exit_price": float(exit_price),
                "profit_usd": float(profit),
                "profit_pips": round(float(pips), 1),
                "account_balance_after": float(mt5.account_info().balance),
            }
    return None


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
    daily_loss_usd = 0.0
    daily_stop = float(os.getenv("ACCOUNT_BALANCE", "20.00")) * 0.03

    while True:
        try:
            # 1. CHECK FOR NEW EXECUTE SIGNALS
            try:
                new_signals = (
                    supabase.table("trade_signals")
                    .select("*")
                    .in_("decision", ["EXECUTE_BUY", "EXECUTE_SELL"])
                    .eq("executed", False)
                    .is_("execution_error", "null")
                    .execute()
                )
            except Exception as e:
                print(f"Supabase poll error: {e}")
                time.sleep(10)
                continue

            for signal in new_signals.data:
                signal_id = signal["id"]

                # Daily loss circuit breaker
                if daily_loss_usd >= daily_stop:
                    print(
                        f"DAILY STOP HIT (${daily_loss_usd:.2f} loss). "
                        f"Refusing new signals."
                    )
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

            # 2. MONITOR OPEN TRADES FOR OUTCOMES
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

                    try:
                        supabase.table("trade_outcomes").insert(outcome).execute()
                        new_balance = outcome["account_balance_after"]
                        os.environ["ACCOUNT_BALANCE"] = str(new_balance)
                    except Exception as e:
                        print(f"Failed to log outcome to Supabase: {e}")

                    closed_trades.append(signal_id)

            for sid in closed_trades:
                del open_trades[sid]

            # 3. KEEP MT5 CONNECTION ALIVE
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
