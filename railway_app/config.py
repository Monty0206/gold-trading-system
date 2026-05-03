import os

from dotenv import load_dotenv

load_dotenv()

ACCOUNT_BALANCE = float(os.getenv("ACCOUNT_BALANCE", "20.00"))
RISK_PCT = float(os.getenv("RISK_PCT", "1.0"))
MAX_LOT = float(os.getenv("MAX_LOT", "0.01"))

HARD_RULES = {
    "max_lot_size": 0.01,
    "max_risk_pct": 1.0,
    "min_rr_ratio": 2.0,
    "max_open_trades": 2,
    "max_daily_loss_pct": 3.0,
    "no_trade_mins_before_news": 30,
    "no_trade_asian_session": True,
    "no_trade_gap_session": True,
    "min_green_votes": 4,
    "min_confluence": 4,
    "min_probability": 60,
    "max_consecutive_losses": 3,         # kill switch after 3 consecutive losses
    "no_trade_friday_after_hm": 14 * 60, # 14:00 UTC Friday cutoff (weekend gap risk)
}

# All OpenRouter model slugs in one place — agents import MODEL from here.
# Never hard-code model strings in agent files.
MODELS = {
    "macro_scout":        "perplexity/sonar-reasoning",   # was claude-sonnet-4-6 — now has live web
    "technical_analyst":  "anthropic/claude-opus-4-5",    # keep Opus for hardest reasoning
    "quant_reasoner":     None,                            # LLM removed — pure Python now
    "bull_advocate":      "openai/gpt-4o",                 # heterogeneous debate
    "bear_advocate":      "anthropic/claude-sonnet-4-5",   # best at risk identification
    "debate_adjudicator": "google/gemini-2.5-pro",        # neutral arbitration
    "risk_manager":       None,                            # LLM removed — pure Python guardrails
    "final_executor":     "anthropic/claude-sonnet-4-5",  # downgraded from Opus — mechanical synthesis
    "news_sentiment":     "perplexity/sonar-pro",         # NEW agent
    "pattern_history":    "anthropic/claude-sonnet-4-5",  # NEW agent
}

# Volatility regime thresholds (ATR-based, in pips)
REGIME_LOW_VOL_ATR    = 8.0
REGIME_HIGH_VOL_ATR   = 20.0
REGIME_EXTREME_ATR    = 35.0

# Minimum confluence by regime
REGIME_CONFLUENCE_MIN = {"LOW": 4, "NORMAL": 4, "HIGH": 5, "EXTREME": 6}

# Lot size multiplier by regime
REGIME_LOT_MULTIPLIER = {"LOW": 1.0, "NORMAL": 1.0, "HIGH": 0.75, "EXTREME": 0.5}

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

MT5_LOGIN = os.getenv("MT5_LOGIN")
MT5_PASSWORD = os.getenv("MT5_PASSWORD")
MT5_SERVER = os.getenv("MT5_SERVER", "Deriv-Server")

# Optional: FMP API key for real economic calendar (free tier: 250 calls/day).
# Register at: https://financialmodelingprep.com/register
# Add FMP_API_KEY to Railway env vars to enable real news events.
# Without it, agents receive an empty calendar (LLM guesses news — less reliable).
FMP_API_KEY = os.getenv("FMP_API_KEY", "")
