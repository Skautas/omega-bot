import os
import asyncio
from telegram import Bot
import ccxt

# Konfigūracija iš aplinkos
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
KRAKEN_API_KEY = os.getenv("KRAKEN_API_KEY")
KRAKEN_SECRET = os.getenv("KRAKEN_SECRET")

# Telegram botas
bot = Bot(token=TELEGRAM_TOKEN) if TELEGRAM_TOKEN else None

# Kraken (spot – paprastesnis pradžiai)
kraken = ccxt.kraken({
    'apiKey': KRAKEN_API_KEY,
    'secret': KRAKEN_SECRET,
    'enableRateLimit': True,
})

async def send_signal():
    try:
        ticker = kraken.fetch_ticker('SOL/USD')
        price = ticker['last']
        msg = f"🟢 **Jūsų OMEGA botas veikia!**\n🪙 SOL/USD: ${price:.2f}"
        if bot:
            await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
            print("✅ Signalas išsiųstas į Telegram")
        else:
            print("❌ Telegram botas neįjungtas")
    except Exception as e:
        print(f"❌ Klaida: {e}")

if __name__ == "__main__":
    asyncio.run(send_signal())
