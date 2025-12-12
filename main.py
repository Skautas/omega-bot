import os
import asyncio
import ccxt
import pandas as pd
import numpy as np
import time
import threading
import requests
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD
from ta.volatility import BollingerBands
from telegram import Bot

# === KONFIGŪRACIJA ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
MULTI_CHAT_IDS = [CHAT_ID]

bot = Bot(token=TELEGRAM_TOKEN) if TELEGRAM_TOKEN else None

# === TURTŲ SĄRAŠAS (tik Kraken) ===
ASSETS = [
    "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "DOGE/USD", "ADA/USD", 
    "ZEC/USD", "XLM/USD", "DOT/USD", "LINK/USD", "LTC/USD", "BCH/USD", "ICP/USD"
]

TIMEFRAME = "15m"

# === PAGALBINĖS FUNKCIJOS ===
def calculate_rsi(close, window=14):
    return RSIIndicator(close, window).rsi()

def calculate_macd(close):
    macd = MACD(close)
    return macd.macd(), macd.macd_signal()

def calculate_ema(close, window):
    return EMAIndicator(close, window).ema_indicator()

def calculate_sl_tp(current_price, signal_type, bb_low, bb_high, ema26_val):
    """Grąžina SL ir TP pagal signalo tipą"""
    if signal_type == "BUY":
        sl = max(bb_low, ema26_val * 0.995)
        tp = current_price + (current_price - sl) * 1.8
    elif signal_type == "SELL":
        sl = min(bb_high, ema26_val * 1.005)
        tp = current_price - (sl - current_price) * 1.8
    else:
        sl, tp = 0, 0
    return sl, tp

def calculate_confidence(symbol, df):
    close = df["close"]
    rsi = calculate_rsi(close)
    rsi_val = rsi.iloc[-1]
    current_price = close.iloc[-1]
    
    bb = BollingerBands(close)
    bb_low = bb.bollinger_lband().iloc[-1]
    bb_high = bb.bollinger_hband().iloc[-1]
    volume_ratio = df["volume"].iloc[-1] / df["volume"].rolling(20).mean().iloc[-1]
    
    score = 0
    signal_type = None

    if rsi_val < 40:
        signal_type = "BUY"
        score += 25
        if current_price <= bb_low:
            score += 20
        if volume_ratio > 1.5:
            score += 15

    elif rsi_val > 65:
        signal_type = "SELL"
        score += 25
        if current_price >= bb_high:
            score += 20
        if volume_ratio > 1.8:
            score += 15

    confidence = min(score, 100)
    return signal_type, confidence, rsi_val, bb_low, bb_high

# === SIUNTIMAS ===
async def send_alert(name, signal, price, sl, tp, confidence, rsi_val):
    if not bot:
        return
    for chat_id in MULTI_CHAT_IDS:
        try:
            emoji = "🟢" if signal == "BUY" else "🔴"
            rr = abs(tp - price) / abs(price - sl) if sl != price else 0
            msg = (
                f"{emoji} **{signal} SIGNAL (15m)**\n"
                f"🪙 {name}\n"
                f"💰 Įėjimas: {price:.4f} USD\n"
                f"🎯 TP: {tp:.4f} USD\n"
                f"🛑 SL: {sl:.4f} USD\n"
                f"📊 RR: {rr:.1f} | Tikimybė: {confidence:.1%}"
            )
            await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
            print(f"✅ Signalas: {name} {signal} @ {price:.4f}")
        except Exception as e:
            print(f"❌ Telegram klaida: {e}")

# === TIKRINIMAS ===
async def check_signals():
    print(f"\n🕒 Tikrinama: {pd.Timestamp.now()}")
    for symbol in ASSETS:
        try:
            exchange = ccxt.kraken()
            ohlcv = exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=100)
            if len(ohlcv) < 50:
                continue

            df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
            close = df["close"]
            
            signal, confidence, rsi_val, bb_low, bb_high = calculate_confidence(symbol, df)
            current_price = close.iloc[-1]
            asset_name = symbol.split("/")[0]
            ema26_val = calculate_ema(close, 26).iloc[-1]
            
            if signal and confidence >= 60:
                sl, tp = calculate_sl_tp(current_price, signal, bb_low, bb_high, ema26_val)
                await send_alert(asset_name, signal, current_price, sl, tp, confidence, rsi_val)
                
        except Exception as e:
            print(f"Klaida {symbol}: {e}")
            continue

# === SELF-PING ===
def keep_colab_alive():
    while True:
        try:
            requests.get("https://colab.research.google.com/")
        except:
            pass
        time.sleep(300)

threading.Thread(target=keep_colab_alive, daemon=True).start()

# === TESTAS ===
async def send_test():
    if bot:
        try:
            await bot.send_message(chat_id=CHAT_ID, text="✅ **OMEGA BOT VEIKIA!**", parse_mode="Markdown")
            print("✅ Testinis pranešimas išsiųstas!")
        except Exception as e:
            print(f"❌ Testo klaida: {e}")

# === PAGRINDINIS CIKLAS ===
async def main():
    await send_test()
    while True:
        await check_signals()
        await asyncio.sleep(600)  # Kas 10 min

if __name__ == "__main__":
    asyncio.run(main())
