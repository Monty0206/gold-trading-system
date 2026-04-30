"""
Supabase memory functions — inject learning into each agent.
Called before every agent run to make agents smarter over time.
"""


def _format_patterns(records: list, label: str) -> str:
    """Format a list of trade records into a human-readable summary."""
    if not records:
        return f"  No {label.lower()} patterns recorded yet."
    lines = []
    for r in records[:5]:
        outcome = r.get("outcome", "UNKNOWN")
        reasoning = (r.get("reasoning_summary") or "")[:120]
        lines.append(f"  - [{outcome}] {reasoning}")
    return "\n".join(lines)


async def get_agent_memory(agent_name: str, supabase) -> str:
    """
    Pull last 30 decisions for this agent, calculate accuracy,
    and return a formatted string to inject into the agent's prompt.
    """
    try:
        perf = (
            supabase.table("agent_performance")
            .select("*, trade_outcomes(*)")
            .eq("agent_name", agent_name)
            .order("created_at", desc=True)
            .limit(30)
            .execute()
        )
    except Exception as e:
        return f"Memory unavailable ({e}). Proceed with current analysis only."

    if not perf.data:
        return "No performance history yet. This is an early session."

    total = len(perf.data)
    correct = sum(1 for p in perf.data if p.get("was_correct"))
    accuracy = (correct / total * 100) if total > 0 else 0

    failures = [p for p in perf.data if not p.get("was_correct")]
    wins = [p for p in perf.data if p.get("was_correct")]

    return (
        f"\nYOUR PERFORMANCE MEMORY ({agent_name}):\n"
        f"- Last {total} decisions: {accuracy:.1f}% accuracy\n"
        f"- Correct calls: {correct}/{total}\n"
        f"- Recent failures: {len(failures)} in last 30 sessions\n\n"
        f"LEARN FROM YOUR FAILURES:\n{_format_patterns(failures, 'FAILURE')}\n\n"
        f"LEARN FROM YOUR WINS:\n{_format_patterns(wins, 'WIN')}\n\n"
        f"USE THIS: Adjust your confidence based on current conditions\n"
        f"vs conditions where you historically failed.\n"
    )


async def get_system_memory(supabase) -> dict:
    """Pull overall system performance for the Final Executor."""
    try:
        outcomes = (
            supabase.table("trade_outcomes")
            .select("*")
            .order("created_at", desc=True)
            .limit(30)
            .execute()
        )
        winning = (
            supabase.table("market_patterns")
            .select("*")
            .gte("win_rate", 65)
            .gte("sample_size", 3)
            .order("win_rate", desc=True)
            .limit(5)
            .execute()
        )
        losing = (
            supabase.table("market_patterns")
            .select("*")
            .lte("win_rate", 40)
            .gte("sample_size", 3)
            .order("win_rate")
            .limit(5)
            .execute()
        )
        return {
            "recent_outcomes": outcomes.data,
            "winning_patterns": winning.data,
            "losing_patterns": losing.data,
        }
    except Exception as e:
        return {
            "recent_outcomes": [],
            "winning_patterns": [],
            "losing_patterns": [],
            "error": str(e),
        }


async def log_signal(signal_data: dict, supabase) -> str:
    """Insert a trade signal row. Returns the new signal UUID."""
    result = supabase.table("trade_signals").insert(signal_data).execute()
    return result.data[0]["id"]


async def log_agent_votes(signal_id: str, all_outputs: dict, supabase) -> None:
    """Insert one agent_performance row per agent for accuracy tracking."""
    agent_map = {
        "macro_scout": "MACRO_SCOUT",
        "technical_analyst": "TECHNICAL_ANALYST",
        "quant_reasoner": "QUANT_REASONER",
        "bull_bear_debate": "BULL_BEAR_DEBATE",
        "risk_manager": "RISK_MANAGER",
    }
    rows = []
    for key, name in agent_map.items():
        output = all_outputs.get(key, {})
        reasoning = (
            output.get("summary")
            or output.get("debate_verdict")
            or output.get("calculation_notes")
            or output.get("risk_notes")
            or ""
        )
        rows.append(
            {
                "signal_id": signal_id,
                "agent_name": name,
                "vote": output.get("vote", "UNKNOWN"),
                "reasoning_summary": str(reasoning)[:200],
            }
        )
    try:
        supabase.table("agent_performance").insert(rows).execute()
    except Exception as e:
        print(f"[Memory] Failed to log agent votes: {e}")


async def update_outcome(signal_id: str, outcome_data: dict, supabase) -> None:
    """
    Called by the home PC after a trade closes.
    Logs the outcome and marks each agent vote correct/incorrect.
    """
    try:
        supabase.table("trade_outcomes").insert(
            {"signal_id": signal_id, **outcome_data}
        ).execute()

        was_win = outcome_data.get("outcome") == "WIN"
        supabase.table("agent_performance").update(
            {"was_correct": was_win, "outcome": outcome_data.get("outcome")}
        ).eq("signal_id", signal_id).execute()

        await _update_pattern_memory(signal_id, outcome_data, supabase)
    except Exception as e:
        print(f"[Memory] Failed to update outcome: {e}")


async def _update_pattern_memory(
    signal_id: str, outcome_data: dict, supabase
) -> None:
    """Update or create a market_patterns row based on this trade's result."""
    try:
        sig_result = (
            supabase.table("trade_signals")
            .select("macro_bias, technical_grade, session")
            .eq("id", signal_id)
            .execute()
        )
        if not sig_result.data:
            return

        sig = sig_result.data[0]
        pattern_name = (
            f"{sig.get('session', 'UNKNOWN')}_"
            f"{sig.get('macro_bias', 'NEUTRAL')}_"
            f"{sig.get('technical_grade', 'C')}"
        )
        was_win = outcome_data.get("outcome") == "WIN"

        existing = (
            supabase.table("market_patterns")
            .select("*")
            .eq("pattern_name", pattern_name)
            .execute()
        )

        if existing.data:
            p = existing.data[0]
            wins = p["win_count"] + (1 if was_win else 0)
            losses = p["loss_count"] + (0 if was_win else 1)
            total = wins + losses
            supabase.table("market_patterns").update(
                {
                    "win_count": wins,
                    "loss_count": losses,
                    "sample_size": total,
                    "win_rate": round(wins / total * 100, 2),
                    "last_seen": outcome_data.get("created_at"),
                }
            ).eq("pattern_name", pattern_name).execute()
        else:
            supabase.table("market_patterns").insert(
                {
                    "pattern_name": pattern_name,
                    "description": f"Auto: {pattern_name}",
                    "session": sig.get("session"),
                    "macro_condition": sig.get("macro_bias"),
                    "technical_condition": sig.get("technical_grade"),
                    "sample_size": 1,
                    "win_count": 1 if was_win else 0,
                    "loss_count": 0 if was_win else 1,
                    "win_rate": 100.0 if was_win else 0.0,
                    "last_seen": outcome_data.get("created_at"),
                }
            ).execute()
    except Exception as e:
        print(f"[Memory] Pattern update failed: {e}")
