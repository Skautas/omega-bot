# 🌍 OMEGA Signal Bot

**Profesionalus 15-minučių signalų botas su fundamentine ir technine analize**

## 🔧 Funkcijos
- **15m + 1h multitimeframe strategija**
- **Fibonacci, S/R, Order Blocks, Liquidity Zones**
- **Makroekonomikos įvykių stebėjimas** (Fed, CPI, NFP)
- **Kripto naujienų sentimentas** (per CryptoPanic)
- **TP/SL su RR ≥ 1.5**
- **Signalai į Telegram**

## 🚀 Paleidimas
1. Sukurkite GitHub repozitorijų
2. Paleiskite Google Colab:
```python
!git clone https://github.com/jusuvardas/omega-bot.git
%cd omega-bot
!pip install -r requirements.txt
import os
os.environ["TELEGRAM_TOKEN"] = "..."
os.environ["TELEGRAM_CHAT_ID"] = "..."
!python main.py
