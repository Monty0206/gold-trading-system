"""Correlation Agent — verifies DXY/Yields/VIX/GVZ coherence. Pure Python."""
import logging

logger = logging.getLogger(__name__)

_BULLISH_MAP = {"dxy": "DOWN", "yields": "DOWN", "vix": "UP", "gvz": "UP"}
_BEARISH_MAP = {"dxy": "UP",   "yields": "UP",   "vix": "DOWN", "gvz": "DOWN"}


def run(macro_data: dict, macro_bias: str) -> dict:
    try:
        signals = {
            "dxy":    _dir(macro_data.get("dxy_change", 0)),
            "yields": _dir(macro_data.get("yield_10y_change", 0)),
            "vix":    _dir(macro_data.get("vix_change", 0)),
            "gvz":    _dir(macro_data.get("gvz_change", 0)),
        }
        target = _BULLISH_MAP if macro_bias == "BULLISH" else _BEARISH_MAP if macro_bias == "BEARISH" else {}
        aligned, checked, breakdown = 0, 0, {}
        for key, expected in target.items():
            actual = signals.get(key, "FLAT")
            if actual != "FLAT":
                checked += 1
                ok = actual == expected
                breakdown[key] = {"expected": expected, "actual": actual, "aligned": ok}
                if ok:
                    aligned += 1
        modifier = round((aligned / max(checked, 1) - 0.5) * 20, 1)
        vote = "GREEN" if aligned >= 2 else ("RED" if aligned == 0 and macro_bias != "NEUTRAL" else "YELLOW")
        result = {
            "agent": "correlation", "vote": vote,
            "aligned_count": aligned, "total_signals": checked,
            "confidence_modifier": modifier, "signal_breakdown": breakdown,
            "note": f"{aligned}/{checked} signals align with {macro_bias}",
        }
        logger.info("Correlation: %s/%s aligned -> %s", aligned, checked, vote)
        return result
    except Exception as exc:
        logger.error("correlation_agent error: %s", exc)
        return {"agent": "correlation", "vote": "YELLOW", "confidence_modifier": 0.0,
                "aligned_count": 0, "total_signals": 0, "note": "Error"}


def _dir(change) -> str:
    try:
        v = float(change)
    except (TypeError, ValueError):
        return "FLAT"
    if v > 0.1:
        return "UP"
    if v < -0.1:
        return "DOWN"
    return "FLAT"
