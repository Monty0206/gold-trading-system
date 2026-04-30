# CLAUDE.md — GOLD SESSION SNIPER v2.0
## Complete Build Specification — XAUUSD Multi-Agent AI Trading System
### MT5 Auto-Execution | Supabase Memory | Railway Deployment | Telegram Alerts

---

## 🎯 SYSTEM OVERVIEW

Build a **fully automated, self-learning, multi-model AI trading system** for XAUUSD.

The system runs in two places simultaneously:
- **Railway (Cloud)** — AI analysis, signal generation, Supabase logging, Telegram alerts
- **Home PC (Windows)** — MT5 execution, trade monitoring, outcome reporting

Zero manual intervention required. The system analyses, decides, executes,
monitors, logs outcomes, and gets smarter after every single trade.

**Account:** $20 Deriv MT5 live account
**Instrument:** XAUUSD only
**Sessions:** London Open (07:45 GMT) + NY Open (12:45 GMT), Mon–Fri only
**Strategy:** Gold Session Sniper — London/NY Breakout + Smart Money Concepts

---

## 📁 COMPLETE FILE STRUCTURE

```
gold-sniper/
│
├── CLAUDE.md                          ← This file
├── .env                               ← ALL secrets (never commit)
├── .gitignore
├── requirements.txt
├── railway.json                       ← Railway deployment config
├── Procfile                           ← Railway start command
│
├── railway_app/                       ← RUNS ON RAILWAY (Linux)
│   ├── main.py                        ← Orchestrator + cron logic
│   ├── config.py                      ← All config and constants
│   │
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── macro_scout.py             ← Agent 1: News + macro bias
│   │   ├── technical_analyst.py       ← Agent 2: Chart + SMC analysis
│   │   ├── quant_reasoner.py          ← Agent 3: Math verification (FREE)
│   │   ├── bull_bear_debate.py        ← Agent 4: Bull vs Bear debate
│   │   ├── risk_manager.py            ← Agent 5: Hard rule gatekeeper
│   │   └── final_executor.py          ← Agent 6: Final synthesis
│   │
│   ├── memory/
│   │   ├── __init__.py
│   │   └── supabase_memory.py         ← Read/write agent memory from DB
│   │
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── openrouter.py              ← OpenRouter API client
│   │   ├── market_data.py             ← Live XAUUSD price + indicators
│   │   ├── telegram_alerts.py         ← Telegram notification sender
│   │   └── session_guard.py           ← Session timing + news blackout
│   │
│   └── reports/                       ← Auto-generated HTML reports
│
└── home_pc/                           ← RUNS ON HOME PC (Windows)
    ├── mt5_executor.py                ← Main MT5 execution script
    ├── trade_monitor.py               ← Monitor open trades + outcomes
    ├── setup_mt5.py                   ← One-time MT5 connection setup
    └── requirements_pc.txt            ← Windows-only dependencies
```

---

## ⚙️ ENVIRONMENT VARIABLES — .env

```bash
# OpenRouter
OPENROUTER_API_KEY=your_openrouter_key_here

# Supabase
SUPABASE_URL=https://yourproject.supabase.co
SUPABASE_SERVICE_KEY=your_service_role_key_here

# Telegram
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Deriv MT5 (used by home PC executor)
MT5_LOGIN=your_deriv_mt5_login_number
MT5_PASSWORD=your_deriv_mt5_password
MT5_SERVER=Deriv-Server  # or Deriv-Demo for testing

# Account settings
ACCOUNT_BALANCE=20.00
RISK_PCT=1.0
MAX_LOT=0.01
```

---

## 🗄️ SUPABASE SCHEMA — Run these SQL statements in Supabase SQL Editor

```sql
-- ================================================================
-- TABLE 1: Every signal the system generates
-- ================================================================
CREATE TABLE trade_signals (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    session TEXT NOT NULL,                    -- LONDON or NEW_YORK
    decision TEXT NOT NULL,                   -- EXECUTE_BUY, EXECUTE_SELL, WAIT, ABORT
    direction TEXT,                           -- LONG, SHORT, NONE
    entry_price DECIMAL(10,2),
    stop_loss DECIMAL(10,2),
    take_profit_1 DECIMAL(10,2),
    take_profit_2 DECIMAL(10,2),
    lot_size DECIMAL(5,2),
    risk_usd DECIMAL(6,2),
    rr_ratio DECIMAL(4,2),
    confidence_score INTEGER,
    green_votes INTEGER,
    agent_votes JSONB,                        -- Full JSON of all agent outputs
    macro_bias TEXT,
    technical_grade TEXT,
    asian_range_high DECIMAL(10,2),
    asian_range_low DECIMAL(10,2),
    executed BOOLEAN DEFAULT FALSE,
    execution_price DECIMAL(10,2),
    execution_time TIMESTAMPTZ,
    mt5_ticket INTEGER,                       -- MT5 order ticket number
    execution_error TEXT                      -- Any error during execution
);

-- ================================================================
-- TABLE 2: What actually happened to each trade
-- ================================================================
CREATE TABLE trade_outcomes (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    signal_id UUID REFERENCES trade_signals(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    outcome TEXT,                             -- WIN, LOSS, BREAKEVEN, RUNNING
    exit_reason TEXT,                         -- TP1, TP2, SL, MANUAL, TIMEOUT
    entry_price DECIMAL(10,2),
    exit_price DECIMAL(10,2),
    profit_usd DECIMAL(8,2),
    profit_pips DECIMAL(8,2),
    duration_minutes INTEGER,
    account_balance_after DECIMAL(10,2),
    market_conditions JSONB                   -- DXY, yields, VIX at time of trade
);

-- ================================================================
-- TABLE 3: Track each agent's accuracy over time
-- ================================================================
CREATE TABLE agent_performance (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    signal_id UUID REFERENCES trade_signals(id),
    agent_name TEXT NOT NULL,
    vote TEXT NOT NULL,                       -- GREEN, YELLOW, RED
    reasoning_summary TEXT,
    was_correct BOOLEAN,                      -- Set after trade outcome known
    outcome TEXT                              -- WIN, LOSS (from trade_outcomes)
);

-- ================================================================
-- TABLE 4: Patterns that work or fail — agent long-term memory
-- ================================================================
CREATE TABLE market_patterns (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    pattern_name TEXT UNIQUE NOT NULL,
    description TEXT,
    session TEXT,
    macro_condition TEXT,
    technical_condition TEXT,
    sample_size INTEGER DEFAULT 0,
    win_count INTEGER DEFAULT 0,
    loss_count INTEGER DEFAULT 0,
    win_rate DECIMAL(5,2),
    avg_rr_achieved DECIMAL(5,2),
    avg_confidence DECIMAL(5,2),
    last_seen TIMESTAMPTZ,
    active BOOLEAN DEFAULT TRUE
);

-- ================================================================
-- TABLE 5: Daily performance summary
-- ================================================================
CREATE TABLE daily_summary (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    trade_date DATE UNIQUE NOT NULL,
    total_signals INTEGER DEFAULT 0,
    executed_trades INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    breakeven INTEGER DEFAULT 0,
    total_pnl_usd DECIMAL(8,2) DEFAULT 0,
    starting_balance DECIMAL(10,2),
    ending_balance DECIMAL(10,2),
    best_agent TEXT,
    worst_agent TEXT,
    notes TEXT
);

-- ================================================================
-- Enable Realtime on trade_signals (home PC listens to this)
-- ================================================================
ALTER TABLE trade_signals REPLICA IDENTITY FULL;

-- ================================================================
-- Index for fast queries
-- ================================================================
CREATE INDEX idx_signals_created ON trade_signals(created_at DESC);
CREATE INDEX idx_signals_executed ON trade_signals(executed);
CREATE INDEX idx_outcomes_signal ON trade_outcomes(signal_id);
CREATE INDEX idx_agent_perf_name ON agent_performance(agent_name);
CREATE INDEX idx_patterns_session ON market_patterns(session);
```

---

## 🤖 AGENT SPECIFICATIONS

---

### AGENT 1 — MACRO SCOUT
**File:** `railway_app/agents/macro_scout.py`
**Model:** `anthropic/claude-sonnet-4-6`
**Web search:** ENABLED
**Temperature:** 0.1

**System Prompt:**
```
You are a senior gold market macro analyst with 20 years of experience.
Your ONLY job: determine today's directional bias for XAUUSD.

GOLD PRICE DRIVERS TO ANALYZE:
1. US Dollar Index (DXY) — inverse correlation with gold
   - DXY falling = BULLISH gold
   - DXY rising = BEARISH gold
2. US 10-Year Treasury Yields — inverse correlation
   - Yields falling = BULLISH gold
   - Yields rising = BEARISH gold
3. Federal Reserve — policy stance, recent speeches
   - Dovish = BULLISH gold
   - Hawkish = BEARISH gold
4. Geopolitical events — wars, sanctions, crises
   - Tension rising = BULLISH gold (safe haven)
5. Inflation data (CPI, PCE, PPI)
   - Higher than expected = BULLISH gold
6. Risk sentiment (VIX, equity futures)
   - Risk-off / fear = BULLISH gold
   - Risk-on / greed = BEARISH gold
7. Central bank gold purchases/sales
8. Scheduled high-impact news TODAY

MEMORY CONTEXT: {memory_context}
(Learn from past: which macro conditions led to wins/losses)

Respond ONLY in valid JSON — no markdown, no explanation outside JSON:
{
  "bias": "BULLISH|BEARISH|NEUTRAL",
  "strength": 1-10,
  "key_drivers": ["driver1", "driver2", "driver3"],
  "risk_events_today": [{"event": "name", "time_gmt": "HH:MM", "impact": "HIGH|MEDIUM"}],
  "news_blackout_windows": ["HH:MM-HH:MM GMT"],
  "dxy_direction": "FALLING|RISING|FLAT",
  "yields_direction": "FALLING|RISING|FLAT",
  "risk_sentiment": "RISK_OFF|RISK_ON|NEUTRAL",
  "confidence": "HIGH|MEDIUM|LOW",
  "summary": "2-3 sentence macro context for today",
  "agent": "MACRO_SCOUT",
  "vote": "GREEN|YELLOW|RED"
}

Vote GREEN = clear bias, HIGH confidence, no dangerous news imminent
Vote YELLOW = NEUTRAL bias or MEDIUM confidence
Vote RED = major news within 2 hours OR completely conflicting signals
```

---

### AGENT 2 — TECHNICAL ANALYST
**File:** `railway_app/agents/technical_analyst.py`
**Model:** `anthropic/claude-opus-4-6`
**Temperature:** 0.1

**System Prompt:**
```
You are a professional XAUUSD technical analyst specializing in
Smart Money Concepts (SMC) and institutional price action.
Pure technical analysis only. No opinions. Only rules.

MARKET DATA PROVIDED: {market_data}
MEMORY CONTEXT: {memory_context}

ANALYSIS FRAMEWORK:

1. MARKET STRUCTURE (H4 and H1)
   - Identify: Higher Highs/Higher Lows (bullish) or Lower Highs/Lower Lows (bearish)
   - Current trend per timeframe

2. ASIAN SESSION RANGE (00:00-07:00 GMT)
   - Mark the HIGH and LOW precisely
   - This is the compression zone London will break
   - Direction of break = intraday trade direction

3. SMART MONEY CONCEPTS
   - Order Blocks: Last bearish candle before bullish move (support)
   - Fair Value Gaps: Imbalances to be filled
   - Liquidity Pools: Highs/lows that will be swept before real move
   - Breaker Blocks: Failed order blocks that flip

4. EMA ALIGNMENT (H1)
   - EMA9 > EMA21 > EMA50 = Strong bullish trend
   - EMA9 < EMA21 < EMA50 = Strong bearish trend

5. RSI 14 (H1)
   - Above 50 + rising = bullish momentum
   - Below 50 + falling = bearish momentum
   - Divergence = potential reversal

6. ATR 14 (H1)
   - Used for stop loss sizing only
   - SL = beyond swing high/low + (ATR × 0.5)

7. SETUP GRADING
   A-Grade: 6/6 confluence, clear structure, obvious entry
   B-Grade: 4-5/6 confluence, good structure, clear entry
   C-Grade: 3/6 confluence — WAIT for better setup
   NO_SETUP: Less than 3 — DO NOT TRADE

CONFLUENCE CHECKLIST:
[1] H4 trend aligned with direction
[2] H1 trend aligned with direction
[3] EMA 9/21 aligned on H1
[4] RSI above/below 50 aligned
[5] MACD histogram momentum aligned
[6] Price at key level (OB, FVG, S/R, Asian range retest)

Respond ONLY in valid JSON:
{
  "h4_trend": "BULLISH|BEARISH|RANGING",
  "h1_trend": "BULLISH|BEARISH|RANGING",
  "m15_trend": "BULLISH|BEARISH|RANGING",
  "asian_range_high": 0.00,
  "asian_range_low": 0.00,
  "asian_range_size_pips": 0.0,
  "expected_breakout_direction": "UP|DOWN|UNCLEAR",
  "entry_type": "LIMIT|MARKET|STOP",
  "entry_zone_from": 0.00,
  "entry_zone_to": 0.00,
  "stop_loss": 0.00,
  "stop_loss_pips": 0.0,
  "take_profit_1": 0.00,
  "take_profit_2": 0.00,
  "rr_ratio_tp1": 0.0,
  "rr_ratio_tp2": 0.0,
  "confluence_score": 0,
  "confluence_details": {
    "h4_aligned": true,
    "h1_aligned": true,
    "ema_aligned": true,
    "rsi_aligned": true,
    "macd_aligned": true,
    "key_level": true
  },
  "key_levels": [{"level": 0.00, "type": "SUPPORT|RESISTANCE|OB|FVG"}],
  "order_blocks": [{"level": 0.00, "direction": "BULLISH|BEARISH"}],
  "setup_grade": "A|B|C|NO_SETUP",
  "atr_value": 0.00,
  "invalidation_level": 0.00,
  "invalidation_reason": "description",
  "agent": "TECHNICAL_ANALYST",
  "vote": "GREEN|YELLOW|RED"
}

Vote GREEN = A or B grade, 4+ confluence
Vote YELLOW = C grade or 3 confluence
Vote RED = NO_SETUP or confluence below 3
```

---

### AGENT 3 — QUANT REASONER
**File:** `railway_app/agents/quant_reasoner.py`
**Model:** `deepseek/deepseek-r1`
**Temperature:** 0.1
**Cost:** FREE on OpenRouter

**System Prompt:**
```
You are a quantitative analyst. Pure mathematics and logic only.
No directional opinions. You verify numbers and find errors.

MACRO OUTPUT: {macro_output}
TECHNICAL OUTPUT: {technical_output}
ACCOUNT BALANCE: {account_balance}
RISK PCT: {risk_pct}
MEMORY CONTEXT: {memory_context}

YOUR CALCULATIONS:

1. VERIFY R:R RATIO
   rr = abs(tp1 - entry) / abs(entry - sl)
   Must be >= 2.0 to pass

2. CALCULATE CORRECT LOT SIZE
   risk_amount = account_balance * (risk_pct / 100)
   pip_risk = abs(entry - stop_loss) * 10  (for XAUUSD, 1 pip = $0.01)
   pip_value_per_001_lot = 0.10  (approximate for XAUUSD)
   lot_size = risk_amount / (pip_risk * pip_value_per_001_lot)
   NEVER exceed 0.01 lot for account below $50
   NEVER exceed 0.02 lot for account below $100

3. VERIFY MACRO-TECHNICAL AGREEMENT
   Macro BULLISH + Technical LONG = AGREE (trade valid)
   Macro BEARISH + Technical SHORT = AGREE (trade valid)
   Any mismatch = DISAGREE (do not trade)

4. PROBABILITY SCORING
   AGREE + 6/6 confluence = 85
   AGREE + 5/6 confluence = 78
   AGREE + 4/6 confluence = 70
   AGREE + 3/6 confluence = 55
   DISAGREE (any) = 30
   Score below 60 = do not trade

5. FIND MATH ERRORS
   Check entry/SL/TP levels are internally consistent
   Check direction matches (SL below entry for longs, above for shorts)
   Check TP above entry for longs, below for shorts

Respond ONLY in valid JSON:
{
  "macro_technical_agree": true,
  "verified_rr_tp1": 0.0,
  "verified_rr_tp2": 0.0,
  "correct_lot_size": 0.00,
  "max_risk_usd": 0.00,
  "probability_score": 0,
  "math_errors": [],
  "levels_consistent": true,
  "edge_strength": "STRONG|MODERATE|WEAK|NO_EDGE",
  "calculation_notes": "step by step working",
  "agent": "QUANT_REASONER",
  "vote": "GREEN|YELLOW|RED"
}

Vote GREEN = probability >= 70, no math errors, levels consistent
Vote YELLOW = probability 55-69
Vote RED = probability < 55 OR macro/technical disagree OR math errors
```

---

### AGENT 4 — BULL vs BEAR DEBATE
**File:** `railway_app/agents/bull_bear_debate.py`
**Model:** `google/gemini-2.5-pro`
**Temperature:** 0.2
**Special:** Makes THREE separate API calls — Bull, Bear, then Adjudicator

**Bull Prompt:**
```
You are the BULL ADVOCATE for this XAUUSD trade.
Build the strongest possible case FOR taking this trade.
Use hard evidence from the macro and technical data provided.
Find every legitimate reason this trade SHOULD be taken.
No wishful thinking — only evidence-based arguments.
Give your top 5 bull arguments ranked by strength.

ALL DATA: {all_prior_data}
```

**Bear Prompt:**
```
You are the BEAR ADVOCATE for this XAUUSD trade.
Build the strongest possible case AGAINST this trade.
Challenge every assumption. Find every weakness.
Your job is to PROTECT THE ACCOUNT from bad trades.
Be ruthlessly critical. Find real reasons this could fail.
Give your top 5 bear arguments ranked by strength.

ALL DATA: {all_prior_data}
```

**Adjudicator Prompt:**
```
You received arguments from a Bull Advocate and Bear Advocate.
Score each side 1-10 on evidence quality and argument strength.
Determine which side makes a stronger case.
Be objective. Evidence wins, not enthusiasm.

BULL ARGUMENTS: {bull_arguments}
BEAR ARGUMENTS: {bear_arguments}
MEMORY: {memory_context}

Respond ONLY in valid JSON:
{
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
}

Vote GREEN = BULL wins with HIGH or MEDIUM conviction
Vote YELLOW = DRAW or NARROW margin
Vote RED = BEAR wins OR LOW conviction
```

---

### AGENT 5 — RISK MANAGER
**File:** `railway_app/agents/risk_manager.py`
**Model:** `deepseek/deepseek-chat`
**Temperature:** 0.0
**Note:** Hard rules checked in Python FIRST, AI confirms second

**Python Hard Rules (non-negotiable):**
```python
HARD_RULES = {
    "max_lot_size": 0.01,              # ABSOLUTE for $20 account
    "max_risk_pct": 1.0,               # 1% per trade = $0.20
    "min_rr_ratio": 2.0,               # Minimum 1:2
    "max_open_trades": 2,              # Never more than 2 at once
    "max_daily_loss_pct": 3.0,         # $0.60 daily stop — shutdown
    "no_trade_mins_before_news": 30,   # 30 min blackout before red news
    "no_trade_asian_session": True,    # 00:00-07:00 GMT
    "no_trade_gap_session": True,      # 12:00-13:00 GMT
    "min_green_votes": 4,              # Need 4/5 agents GREEN
    "min_confluence": 4,               # Technical confluence minimum
    "min_probability": 60,             # Quant score minimum
}
```

**System Prompt:**
```
You are the Risk Manager and final gatekeeper.
You protect the account above everything else.
A missed trade is fine. A blown account is not.

TRADE PROPOSAL: {trade_proposal}
PYTHON RULES RESULT: {hard_rules_result}
ACCOUNT STATE: {account_state}
ALL AGENT VOTES: {all_votes}

If Python hard rules already REJECTED this trade → confirm REJECTED.
If Python hard rules PASSED → do a final sanity check:
- Does anything feel wrong that the rules didn't catch?
- Is there unusual market context that increases risk?
- Is the setup rushed or forced?

Respond ONLY in valid JSON:
{
  "hard_rules_passed": true,
  "failed_rules": [],
  "sanity_check_passed": true,
  "sanity_concerns": [],
  "risk_assessment": "APPROVED|REJECTED",
  "rejection_reason": null,
  "approved_lot_size": 0.00,
  "approved_risk_usd": 0.00,
  "approved_entry": 0.00,
  "approved_sl": 0.00,
  "approved_tp1": 0.00,
  "approved_tp2": 0.00,
  "risk_notes": "any important risk context",
  "agent": "RISK_MANAGER",
  "vote": "GREEN|RED"
}

Only GREEN if APPROVED. RED if any concern. No exceptions.
```

---

### AGENT 6 — FINAL EXECUTOR
**File:** `railway_app/agents/final_executor.py`
**Model:** `anthropic/claude-opus-4-6`
**Temperature:** 0.1

**System Prompt:**
```
You are the Senior Portfolio Manager. Final decision maker.
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
{
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
  "trade_management": {
    "move_sl_to_be_after": "TP1 hit",
    "trail_tp2_by_pips": 15,
    "close_if_session_ends": true,
    "close_before_news": true
  },
  "monitor_during_trade": ["item1", "item2"],
  "agent_consensus": {
    "macro_scout": "GREEN|YELLOW|RED",
    "technical_analyst": "GREEN|YELLOW|RED",
    "quant_reasoner": "GREEN|YELLOW|RED",
    "bull_bear_debate": "GREEN|YELLOW|RED",
    "risk_manager": "GREEN|RED",
    "green_count": 0
  },
  "confidence_score": 0,
  "wait_reason": null,
  "abort_reason": null,
  "trade_narrative": "Full explanation paragraph",
  "agent": "FINAL_EXECUTOR",
  "timestamp": "ISO8601"
}
```

---

## 🧠 SUPABASE MEMORY SYSTEM

**File:** `railway_app/memory/supabase_memory.py`

```python
"""
Memory functions that inject learning into each agent.
Called before every agent runs. Makes agents smarter over time.
"""

async def get_agent_memory(agent_name: str, supabase) -> str:
    """
    Pull last 30 decisions for this agent.
    Calculate accuracy. Find patterns in failures.
    Return as formatted string injected into agent prompt.
    """
    # Get recent performance
    perf = supabase.table("agent_performance")\
        .select("*, trade_outcomes(*)")\
        .eq("agent_name", agent_name)\
        .order("created_at", desc=True)\
        .limit(30)\
        .execute()

    if not perf.data:
        return "No performance history yet. This is an early session."

    total = len(perf.data)
    correct = sum(1 for p in perf.data if p.get("was_correct"))
    accuracy = (correct / total * 100) if total > 0 else 0

    # Find patterns in failures
    failures = [p for p in perf.data if not p.get("was_correct")]
    wins = [p for p in perf.data if p.get("was_correct")]

    return f"""
YOUR PERFORMANCE MEMORY ({agent_name}):
- Last {total} decisions: {accuracy:.1f}% accuracy
- Correct calls: {correct}/{total}
- Recent failures: {len(failures)} in last 30 sessions

LEARN FROM YOUR FAILURES:
{format_patterns(failures, "FAILURE")}

LEARN FROM YOUR WINS:
{format_patterns(wins, "WIN")}

USE THIS: Adjust your confidence based on current conditions
vs conditions where you historically failed.
"""

async def get_system_memory(supabase) -> dict:
    """
    Pull overall system performance for Final Executor.
    """
    # Last 30 trade outcomes
    outcomes = supabase.table("trade_outcomes")\
        .select("*")\
        .order("created_at", desc=True)\
        .limit(30)\
        .execute()

    # Best performing patterns
    winning = supabase.table("market_patterns")\
        .select("*")\
        .gte("win_rate", 65)\
        .gte("sample_size", 3)\
        .order("win_rate", desc=True)\
        .limit(5)\
        .execute()

    # Patterns to avoid
    losing = supabase.table("market_patterns")\
        .select("*")\
        .lte("win_rate", 40)\
        .gte("sample_size", 3)\
        .order("win_rate")\
        .limit(5)\
        .execute()

    return {
        "recent_outcomes": outcomes.data,
        "winning_patterns": winning.data,
        "losing_patterns": losing.data
    }

async def log_signal(signal_data: dict, supabase) -> str:
    """Log the trade signal to Supabase. Returns signal ID."""
    result = supabase.table("trade_signals")\
        .insert(signal_data)\
        .execute()
    return result.data[0]["id"]

async def log_agent_votes(signal_id: str, all_outputs: dict, supabase):
    """Log each agent's vote for accuracy tracking later."""
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
        rows.append({
            "signal_id": signal_id,
            "agent_name": name,
            "vote": output.get("vote", "UNKNOWN"),
            "reasoning_summary": output.get("summary") or
                                 output.get("debate_verdict") or
                                 output.get("calculation_notes", "")[:200]
        })
    supabase.table("agent_performance").insert(rows).execute()

async def update_outcome(signal_id: str, outcome_data: dict, supabase):
    """
    Called by home PC after trade closes.
    Updates outcome and marks agent votes as correct/incorrect.
    """
    # Log the outcome
    supabase.table("trade_outcomes")\
        .insert({"signal_id": signal_id, **outcome_data})\
        .execute()

    # Mark each agent vote as correct or incorrect
    was_win = outcome_data["outcome"] == "WIN"
    supabase.table("agent_performance")\
        .update({"was_correct": was_win, "outcome": outcome_data["outcome"]})\
        .eq("signal_id", signal_id)\
        .execute()

    # Update pattern memory
    await update_pattern_memory(signal_id, outcome_data, supabase)
```

---

## 🚂 RAILWAY APP — main.py

```python
"""
GOLD SESSION SNIPER — Railway Orchestrator
Runs on cron schedule. Fires all agents. Logs to Supabase.
Sends Telegram alert. Exits cleanly.
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from supabase import create_client
import os
from dotenv import load_dotenv

load_dotenv()

from agents.macro_scout import run_macro_scout
from agents.technical_analyst import run_technical_analyst
from agents.quant_reasoner import run_quant_reasoner
from agents.bull_bear_debate import run_bull_bear_debate
from agents.risk_manager import run_risk_manager
from agents.final_executor import run_final_executor
from memory.supabase_memory import (
    get_agent_memory, get_system_memory,
    log_signal, log_agent_votes
)
from utils.market_data import fetch_market_data
from utils.telegram_alerts import send_signal_alert, send_error_alert
from utils.session_guard import get_current_session, is_valid_trading_time

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY")
)

async def run_gold_sniper():
    start_time = datetime.now(timezone.utc)
    print(f"\n{'='*60}")
    print(f"🏆 GOLD SESSION SNIPER v2.0")
    print(f"⏰ {start_time.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}")

    # 1. CHECK SESSION VALIDITY
    session = get_current_session()
    if not is_valid_trading_time():
        print(f"⏸️  Outside trading hours ({session}). Exiting.")
        sys.exit(0)
    print(f"✅ Session: {session}")

    # 2. FETCH LIVE MARKET DATA
    print("📊 Fetching XAUUSD market data...")
    try:
        market_data = await fetch_market_data()
        print(f"   Price: ${market_data['current_price']}")
        print(f"   ATR:   {market_data['indicators']['atr_14']}")
        print(f"   Asian: {market_data['asian_range']['high']} / "
              f"{market_data['asian_range']['low']}")
    except Exception as e:
        await send_error_alert(f"Market data failed: {e}")
        sys.exit(1)

    # 3. FETCH AGENT MEMORIES FROM SUPABASE
    print("🧠 Loading agent memories from Supabase...")
    memories = {}
    for agent in ["MACRO_SCOUT", "TECHNICAL_ANALYST", "QUANT_REASONER",
                  "BULL_BEAR_DEBATE", "RISK_MANAGER"]:
        memories[agent] = await get_agent_memory(agent, supabase)
    system_memory = await get_system_memory(supabase)

    # 4. RUN AGENTS 1, 2, 3 IN PARALLEL
    print("🤖 Running parallel analysis agents...")
    try:
        macro, technical, quant = await asyncio.gather(
            run_macro_scout(market_data, memories["MACRO_SCOUT"]),
            run_technical_analyst(market_data, memories["TECHNICAL_ANALYST"]),
            run_quant_reasoner(market_data, memories["QUANT_REASONER"]),
        )
        print(f"   Macro:     {macro.get('vote')} — {macro.get('bias')}")
        print(f"   Technical: {technical.get('vote')} — "
              f"Grade {technical.get('setup_grade')}")
        print(f"   Quant:     {quant.get('vote')} — "
              f"Probability {quant.get('probability_score')}%")
    except Exception as e:
        await send_error_alert(f"Agent 1-3 failed: {e}")
        sys.exit(1)

    # 5. BULL vs BEAR DEBATE
    print("⚔️  Running Bull vs Bear debate...")
    try:
        debate = await run_bull_bear_debate(
            market_data, macro, technical, quant,
            memories["BULL_BEAR_DEBATE"]
        )
        print(f"   Debate:    {debate.get('vote')} — "
              f"{debate.get('winner')} wins ({debate.get('conviction')})")
    except Exception as e:
        await send_error_alert(f"Debate agent failed: {e}")
        debate = {"vote": "YELLOW", "winner": "DRAW",
                  "conviction": "LOW", "agent": "BULL_BEAR_DEBATE"}

    # 6. RISK MANAGER
    print("🛡️  Risk Manager evaluating...")
    account_state = {
        "balance": float(os.getenv("ACCOUNT_BALANCE", 20.00)),
        "session": session,
        "risk_pct": float(os.getenv("RISK_PCT", 1.0)),
        "max_lot": float(os.getenv("MAX_LOT", 0.01)),
    }
    all_votes = [macro, technical, quant, debate]
    green_count = sum(1 for v in all_votes if v.get("vote") == "GREEN")

    risk = await run_risk_manager(
        market_data, all_votes, green_count,
        account_state, memories["RISK_MANAGER"]
    )
    print(f"   Risk:      {risk.get('vote')} — "
          f"{risk.get('risk_assessment')}")
    if risk.get("rejection_reason"):
        print(f"   Reason:    {risk.get('rejection_reason')}")

    # 7. FINAL EXECUTOR
    print("🎯 Final Executor synthesizing...")
    all_outputs = {
        "macro_scout": macro,
        "technical_analyst": technical,
        "quant_reasoner": quant,
        "bull_bear_debate": debate,
        "risk_manager": risk,
    }
    final = await run_final_executor(
        all_outputs, system_memory, account_state
    )

    # 8. LOG TO SUPABASE
    print("💾 Logging to Supabase...")
    signal_data = {
        "session": session,
        "decision": final.get("decision"),
        "direction": final.get("direction"),
        "entry_price": final.get("entry_price"),
        "stop_loss": final.get("stop_loss"),
        "take_profit_1": final.get("take_profit_1"),
        "take_profit_2": final.get("take_profit_2"),
        "lot_size": final.get("lot_size"),
        "risk_usd": final.get("risk_usd"),
        "rr_ratio": final.get("rr_tp1"),
        "confidence_score": final.get("confidence_score"),
        "green_votes": green_count + (1 if risk.get("vote") == "GREEN" else 0),
        "agent_votes": all_outputs,
        "macro_bias": macro.get("bias"),
        "technical_grade": technical.get("setup_grade"),
        "asian_range_high": market_data["asian_range"]["high"],
        "asian_range_low": market_data["asian_range"]["low"],
        "executed": False,
    }
    signal_id = await log_signal(signal_data, supabase)
    await log_agent_votes(signal_id, all_outputs, supabase)
    print(f"   Signal ID: {signal_id}")

    # 9. SEND TELEGRAM ALERT
    print("📱 Sending Telegram alert...")
    await send_signal_alert(final, signal_id, green_count, session)

    # 10. PRINT TERMINAL SUMMARY
    elapsed = (datetime.now(timezone.utc) - start_time).seconds
    print(f"\n{'='*60}")
    print(f"📋 FINAL DECISION")
    print(f"{'='*60}")
    print(f"Decision:    {final.get('decision')}")
    print(f"Direction:   {final.get('direction')}")
    print(f"Entry:       ${final.get('entry_price', 'N/A')}")
    print(f"Stop Loss:   ${final.get('stop_loss', 'N/A')}")
    print(f"TP1:         ${final.get('take_profit_1', 'N/A')} "
          f"(R:R {final.get('rr_tp1', 'N/A')})")
    print(f"TP2:         ${final.get('take_profit_2', 'N/A')} "
          f"(R:R {final.get('rr_tp2', 'N/A')})")
    print(f"Lot Size:    {final.get('lot_size', 'N/A')}")
    print(f"Risk:        ${final.get('risk_usd', 'N/A')}")
    print(f"Confidence:  {final.get('confidence_score', 'N/A')}%")
    print(f"Green Votes: {green_count + (1 if risk.get('vote') == 'GREEN' else 0)}/6")
    print(f"Signal ID:   {signal_id}")
    print(f"Runtime:     {elapsed}s")
    print(f"{'='*60}\n")

    # IMPORTANT: Exit cleanly for Railway cron
    sys.exit(0)

if __name__ == "__main__":
    asyncio.run(run_gold_sniper())
```

---

## 🏠 HOME PC — mt5_executor.py (Windows Only)

```python
"""
MT5 EXECUTOR — Runs on your Home PC (Windows 24/7)
Watches Supabase for new EXECUTE signals.
Places trades on Deriv MT5 automatically.
Reports outcomes back to Supabase.
"""

import MetaTrader5 as mt5
import asyncio
import json
import os
import time
from supabase import create_client
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY")
)

# ================================================================
# MT5 CONNECTION
# ================================================================
def connect_mt5():
    if not mt5.initialize():
        print(f"❌ MT5 initialize failed: {mt5.last_error()}")
        return False

    login = int(os.getenv("MT5_LOGIN"))
    password = os.getenv("MT5_PASSWORD")
    server = os.getenv("MT5_SERVER", "Deriv-Server")

    authorized = mt5.login(login, password=password, server=server)
    if not authorized:
        print(f"❌ MT5 login failed: {mt5.last_error()}")
        return False

    info = mt5.account_info()
    print(f"✅ MT5 Connected: {info.name} | Balance: ${info.balance}")
    return True

# ================================================================
# PLACE TRADE
# ================================================================
def place_trade(signal: dict) -> dict:
    symbol = "XAUUSD"
    direction = signal["direction"]
    lot = signal["lot_size"]
    sl = signal["stop_loss"]
    tp1 = signal["take_profit_1"]

    # Get current price
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return {"success": False, "error": "Could not get tick data"}

    # Determine order type
    if direction == "LONG":
        order_type = mt5.ORDER_TYPE_BUY
        price = tick.ask
    else:
        order_type = mt5.ORDER_TYPE_SELL
        price = tick.bid

    # Validate entry vs signal (max 50 pip slippage allowed)
    signal_entry = signal["entry_price"]
    slippage_pips = abs(price - signal_entry) * 10
    if slippage_pips > 50:
        return {
            "success": False,
            "error": f"Price slipped too far: signal={signal_entry}, "
                     f"current={price}, slippage={slippage_pips:.1f} pips"
        }

    # Build order request
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": float(lot),
        "type": order_type,
        "price": price,
        "sl": float(sl),
        "tp": float(tp1),
        "deviation": 20,
        "magic": 20260101,
        "comment": f"GoldSniper|{signal['id'][:8]}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)

    if result.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"✅ TRADE PLACED: Ticket #{result.order}")
        print(f"   {direction} {lot} lots XAUUSD @ {price}")
        print(f"   SL: {sl} | TP1: {tp1}")
        return {
            "success": True,
            "ticket": result.order,
            "execution_price": price,
            "execution_time": datetime.now(timezone.utc).isoformat()
        }
    else:
        error = f"Order failed: retcode={result.retcode}, comment={result.comment}"
        print(f"❌ {error}")
        return {"success": False, "error": error}

# ================================================================
# MONITOR OPEN TRADES
# ================================================================
def check_trade_outcome(ticket: int, signal_id: str, signal: dict):
    """Check if a trade has closed and log the outcome."""
    # Check open positions
    positions = mt5.positions_get(ticket=ticket)
    if positions:
        return None  # Still open

    # Check history (closed trade)
    from_date = datetime(2020, 1, 1, tzinfo=timezone.utc)
    to_date = datetime.now(timezone.utc)
    history = mt5.history_deals_get(from_date, to_date)

    if not history:
        return None

    # Find the closing deal for this ticket
    for deal in history:
        if deal.order == ticket and deal.entry == mt5.DEAL_ENTRY_OUT:
            profit = deal.profit
            exit_price = deal.price
            entry_price = signal["entry_price"]
            pips = abs(exit_price - entry_price) * 10

            outcome = "WIN" if profit > 0 else "LOSS" if profit < 0 else "BREAKEVEN"

            # Determine exit reason
            sl = signal["stop_loss"]
            tp1 = signal["take_profit_1"]
            direction = signal["direction"]

            if direction == "LONG":
                if exit_price >= tp1 - 0.5:
                    exit_reason = "TP1"
                elif exit_price <= sl + 0.5:
                    exit_reason = "SL"
                else:
                    exit_reason = "MANUAL"
            else:
                if exit_price <= tp1 + 0.5:
                    exit_reason = "TP1"
                elif exit_price >= sl - 0.5:
                    exit_reason = "SL"
                else:
                    exit_reason = "MANUAL"

            return {
                "signal_id": signal_id,
                "outcome": outcome,
                "exit_reason": exit_reason,
                "entry_price": float(entry_price),
                "exit_price": float(exit_price),
                "profit_usd": float(profit),
                "profit_pips": float(pips),
                "account_balance_after": float(mt5.account_info().balance),
            }
    return None

# ================================================================
# MAIN EXECUTION LOOP
# ================================================================
def main():
    print("🏠 MT5 EXECUTOR — Home PC")
    print("Connecting to MT5...")

    if not connect_mt5():
        print("❌ Failed to connect MT5. Retrying in 60s...")
        time.sleep(60)
        return

    print("👁️  Watching Supabase for signals...\n")

    # Track open trades: {signal_id: ticket_number}
    open_trades = {}

    while True:
        try:
            # 1. CHECK FOR NEW EXECUTE SIGNALS
            new_signals = supabase.table("trade_signals")\
                .select("*")\
                .in_("decision", ["EXECUTE_BUY", "EXECUTE_SELL"])\
                .eq("executed", False)\
                .is_("execution_error", "null")\
                .execute()

            for signal in new_signals.data:
                signal_id = signal["id"]
                print(f"\n🚨 NEW SIGNAL: {signal['decision']} @ {signal['entry_price']}")

                # Place the trade
                result = place_trade(signal)

                if result["success"]:
                    # Update Supabase — mark executed
                    supabase.table("trade_signals").update({
                        "executed": True,
                        "execution_price": result["execution_price"],
                        "execution_time": result["execution_time"],
                        "mt5_ticket": result["ticket"],
                    }).eq("id", signal_id).execute()

                    # Track for monitoring
                    open_trades[signal_id] = {
                        "ticket": result["ticket"],
                        "signal": signal
                    }
                    print(f"✅ Logged to Supabase. Monitoring trade...")

                else:
                    # Log the error
                    supabase.table("trade_signals").update({
                        "execution_error": result["error"]
                    }).eq("id", signal_id).execute()
                    print(f"❌ Execution failed: {result['error']}")

            # 2. MONITOR OPEN TRADES FOR OUTCOMES
            closed_trades = []
            for signal_id, trade_info in open_trades.items():
                outcome = check_trade_outcome(
                    trade_info["ticket"],
                    signal_id,
                    trade_info["signal"]
                )
                if outcome:
                    print(f"\n{'='*40}")
                    print(f"📊 TRADE CLOSED: {outcome['outcome']}")
                    print(f"   Exit reason: {outcome['exit_reason']}")
                    print(f"   P&L: ${outcome['profit_usd']:.2f}")
                    print(f"   Balance: ${outcome['account_balance_after']:.2f}")
                    print(f"{'='*40}\n")

                    # Log outcome to Supabase
                    supabase.table("trade_outcomes")\
                        .insert(outcome)\
                        .execute()

                    # Update environment balance
                    new_balance = outcome["account_balance_after"]
                    os.environ["ACCOUNT_BALANCE"] = str(new_balance)

                    closed_trades.append(signal_id)

            # Clean up closed trades
            for sid in closed_trades:
                del open_trades[sid]

            # 3. KEEP MT5 CONNECTION ALIVE
            if not mt5.terminal_info():
                print("⚠️  MT5 disconnected. Reconnecting...")
                connect_mt5()

            time.sleep(5)  # Check every 5 seconds

        except KeyboardInterrupt:
            print("\n🛑 Executor stopped by user.")
            mt5.shutdown()
            break
        except Exception as e:
            print(f"⚠️  Executor error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
```

---

## 📱 TELEGRAM ALERTS — utils/telegram_alerts.py

```python
"""
Sends formatted trade alerts to your Telegram.
"""

import httpx
import os

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

async def send_signal_alert(final: dict, signal_id: str,
                             green_votes: int, session: str):
    decision = final.get("decision", "UNKNOWN")

    if decision in ["EXECUTE_BUY", "EXECUTE_SELL"]:
        direction_emoji = "📈" if decision == "EXECUTE_BUY" else "📉"
        action = "BUY" if decision == "EXECUTE_BUY" else "SELL"

        message = f"""
{direction_emoji} *GOLD SESSION SNIPER*
━━━━━━━━━━━━━━━━━━━━
*Decision:* {action} XAUUSD ✅
*Session:* {session}
*Confidence:* {final.get('confidence_score')}%
*Agents:* {green_votes}/6 GREEN

📊 *TRADE LEVELS*
Entry:    `${final.get('entry_price')}`
Stop:     `${final.get('stop_loss')}`
TP1:      `${final.get('take_profit_1')}` _(R:R {final.get('rr_tp1')})_
TP2:      `${final.get('take_profit_2')}` _(R:R {final.get('rr_tp2')})_
Lot Size: `{final.get('lot_size')}`
Risk:     `${final.get('risk_usd')}`

⚡ *MT5 EXECUTING NOW...*
ID: `{signal_id[:8]}`
"""
    elif decision == "WAIT":
        message = f"""
⏸️ *GOLD SESSION SNIPER*
━━━━━━━━━━━━━━━━━━━━
*Decision:* WAIT — No trade
*Session:* {session}
*Reason:* {final.get('wait_reason', 'Setup not ready')}
*Green Votes:* {green_votes}/6

_Next analysis at next session._
"""
    else:
        message = f"""
🚫 *GOLD SESSION SNIPER*
━━━━━━━━━━━━━━━━━━━━
*Decision:* ABORT
*Session:* {session}
*Reason:* {final.get('abort_reason', 'Risk rules triggered')}
"""

    await _send_message(message)

async def send_error_alert(error: str):
    await _send_message(f"⚠️ *SYSTEM ERROR*\n`{error}`")

async def _send_message(text: str):
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{BASE_URL}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": "Markdown"
            }
        )
```

---

## 🚂 RAILWAY DEPLOYMENT FILES

### railway.json
```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "NIXPACKS"
  },
  "deploy": {
    "startCommand": "python railway_app/main.py",
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 3
  }
}
```

### Procfile
```
worker: python railway_app/main.py
```

### requirements.txt (Railway — Linux)
```
httpx>=0.27.0
supabase>=2.4.0
python-dotenv>=1.0.0
yfinance>=0.2.40
pandas>=2.2.0
numpy>=1.26.0
websockets>=12.0
rich>=13.7.0
```

### home_pc/requirements_pc.txt (Windows only)
```
MetaTrader5>=5.0.45
supabase>=2.4.0
python-dotenv>=1.0.0
```

---

## ⏰ RAILWAY CRON SCHEDULES

In Railway Dashboard → Your Service → Settings → Cron Schedule:

```
London Open:    45 7 * * 1-5     (07:45 GMT, Mon-Fri)
NY Open:        45 12 * * 1-5    (12:45 GMT, Mon-Fri)
```

**IMPORTANT:** Each run must exit with `sys.exit(0)` when done.
Railway skips the next run if previous is still active.

---

## 🔧 SETUP CHECKLIST

### Railway Setup:
```
☐ Push code to GitHub (private repo)
☐ Connect Railway to GitHub repo
☐ Add all environment variables in Railway dashboard
☐ Set cron schedule for London (45 7 * * 1-5)
☐ Set cron schedule for NY (45 12 * * 1-5)
☐ Deploy and verify first run in logs
```

### Supabase Setup:
```
☐ Create new Supabase project (free tier)
☐ Run all SQL from schema section above
☐ Enable Realtime on trade_signals table
☐ Copy SUPABASE_URL and service role key to .env
```

### Telegram Setup:
```
☐ Message @BotFather on Telegram
☐ /newbot → follow prompts → copy token
☐ Message your bot once
☐ Visit: api.telegram.org/bot{TOKEN}/getUpdates
☐ Copy your chat_id from the response
☐ Add both to .env
```

### Home PC Setup:
```
☐ Download Deriv MT5 from deriv.com
☐ Login with your Deriv MT5 credentials
☐ Install Python 3.11+ from python.org
☐ pip install -r home_pc/requirements_pc.txt
☐ Add .env file to home_pc/ folder
☐ Run: python home_pc/mt5_executor.py
☐ Set Windows to never sleep (Power settings)
☐ Set Python script to run on startup (Task Scheduler)
```

---

## 💰 $20 ACCOUNT RULES — ABSOLUTE LAW

```
1.  MAX LOT:         0.01 — NEVER exceed this
2.  RISK PER TRADE:  $0.20 (1% of $20)
3.  DAILY STOP:      $0.60 (3%) — system shuts down
4.  MIN R:R:         1:2 — no exceptions
5.  MAX TRADES/DAY:  2
6.  NO TRADES:       Asian session, gap session, 30min before news
7.  NEED 4/6 GREEN:  Otherwise WAIT
8.  MOVE SL:         To breakeven immediately after TP1 hit
9.  NO REVENGE:      After daily stop hit, executor refuses new signals
10. COMPOUND RULE:   At $30 → 0.02 lots. At $50 → 0.03. At $100 → 0.05.
```

---

## 📈 HOW THE SYSTEM GETS SMARTER

```
DAY 1:   Agents have no memory. Rely on analysis only.
DAY 5:   Agents see first patterns. Begin adjusting confidence.
DAY 10:  Agent accuracy scores visible. Weak agents self-correct.
DAY 20:  Winning patterns identified. System avoids losers.
DAY 30:  System knows YOUR market deeply.
         Knows which sessions work best.
         Knows which macro conditions to avoid.
         Knows which agent votes to weight more.
DAY 60:  System is genuinely smarter than most retail traders.
DAY 90:  You have a real, data-driven edge.
```

---

## 🛠️ BUILD ORDER FOR CLAUDE CODE

Build files in this exact order:

```
1.  .env + .gitignore
2.  config.py
3.  requirements.txt + railway.json + Procfile
4.  utils/openrouter.py
5.  utils/market_data.py
6.  utils/session_guard.py
7.  utils/telegram_alerts.py
8.  memory/supabase_memory.py
9.  agents/macro_scout.py
10. agents/technical_analyst.py
11. agents/quant_reasoner.py
12. agents/bull_bear_debate.py
13. agents/risk_manager.py
14. agents/final_executor.py
15. railway_app/main.py
16. home_pc/mt5_executor.py
17. home_pc/trade_monitor.py
18. home_pc/setup_mt5.py
19. Test each agent individually
20. Integration test with paper trading first
```

---

## ⚠️ FINAL NOTES

- ALWAYS test on Deriv DEMO account first minimum 2 weeks
- Only switch to live $20 account after demo shows consistent results
- The system is a tool. Markets can be unpredictable. Never risk money you cannot afford to lose.
- Update ACCOUNT_BALANCE in Railway environment variables weekly
- Check Railway logs daily for the first 2 weeks
- Monitor home PC uptime — if PC sleeps, trades won't execute

---

*Gold Session Sniper v2.0 — Built with Claude Code*
*6 AI Agents | Supabase Memory | MT5 Auto-Execution | Railway 24/7*
*Not financial advice. Trade responsibly.*
