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

# List API Binance Alternatif untuk menghindari blokir lokasi Railway
BINANCE_URLS = [
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://data-api.binance.vision" # Biasanya paling ampuh di Cloud
]

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
        }, timeout=10)
    except: pass

def call_binance(endpoint):
    """Fungsi untuk mencoba berbagai URL Binance sampai berhasil"""
    for base_url in BINANCE_URLS:
        try:
            url = f"{base_url}{endpoint}"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                return response.json()
        except:
            continue
    return None

def get_rsi(symbol):
    data = call_binance(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=100")
    if not data or not isinstance(data, list): return None
    try:
        closes = [float(x[4]) for x in data]
        deltas = [closes[i+1] - closes[i] for i in range(len(closes)-1)]
        up = [x if x > 0 else 0 for x in deltas]
        down = [abs(x) if x < 0 else 0 for x in deltas]
        avg_gain = sum(up[-14:]) / 14
        avg_loss = sum(down[-14:]) / 14
        if avg_loss == 0: return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    except: return None

def analyze():
    print("Mencoba memanggil data Binance (Bypass Region)...")
    data = call_binance("/api/v3/ticker/24hr")
    
    if not data or not isinstance(data, list):
        print("❌ Semua API Binance menolak koneksi (Restricted Location).")
        return

    now = time.time()
    for coin in data:
        if not isinstance(coin, dict) or not coin.get('symbol', '').endswith("USDT"):
            continue
            
        try:
            change = float(coin.get('priceChangePercent', 0))
            volume = float(coin.get('quoteVolume', 0))
            if volume < VOL_MIN_USDT: continue

            side = "LONG" if change >= LONG_THRESHOLD else "SHORT" if change <= SHORT_THRESHOLD else None

            if side:
                sig_id = f"{coin['symbol']}_{side}"
                if sig_id in sent_signals and (now - sent_signals[sig_id] < 14400):
                    continue

                rsi_val = get_rsi(coin['symbol'])
                if rsi_val is None: continue
                
                last_price = float(coin['lastPrice'])
                tp = last_price * (1.03 if side == "LONG" else 0.97)
                sl = last_price * (0.98 if side == "LONG" else 1.02)
                
                msg = (
                    f"{'🚀' if side == 'LONG' else '🔻'} *BINANCE {side}*\n\n"
                    f"Pair: #{coin['symbol']}\n"
                    f"Price: `{last_price}`\n"
                    f"24h Change: `{change}%`\n"
                    f"RSI (1h): `{rsi_val:.2f}`\n\n"
                    f"🎯 Target: `{tp:.4f}`\n"
                    f"🛑 SL: `{sl:.4f}`\n\n"
                    f"📈 [Chart TradingView](https://www.tradingview.com/chart/?symbol=BINANCE:{coin['symbol']})"
                )
                send_telegram(msg)
                sent_signals[sig_id] = now
                print(f"✅ Berhasil: {coin['symbol']}")
        except: continue

if __name__ == "__main__":
    while True:
        analyze()
        time.sleep(300)
