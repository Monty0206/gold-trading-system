"""
Supabase memory functions — inject learning into each agent.
Called before every agent run to make agents smarter over time.
"""

from datetime import datetime, timezone


def _format_patterns(records: list, label: str) -> str:
    if not records:
        return f"  No {label.lower()} patterns recorded yet."
    lines = []
    for r in records[:5]:
        outcome = r.get("outcome", "UNKNOWN")
        reasoning = (r.get("reasoning_summary") or "")[:120]
        lines.append(f"  - [{outcome}] {reasoning}")
    return "\n".join(lines)


async def get_agent_memory(agent_name: str, supabase) -> str:
    """Pull last 30 decisions for this agent and return a formatted context string."""
    try:
        perf = (
            supabase.table("agent_performance")
            .select("vote, was_correct, outcome, reasoning_summary, created_at")
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
    # Only count rows where was_correct is not None (YELLOW votes are excluded)
    scored = [p for p in perf.data if p.get("was_correct") is not None]
    correct = sum(1 for p in scored if p.get("was_correct"))
    accuracy = (correct / len(scored) * 100) if scored else 0

    failures = [p for p in perf.data if p.get("was_correct") is False]
    wins = [p for p in perf.data if p.get("was_correct") is True]

    return (
        f"\nYOUR PERFORMANCE MEMORY ({agent_name}):\n"
        f"- Last {total} decisions: {accuracy:.1f}% accuracy ({len(scored)} scored)\n"
        f"- Correct calls: {correct}/{len(scored)}\n"
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


async def get_balance_from_supabase(supabase, fallback: float = 20.0) -> float:
    """Read latest account balance from trade_outcomes. Falls back to env/default."""
    try:
        row = (
            supabase.table("trade_outcomes")
            .select("account_balance_after")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if row.data and row.data[0].get("account_balance_after"):
            bal = float(row.data[0]["account_balance_after"])
            if bal > 0:
                return bal
    except Exception as e:
        print(f"[Memory] Balance read failed: {e}")
    return fallback


async def log_signal(signal_data: dict, supabase) -> str:
    """Insert a trade signal row. Returns the new signal UUID."""
    result = supabase.table("trade_signals").insert(signal_data).execute()
    return result.data[0]["id"]


async def log_agent_votes(signal_id: str, all_outputs: dict, supabase) -> None:
    """Insert one agent_performance row per agent for accuracy tracking."""
    agent_map = {
        "macro_scout":      "MACRO_SCOUT",
        "technical_analyst": "TECHNICAL_ANALYST",
        "quant_reasoner":   "QUANT_REASONER",
        "bull_bear_debate": "BULL_BEAR_DEBATE",
        "risk_manager":     "RISK_MANAGER",
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
        rows.append({
            "signal_id": signal_id,
            "agent_name": name,
            "vote": output.get("vote", "UNKNOWN"),
            "reasoning_summary": str(reasoning)[:200],
        })
    try:
        supabase.table("agent_performance").insert(rows).execute()
    except Exception as e:
        print(f"[Memory] Failed to log agent votes: {e}")


async def update_outcome(signal_id: str, outcome_data: dict, supabase) -> None:
    """
    Called by home PC after a trade closes.
    Logs the outcome and marks each agent vote correct/incorrect using
    vote-direction logic: GREEN+WIN=correct, GREEN+LOSS=wrong,
    RED+LOSS=correct, RED+WIN=wrong, YELLOW=not scored (was_correct=NULL).
    """
    try:
        supabase.table("trade_outcomes").insert(
            {"signal_id": signal_id, **outcome_data}
        ).execute()

        outcome = outcome_data.get("outcome")  # WIN / LOSS / BREAKEVEN
        _mark_agent_correctness(signal_id, outcome, supabase)
        await _update_pattern_memory(signal_id, outcome_data, supabase)
    except Exception as e:
        print(f"[Memory] Failed to update outcome: {e}")


def _mark_agent_correctness(signal_id: str, outcome: str, supabase) -> None:
    """Update was_correct for each agent vote based on vote direction."""
    try:
        rows = (
            supabase.table("agent_performance")
            .select("id, vote")
            .eq("signal_id", signal_id)
            .execute()
        )
        for row in (rows.data or []):
            vote = row.get("vote", "")
            if vote == "YELLOW":
                # Neutral vote — don't score, leave was_correct NULL
                continue
            if outcome == "WIN":
                was_correct = (vote == "GREEN")   # GREEN on a winner = correct
            elif outcome == "LOSS":
                was_correct = (vote == "RED")     # RED on a loser = correct caution
            else:
                continue  # BREAKEVEN — don't score
            supabase.table("agent_performance").update(
                {"was_correct": was_correct, "outcome": outcome}
            ).eq("id", row["id"]).execute()
    except Exception as e:
        print(f"[Memory] Agent correctness update failed: {e}")


async def _update_pattern_memory(
    signal_id: str, outcome_data: dict, supabase
) -> None:
    """Upsert a market_patterns row based on this trade's session/bias/grade."""
    try:
        sig_result = (
            supabase.table("trade_signals")
            .select("macro_bias, technical_grade, session, direction")
            .eq("id", signal_id)
            .execute()
        )
        if not sig_result.data:
            return

        sig = sig_result.data[0]
        pattern_name = (
            f"{sig.get('session','UNKNOWN')}_"
            f"{sig.get('macro_bias','NEUTRAL')}_"
            f"{sig.get('technical_grade','C')}_"
            f"{sig.get('direction','UNKNOWN')}"
        )
        was_win = outcome_data.get("outcome") == "WIN"
        now_iso = datetime.now(timezone.utc).isoformat()

        existing = (
            supabase.table("market_patterns")
            .select("win_count, loss_count, sample_size")
            .eq("pattern_name", pattern_name)
            .execute()
        )

        if existing.data:
            p = existing.data[0]
            wins   = p["win_count"]   + (1 if was_win else 0)
            losses = p["loss_count"]  + (0 if was_win else 1)
            total  = wins + losses
            supabase.table("market_patterns").update({
                "win_count":   wins,
                "loss_count":  losses,
                "sample_size": total,
                "win_rate":    round(wins / total * 100, 2),
                "last_seen":   now_iso,
            }).eq("pattern_name", pattern_name).execute()
        else:
            supabase.table("market_patterns").upsert({
                "pattern_name":      pattern_name,
                "description":       f"Auto: {pattern_name}",
                "session":           sig.get("session"),
                "macro_condition":   sig.get("macro_bias"),
                "technical_condition": sig.get("technical_grade"),
                "sample_size":       1,
                "win_count":         1 if was_win else 0,
                "loss_count":        0 if was_win else 1,
                "win_rate":          100.0 if was_win else 0.0,
                "last_seen":         now_iso,
            }, on_conflict="pattern_name").execute()
    except Exception as e:
        print(f"[Memory] Pattern update failed: {e}")
