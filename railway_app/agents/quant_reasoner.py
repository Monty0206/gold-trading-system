"""
Agent 3 — Quant Reasoner (PURE PYTHON, NO LLM)
Runs SEQUENTIALLY after macro + technical agents.
All math (lot sizing, R:R, agreement, probability) is deterministic.
"""

import logging
import math
import os

from config import MODELS  # noqa: F401  (kept for compatibility/lookup)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Lot sizing (CHANGE 2 — never round up; reject if min lot over-risks > 2x)
# ─────────────────────────────────────────────────────────────────────────────

def _compute_lot_size(account_balance: float, risk_pct: float, sl_pips: float,
                      pip_value_per_lot: float = 10.0, min_lot: float = 0.01,
                      lot_step: float = 0.01) -> dict:
    """
    Computes safe lot size. If min_lot would risk more than 2x the target,
    returns lot=0.0 and rejects the trade rather than over-risking.
    """
    if sl_pips <= 0 or pip_value_per_lot <= 0 or account_balance <= 0:
        return {
            "lot_size": 0.0,
            "actual_risk_usd": 0.0,
            "target_risk_usd": 0.0,
            "rejected": True,
            "rejection_reason": "Invalid inputs (sl_pips/pip_value/balance must be > 0)"
        }

    risk_usd = account_balance * (risk_pct / 100.0)
    raw_lot = risk_usd / (sl_pips * pip_value_per_lot)

    # Round DOWN to lot_step (never round up — that increases risk)
    safe_lot = math.floor(raw_lot / lot_step) * lot_step

    if safe_lot < min_lot:
        # Check if min_lot would over-risk beyond 2x target
        actual_risk_usd = min_lot * sl_pips * pip_value_per_lot
        if actual_risk_usd > risk_usd * 2.0:
            # Reject trade — minimum lot risks too much
            return {
                "lot_size": 0.0,
                "actual_risk_usd": round(actual_risk_usd, 2),
                "target_risk_usd": round(risk_usd, 2),
                "rejected": True,
                "rejection_reason": f"Min lot {min_lot} risks ${actual_risk_usd:.2f} but target is ${risk_usd:.2f} — account too small for this SL"
            }
        safe_lot = min_lot  # Accept the slight over-risk (within 2x)

    actual_risk_usd = safe_lot * sl_pips * pip_value_per_lot
    return {
        "lot_size": safe_lot,
        "actual_risk_usd": round(actual_risk_usd, 2),
        "target_risk_usd": round(risk_usd, 2),
        "rejected": False,
        "rejection_reason": None
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _entry_midpoint(technical: dict) -> float:
    zone_from = float(technical.get("entry_zone_from") or 0)
    zone_to   = float(technical.get("entry_zone_to") or 0)
    if zone_from > 0 and zone_to > 0:
        return round((zone_from + zone_to) / 2, 2)
    return zone_from or zone_to


def _macro_technical_agreement(macro_bias: str, breakout_dir: str,
                                technical_grade: str, confluence: int) -> tuple[bool, str]:
    """Determine if macro and technical agree.
    AGREE: BULLISH+UP or BEARISH+DOWN.
    Also: NEUTRAL macro + Grade A technical + confluence >= 5 counts as AGREE.
    """
    if macro_bias == "BULLISH" and breakout_dir == "UP":
        return True, "Macro BULLISH aligns with UP breakout"
    if macro_bias == "BEARISH" and breakout_dir == "DOWN":
        return True, "Macro BEARISH aligns with DOWN breakout"
    # NEUTRAL macro acceptable when technical is exceptionally strong
    if macro_bias == "NEUTRAL" and technical_grade == "A" and confluence >= 5:
        return True, "Macro NEUTRAL but Grade A + confluence >=5 — technical override"
    return False, f"Macro {macro_bias} vs breakout {breakout_dir} — no agreement"


def _probability_from_lookup(agree: bool, confluence: int,
                              regime_multiplier: float = 1.0) -> int:
    """Probability lookup table, factoring in regime multiplier."""
    if not agree:
        base = 30
    else:
        if confluence >= 6:
            base = 85
        elif confluence == 5:
            base = 78
        elif confluence == 4:
            base = 70
        elif confluence == 3:
            base = 55
        else:
            base = 40
    # Regime multiplier: HIGH/EXTREME volatility reduces probability
    adjusted = int(round(base * regime_multiplier))
    return max(0, min(100, adjusted))


def _verify_levels_consistent(direction: str, entry: float, sl: float,
                                tp1: float, tp2: float) -> list:
    """Return list of math errors found, empty list if all good."""
    errors = []
    if entry <= 0 or sl <= 0 or tp1 <= 0:
        errors.append("Entry/SL/TP1 must all be > 0")
        return errors

    if direction == "LONG" or direction == "UP":
        if sl >= entry:
            errors.append(f"LONG: SL ({sl}) must be below entry ({entry})")
        if tp1 <= entry:
            errors.append(f"LONG: TP1 ({tp1}) must be above entry ({entry})")
        if tp2 and tp2 <= entry:
            errors.append(f"LONG: TP2 ({tp2}) must be above entry ({entry})")
    elif direction == "SHORT" or direction == "DOWN":
        if sl <= entry:
            errors.append(f"SHORT: SL ({sl}) must be above entry ({entry})")
        if tp1 >= entry:
            errors.append(f"SHORT: TP1 ({tp1}) must be below entry ({entry})")
        if tp2 and tp2 >= entry:
            errors.append(f"SHORT: TP2 ({tp2}) must be below entry ({entry})")
    return errors


# ─────────────────────────────────────────────────────────────────────────────
# Main run function — pure Python, no LLM
# ─────────────────────────────────────────────────────────────────────────────

async def run_quant_reasoner(
    market_data: dict,
    memory_context: str,
    macro_output: dict,
    technical_output: dict,
    account_balance: float,
    regime_result: dict | None = None,
) -> dict:
    """Pure Python quant reasoner. No LLM call. Deterministic.

    regime_result: optional dict from volatility_regime agent containing
                   'lot_multiplier' and 'regime'.
    """
    risk_pct = float(os.getenv("RISK_PCT", "1.0"))

    # Pull technical inputs
    entry = _entry_midpoint(technical_output)
    sl    = float(technical_output.get("stop_loss", 0) or 0)
    tp1   = float(technical_output.get("take_profit_1", 0) or 0)
    tp2   = float(technical_output.get("take_profit_2", 0) or 0)
    breakout_dir   = technical_output.get("expected_breakout_direction", "UNCLEAR")
    technical_grade = technical_output.get("setup_grade", "NO_SETUP")
    confluence = int(technical_output.get("confluence_score", 0) or 0)
    macro_bias = macro_output.get("bias", "NEUTRAL")

    # SL distance (XAUUSD: 1 pip = $0.10 per 0.01 lot, $10 per 1 lot)
    sl_pips = abs(entry - sl) * 10 if (entry and sl) else 0

    # Regime adjustment
    lot_multiplier = 1.0
    regime_label = "NORMAL"
    if regime_result:
        lot_multiplier = float(regime_result.get("lot_multiplier", 1.0))
        regime_label = regime_result.get("regime", "NORMAL")

    # 1. Compute lot size with safe rejection logic
    lot_calc = _compute_lot_size(
        account_balance=account_balance,
        risk_pct=risk_pct,
        sl_pips=sl_pips,
        pip_value_per_lot=10.0,
        min_lot=0.01,
        lot_step=0.01,
    )

    # Apply regime lot multiplier (never increases lot, only reduces)
    lot_size = lot_calc["lot_size"]
    if lot_size > 0 and lot_multiplier < 1.0:
        # Round DOWN to nearest 0.01 step
        lot_size = math.floor((lot_size * lot_multiplier) / 0.01) * 0.01
        # Don't drop below 0.01 if original lot was non-zero
        if lot_size < 0.01:
            lot_size = 0.01
    actual_risk_usd = round(lot_size * sl_pips * 10.0, 2) if sl_pips else 0.0

    # If lot rejected — return ABORT vote immediately
    if lot_calc["rejected"]:
        logger.warning(f"Quant: lot rejected — {lot_calc['rejection_reason']}")
        return {
            "macro_technical_agree": False,
            "verified_rr_tp1": 0.0,
            "verified_rr_tp2": 0.0,
            "correct_lot_size": 0.0,
            "max_risk_usd": lot_calc["target_risk_usd"],
            "actual_risk_usd": lot_calc["actual_risk_usd"],
            "probability_score": 0,
            "math_errors": [lot_calc["rejection_reason"]],
            "levels_consistent": False,
            "edge_strength": "NO_EDGE",
            "calculation_notes": (
                f"ABORT: {lot_calc['rejection_reason']}. "
                f"sl_pips={sl_pips:.1f}, balance=${account_balance:.2f}, risk_pct={risk_pct}%"
            ),
            "agent": "QUANT_REASONER",
            "vote": "RED",
            "abort": True,
            "regime": regime_label,
        }

    # 2. R:R calculation
    rr_tp1 = round(abs(tp1 - entry) / abs(entry - sl), 2) if (sl and entry and tp1 and abs(entry - sl) > 0) else 0.0
    rr_tp2 = round(abs(tp2 - entry) / abs(entry - sl), 2) if (sl and entry and tp2 and abs(entry - sl) > 0) else 0.0

    # 3. Macro-technical agreement
    agree, agreement_note = _macro_technical_agreement(
        macro_bias=macro_bias,
        breakout_dir=breakout_dir,
        technical_grade=technical_grade,
        confluence=confluence,
    )

    # 4. Find math errors (level consistency)
    math_errors = _verify_levels_consistent(
        direction=breakout_dir,
        entry=entry,
        sl=sl,
        tp1=tp1,
        tp2=tp2,
    )
    # R:R minimum check
    if rr_tp1 > 0 and rr_tp1 < 2.0:
        math_errors.append(f"R:R TP1 {rr_tp1} below minimum 2.0")
    levels_consistent = len(math_errors) == 0

    # 5. Probability scoring (factor in regime multiplier)
    # Use lot_multiplier as a proxy for the regime confidence multiplier:
    #   LOW/NORMAL = 1.0, HIGH = 0.75, EXTREME = 0.5
    probability_score = _probability_from_lookup(
        agree=agree,
        confluence=confluence,
        regime_multiplier=lot_multiplier,
    )

    # 6. Edge strength
    if probability_score >= 78:
        edge_strength = "STRONG"
    elif probability_score >= 70:
        edge_strength = "MODERATE"
    elif probability_score >= 55:
        edge_strength = "WEAK"
    else:
        edge_strength = "NO_EDGE"

    # 7. Vote
    if probability_score >= 70 and not math_errors and levels_consistent and agree:
        vote = "GREEN"
    elif probability_score >= 55 and agree:
        vote = "YELLOW"
    else:
        vote = "RED"

    calculation_notes = (
        f"sl_pips={sl_pips:.1f}, target_risk=${lot_calc['target_risk_usd']}, "
        f"actual_risk=${actual_risk_usd}, lot={lot_size:.2f}, "
        f"regime={regime_label} (mult={lot_multiplier}), "
        f"agree={agree} ({agreement_note}), "
        f"confluence={confluence}/6, prob={probability_score}, edge={edge_strength}"
    )

    return {
        "macro_technical_agree": agree,
        "agreement_note": agreement_note,
        "verified_rr_tp1": rr_tp1,
        "verified_rr_tp2": rr_tp2,
        "correct_lot_size": lot_size,
        "max_risk_usd": lot_calc["target_risk_usd"],
        "actual_risk_usd": actual_risk_usd,
        "probability_score": probability_score,
        "math_errors": math_errors,
        "levels_consistent": levels_consistent,
        "edge_strength": edge_strength,
        "calculation_notes": calculation_notes,
        "agent": "QUANT_REASONER",
        "vote": vote,
        "abort": False,
        "regime": regime_label,
    }
