import requests
import time
import os

# --- KONFIGURASI ---
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Sinyal Threshold
LONG_THRESHOLD = 3.5   
SHORT_THRESHOLD = -3.5 
VOL_MIN_USDT = 2000000 

sent_signals = {}

def send_telegram(text):
    if not TOKEN or not CHAT_ID: return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id": CHAT_ID, 
            "text": text, 
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        })
    except: pass

def get_rsi(symbol):
    """Menghitung RSI periode 14 menggunakan data kline 1 jam"""
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit=100"
    try:
        r = requests.get(url, timeout=10).json()
        closes = [float(x[4]) for x in r]
        
        deltas = []
        for i in range(len(closes)-1):
            deltas.append(closes[i+1] - closes[i])
            
        up = [x if x > 0 else 0 for x in deltas]
        down = [abs(x) if x < 0 else 0 for x in deltas]
        
        avg_gain = sum(up[-14:]) / 14
        avg_loss = sum(down[-14:]) / 14
        
        if avg_loss == 0: return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    except:
        return None

def analyze():
    print("Menganalisis Binance + RSI...")
    url = "https://api.binance.com/api/v3/ticker/24hr"
    try:
        data = requests.get(url).json()
    except: return

    now = time.time()
    
    for coin in data:
        symbol = coin['symbol']
        if not symbol.endswith("USDT"): continue
        
        change = float(coin['priceChangePercent'])
        volume = float(coin['quoteVolume'])

        if volume < VOL_MIN_USDT: continue

        side = None
        if change >= LONG_THRESHOLD: side = "LONG"
        elif change <= SHORT_THRESHOLD: side = "SHORT"

        if side:
            sig_id = f"{symbol}_{side}"
            if sig_id in sent_signals and (now - sent_signals[sig_id] < 14400):
                continue

            # Ambil RSI
            rsi_val = get_rsi(symbol)
            if rsi_val is None: continue
            
            last_price = float(coin['lastPrice'])
            tp = last_price * (1.03 if side == "LONG" else 0.97)
            sl = last_price * (0.98 if side == "LONG" else 1.02)
            
            # Link TradingView
            tv_url = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}"

            msg = (
                f"{'🚀' if side == 'LONG' else '🔻'} *BINANCE {side}*\n\n"
                f"Pair: #{symbol}\n"
                f"Price: `{last_price}`\n"
                f"24h Change: `{change}%`\n"
                f"RSI (1h): `{rsi_val:.2f}`\n\n"
                f"🎯 Target: `{tp:.4f}`\n"
                f"🛑 SL: `{sl:.4f}`\n\n"
                f"📈 [Buka Chart TradingView]({tv_url})"
            )
            
            send_telegram(msg)
            sent_signals[sig_id] = now
            print(f"✅ Sinyal {symbol} (RSI: {rsi_val:.2f})")

if __name__ == "__main__":
    while True:
        analyze()
        time.sleep(300)
