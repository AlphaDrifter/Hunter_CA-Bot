import re
import asyncio
import os
import requests

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    Application,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

# =========================
# CONFIG
# =========================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or "PUT_YOUR_BOT_TOKEN_HERE"

DEX_BASE = "https://dexscreener.com/solana/"
JUP_BASE = "https://jup.ag/swap/SOL-"
GECKO_OHLCV = "https://api.geckoterminal.com/api/v2/networks/solana/tokens/"

BASE58_RE = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")

# =========================
# HELPERS
# =========================
def is_valid_solana_address(addr: str) -> bool:
    return 32 <= len(addr) <= 44


def fmt_usd(v):
    try:
        v = float(v)
        if v >= 1_000_000:
            return f"${v/1_000_000:.2f}M"
        if v >= 1_000:
            return f"${v/1_000:.2f}K"
        return f"${v:.2f}"
    except Exception:
        return "N/A"

def fmt_price(v):
    try:
        v = float(v)
        if v >= 1:
            return f"${v:,.4f}"
        if v >= 0.01:
            return f"${v:,.4f}"
        if v >= 0.0001:
            return f"${v:,.6f}"
        return f"${v:,.8f}"
    except Exception:
        return "N/A"


def fetch_ath_price_geckoterminal(ca: str, timeframe: str = "day", limit: int = 1000):
    """
    Retourne l'ATH PRICE (USD) approx en prenant le max des highs sur OHLCV.
    timeframe: 'day' (reco), 'hour', etc.
    """
    url = f"{GECKO_OHLCV}{ca}/ohlcv/{timeframe}?aggregate=1&limit={limit}"
    try:
        r = requests.get(url, timeout=10)
        data = r.json() if r.ok else None
        if not data:
            return None

        # Structure GeckoTerminal généralement:
        # data["data"]["attributes"]["ohlcv_list"] = [[ts, open, high, low, close, volume], ...]
        ohlcv_list = (
            (data.get("data") or {}).get("attributes", {}) or {}
        ).get("ohlcv_list")

        if not ohlcv_list:
            return None

        ath = None
        for c in ohlcv_list:
            if not isinstance(c, list) or len(c) < 3:
                continue
            high = c[2]
            try:
                high = float(high)
            except Exception:
                continue
            ath = high if ath is None else max(ath, high)

        return ath
    except Exception:
        return None

def fetch_dexscreener_best_pair(ca: str):
    url = f"https://api.dexscreener.com/latest/dex/tokens/{ca}"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        pairs = data.get("pairs") or []
        if not pairs:
            return None
        return sorted(
            pairs,
            key=lambda p: (p.get("liquidity", {}) or {}).get("usd", 0),
            reverse=True
        )[0]
    except Exception:
        return None


# =========================
# MAIN HANDLER
# =========================
async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    # Ignore ETH addresses
    if "0x" in text.lower():
        return

    for ca in BASE58_RE.findall(text):
        if not is_valid_solana_address(ca):
            continue

        pair = fetch_dexscreener_best_pair(ca)

        dex_url = f"{DEX_BASE}{ca}"
        jup_url = f"{JUP_BASE}{ca}"

        # =========================
        # Fallback if no Dex data
        # =========================
        if not pair:
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Dex", url=dex_url),
                    InlineKeyboardButton("Buy (Jupiter)", url=jup_url),
                ],
            ])
            
            await update.message.reply_text(
                f"🟢 SOL CA detected\n\nCA:\n`{ca}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )

            # 🔥 delete member message
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=update.effective_message.message_id
                )
            except Exception as e:
                print("Delete failed:", e)

            return

        # =========================
        # Parse pair infos
        # =========================
        base = pair.get("baseToken") or {}
        symbol = base.get("symbol") or "TOKEN"
        name = base.get("name") or ""

        image_url = (pair.get("info") or {}).get("imageUrl")

        liq = (pair.get("liquidity") or {}).get("usd")
        vol24 = (pair.get("volume") or {}).get("h24")
        chg24 = (pair.get("priceChange") or {}).get("h24")
        mc = pair.get("marketCap") or pair.get("fdv")  # fallback sur FDV si MC absent
                
        liq_txt = fmt_usd(liq)
        vol_txt = fmt_usd(vol24)
        mc_txt = fmt_usd(mc)
                
        try:
            chg_txt = f"{float(chg24):+.2f}%"
        except Exception:
            chg_txt = "N/A"

        caption = (
            f"🟢 <b>{symbol}</b> - <i>{name}</i>\n"
            f"<b>CA:</b> <code>{ca}</code>\n\n"
            f"💧 <b>Liquidity:</b> {liq_txt}\n"
            f"📈 <b>24h:</b> {chg_txt}\n"
            f"📊 <b>Vol 24h:</b> {vol_txt}\n"
            f"🏷️ <b>MC:</b> {mc_txt}\n"
            
        )
        
    dex_link = pair.get("url") or dex_url

    keyboard = InlineKeyboardMarkup([
           [
               InlineKeyboardButton("Dex", url=dex_link),
               InlineKeyboardButton("Buy (Jupiter)", url=jup_url),
           ],
    ])

    # =========================
    # SEND BOT MESSAGE
    # =========================
    if image_url:
     await update.message.reply_photo(
         photo=image_url,
         caption=caption,
         parse_mode=ParseMode.HTML,
         reply_markup=keyboard
      )
    else:
     await update.message.reply_text(
         caption,
         parse_mode=ParseMode.HTML,
         reply_markup=keyboard
      )

    # =========================
    # 🔥 DELETE MEMBER MESSAGE
    # =========================
    try:
     await context.bot.delete_message(
       chat_id=update.effective_chat.id,
       message_id=update.effective_message.message_id
      )
    except Exception as e:
        print("Delete failed:", e)

    return


# =========================
# MAIN
# =========================
def main():
    if not TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN not set")
        return

    asyncio.set_event_loop(asyncio.new_event_loop())

    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    print("🤖 Bot started (SOL ONLY)")
    app.run_polling()


from flask import Flask
import threading
import os

app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "Bot is running"

def run_bot():
    main()

if __name__ == "__main__":
    # lance le bot dans un thread
    threading.Thread(target=run_bot).start()

    # lance le serveur web pour Render
    app_flask.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
