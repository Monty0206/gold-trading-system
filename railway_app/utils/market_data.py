import asyncio
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf


async def fetch_market_data() -> dict:
    """Fetch live XAUUSD price and technical indicators (runs sync yfinance in executor)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_sync)


def _ensure_utc(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise DataFrame index to UTC timezone-aware."""
    if df.empty:
        return df
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    return df


def _fetch_sync() -> dict:
    ticker = yf.Ticker("GC=F")

    df_1h = _ensure_utc(ticker.history(period="30d", interval="1h"))
    df_4h = _ensure_utc(ticker.history(period="60d", interval="4h"))
    df_15m = _ensure_utc(ticker.history(period="5d", interval="15m"))

    if df_1h.empty:
        raise ValueError("yfinance returned empty 1H dataframe for GC=F")

    current_price = float(df_1h["Close"].iloc[-1])
    now = datetime.now(timezone.utc)
    today_ts = pd.Timestamp(now.date()).tz_localize("UTC")

    # ---- Indicators (H1) ----
    df = df_1h.copy()

    df["ema9"] = df["Close"].ewm(span=9, adjust=False).mean()
    df["ema21"] = df["Close"].ewm(span=21, adjust=False).mean()
    df["ema50"] = df["Close"].ewm(span=50, adjust=False).mean()

    delta = df["Close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta).clip(lower=0).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    hl = df["High"] - df["Low"]
    hc = (df["High"] - df["Close"].shift(1)).abs()
    lc = (df["Low"] - df["Close"].shift(1)).abs()
    df["atr"] = pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(14).mean()

    ema12 = df["Close"].ewm(span=12, adjust=False).mean()
    ema26 = df["Close"].ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    last = df.iloc[-1]

    # ---- H4 trend ----
    h4_trend = "RANGING"
    if not df_4h.empty and len(df_4h) >= 21:
        df4 = df_4h.copy()
        df4["ema9"] = df4["Close"].ewm(span=9, adjust=False).mean()
        df4["ema21"] = df4["Close"].ewm(span=21, adjust=False).mean()
        l4 = df4.iloc[-1]
        h4_trend = "BULLISH" if l4["ema9"] > l4["ema21"] else "BEARISH"

    # ---- Asian range: 00:00–07:00 UTC ----
    asian_end_ts = today_ts + pd.Timedelta(hours=7)
    asian_slice = df_15m[(df_15m.index >= today_ts) & (df_15m.index < asian_end_ts)]

    if not asian_slice.empty:
        asian_high = float(asian_slice["High"].max())
        asian_low = float(asian_slice["Low"].min())
    else:
        # Fallback: last 7 hours
        fallback = df_15m[df_15m.index >= (pd.Timestamp(now) - pd.Timedelta(hours=7))]
        if not fallback.empty:
            asian_high = float(fallback["High"].max())
            asian_low = float(fallback["Low"].min())
        else:
            asian_high = round(current_price + 5.0, 2)
            asian_low = round(current_price - 5.0, 2)

    # ---- Day range ----
    day_slice = df_1h[df_1h.index >= today_ts]
    day_high = float(day_slice["High"].max()) if not day_slice.empty else current_price + 10
    day_low = float(day_slice["Low"].min()) if not day_slice.empty else current_price - 10

    # ---- Recent 20 candles for agent context ----
    recent_candles = []
    for i in range(max(0, len(df) - 20), len(df)):
        row = df.iloc[i]
        recent_candles.append({
            "time": str(df.index[i]),
            "open": round(float(row["Open"]), 2),
            "high": round(float(row["High"]), 2),
            "low": round(float(row["Low"]), 2),
            "close": round(float(row["Close"]), 2),
        })

    return {
        "current_price": round(current_price, 2),
        "timestamp": now.isoformat(),
        "h4_trend": h4_trend,
        "asian_range": {
            "high": round(asian_high, 2),
            "low": round(asian_low, 2),
            "size_pips": round(abs(asian_high - asian_low) * 10, 1),
        },
        "indicators": {
            "ema9": round(float(last["ema9"]), 2),
            "ema21": round(float(last["ema21"]), 2),
            "ema50": round(float(last["ema50"]), 2),
            "rsi_14": round(float(last["rsi"]), 2),
            "atr_14": round(float(last["atr"]), 2),
            "macd": round(float(last["macd"]), 4),
            "macd_signal": round(float(last["macd_signal"]), 4),
            "macd_histogram": round(float(last["macd_hist"]), 4),
        },
        "ema_aligned_bullish": bool(last["ema9"] > last["ema21"] > last["ema50"]),
        "ema_aligned_bearish": bool(last["ema9"] < last["ema21"] < last["ema50"]),
        "rsi_above_50": bool(last["rsi"] > 50),
        "macd_bullish": bool(last["macd_hist"] > 0),
        "day_high": round(day_high, 2),
        "day_low": round(day_low, 2),
        "recent_candles_1h": recent_candles,
    }
