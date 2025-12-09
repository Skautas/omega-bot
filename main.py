import os
import asyncio
import ccxt
import pandas as pd
import numpy as np
import time
import threading
import requests
from ta.trend import EMAIndicator
from telegram import Bot

# === Konfigūracija ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
bot = Bot(token=TELEGRAM_TOKEN) if TELEGRAM_TOKEN else None
exchange = ccxt.kraken()
TIMEFRAME = "15m"

# === Turtai (tik Kraken palaikomi) ===
ASSETS = {
    "BTC": "BTC/USD",
    "ETH": "ETH/USD",
    "SOL": "SOL/USD",
    "XRP": "XRP/USD",
    "ZEC": "ZEC/USD",
    "ICP": "ICP/USD"
}

# === Pagalbinės funkcijos ===
def calculate_atr(high, low, close, period=14):
    hl = high - low
    hc = abs(high - close.shift(1))
    lc = abs(low - close.shift(1))
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def calculate_fib_levels(high, low):
    diff = high - low
    return {
        "0.0": high,
        "0.236": high - 0.236 * diff,
        "0.382": high - 0.382 * diff,
        "0.5": high - 0.5 * diff,
        "0.618": high - 0.618 * diff,
        "0.786": high - 0.786 * diff,
        "1.0": low,
    }

def detect_sr_levels(prices, window=5):
    levels = []
    for i in range(window, len(prices) - window):
        is_high = all(prices[i] >= prices[i - j] and prices[i] >= prices[i + j] for j in range(1, window + 1))
        is_low = all(prices[i] <= prices[i - j] and prices[i] <= prices[i + j] for j in range(1, window + 1))
        if is_high or is_low:
            levels.append(prices[i])
    levels = sorted(set(levels))
    filtered = []
    for lvl in levels:
        if not filtered or abs(lvl - filtered[-1]) > lvl * 0.005:
            filtered.append(lvl)
    return filtered

def is_near_level(price, levels, tolerance=0.003):
    return any(abs(price - lvl) / lvl <= tolerance for lvl in levels)

def detect_liquidity_zones(ohlcv, lookback=100):
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["body"] = abs(df["close"] - df["open"])
    volume_threshold = df["volume"].quantile(0.8)
    liquidity_pools = df[(df["volume"] > volume_threshold) & (df["body"] > df["high"] - df["low"] * 0.6)]
    return liquidity_pools[["low", "high"]].values

def detect_true_order_blocks(ohlcv, window=3):
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    ob_blocks = []
    for i in range(window, len(df) - window):
        candle = df.iloc[i]
        next_candles = df.iloc[i+1:i+window+1]
        if candle["close"] < candle["open"] and next_candles["close"].min() > candle["low"]:
            ob_blocks.append(("bull", candle["low"], candle["high"]))
        elif candle["close"] > candle["open"] and next_candles["close"].max() < candle["high"]:
            ob_blocks.append(("bear", candle["low"], candle["high"]))
    return ob_blocks

def detect_mss(closes, lookback=20):
    recent = closes[-lookback:]
    highs = pd.Series(recent).rolling(3).max().dropna()
    lows = pd.Series(recent).rolling(3).min().dropna()
    if highs.iloc[-1] > highs.iloc[-3] and lows.iloc[-1] > lows.iloc[-3]:
        return "bullish"
    elif highs.iloc[-1] < highs.iloc[-3] and lows.iloc[-1] < lows.iloc[-3]:
        return "bearish"
    return "neutral"

def calculate_poc(ohlcv, levels=50):
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    price_range = np.linspace(df["low"].min(), df["high"].max(), levels)
    volume_profile = []
    for i in range(len(price_range) - 1):
        low_p = price_range[i]
        high_p = price_range[i + 1]
        vol = df[(df["high"] >= low_p) & (df["low"] <= high_p)]["volume"].sum()
        volume_profile.append((low_p, high_p, vol))
    poc = max(volume_profile, key=lambda x: x[2])
    return (poc[0] + poc[1]) / 2

# === Signalų skaičiavimas ===
def calculate_signal(symbol, force_mode=False):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=200)
        if len(ohlcv) < 50:
            return "hold", 0.0, 0, 0, 0
        
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        closes = df["close"]
        current_price = closes.iloc[-1]
        avg_volume = df["volume"].rolling(20).mean().iloc[-1]
        high_volume = df["volume"].iloc[-1] > avg_volume * (1.3 if force_mode else 1.5)

        ema9 = EMAIndicator(closes, window=9).ema_indicator()
        ema21 = EMAIndicator(closes, window=21).ema_indicator()
        ema_cross_up = ema9.iloc[-2] <= ema21.iloc[-2] and ema9.iloc[-1] > ema21.iloc[-1]
        ema_cross_down = ema9.iloc[-2] >= ema21.iloc[-2] and ema9.iloc[-1] < ema21.iloc[-1]

        if not (ema_cross_up or ema_cross_down):
            return "hold", 0.0, 0, 0, 0

        recent_high = closes[-50:].max()
        recent_low = closes[-50:].min()
        fib = calculate_fib_levels(recent_high, recent_low)
        sr_levels = detect_sr_levels(closes.tolist())
        liquidity_pools = detect_liquidity_zones(ohlcv)
        ob_blocks = detect_true_order_blocks(ohlcv)
        mss = detect_mss(closes)
        poc = calculate_poc(ohlcv)

        near_fib_buy = is_near_level(current_price, [fib["0.618"], fib["0.786"]])
        near_fib_sell = is_near_level(current_price, [fib["0.236"], fib["0.382"]])
        near_sr = is_near_level(current_price, sr_levels)
        near_liquidity = any(abs(current_price - lvl) / lvl <= 0.005 for lvl in liquidity_pools.flatten())
        near_ob_bull = any(b[0] == "bull" and b[1] <= current_price <= b[2] for b in ob_blocks)
        near_ob_bear = any(b[0] == "bear" and b[1] <= current_price <= b[2] for b in ob_blocks)
        near_poc = abs(current_price - poc) / poc <= 0.005

        body = abs(df["close"].iloc[-1] - df["open"].iloc[-1])
        wick_up = df["high"].iloc[-1] - max(df["close"].iloc[-1], df["open"].iloc[-1])
        wick_down = min(df["close"].iloc[-1], df["open"].iloc[-1]) - df["low"].iloc[-1]
        clean_candle = (wick_up < (0.5 if force_mode else 0.4) * body) and (wick_down < (0.5 if force_mode else 0.4) * body)

        score = 0
        if high_volume: score += 20 if force_mode else 25
        if near_sr: score += 20 if force_mode else 25
        if near_fib_buy or near_fib_sell: score += 30
        if clean_candle: score += 15 if force_mode else 20
        if near_liquidity: score += 15
        if near_ob_bull or near_ob_bear: score += 15
        if (mss == "bullish" and ema_cross_up) or (mss == "bearish" and ema_cross_down): score += 10
        if near_poc: score += 10

        confidence = min(score / 100.0, 1.0)
        threshold = 0.60 if force_mode else 0.75
        rr_factor = 1.5 if force_mode else 1.8

        atr_val = calculate_atr(df["high"], df["low"], df["close"], 14).iloc[-1]

        if ema_cross_up and confidence >= threshold:
            sl = min(fib["0.786"], recent_low * 0.995)
            tp = current_price + (current_price - sl) * rr_factor
            return "BUY", confidence, current_price, tp, sl
        elif ema_cross_down and confidence >= threshold:
            sl = max(fib["0.236"], recent_high * 1.005)
            tp = current_price - (sl - current_price) * rr_factor
            return "SELL", confidence, current_price, tp, sl
        else:
            return "hold", 0.0, 0, 0, 0

    except Exception as e:
        print(f"Klaida {symbol}: {e}")
        return "hold", 0.0, 0, 0, 0

# === Siuntimas į Telegram ===
async def send_signal(name, signal, price, tp, sl, confidence):
    if not bot:
        return
    try:
        rr = round(abs(tp - price) / abs(price - sl), 1)
        emoji = "🟢" if signal == "BUY" else "🔴"
        msg = (
            f"{emoji} **{signal} SIGNAL (15m)**\n"
            f"🪙 {name}\n"
            f"💰 Įėjimas: {price:.4f} USD\n"
            f"🎯 TP: {tp:.4f} USD\n"
            f"🛑 SL: {sl:.4f} USD\n"
            f"📊 RR: {rr} | Tikimybė: {confidence:.1%}\n"
            f"🔍 Patvirtinimas: Fib + S/R + OB + Liquidity + MSS + POC"
        )
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
        print(f"✅ Signalas: {name} {signal} @ {price:.4f}")
    except Exception as e:
        print(f"❌ Telegram klaida: {e}")

# === Self-ping funkcija (neleidžia Colab užmigti) ===
def keep_colab_alive():
    while True:
        try:
            requests.get("https://colab.research.google.com/")
        except:
            pass
        time.sleep(300)

threading.Thread(target=keep_colab_alive, daemon=True).start()

# === Pagrindinis ciklas ===
last_forced_signal_time = None

async def check_all_signals():
    global last_forced_signal_time
    now = pd.Timestamp.now()
    print(f"\n🕒 Tikrinama: {now}")

    for name, pair in ASSETS.items():
        signal, conf, price, tp, sl = calculate_signal(pair, force_mode=False)
        if signal != "hold":
            await send_signal(name, signal, price, tp, sl, conf)
            return

    if last_forced_signal_time is None or (now - last_forced_signal_time).total_seconds() >= 900:
        print("🔍 Priverstinis signalo paieška (≥60%)...")
        for name, pair in ASSETS.items():
            signal, conf, price, tp, sl = calculate_signal(pair, force_mode=True)
            if signal != "hold":
                await send_signal(name, signal, price, tp, sl, conf)
                last_forced_signal_time = now
                return

# === Testinė funkcija ===
async def send_test_message():
    if bot:
        test_msg = (
            "🧪 **TESTAS: Jūsų OMEGA botas veikia!**\n"
            "✅ Ryšys su Telegram – sėkmingas\n"
            "🕒 Laikas: " + pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S") + "\n"
            "📊 Turtai: BTC, ETH, SOL, XRP, ZEC, ICP"
        )
        try:
            await bot.send_message(chat_id=CHAT_ID, text=test_msg, parse_mode="Markdown")
            print("✅ Testinis pranešimas išsiųstas į Telegram!")
        except Exception as e:
            print(f"❌ Klaida siunčiant testą: {e}")
    else:
        print("❌ Telegram botas neįjungtas")

# === Paleidimas ===
if __name__ == "__main__":
    asyncio.run(send_test_message())
    asyncio.run(main_loop := asyncio.wait_for(check_all_signals(), timeout=1))
    while True:
        asyncio.run(check_all_signals())
        time.sleep(900)
