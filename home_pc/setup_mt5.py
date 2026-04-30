"""
SETUP MT5 — One-time connection test.
Run this first to verify your MT5 credentials and account access.
"""

import os
from datetime import datetime, timezone, timedelta

import MetaTrader5 as mt5
from dotenv import load_dotenv

load_dotenv()


def main():
    print("=" * 55)
    print("GOLD SESSION SNIPER — MT5 Setup & Connection Test")
    print("=" * 55)

    # 1. Initialise MT5
    if not mt5.initialize():
        print(f"FAILED: mt5.initialize() — {mt5.last_error()}")
        print("\nMake sure MetaTrader 5 is installed and running.")
        return

    print(f"MT5 Terminal version: {mt5.version()}")

    # 2. Login
    login = os.getenv("MT5_LOGIN")
    password = os.getenv("MT5_PASSWORD")
    server = os.getenv("MT5_SERVER", "Deriv-Server")

    if not login or not password:
        print("\nERROR: MT5_LOGIN or MT5_PASSWORD not set in .env file")
        mt5.shutdown()
        return

    print(f"\nConnecting to {server} as #{login}...")
    authorized = mt5.login(int(login), password=password, server=server)

    if not authorized:
        print(f"FAILED: mt5.login() — {mt5.last_error()}")
        mt5.shutdown()
        return

    # 3. Account info
    info = mt5.account_info()
    print(f"\n{'='*40}")
    print(f"  CONNECTION SUCCESSFUL")
    print(f"{'='*40}")
    print(f"  Name:        {info.name}")
    print(f"  Login:       {info.login}")
    print(f"  Server:      {info.server}")
    print(f"  Currency:    {info.currency}")
    print(f"  Balance:     ${info.balance:.2f}")
    print(f"  Equity:      ${info.equity:.2f}")
    print(f"  Leverage:    1:{info.leverage}")
    print(f"  Account Type: {'DEMO' if 'demo' in info.server.lower() else 'LIVE'}")
    print(f"{'='*40}\n")

    # 4. Check XAUUSD symbol
    print("Checking XAUUSD symbol...")
    symbol_info = mt5.symbol_info("XAUUSD")
    if symbol_info is None:
        print("WARNING: XAUUSD symbol not found.")
        print("Trying to add it...")
        if not mt5.symbol_select("XAUUSD", True):
            print("FAILED to add XAUUSD. Check your broker's symbol list.")
        else:
            symbol_info = mt5.symbol_info("XAUUSD")

    if symbol_info:
        tick = mt5.symbol_info_tick("XAUUSD")
        print(f"  XAUUSD found:")
        print(f"    Bid:         ${tick.bid:.2f}")
        print(f"    Ask:         ${tick.ask:.2f}")
        print(f"    Spread:      {round((tick.ask - tick.bid) * 10, 1)} pips")
        print(f"    Min lot:     {symbol_info.volume_min}")
        print(f"    Max lot:     {symbol_info.volume_max}")
        print(f"    Lot step:    {symbol_info.volume_step}")
        print(f"    Contract sz: {symbol_info.trade_contract_size}")
    else:
        print("  XAUUSD not available on this account.")

    # 5. Recent price history check
    print("\nFetching recent XAUUSD H1 candles (last 5)...")
    from datetime import datetime as dt
    rates = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_H1, 0, 5)
    if rates is not None and len(rates) > 0:
        for r in rates:
            bar_time = datetime.fromtimestamp(r[0], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            print(f"    {bar_time}  O:{r[1]:.2f}  H:{r[2]:.2f}  L:{r[3]:.2f}  C:{r[4]:.2f}")
    else:
        print(f"  Failed to fetch rates: {mt5.last_error()}")

    # 6. Verify .env variables
    print("\nEnvironment variable check:")
    vars_to_check = [
        "OPENROUTER_API_KEY",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "ACCOUNT_BALANCE",
        "RISK_PCT",
        "MAX_LOT",
    ]
    for var in vars_to_check:
        val = os.getenv(var)
        if val and val != f"your_{var.lower()}_here":
            masked = val[:4] + "****" if len(val) > 4 else "****"
            print(f"  [OK] {var}: {masked}")
        else:
            print(f"  [MISSING] {var}: not set")

    print("\nSetup complete. You are ready to run mt5_executor.py")
    print("REMINDER: Test on DEMO account for at least 2 weeks first!\n")

    mt5.shutdown()


if __name__ == "__main__":
    main()
