import requests
import time
import os

# Konfigurasi dari Environment Variables Railway
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("ALTFINS_API_KEY")

# Endpoint API altFINS
ENDPOINTS = {
    "VOLUME": "https://api.altfins.com/v1/signals/unusual-volume",
    "BREAKOUT": "https://api.altfins.com/v1/signals/resistance-breakout"
}

# Pengaturan Risk Management (Persentase)
TP1_PCT = 0.02  # 2%
TP2_PCT = 0.05  # 5%
SL_PCT = 0.015  # 1.5%

# Cache untuk mencegah spam (Reset otomatis di loop)
sent_signals = {}

def calculate_levels(price, side):
    if side == "LONG":
        tp1 = price * (1 + TP1_PCT)
        tp2 = price * (1 + TP2_PCT)
        sl = price * (1 - SL_PCT)
    else:
        tp1 = price * (1 - TP1_PCT)
        tp2 = price * (1 - TP2_PCT)
        sl = price * (1 + SL_PCT)
    return tp1, tp2, sl

def send_telegram_msg(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id": CHAT_ID, 
            "text": text, 
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        })
    except Exception as e:
        print(f"Error Telegram: {e}")

def fetch_signals():
    headers = {"Authorization": f"Bearer {API_KEY}"}
    now = time.time()

    for signal_type, url in ENDPOINTS.items():
        try:
            response = requests.get(url, headers=headers, timeout=20)
            if response.status_code == 200:
                signals = response.json()
                
                for coin in signals[:5]: # Ambil 5 koin teratas per scan
                    symbol = coin.get("symbol")
                    price = float(coin.get("lastPrice", 0))
                    
                    # Tentukan SIDE (Default Long untuk Breakout/Volume, 
                    # namun altFINS biasanya menyertakan trend koin tersebut)
                    side = "LONG" # Secara default sinyal breakout altFINS adalah Bullish
                    
                    # Cek duplikasi
                    signal_key = f"{symbol}_{side}_{signal_type}"
                    if signal_key in sent_signals and (now - sent_signals[signal_key] < 3600):
                        continue

                    # Hitung TP & SL
                    tp1, tp2, sl = calculate_levels(price, side)

                    emoji = "🚀" if side == "LONG" else "🔻"
                    msg = f"""
{emoji} *FUTURES SIGNAL: {symbol}*
*Type:* {signal_type} Analysis

*Side:* `{side}`
*Entry:* `{price:.4f}`

🎯 *Targets:*
TP1: `{tp1:.4f}` (2%)
TP2: `{tp2:.4f}` (5%)
🛑 SL: `{sl:.4f}` (1.5%)

_Data by altFINS API_
                    """
                    
                    send_telegram_msg(msg)
                    sent_signals[signal_key] = now
            else:
                print(f"API {signal_type} Error: {response.status_code}")
        except Exception as e:
            print(f"Error: {e}")

# ================= MAIN LOOP =================
print("Futures Bot Active...")

while True:
    fetch_signals()
    
    # Bersihkan cache lama setiap loop
    current_time = time.time()
    sent_signals = {k: v for k, v in sent_signals.items() if current_time - v < 14400}
    
    # Scan setiap 10 menit
    time.sleep(600)
