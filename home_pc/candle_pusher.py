"""
CANDLE PUSHER — Runs on Home PC alongside mt5_executor.py
Reads live XAUUSD candles from MT5 every 60 seconds.
Writes M15 / H1 / H4 candles + bid/ask to Supabase live_market_data table.
Railway market_data.py reads from this table first (yfinance is the fallback).

Required Supabase table — run once in SQL editor:
    CREATE TABLE live_market_data (
        id          UUID DEFAULT gen_random_uuid() PRIMARY KEY,
        pushed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        symbol      TEXT NOT NULL DEFAULT 'XAUUSD',
        bid         DECIMAL(10,2),
        ask         DECIMAL(10,2),
        spread_pips DECIMAL(6,1),
        candles_15m JSONB,
        candles_1h  JSONB,
        candles_4h  JSONB
    );
    CREATE INDEX idx_live_market_data_pushed ON live_market_data(pushed_at DESC);
"""

import os
import signal
import sys
import time
from datetime import datetime, timezone

import MetaTrader5 as mt5
import httpx
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
PUSH_INTERVAL_S   = 60          # push candles every 60 s
M15_BARS          = 480         # ~5 days of 15m bars
H1_BARS           = 720         # ~30 days of 1h bars
H4_BARS           = 360         # ~60 days of 4h bars
MAX_TABLE_ROWS    = 60          # keep only the last 60 rows (~1 hour)
RECONNECT_DELAY_S = 30          # MT5 reconnect interval
MAX_RECONNECT_S   = 300         # cap reconnect backoff at 5 min
ALERT_AFTER_S     = 300         # Telegram alert if disconnected >5 min

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY"),
)

# Detected at startup — same symbol auto-detection as mt5_executor
SYMBOL: str = "XAUUSD"


# ── Graceful shutdown ─────────────────────────────────────────────────────────

def _shutdown(*_):
    print("\nShutting down candle pusher.")
    mt5.shutdown()
    sys.exit(0)

signal.signal(signal.SIGTERM, _shutdown)


# ── Telegram ──────────────────────────────────────────────────────────────────

def _telegram(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        with httpx.Client(timeout=10.0) as client:
            client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            )
    except Exception:
        pass


# ── MT5 helpers ───────────────────────────────────────────────────────────────

def connect_mt5() -> bool:
    """Initialize MT5 and log in. Returns True on success."""
    if not mt5.initialize():
        print(f"[MT5] initialize() failed: {mt5.last_error()}")
        return False

    login_env = os.getenv("MT5_LOGIN")
    if login_env is None:
        print("[MT5] MT5_LOGIN env var not set")
        return False

    authorized = mt5.login(
        int(login_env),
        password=os.getenv("MT5_PASSWORD", ""),
        server=os.getenv("MT5_SERVER", "Deriv-Server"),
    )
    if not authorized:
        print(f"[MT5] login() failed: {mt5.last_error()}")
        mt5.shutdown()
        return False

    info = mt5.account_info()
    print(f"[MT5] Connected — {info.name} | Balance: ${info.balance:.2f}")
    return True


def detect_symbol() -> str:
    """Try common Deriv XAUUSD symbol names and return the one that works."""
    candidates = ["XAUUSD", "XAUUSD.", "XAUUSDm", "XAUUSDc", "XAUUSDi", "Gold", "GOLD"]
    for sym in candidates:
        info = mt5.symbol_info(sym)
        if info is not None:
            mt5.symbol_select(sym, True)
            print(f"[MT5] Using symbol: {sym}")
            return sym
    print("[MT5] WARNING: no XAUUSD symbol found — defaulting to 'XAUUSD'")
    return "XAUUSD"


def _bars_to_json(rates) -> list:
    """Convert MT5 rates array to a JSON-serialisable list."""
    if rates is None or len(rates) == 0:
        return []
    result = []
    for bar in rates:
        result.append({
            "time":  int(bar[0]),          # UTC epoch seconds
            "open":  round(float(bar[1]), 2),
            "high":  round(float(bar[2]), 2),
            "low":   round(float(bar[3]), 2),
            "close": round(float(bar[4]), 2),
            "vol":   int(bar[5]),
        })
    return result


# ── Main push logic ───────────────────────────────────────────────────────────

def push_candles(symbol: str) -> bool:
    """Fetch candles from MT5 and upsert one row into Supabase. Returns True on success."""
    # Current bid/ask
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print(f"[Pusher] Could not get tick for {symbol}")
        return False

    bid         = round(float(tick.bid), 2)
    ask         = round(float(tick.ask), 2)
    spread_pips = round((ask - bid) * 10, 1)  # 1 pip = $0.10 for XAUUSD

    # Fetch candles
    rates_15m = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, M15_BARS)
    rates_1h  = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1,  0, H1_BARS)
    rates_4h  = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H4,  0, H4_BARS)

    if rates_15m is None or len(rates_15m) < 10:
        print(f"[Pusher] Insufficient M15 data ({len(rates_15m) if rates_15m is not None else 0} bars)")
        return False

    now_iso = datetime.now(timezone.utc).isoformat()

    row = {
        "pushed_at":   now_iso,
        "symbol":      symbol,
        "bid":         bid,
        "ask":         ask,
        "spread_pips": spread_pips,
        "candles_15m": _bars_to_json(rates_15m),
        "candles_1h":  _bars_to_json(rates_1h),
        "candles_4h":  _bars_to_json(rates_4h),
    }

    supabase.table("live_market_data").insert(row).execute()

    # Prune old rows — keep only the last MAX_TABLE_ROWS
    try:
        all_rows = (
            supabase.table("live_market_data")
            .select("id, pushed_at")
            .order("pushed_at", desc=True)
            .execute()
        )
        rows = all_rows.data or []
        if len(rows) > MAX_TABLE_ROWS:
            old_ids = [r["id"] for r in rows[MAX_TABLE_ROWS:]]
            supabase.table("live_market_data").delete().in_("id", old_ids).execute()
    except Exception as e:
        print(f"[Pusher] Prune failed (non-fatal): {e}")

    print(
        f"[Pusher] {now_iso[:19]}Z  bid={bid}  ask={ask}  "
        f"spread={spread_pips}pips  "
        f"M15={len(rates_15m)}  "
        f"H1={len(rates_1h) if rates_1h is not None else 0}  "
        f"H4={len(rates_4h) if rates_4h is not None else 0}"
    )
    return True


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 56)
    print("GOLD SNIPER — Candle Pusher")
    print(f"Push interval: {PUSH_INTERVAL_S}s | Table rows kept: {MAX_TABLE_ROWS}")
    print("=" * 56)

    # Initial MT5 connection
    backoff = RECONNECT_DELAY_S
    while not connect_mt5():
        print(f"[MT5] Retrying in {backoff}s...")
        time.sleep(backoff)
        backoff = min(backoff * 2, MAX_RECONNECT_S)

    global SYMBOL
    SYMBOL = detect_symbol()

    disconnect_since: datetime | None = None
    alerted = False

    while True:
        try:
            # Health-check MT5 connection
            if not mt5.terminal_info():
                if disconnect_since is None:
                    disconnect_since = datetime.now(timezone.utc)
                    print("[MT5] Disconnected — attempting reconnect...")
                    mt5.shutdown()

                elapsed = (datetime.now(timezone.utc) - disconnect_since).total_seconds()

                if elapsed >= ALERT_AFTER_S and not alerted:
                    _telegram(
                        f"CANDLE PUSHER: MT5 disconnected for "
                        f"{int(elapsed / 60)} min — Railway will use yfinance fallback."
                    )
                    alerted = True

                if connect_mt5():
                    disconnect_since = None
                    alerted = False
                    SYMBOL = detect_symbol()
                    print("[MT5] Reconnected.")
                else:
                    time.sleep(RECONNECT_DELAY_S)
                    continue

            # Push candles
            push_candles(SYMBOL)
            time.sleep(PUSH_INTERVAL_S)

        except KeyboardInterrupt:
            print("\nStopped by user.")
            mt5.shutdown()
            break
        except Exception as e:
            print(f"[Pusher] Unhandled error: {e}")
            time.sleep(PUSH_INTERVAL_S)


if __name__ == "__main__":
    main()
