import os
import asyncio
import ccxt
import pandas as pd
import numpy as np
import time
import threading
import requests
from ta.momentum import RSIIndicator, WilliamsRIndicator
from ta.trend import EMAIndicator, MACD
from ta.volatility import BollingerBands, AverageTrueRange
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

def get_bias(rsi_val, macd_line, macd_signal, ema9, ema26, close):
    rsi_bias = "NEUTRAL"
    if rsi_val < 35 or rsi_val > 65:
        rsi_bias = "NEUTRAL"
    else:
        rsi_bias = "LONG" if rsi_val > 50 else "SHORT"
    
    macd_bias = "LONG" if macd_line.iloc[-1] > macd_signal.iloc[-1] else "SHORT"
    ema_bias = "LONG" if ema9.iloc[-1] > ema26.iloc[-1] else "SHORT"
    
    biases = [rsi_bias, macd_bias, ema_bias]
    long_count = biases.count("LONG")
    short_count = biases.count("SHORT")
    
    if long_count >= 2:
        return "LONG"
    elif short_count >= 2:
        return "SHORT"
    else:
        return "NEUTRAL"

def calculate_confidence(symbol, df, bias):
    close = df["close"]
    rsi = calculate_rsi(close)
    rsi_val = rsi.iloc[-1]
    current_price = close.iloc[-1]
    
    bb = BollingerBands(close)
    bb_low = bb.bollinger_lband().iloc[-1]
    bb_high = bb.bollinger_hband().iloc[-1]
    volume_ratio = df["volume"].iloc[-1] / df["volume"].rolling(20).mean().iloc[-1]
    
    score = 0
    signal_type = "HOLD"

    if rsi_val < 40:
        signal_type = "BUY"
        score += 25
        if current_price <= bb_low:
            score += 20
        if volume_ratio > 1.5:
            score += 15
        if rsi_val < 30:
            score += 10

    elif rsi_val > 65:
        signal_type = "SELL"
        williams_r = WilliamsRIndicator(df["high"], df["low"], close).williams_r().iloc[-1]
        if williams_r > -15:
            score += 15
        if volume_ratio > 1.8:
            score += 15
        if current_price >= bb_high:
            score += 20
        if rsi_val > 75:
            score += 10

    elif (rsi_val >= 40 and rsi_val < 45) or (rsi_val <= 65 and rsi_val > 60):
        score += 5

    confidence = min(score, 100)

    if confidence >= 60:
        fires = "🔥🔥🔥"
    elif confidence >= 40:
        fires = "🔥🔥"
    else:
        fires = "🔥"

    return signal_type, confidence, fires, rsi_val

# === TELEGRAM SIUNTIMAS ===
async def send_alert(name, signal, price, confidence, fires, rsi_val):
    if not bot:
        return
    for chat_id in MULTI_CHAT_IDS:
        try:
            if signal == "BUY" and confidence >= 60:
                msg = f"🟢 {fires} **BUY ALERT **({name})\n💰 Kaina: {price:.4f}\n📊 RSI: {rsi_val:.1f} | Tikimybė: {confidence:.1f}%"
            elif signal == "SELL" and confidence >= 60:
                msg = f"🔴 {fires} **SELL ALERT **({name})\n💰 Kaina: {price:.4f}\n📊 RSI: {rsi_val:.1f} | Tikimybė: {confidence:.1f}%"
            elif (signal == "BUY" and confidence >= 40) or (signal == "SELL" and confidence >= 40):
                msg = f"🟡 {fires} **WATCH **({name})\n💰 Kaina: {price:.4f}\n📊 RSI: {rsi_val:.1f} | Tikimybė: {confidence:.1f}%"
            else:
                return
            await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
            print(f"✅ Signalas: {name} {signal} @ {price:.4f}")
        except Exception as e:
            print(f"❌ Telegram klaida: {e}")

# === SIGNALŲ TIKRINIMAS ===
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
            
            rsi = calculate_rsi(close)
            macd_line, macd_signal = calculate_macd(close)
            ema9 = calculate_ema(close, 9)
            ema26 = calculate_ema(close, 26)
            
            bias = get_bias(rsi.iloc[-1], macd_line, macd_signal, ema9, ema26, close)
            signal, confidence, fires, rsi_val = calculate_confidence(symbol, df, bias)
            
            current_price = close.iloc[-1]
            asset_name = symbol.split("/")[0]
            
            if signal != "HOLD" and confidence >= 40:
                await send_alert(asset_name, signal, current_price, confidence, fires, rsi_val)
                
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
        await bot.send_message(chat_id=CHAT_ID, text="🧪 **OMEGA BOT VEIKIA**", parse_mode="Markdown")
        print("✅ Testas išsiųstas!")

# === PAGRINDINIS CIKLAS ===
async def main():
    await send_test()
    while True:
        await check_signals()
        await asyncio.sleep(900)

if __name__ == "__main__":
    asyncio.run(main())
