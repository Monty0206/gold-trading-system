"""
Market data module — fetches live XAUUSD data.

Primary source: Supabase live_market_data table (pushed by home/candle_pusher.py).
  - Uses real Deriv XAUUSD spot prices from MT5, not futures.
  - Checked first; if data is stale (>5 min) or table missing, falls back to yfinance.

Fallback: yfinance GC=F (COMEX gold futures).
  - NOTE: GC=F can differ from Deriv spot by $5-15 due to contango.
  - Acceptable for direction analysis; be aware of level offsets.

Also fetches:
  - DXY (DX-Y.NYB), US 10Y yields (^TNX), VIX (^VIX) via yfinance
  - Economic calendar from FMP free API (requires FMP_API_KEY env var)
"""

import asyncio
import json
import os
from datetime import datetime, timezone

import httpx
import numpy as np
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

FMP_API_KEY = os.getenv("FMP_API_KEY", "")


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

async def fetch_market_data(supabase=None) -> dict:
    """Fetch live XAUUSD + macro data.
    Pass supabase client to enable live MT5 candle source from home PC."""
    return await asyncio.to_thread(_fetch_sync, supabase)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_utc(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    return df


_REQUIRED_OHLC = {"open", "high", "low", "close"}


def _parse_candles(raw) -> list:
    """Safely parse JSONB candle data that may arrive as a str, list, or None.

    Supabase may return JSONB columns as a Python list (parsed) or as a JSON
    string (if the value was inserted via json.dumps). Handle both.
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"[MarketData] candle json.loads failed: {exc}")
            return []
    if not isinstance(raw, list):
        print(f"[MarketData] unexpected candle type {type(raw)} — expected list")
        return []
    return raw


def _json_to_df(candles: list) -> pd.DataFrame:
    """Convert a list of OHLC dicts (from Supabase/MT5 pusher) to a DataFrame."""
    if not candles:
        return pd.DataFrame()

    try:
        df = pd.DataFrame(candles)
    except Exception as exc:
        print(f"[MarketData] pd.DataFrame(candles) failed: {exc}")
        return pd.DataFrame()

    cols_lower = {c.lower() for c in df.columns}
    if not _REQUIRED_OHLC.issubset(cols_lower):
        missing = _REQUIRED_OHLC - cols_lower
        print(f"[MarketData] candle DataFrame missing columns: {missing}")
        return pd.DataFrame()

    # Normalise column names to Title case (Open, High, Low, Close)
    rename = {}
    for col in df.columns:
        if col.lower() in ("open", "high", "low", "close", "volume"):
            rename[col] = col.capitalize()
    if rename:
        df.rename(columns=rename, inplace=True)

    if "time" in df.columns:
        df.index = pd.to_datetime(df["time"], unit="s", utc=True)
        df.sort_index(inplace=True)

    return df


def _wilder_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's smoothed RSI — matches MT5 and TradingView exactly."""
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _wilder_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder's smoothed ATR — matches MT5 and TradingView exactly."""
    hl = df["High"] - df["Low"]
    hc = (df["High"] - df["Close"].shift(1)).abs()
    lc = (df["Low"] - df["Close"].shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def _compute_swing_points(df: pd.DataFrame, lookback: int = 5) -> tuple[list, list]:
    """Return (swing_highs, swing_lows) from recent candles."""
    highs = df["High"].tolist()
    lows = df["Low"].tolist()
    swing_highs, swing_lows = [], []
    for i in range(1, len(highs) - 1):
        if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
            swing_highs.append(round(highs[i], 2))
        if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
            swing_lows.append(round(lows[i], 2))
    return swing_highs[-lookback:], swing_lows[-lookback:]


# ─────────────────────────────────────────────────────────────────────────────
# Macro data (DXY, 10Y yields, VIX)
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_macro_tickers() -> dict:
    """Fetch DXY, US 10Y yields, and VIX from yfinance."""
    result = {}
    for key, sym in [("dxy", "DX-Y.NYB"), ("tnx_10y", "^TNX"), ("vix", "^VIX")]:
        try:
            df = _ensure_utc(yf.Ticker(sym).history(period="5d", interval="1h"))
            if not df.empty:
                cur = float(df["Close"].iloc[-1])
                prev = float(df["Close"].iloc[-2]) if len(df) >= 2 else cur
                chg = (cur - prev) / prev * 100 if prev else 0
                direction = "RISING" if cur > prev else "FALLING" if cur < prev else "FLAT"
                result[key] = {
                    "current": round(cur, 4),
                    "prev_close": round(prev, 4),
                    "change_pct": round(chg, 3),
                    "direction": direction,
                }
            else:
                result[key] = {"current": None, "direction": "UNKNOWN"}
        except Exception as e:
            result[key] = {"current": None, "direction": "UNKNOWN", "error": str(e)[:80]}
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Economic calendar (FMP free tier)
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_economic_calendar() -> list:
    """Fetch today's high/medium impact events from FMP.
    Returns [] if FMP_API_KEY not set — agents then receive no calendar data."""
    if not FMP_API_KEY:
        print("[MarketData] FMP_API_KEY not set — economic calendar disabled. "
              "Set FMP_API_KEY env var for real news events.")
        return []
    try:
        today = datetime.now(timezone.utc).date().isoformat()
        url = (
            f"https://financialmodelingprep.com/api/v3/economic_calendar"
            f"?from={today}&to={today}&apikey={FMP_API_KEY}"
        )
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url)
            resp.raise_for_status()
            events = resp.json() or []

        result = []
        for ev in events:
            impact = ev.get("impact", "")
            if impact not in ("High", "Medium"):
                continue
            dt_str = ev.get("date", "")
            try:
                dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                time_gmt = dt.strftime("%H:%M")
            except Exception:
                time_gmt = "00:00"
            result.append({
                "event": ev.get("event", ""),
                "time_gmt": time_gmt,
                "impact": "HIGH" if impact == "High" else "MEDIUM",
                "country": ev.get("country", ""),
                "currency": ev.get("currency", ""),
            })
        print(f"[MarketData] Economic calendar: {len(result)} events today.")
        return result
    except Exception as e:
        print(f"[MarketData] FMP calendar fetch failed: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Supabase live candles (from home PC MT5 candle_pusher.py)
# ─────────────────────────────────────────────────────────────────────────────

def _try_supabase_candles(supabase) -> dict | None:
    """Read latest MT5 candle data from Supabase. Returns None if stale or unavailable."""
    if supabase is None:
        return None
    try:
        row = (
            supabase.table("live_market_data")
            .select("*")
            .order("pushed_at", desc=True)
            .limit(1)
            .execute()
        )
        if not row.data:
            print("[MarketData] No rows in live_market_data — using yfinance fallback")
            return None
        data = row.data[0]
        pushed_str = data.get("pushed_at", "")
        pushed_at = datetime.fromisoformat(pushed_str.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - pushed_at).total_seconds()
        if age > 300:
            print(f"[MarketData] live_market_data is {age:.0f}s old — using yfinance fallback")
            return None
        print(f"[MarketData] Using MT5 live candles (age: {age:.0f}s)")
        return data
    except Exception as e:
        print(f"[MarketData] Supabase candle read error: {e} — using yfinance fallback")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Core synchronous fetch (runs in thread via asyncio.to_thread)
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_sync(supabase=None) -> dict:
    now = datetime.now(timezone.utc)

    # ── 1. Try Supabase (live MT5 Deriv spot prices) ─────────────────────────
    live = _try_supabase_candles(supabase)

    if live is not None:
        try:
            df_1h  = _json_to_df(_parse_candles(live.get("candles_1h")))
            df_4h  = _json_to_df(_parse_candles(live.get("candles_4h")))
            df_15m = _json_to_df(_parse_candles(live.get("candles_15m")))
        except Exception as exc:
            print(f"[MarketData] Supabase candle parse error: {exc} — using yfinance fallback")
            live = None
            df_1h = df_4h = df_15m = pd.DataFrame()

        if live is not None and df_1h.empty:
            print("[MarketData] Supabase 1H candles empty — using yfinance fallback")
            live = None

    if live is None:
        # ── 2. yfinance fallback (GC=F futures) ──────────────────────────────
        ticker = yf.Ticker("GC=F")
        df_1h = _ensure_utc(ticker.history(period="30d", interval="1h"))
        df_4h = _ensure_utc(ticker.history(period="60d", interval="4h"))
        df_15m = _ensure_utc(ticker.history(period="5d", interval="15m"))

        if df_1h.empty:
            raise ValueError("yfinance returned empty 1H dataframe for GC=F")

        # Staleness check: last candle must be within 6 hours
        last_ts = df_1h.index[-1]
        age_h = (pd.Timestamp(now) - last_ts).total_seconds() / 3600
        if age_h > 6:
            raise ValueError(
                f"yfinance data stale — last candle {last_ts} is {age_h:.1f}h old. "
                "Market may be closed or yfinance feed delayed."
            )
        current_price = float(df_1h["Close"].iloc[-1])
        spread_pips = 0.0
        data_source = "YFINANCE_GCF"
    else:
        current_price = float(live.get("bid") or df_1h["Close"].iloc[-1])
        spread_pips = float(live.get("spread_pips") or 0)
        data_source = "MT5_LIVE"

    # ── 3. Indicators (H1, Wilder's) ─────────────────────────────────────────
    df = df_1h.copy()
    df["ema9"]  = df["Close"].ewm(span=9,  adjust=False).mean()
    df["ema21"] = df["Close"].ewm(span=21, adjust=False).mean()
    df["ema50"] = df["Close"].ewm(span=50, adjust=False).mean()
    df["rsi"]   = _wilder_rsi(df["Close"])
    df["atr"]   = _wilder_atr(df)

    ema12 = df["Close"].ewm(span=12, adjust=False).mean()
    ema26 = df["Close"].ewm(span=26, adjust=False).mean()
    df["macd"]        = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"]   = df["macd"] - df["macd_signal"]
    last = df.iloc[-1]

    # ── 4. H4 trend ──────────────────────────────────────────────────────────
    h4_trend = "RANGING"
    if not df_4h.empty and len(df_4h) >= 21:
        df4 = df_4h.copy()
        df4["ema9"]  = df4["Close"].ewm(span=9,  adjust=False).mean()
        df4["ema21"] = df4["Close"].ewm(span=21, adjust=False).mean()
        l4 = df4.iloc[-1]
        h4_trend = "BULLISH" if l4["ema9"] > l4["ema21"] else "BEARISH"

    # ── 5. Asian range: 23:00 UTC prev day → 07:00 UTC today ─────────────────
    today_ts     = pd.Timestamp(now.date()).tz_localize("UTC")
    asian_start  = today_ts - pd.Timedelta(hours=1)   # 23:00 UTC previous day
    asian_end    = today_ts + pd.Timedelta(hours=7)   # 07:00 UTC today

    asian_slice = pd.DataFrame()
    if not df_15m.empty and df_15m.index.tz is not None:
        asian_slice = df_15m[
            (df_15m.index >= asian_start) & (df_15m.index < asian_end)
        ]

    if not asian_slice.empty:
        asian_high = float(asian_slice["High"].max())
        asian_low  = float(asian_slice["Low"].min())
    else:
        # 8-hour fallback (covers pre-London period when Asian data is thin)
        fallback_start = pd.Timestamp(now) - pd.Timedelta(hours=8)
        fb = (
            df_15m[df_15m.index >= fallback_start]
            if not df_15m.empty and df_15m.index.tz is not None
            else pd.DataFrame()
        )
        if not fb.empty:
            print("[MarketData] Using 8h fallback for Asian range (expected window empty)")
            asian_high = float(fb["High"].max())
            asian_low  = float(fb["Low"].min())
        else:
            raise ValueError(
                "Cannot determine Asian range — no 15m candle data available. "
                "Aborting session to prevent trades on fabricated levels."
            )

    # ── 6. Day range ──────────────────────────────────────────────────────────
    day_slice = (
        df[df.index >= today_ts]
        if not df.empty and df.index.tz is not None
        else pd.DataFrame()
    )
    day_high = float(day_slice["High"].max()) if not day_slice.empty else float(df["High"].max())
    day_low  = float(day_slice["Low"].min())  if not day_slice.empty else float(df["Low"].min())

    # ── 7. Swing highs/lows for SMC context ──────────────────────────────────
    swing_highs, swing_lows = _compute_swing_points(df.tail(30))

    # ── 8. Recent H1 candles with explicit "current" flag ────────────────────
    recent_candles = []
    for i in range(max(0, len(df) - 20), len(df)):
        row = df.iloc[i]
        recent_candles.append({
            "time": str(df.index[i]),
            "open":  round(float(row["Open"]),  2),
            "high":  round(float(row["High"]),  2),
            "low":   round(float(row["Low"]),   2),
            "close": round(float(row["Close"]), 2),
            "current": i == len(df) - 1,
        })

    # ── 9. Macro tickers + economic calendar ─────────────────────────────────
    macro_tickers = _fetch_macro_tickers()
    calendar      = _fetch_economic_calendar()

    return {
        "current_price":  round(current_price, 2),
        "timestamp":      now.isoformat(),
        "data_source":    data_source,
        "spread_pips":    round(spread_pips, 1),
        "h4_trend":       h4_trend,
        "asian_range": {
            "high":      round(asian_high, 2),
            "low":       round(asian_low,  2),
            "size_pips": round(abs(asian_high - asian_low) * 10, 1),
        },
        "indicators": {
            "ema9":            round(float(last["ema9"]),        2),
            "ema21":           round(float(last["ema21"]),       2),
            "ema50":           round(float(last["ema50"]),       2),
            "rsi_14":          round(float(last["rsi"]),         2),
            "atr_14":          round(float(last["atr"]),         2),
            "macd":            round(float(last["macd"]),        4),
            "macd_signal":     round(float(last["macd_signal"]), 4),
            "macd_histogram":  round(float(last["macd_hist"]),   4),
        },
        "ema_aligned_bullish": bool(last["ema9"] > last["ema21"] > last["ema50"]),
        "ema_aligned_bearish": bool(last["ema9"] < last["ema21"] < last["ema50"]),
        "rsi_above_50":  bool(last["rsi"]      > 50),
        "macd_bullish":  bool(last["macd_hist"] > 0),
        "day_high":      round(day_high, 2),
        "day_low":       round(day_low,  2),
        "recent_candles_1h": recent_candles,
        "swing_highs": swing_highs,
        "swing_lows":  swing_lows,
        # Macro feeds — injected into Macro Scout prompt
        "macro": {
            "dxy":        macro_tickers.get("dxy",    {}),
            "tnx_10y":    macro_tickers.get("tnx_10y", {}),
            "vix":        macro_tickers.get("vix",    {}),
        },
        "economic_calendar": calendar,
    }
