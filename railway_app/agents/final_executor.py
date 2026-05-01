"""
Agent 6 — Final Executor
Model: config.MODELS["final_executor"]  |  Temp: 0.1
Senior Portfolio Manager. Receives all 5 agent outputs. Produces ONE final call.
Python guardrails enforce decision rules AFTER LLM call — LLM cannot override them.
"""

import json
from datetime import datetime, timezone

from config import MODELS
from utils.openrouter import call_openrouter

MODEL = MODELS["final_executor"]

_SYSTEM_TEMPLATE = """You are the Senior Portfolio Manager. Final decision maker.
You receive all 5 agent outputs. You produce ONE final trade call.

Be precise. Be decisive. No ambiguity.
Write as if briefing a professional trader who will execute immediately.

ALL AGENT OUTPUTS: {all_outputs}
RECENT PERFORMANCE: {performance_memory}
WINNING PATTERNS: {winning_patterns}
LOSING PATTERNS: {losing_patterns}
CURRENT ACCOUNT: ${account_balance}

DECISION RULES:
- 5/5 GREEN → EXECUTE with full confidence
- 4/5 GREEN (Risk Manager must be one of the 4) → EXECUTE
- 3/5 or fewer GREEN → WAIT
- Risk Manager RED → ABORT regardless of other votes

Respond ONLY in valid JSON:
{{
  "decision": "EXECUTE_BUY|EXECUTE_SELL|WAIT|ABORT",
  "direction": "LONG|SHORT|NONE",
  "entry_price": 0.00,
  "entry_type": "MARKET|LIMIT",
  "stop_loss": 0.00,
  "take_profit_1": 0.00,
  "take_profit_2": 0.00,
  "lot_size": 0.00,
  "risk_usd": 0.00,
  "rr_tp1": 0.0,
  "rr_tp2": 0.0,
  "session": "LONDON|NEW_YORK",
  "entry_window_gmt": "HH:MM-HH:MM",
  "invalidation_level": 0.00,
  "invalidation_condition": "description",
  "confidence_score": 0,
  "wait_reason": null,
  "abort_reason": null,
  "trade_narrative": "Full explanation paragraph",
  "agent": "FINAL_EXECUTOR",
  "timestamp": "ISO8601"
}}"""

_VOTE_NAMES = [
    "macro_scout", "technical_analyst", "quant_reasoner",
    "bull_bear_debate", "risk_manager",
]


async def run_final_executor(
    all_outputs: dict,
    system_memory: dict,
    account_state: dict,
) -> dict:
    """Run Final Executor — synthesises all agents into one trade decision."""
    account_balance = account_state.get("balance", 20.0)

    recent = system_memory.get("recent_outcomes", [])
    winning = system_memory.get("winning_patterns", [])
    losing = system_memory.get("losing_patterns", [])

    if recent:
        wins = sum(1 for o in recent if o.get("outcome") == "WIN")
        total = len(recent)
        perf_str = (
            f"Last {total} trades: {wins} wins, {total - wins} losses "
            f"({round(wins / total * 100, 1)}% win rate)."
        )
    else:
        perf_str = "No recent trade history."

    system = (
        _SYSTEM_TEMPLATE
        .replace("{all_outputs}", json.dumps(all_outputs, indent=2)[:6000])
        .replace("{performance_memory}", perf_str)
        .replace("{winning_patterns}", json.dumps(winning[:3], indent=2))
        .replace("{losing_patterns}", json.dumps(losing[:3], indent=2))
        .replace("{account_balance}", str(account_balance))
    )

    # Python computes green count — not the LLM
    green_count = sum(
        1 for k in _VOTE_NAMES
        if all_outputs.get(k, {}).get("vote") == "GREEN"
    )
    risk_vote = all_outputs.get("risk_manager", {}).get("vote", "RED")

    user_message = (
        "Agent votes summary:\n"
        + "\n".join(
            f"  {k}: {all_outputs.get(k, {}).get('vote', 'UNKNOWN')}"
            for k in _VOTE_NAMES
        )
        + f"\n\nGreen votes: {green_count}/5\n"
        f"Risk Manager vote: {risk_vote}\n"
        f"Account balance: ${account_balance}\n"
        f"Session: {account_state.get('session', 'UNKNOWN')}\n\n"
        f"Apply decision rules and produce final JSON trade call.\n"
        f"Current UTC time: {datetime.now(timezone.utc).isoformat()}"
    )

    try:
        result = await call_openrouter(
            model=MODEL,
            system_prompt=system,
            user_message=user_message,
            temperature=0.1,
        )
    except Exception as e:
        print(f"[FinalExecutor] Error: {e}")
        result = {
            "decision": "ABORT",
            "abort_reason": f"Final Executor error: {str(e)[:200]}",
        }

    result.setdefault("agent", "FINAL_EXECUTOR")
    result.setdefault("timestamp", datetime.now(timezone.utc).isoformat())

    # ── Python guardrails — override LLM if it violated decision rules ────────
    decision = result.get("decision", "")

    # Risk Manager RED always overrides to ABORT
    if risk_vote == "RED" and decision not in ("WAIT", "ABORT"):
        result["decision"] = "ABORT"
        result["abort_reason"] = "Risk Manager voted RED — Python override to ABORT"
        result["direction"] = "NONE"
        result["entry_price"] = 0.0
        result["stop_loss"] = 0.0
        result["take_profit_1"] = 0.0
        result["take_profit_2"] = 0.0
        result["lot_size"] = 0.0
        result["risk_usd"] = 0.0

    # Fewer than 4 green votes → force WAIT
    elif green_count < 4 and result.get("decision", "").startswith("EXECUTE"):
        result["decision"] = "WAIT"
        result["wait_reason"] = (
            f"Python guardrail: only {green_count}/5 green votes — need 4+. "
            f"LLM tried to execute anyway."
        )
        result["direction"] = "NONE"
        result["entry_price"] = 0.0
        result["stop_loss"] = 0.0
        result["take_profit_1"] = 0.0
        result["take_profit_2"] = 0.0
        result["lot_size"] = 0.0
        result["risk_usd"] = 0.0

    return result
