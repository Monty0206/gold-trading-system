import os

import httpx
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


async def send_signal_alert(
    final: dict, signal_id: str, green_votes: int, session: str
) -> None:
    decision = final.get("decision", "UNKNOWN")

    if decision in ("EXECUTE_BUY", "EXECUTE_SELL"):
        direction_emoji = "📈" if decision == "EXECUTE_BUY" else "📉"
        action = "BUY" if decision == "EXECUTE_BUY" else "SELL"
        message = (
            f"{direction_emoji} *GOLD SESSION SNIPER*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"*Decision:* {action} XAUUSD ✅\n"
            f"*Session:* {session}\n"
            f"*Confidence:* {final.get('confidence_score')}%\n"
            f"*Agents:* {green_votes}/6 GREEN\n\n"
            f"📊 *TRADE LEVELS*\n"
            f"Entry:    `${final.get('entry_price')}`\n"
            f"Stop:     `${final.get('stop_loss')}`\n"
            f"TP1:      `${final.get('take_profit_1')}` _(R:R {final.get('rr_tp1')})_\n"
            f"TP2:      `${final.get('take_profit_2')}` _(R:R {final.get('rr_tp2')})_\n"
            f"Lot Size: `{final.get('lot_size')}`\n"
            f"Risk:     `${final.get('risk_usd')}`\n\n"
            f"⚡ *MT5 EXECUTING NOW...*\n"
            f"ID: `{str(signal_id)[:8]}`"
        )

    elif decision == "WAIT":
        message = (
            f"⏸️ *GOLD SESSION SNIPER*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"*Decision:* WAIT — No trade\n"
            f"*Session:* {session}\n"
            f"*Reason:* {final.get('wait_reason', 'Setup not ready')}\n"
            f"*Green Votes:* {green_votes}/6\n\n"
            f"_Next analysis at next session._"
        )

    else:
        message = (
            f"🚫 *GOLD SESSION SNIPER*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"*Decision:* ABORT\n"
            f"*Session:* {session}\n"
            f"*Reason:* {final.get('abort_reason', 'Risk rules triggered')}"
        )

    await _send_message(message)


async def send_error_alert(error: str) -> None:
    await _send_message(f"⚠️ *SYSTEM ERROR*\n`{error}`")


async def _send_message(text: str) -> None:
    if not BOT_TOKEN or not CHAT_ID:
        print(f"[Telegram] Token/ChatID not set — skipping alert.")
        return
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.post(
                f"{BASE_URL}/sendMessage",
                json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"},
            )
    except Exception as e:
        print(f"[Telegram] Failed to send message: {e}")
