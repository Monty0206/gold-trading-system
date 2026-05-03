"""Volatility Regime Agent — classifies ATR-based market regime. Pure Python."""
import logging

logger = logging.getLogger(__name__)

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

from config import (REGIME_LOW_VOL_ATR, REGIME_HIGH_VOL_ATR,
                       REGIME_EXTREME_ATR, REGIME_CONFLUENCE_MIN,
                       REGIME_LOT_MULTIPLIER)


def run(candles_m15: list, current_atr: float = None) -> dict:
    try:
        atr = current_atr if current_atr is not None else _atr(candles_m15)
        regime = _classify(atr)
        result = {
            "agent": "volatility_regime", "vote": "GREEN",
            "atr_pips": round(atr, 2), "regime": regime,
            "min_confluence": REGIME_CONFLUENCE_MIN[regime],
            "lot_multiplier": REGIME_LOT_MULTIPLIER[regime],
            "sl_multiplier": {"LOW": 0.8, "NORMAL": 1.0, "HIGH": 1.2, "EXTREME": 1.5}[regime],
            "note": {
                "LOW":     "Low vol — tighter SL, normal lots",
                "NORMAL":  "Normal vol — standard params",
                "HIGH":    "High vol — 25% lot reduction, need 5/6 confluence",
                "EXTREME": "Extreme vol — 50% lot reduction, need 6/6 or skip",
            }[regime],
        }
        logger.info("Regime: %s (ATR=%.1f pips)", regime, atr)
        return result
    except Exception as exc:
        logger.error("volatility_regime error: %s", exc)
        return {"agent": "volatility_regime", "vote": "GREEN", "atr_pips": 15.0,
                "regime": "NORMAL", "min_confluence": 4, "lot_multiplier": 1.0,
                "sl_multiplier": 1.0, "note": "Default (error)"}


def _atr(candles: list, period: int = 14) -> float:
    if len(candles) < period + 1:
        return 15.0
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = float(candles[i]["high"]), float(candles[i]["low"]), float(candles[i-1]["close"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)) * 10)
    if _HAS_NUMPY:
        import numpy as np
        return float(np.mean(trs[-period:]))
    return sum(trs[-period:]) / period


def _classify(atr: float) -> str:
    if atr < REGIME_LOW_VOL_ATR:   return "LOW"
    if atr < REGIME_HIGH_VOL_ATR:  return "NORMAL"
    if atr < REGIME_EXTREME_ATR:   return "HIGH"
    return "EXTREME"
