import requests
import time
import os

# --- KONFIGURASI ---
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("ALTFINS_API_KEY")

# PERBAIKAN: URL Endpoint sesuai standar API altFINS
# Kita akan mencoba endpoint scanner yang lebih umum
ENDPOINTS = {
    "VOLUME": "https://api.altfins.com/api/v1/scanner/unusual-volume",
    "BREAKOUT": "https://api.altfins.com/api/v1/scanner/resistance-breakout"
}

# Risk Management
TP1_PCT = 0.02
TP2_PCT = 0.05
SL_PCT = 0.015

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

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except:
        pass

def fetch_signals():
    # Pastikan API_KEY di Railway tidak ada spasi
    headers = {
        "Authorization": f"Bearer {API_KEY.strip()}",
        "Accept": "application/json"
    }
    now = time.time()

    for signal_name, url in ENDPOINTS.items():
        print(f"Mengecek {signal_name} ke: {url}")
        try:
            # Tambahkan param filter umum agar tidak 500
            response = requests.get(url, headers=headers, params={"exchange": "binance"}, timeout=20)
            
            if response.status_code == 200:
                data = response.json()
                signals = data.get('data', data) if isinstance(data, dict) else data
                
                if not signals:
                    continue

                for coin in signals[:5]:
                    symbol = coin.get("symbol")
                    # altFINS kadang menggunakan 'last' atau 'price'
                    price_val = coin.get("last") or coin.get("price") or coin.get("close")
                    
                    if not symbol or not price_val: continue
                        
                    price = float(price_val)
                    side = "LONG"
                    
                    signal_key = f"{symbol}_{signal_name}"
                    if signal_key in sent_signals and (now - sent_signals[signal_key] < 3600):
                        continue

                    tp1, tp2, sl = calculate_levels(price, side)

                    pesan = (
                        f"🎯 *ALTFINS {signal_name}*\n\n"
                        f"Koin: *{symbol}*\n"
                        f"Entry: `{price:.4f}`\n\n"
                        f"🚀 TP1: `{tp1:.4f}`\n"
                        f"🛑 SL: `{sl:.4f}`"
                    )
                    
                    send_telegram(pesan)
                    sent_signals[signal_key] = now
                    print(f"✅ Sinyal {symbol} terkirim!")

            else:
                print(f"❌ {signal_name} Gagal ({response.status_code})")
                print(f"Pesan: {response.text}")

        except Exception as e:
            print(f"⚠️ Error: {e}")

if __name__ == "__main__":
    print("Bot altFINS Running...")
    while True:
        fetch_signals()
        time.sleep(600)
