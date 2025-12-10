import feedparser
import pandas as pd
from datetime import datetime

# === Makroekonomikos įvykiai ===
MACRO_EVENTS = [
    ("2025-12-11", "US CPI", 3),
    ("2025-12-18", "Fed Interest Rate Decision", 3),
    ("2026-01-15", "FOMC Minutes", 2),
    # Pridėkite daugiau iš https://tradingeconomics.com/calendar
]

# === Kripto naujienų šaltiniai ===
CRYPTO_FEEDS = ["https://cryptopanic.com/rss/feeds/news/all/"]

def is_high_impact_macro_today() -> bool:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    for date, event, impact in MACRO_EVENTS:
        if date == today and impact >= 2:
            print(f"🔔 Makro įspėjimas: {event}")
            return True
    return False

def get_crypto_sentiment(symbol: str) -> str:
    try:
        positive_words = ["bull", "buy", "green", "approval", "adopt", "up", "gain", "soar"]
        negative_words = ["bear", "sell", "red", "ban", "hack", "crash", "down", "drop", "fall"]
        
        all_titles = []
        feed = feedparser.parse(CRYPTO_FEEDS[0])
        for entry in feed.entries[:10]:
            title = entry.title.lower()
            if symbol.lower() in title or "bitcoin" in title:
                all_titles.append(title)
        
        if not all_titles:
            return "neutral"
        
        pos_score = sum(1 for t in all_titles for w in positive_words if w in t)
        neg_score = sum(1 for t in all_titles for w in negative_words if w in t)
        
        if pos_score > neg_score:
            return "positive"
        elif neg_score > pos_score:
            return "negative"
        else:
            return "neutral"
    except:
        return "neutral"

def fundamental_filter(symbol: str) -> bool:
    if is_high_impact_macro_today():
        return False
    if symbol in ["BTC", "ETH"]:
        sentiment = get_crypto_sentiment(symbol)
        if sentiment == "negative":
            print(f"📰 Neigiamas sentimentas: {symbol}")
            return False
    return True
