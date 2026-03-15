import requests
import time
import os

# --- KONFIGURASI ---
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Sinyal Threshold
LONG_THRESHOLD = 4.0   # Naik > 4% dianggap potensi Long
SHORT_THRESHOLD = -4.0 # Turun > 4% dianggap potensi Short
VOL_MIN_USDT = 2000000 # Minimal volume 2jt USDT agar koin tidak terlalu beresiko

sent_signals = {}

def send_telegram(text):
    if not TOKEN or not CHAT_ID:
        print("❌ Token/Chat ID belum diset di Railway")
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"})
    except: pass

def get_market_data():
    url = "https://api.binance.com/api/v3/ticker/24hr"
    try:
        r = requests.get(url, timeout=10)
        return r.json() if r.status_code == 200 else []
    except:
        return []

def analyze():
    print("Menganalisis pergerakan Binance...")
    data = get_market_data()
    now = time.time()
    
    for coin in data:
        symbol = coin['symbol']
        # Filter hanya pair USDT (Futures friendly)
        if not symbol.endswith("USDT"): continue
        
        last_price = float(coin['lastPrice'])
        change = float(coin['priceChangePercent'])
        volume = float(coin['quoteVolume'])

        # Filter volume agar tidak memantau koin mati
        if volume < VOL_MIN_USDT: continue

        side = None
        if change >= LONG_THRESHOLD:
            side = "LONG"
        elif change <= SHORT_THRESHOLD:
            side = "SHORT"

        if side:
            # Cegah spam koin yang sama selama 4 jam
            sig_id = f"{symbol}_{side}"
            if sig_id in sent_signals and (now - sent_signals[sig_id] < 14400):
                continue

            # Kalkulasi Target
            if side == "LONG":
                tp = last_price * 1.03
                sl = last_price * 0.98
                emoji = "🚀"
            else:
                tp = last_price * 0.97
                sl = last_price * 1.02
                emoji = "🔻"

            msg = (
                f"{emoji} *BINANCE FUTURES SIGNAL*\n\n"
                f"Pair: #{symbol}\n"
                f"Side: *{side}*\n"
                f"Price: `{last_price}`\n"
                f"24h Change: `{change}%`\n\n"
                f"🎯 Target: `{tp:.4f}`\n"
                f"🛑 Stop Loss: `{sl:.4f}`\n\n"
                f"⚡ *Auto-detected by Binance Scanner*"
            )
            
            send_telegram(msg)
            sent_signals[sig_id] = now
            print(f"✅ Berhasil kirim {side} {symbol}")

if __name__ == "__main__":
    print("Bot Binance Long/Short Aktif...")
    while True:
        analyze()
        # Scan setiap 5 menit (300 detik)
        time.sleep(300)
