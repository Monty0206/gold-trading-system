"""
Agent 4 — Bull vs Bear Debate
Model: config.MODELS["bull_bear_debate"]  |  Temp: 0.2
Three sequential calls: Bull advocate → Bear advocate → Adjudicator.
"""

import json

from config import MODELS
from utils.openrouter import call_openrouter, call_openrouter_text

MODEL = MODELS["bull_bear_debate"]

_BULL_SYSTEM = """You are the BULL ADVOCATE for this XAUUSD trade.
Build the strongest possible case FOR taking this trade.
Use hard evidence from the macro and technical data provided.
Find every legitimate reason this trade SHOULD be taken.
No wishful thinking — only evidence-based arguments.
Give your top 5 bull arguments ranked by strength.

ALL DATA: {all_prior_data}"""

_BEAR_SYSTEM = """You are the BEAR ADVOCATE for this XAUUSD trade.
Build the strongest possible case AGAINST this trade.
Challenge every assumption. Find every weakness.
Your job is to PROTECT THE ACCOUNT from bad trades.
Be ruthlessly critical. Find real reasons this could fail.
Give your top 5 bear arguments ranked by strength.

ALL DATA: {all_prior_data}"""

_ADJUDICATOR_SYSTEM = """You received arguments from a Bull Advocate and Bear Advocate.
Score each side 1-10 on evidence quality and argument strength.
Determine which side makes a stronger case.
Be objective. Evidence wins, not enthusiasm.

BULL ARGUMENTS: {bull_arguments}
BEAR ARGUMENTS: {bear_arguments}
MEMORY: {memory_context}

Respond ONLY with a JSON object. Begin your response with {{ and end with }}.
No prose, no markdown fences.
{{
  "bull_score": 0,
  "bear_score": 0,
  "bull_strongest_point": "text",
  "bear_strongest_point": "text",
  "winner": "BULL|BEAR|DRAW",
  "margin": "DECISIVE|NARROW|TIED",
  "conviction": "HIGH|MEDIUM|LOW",
  "key_risk_identified": "main risk to watch",
  "debate_verdict": "2-3 sentence summary",
  "agent": "BULL_BEAR_DEBATE",
  "vote": "GREEN|YELLOW|RED"
}}

Vote GREEN = BULL wins with HIGH or MEDIUM conviction
Vote YELLOW = DRAW or NARROW margin
Vote RED = BEAR wins OR LOW conviction"""


async def run_bull_bear_debate(
    market_data: dict,
    macro: dict,
    technical: dict,
    quant: dict,
    memory_context: str,
) -> dict:
    """Run Bull vs Bear debate — three sequential API calls."""
    all_data_str = json.dumps(
        {
            "market_data": {
                "price": market_data["current_price"],
                "asian_range": market_data["asian_range"],
                "indicators": market_data["indicators"],
                "h4_trend": market_data["h4_trend"],
                "macro": market_data.get("macro", {}),
            },
            "macro_scout": macro,
            "technical_analyst": technical,
            "quant_reasoner": quant,
        },
        indent=2,
    )

    user_for_advocates = (
        f"Here is all the data for the potential XAUUSD trade:\n\n{all_data_str[:3000]}\n\n"
        f"Build your case based on this evidence."
    )

    bull_system = _BULL_SYSTEM.replace("{all_prior_data}", all_data_str[:3000])
    bear_system = _BEAR_SYSTEM.replace("{all_prior_data}", all_data_str[:3000])

    # Step 1 — Bull arguments
    try:
        bull_args = await call_openrouter_text(
            model=MODEL,
            system_prompt=bull_system,
            user_message=user_for_advocates,
            temperature=0.2,
            max_tokens=1024,
        )
    except Exception as e:
        bull_args = f"Bull advocate failed: {e}"

    # Step 2 — Bear arguments
    try:
        bear_args = await call_openrouter_text(
            model=MODEL,
            system_prompt=bear_system,
            user_message=user_for_advocates,
            temperature=0.2,
            max_tokens=1024,
        )
    except Exception as e:
        bear_args = f"Bear advocate failed: {e}"

    # Step 3 — Adjudicator synthesises and votes
    adj_system = (
        _ADJUDICATOR_SYSTEM
        .replace("{bull_arguments}", bull_args[:1500])
        .replace("{bear_arguments}", bear_args[:1500])
        .replace("{memory_context}", memory_context[:500])
    )

    adj_user = (
        f"Score the Bull and Bear arguments above.\n"
        f"Return ONLY a JSON object with bull_score, bear_score, winner, margin, "
        f"conviction, key_risk_identified, debate_verdict, agent, vote."
    )

    try:
        result = await call_openrouter(
            model=MODEL,
            system_prompt=adj_system,
            user_message=adj_user,
            temperature=0.2,
        )
        result.setdefault("agent", "BULL_BEAR_DEBATE")
        result["bull_arguments"] = bull_args[:500]
        result["bear_arguments"] = bear_args[:500]
        return result
    except Exception as e:
        print(f"[BullBearDebate] Adjudicator error: {e}")
        return {
            "bull_score": 5,
            "bear_score": 5,
            "bull_strongest_point": bull_args[:200] if isinstance(bull_args, str) else "N/A",
            "bear_strongest_point": bear_args[:200] if isinstance(bear_args, str) else "N/A",
            "winner": "DRAW",
            "margin": "TIED",
            "conviction": "LOW",
            "key_risk_identified": f"Debate agent error: {str(e)[:100]}",
            "debate_verdict": f"Adjudicator failed: {str(e)[:200]}",
            "agent": "BULL_BEAR_DEBATE",
            "vote": "RED",
        }
