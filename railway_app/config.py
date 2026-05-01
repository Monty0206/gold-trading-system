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
    "macro_scout":      "anthropic/claude-sonnet-4-6",
    "technical_analyst": "anthropic/claude-opus-4-6",
    "quant_reasoner":   "deepseek/deepseek-chat",   # V3: fast arithmetic, no slow R1 reasoning
    "bull_bear_debate": "google/gemini-2.5-pro",
    "risk_manager":     "deepseek/deepseek-chat",
    "final_executor":   "anthropic/claude-opus-4-6",
}

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
