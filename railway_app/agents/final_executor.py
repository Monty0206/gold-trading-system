"""
Agent 6 — Final Executor
Model: anthropic/claude-opus-4-6  |  Temp: 0.1
Senior Portfolio Manager — receives all 5 agent outputs and produces ONE final call.
"""

import json
from datetime import datetime, timezone
from utils.openrouter import call_openrouter

MODEL = "anthropic/claude-opus-4-6"

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
- 4/5 GREEN → EXECUTE (Risk Manager must be one of the 4)
- 3/5 or fewer GREEN → WAIT (log reason)
- Risk Manager RED → ABORT regardless of other votes
- Daily loss limit hit → ABORT regardless of setup

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
  "trade_management": {{
    "move_sl_to_be_after": "TP1 hit",
    "trail_tp2_by_pips": 15,
    "close_if_session_ends": true,
    "close_before_news": true
  }},
  "monitor_during_trade": ["item1", "item2"],
  "agent_consensus": {{
    "macro_scout": "GREEN|YELLOW|RED",
    "technical_analyst": "GREEN|YELLOW|RED",
    "quant_reasoner": "GREEN|YELLOW|RED",
    "bull_bear_debate": "GREEN|YELLOW|RED",
    "risk_manager": "GREEN|RED",
    "green_count": 0
  }},
  "confidence_score": 0,
  "wait_reason": null,
  "abort_reason": null,
  "trade_narrative": "Full explanation paragraph",
  "agent": "FINAL_EXECUTOR",
  "timestamp": "ISO8601"
}}"""


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

    # Summarise recent performance
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

    # Build the green vote count
    vote_names = ["macro_scout", "technical_analyst", "quant_reasoner",
                  "bull_bear_debate", "risk_manager"]
    green_count = sum(
        1 for k in vote_names
        if all_outputs.get(k, {}).get("vote") == "GREEN"
    )
    risk_vote = all_outputs.get("risk_manager", {}).get("vote", "RED")

    user_message = (
        f"Agent votes summary:\n"
        + "\n".join(
            f"  {k}: {all_outputs.get(k, {}).get('vote', 'UNKNOWN')}"
            for k in vote_names
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
        result.setdefault("agent", "FINAL_EXECUTOR")
        result.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        # Enforce: Risk Manager RED always → ABORT
        if risk_vote == "RED" and result.get("decision") not in ("WAIT", "ABORT"):
            result["decision"] = "ABORT"
            result["abort_reason"] = "Risk Manager voted RED — overriding to ABORT"
            result["direction"] = "NONE"
        return result
    except Exception as e:
        print(f"[FinalExecutor] Error: {e}")
        return {
            "decision": "ABORT",
            "direction": "NONE",
            "entry_price": 0.0,
            "entry_type": "MARKET",
            "stop_loss": 0.0,
            "take_profit_1": 0.0,
            "take_profit_2": 0.0,
            "lot_size": 0.0,
            "risk_usd": 0.0,
            "rr_tp1": 0.0,
            "rr_tp2": 0.0,
            "session": account_state.get("session", "UNKNOWN"),
            "entry_window_gmt": "N/A",
            "invalidation_level": 0.0,
            "invalidation_condition": "Final Executor failed",
            "trade_management": {},
            "monitor_during_trade": [],
            "agent_consensus": {k: all_outputs.get(k, {}).get("vote", "UNKNOWN") for k in vote_names},
            "confidence_score": 0,
            "wait_reason": None,
            "abort_reason": f"Final Executor error: {str(e)[:200]}",
            "trade_narrative": f"System error in Final Executor: {str(e)[:300]}",
            "agent": "FINAL_EXECUTOR",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
