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
MULTI_CHAT_IDS = [CHAT_ID]  # Pridėkite daugiau ID jei reikia

bot = Bot(token=TELEGRAM_TOKEN) if TELEGRAM_TOKEN else None

# === EXCHANGE SU HYBRIDU (Kraken + Binance) ===
def get_exchange(symbol):
    """Grąžina tinkamą exchange pagal simbolį"""
    # Kraken palaiko: BTC, ETH, SOL, XRP, DOGE, ADA, ZEC, XLM, DOT, LINK, LTC, BCH, ICP
    kraken_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "ZEC", "XLM", "DOT", "LINK", "LTC", "BCH", "ICP"]
    asset = symbol.split("/")[0]
    
    if asset in kraken_assets:
        return ccxt.kraken(), "USD"
    else:
        # WLFI, SUI, STRK – naudojame Binance (USDT)
        return ccxt.binance(), "USDT"

# === 16 TURTŲ SĄRAŠAS ===
ASSETS = [
    "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "DOGE/USD", "ADA/USD", 
    "ZEC/USD", "XLM/USD", "DOT/USD", "WLFI/USDT", "SUI/USDT", "LINK/USD", 
    "LTC/USD", "BCH/USD", "STRK/USDT", "ICP/USD"
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
    """Grąžina rinkos kryptį: LONG/SHORT/NEUTRAL"""
    rsi_bias = "NEUTRAL"
    if rsi_val < 35:
        rsi_bias = "NEUTRAL"  # RSI override
    elif rsi_val > 65:
        rsi_bias = "NEUTRAL"
    else:
        rsi_bias = "LONG" if rsi_val > 50 else "SHORT"
    
    macd_bias = "LONG" if macd_line.iloc[-1] > macd_signal.iloc[-1] else "SHORT"
    ema_bias = "LONG" if ema9.iloc[-1] > ema26.iloc[-1] else "SHORT"
    
    # 2/3 sutarimas
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
    """Skaičiuoja 0-100% tikimybę"""
    close = df["close"]
    rsi = calculate_rsi(close)
    macd_line, macd_signal = calculate_macd(close)
    ema9 = calculate_ema(close, 9)
    ema26 = calculate_ema(close, 26)
    bb = BollingerBands(close)
    atr = AverageTrueRange(df["high"], df["low"], close).average_true_range()
    
    rsi_val = rsi.iloc[-1]
    current_price = close.iloc[-1]
    bb_low = bb.bollinger_lband().iloc[-1]
    bb_high = bb.bollinger_hband().iloc[-1]
    
    score = 0
    signal_type = "HOLD"
    
    # PURE MEAN-REVERSION: BUY tik jei RSI < 30
    if rsi_val < 30:
        signal_type = "BUY"
        # Patikriname bias
        if bias != "SHORT":  # SHORT bias blokuoja BUY
            score += 30  # RSI < 30
            if current_price <= bb_low:
                score += 20  # Apatinė Bollinger juosta
            if df["volume"].iloc[-1] > df["volume"].rolling(20).mean().iloc[-1] * 1.5:
                score += 15  # Tūrio patvirtinimas
            if ema9.iloc[-1] > ema26.iloc[-1]:
                score += 10  # EMA trendas
            # Watch alertas (RSI 30-35)
            if rsi_val >= 30 and rsi_val < 35:
                score += 10
    
    # SHORT: tik jei RSI > 70 ir 5 sluoksniai
    elif rsi_val > 70:
        signal_type = "SELL"
        if bias != "LONG":  # LONG bias blokuoja SELL
            # 5-LAYER SHORT SAFETY
            williams_r = WilliamsRIndicator(df["high"], df["low"], close).williams_r().iloc[-1]
            adx = df["high"]  # Supaprastinta
            volume_ratio = df["volume"].iloc[-1] / df["volume"].rolling(20).mean().iloc[-1]
            
            if williams_r > -10:  # Perkrauta
                score += 15
            if volume_ratio > 2.0:
                score += 15
            if current_price >= bb_high:
                score += 20
            if bias == "SHORT":
                score += 25
            if rsi_val > 75:
                score += 15  # Extreme overbought
    
    confidence = min(score, 100)
    
    # 🔥 FIRE RATING
    if confidence >= 60:
        fires = "🔥🔥🔥"
    elif confidence >= 40:
        fires = "🔥🔥"
    else:
        fires = "🔥"
    
    return signal_type, confidence, fires

# === SIUNTIMO FUNKCIJA ===
async def send_alert(name, signal, price, confidence, fires, rsi_val):
    if not bot:
        return
    
    for chat_id in MULTI_CHAT_IDS:
        try:
            if signal == "BUY" and confidence >= 60:
                msg = (
                    f"🟢 {fires} **BUY ALERT **({name})\n"
                    f"💰 Kaina: {price:.4f}\n"
                    f"📊 RSI: {rsi_val:.1f} | Tikimybė: {confidence:.1f}%\n"
                    f"🎯 Strategija: PURE MEAN-REVERSION\n"
                    f"🔍 Patvirtinimas: RSI<30 + Bollinger + Tūris"
                )
            elif signal == "SELL" and confidence >= 60:
                msg = (
                    f"🔴 {fires} **SELL ALERT **({name})\n"
                    f"💰 Kaina: {price:.4f}\n"
                    f"📊 RSI: {rsi_val:.1) | Tikimybė: {confidence:.1f}%\n"
                    f"🎯 Strategija: OVERBOUGHT SHORT\n"
                    f"🔍 Patvirtinimas: RSI>70 + 5-Layer Safety"
                )
            elif (signal == "BUY" and confidence >= 40) or (signal == "SELL" and confidence >= 40):
                msg = (
                    f"🟡 {fires} **WATCH **({name})\n"
                    f"💰 Kaina: {price:.4f}\n"
                    f"📊 RSI: {rsi_val:.1f} | Tikimybė: {confidence:.1f}%\n"
                    f"⚠️ Laukite stipresnio patvirtinimo"
                )
            else:
                return
            
            await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
            print(f"✅ Pranešimas išsiųstas: {name} {signal} @ {price:.4f}")
            
        except Exception as e:
            print(f"❌ Telegram klaida: {e}")

# === PAGRINDINĖ SIGNALŲ FUNKCIJA ===
async def check_signals():
    print(f"\n🕒 Tikrinama: {pd.Timestamp.now()}")
    
    for symbol in ASSETS:
        try:
            exchange, quote = get_exchange(symbol)
            ohlcv = exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=100)
            if len(ohlcv) < 50:
                continue
            
            df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
            close = df["close"]
            rsi = calculate_rsi(close)
            rsi_val = rsi.iloc[-1]
            
            # MA 9/26 crossover
            ema9 = calculate_ema(close, 9)
            ema26 = calculate_ema(close, 26)
            macd_line, macd_signal = calculate_macd(close)
            
            bias = get_bias(rsi_val, macd_line, macd_signal, ema9, ema26, close)
            signal, confidence, fires = calculate_confidence(symbol, df, bias)
            
            current_price = close.iloc[-1]
            asset_name = symbol.split("/")[0]
            
            # Siunčiam tik jei yra signalas
            if signal != "HOLD" and confidence >= 40:
                await send_alert(asset_name, signal, current_price, confidence, fires, rsi_val)
                
        except Exception as e:
            print(f"Klaida {symbol}: {e}")
            continue

# === SELF-PING FUNKCIJA ===
def keep_colab_alive():
    while True:
        try:
            requests.get("https://colab.research.google.com/")
        except:
            pass
        time.sleep(300)

threading.Thread(target=keep_colab_alive, daemon=True).start()

# === WATCHDOG FUNKCIJA ===
def run_with_watchdog():
    """Paleidžia botą su auto-atkūrimu"""
    while True:
        try:
            asyncio.run(check_signals())
            print("⏳ Laukiama 15 min...")
            time.sleep(900)
        except KeyboardInterrupt:
            print("\n🛑 Sustabdyta vartotojo")
            break
        except Exception as e:
            print(f"⚠️ Klaida: {e}. Bandome iš naujo po 30 sec...")
            time.sleep(30)

# === PAGALBINĖ TESTINĖ FUNKCIJA ===
def send_test_message():
    if not bot:
        print("❌ Telegram neįjungtas")
        return
    try:
        test_msg = (
            "🧪 **OMEGA-PRO TESTAS**\n"
            "✅ Botas veikia!\n"
            "📊 Stebimi turtai: 16 kripto\n"
            "🔍 Strategija: Pure Mean-Reversion + Bias Gating"
        )
        asyncio.run(bot.send_message(chat_id=CHAT_ID, text=test_msg, parse_mode="Markdown"))
        print("✅ Testas išsiųstas!")
    except Exception as e:
        print(f"❌ Testo klaida: {e}")

# === PAGRINDINIS PALEIDIMAS ===
if __name__ == "__main__":
    send_test_message()
    run_with_watchdog()
