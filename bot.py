import requests
import time
import os
import threading
from datetime import datetime

# --- KONFIGURASI RAILWAY ---
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
# Pastikan di Railway formatnya: 123456,7891011 (tanpa spasi setelah koma)
WHITELIST_IDS = os.getenv("WHITELIST_IDS", "").split(",")

# Konfigurasi Risk & Filter
LEVERAGE = 20          
VOL_MIN_USDT = 5000000 
COOLDOWN_SECONDS = 14400 

BINANCE_URLS = ["https://api1.binance.com", "https://api2.binance.com", "https://api3.binance.com"]

# Database RAM
active_positions = {} 
sent_signals = {}
last_update_id = 0

# --- HELPER MATEMATIKA (Pengganti Numpy) ---
def calculate_mean(data):
    if not data: return 0
    return sum(data) / len(data)

# --- FUNGSI DATA BINANCE ---
def call_binance(endpoint):
    for base_url in BINANCE_URLS:
        try:
            res = requests.get(f"{base_url}{endpoint}", timeout=10)
            if res.status_code == 200: return res.json()
        except: continue
    return None

def get_klines(symbol, interval, limit=50):
    data = call_binance(f"/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}")
    if not data or not isinstance(data, list): return None
    return [{"h": float(x[2]), "l": float(x[3]), "c": float(x[4]), "v": float(x[5])} for x in data]

# --- LOGIKA SMC (ICT) ---
def get_trend_htf(symbol):
    candles = get_klines(symbol, "4h", 20)
    if not candles: return "NEUTRAL"
    ema = calculate_mean([x['c'] for x in candles])
    return "BULLISH" if candles[-1]['c'] > ema else "BEARISH"

def get_ict_analysis(symbol):
    c_1h = get_klines(symbol, "1h", 20)
    if not c_1h or len(c_1h) < 5: return None
    
    htf_trend = get_trend_htf(symbol)
    avg_vol = calculate_mean([x['v'] for x in c_1h[-10:]])
    
    curr, prev2 = c_1h[-1], c_1h[-3]
    is_displacement = curr['v'] > (avg_vol * 1.3)

    # Bullish FVG
    if htf_trend == "BULLISH" and is_displacement and curr['l'] > prev2['h']:
        return {"side": "LONG", "reason": "BULLISH FVG (SMC)"}
    # Bearish FVG
    if htf_trend == "BEARISH" and is_displacement and curr['h'] < prev2['l']:
        return {"side": "SHORT", "reason": "BEARISH FVG (SMC)"}
    
    return None

# --- TELEGRAM HANDLER ---
def send_telegram(text, target_id=None):
    if not TOKEN: return
    dest = target_id if target_id else CHAT_ID
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": dest, "text": text, "parse_mode": "Markdown"}
    try: 
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Error: {e}")

def handle_commands():
    global last_update_id
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    try:
        response = requests.get(url, params={"offset": last_update_id + 1, "timeout": 5}, timeout=10).json()
        if not response.get("result"): return
        for update in response["result"]:
            last_update_id = update["update_id"]
            message = update.get("message", {})
            text = message.get("text", "")
            sender_id = str(message.get("from", {}).get("id"))
            
            if sender_id not in WHITELIST_IDS: continue

            if "Analisa" in text:
                coin = text.split()[-1].upper()
                sym = coin if "USDT" in coin else coin + "USDT"
                send_telegram(f"🔍 *Menganalisa {sym}...*", sender_id)
                
                ict = get_ict_analysis(sym)
                ticker = call_binance(f"/api/v3/ticker/price?symbol={sym}")
                
                if ict and ticker:
                    p = float(ticker['price'])
                    msg = f"✅ *{sym} FOUND*\nSide: `{ict['side']}`\nEntry: `{p}`\nLogic: `{ict['reason']}`"
                    send_telegram(msg, sender_id)
                else:
                    send_telegram(f"❌ *{sym}*: Belum ada setup valid sesuai trend HTF.", sender_id)
    except: pass

# --- MAIN LOOP ---
def worker_commands():
    while True:
        handle_commands()
        time.sleep(2)

def main():
    print("SMC Bot v5.1 Started...")
    threading.Thread(target=worker_commands, daemon=True).start()
    
    while True:
        try:
            market_data = call_binance("/api/v3/ticker/24hr")
            if not market_data:
                time.sleep(10)
                continue
            
            # Scan otomatis bisa ditambahkan di sini
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Scanning Market...")
            
        except Exception as e:
            print(f"Main Loop Error: {e}")
        time.sleep(60)

if __name__ == "__main__":
    main()
