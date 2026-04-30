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
}

MODELS = {
    "macro_scout": "anthropic/claude-sonnet-4-6",
    "technical_analyst": "anthropic/claude-opus-4-7",
    "quant_reasoner": "deepseek/deepseek-r1",
    "bull_bear_debate": "google/gemini-2.5-pro",
    "risk_manager": "deepseek/deepseek-chat",
    "final_executor": "anthropic/claude-opus-4-7",
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
