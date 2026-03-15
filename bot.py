import requests
import time
import os

# --- KONFIGURASI ---
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("ALTFINS_API_KEY", "")

# URL API v2 sesuai temuan Anda
URL = "https://altfins.com/api/v2/public/signals-feed/search-requests"

# Risk Management
TP1_PCT = 0.02
SL_PCT = 0.015
sent_signals = {}

def send_telegram(text):
    if not TOKEN or not CHAT_ID: return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def fetch_signals():
    if not API_KEY:
        print("❌ API_KEY belum diisi di Variables Railway!")
        return

    headers = {
        "Authorization": f"Bearer {API_KEY.strip()}",
        "Content-Type": "application/json"
    }
    
    # Payload untuk mencari sinyal Unusual Volume & Resistance Breakout
    # Sesuai standar API v2 altFINS
    payload = {
        "filter": {
            "signalType": ["UNUSUAL_VOLUME", "RESISTANCE_BREAKOUT"],
            "exchange": "Binance"
        },
        "limit": 5
    }

    print(f"Mengecek sinyal via API v2...")
    try:
        # Menggunakan POST sesuai kebutuhan endpoint search-requests
        response = requests.post(URL, headers=headers, json=payload, timeout=20)
        
        if response.status_code == 200:
            data = response.json()
            # Biasanya data ada di dalam list atau key 'items'
            signals = data if isinstance(data, list) else data.get('items', data.get('data', []))
            
            if not signals:
                print("Sinyal belum ditemukan saat ini.")
                return

            now = time.time()
            for coin in signals:
                symbol = coin.get("symbol")
                price = float(coin.get("lastPrice") or coin.get("price") or 0)
                signal_name = coin.get("signalType", "ALGO")

                if not symbol or price == 0: continue
                
                sig_id = f"{symbol}_{signal_name}"
                if sig_id in sent_signals and (now - sent_signals[sig_id] < 3600):
                    continue

                # Kalkulasi Futures Long
                tp1 = price * (1 + TP1_PCT)
                sl = price * (1 - SL_PCT)

                msg = (
                    f"🚀 *ALTFINS V2 SIGNAL*\n\n"
                    f"Pair: #{symbol}\n"
                    f"Type: `{signal_name}`\n"
                    f"Entry: `{price:.4f}`\n\n"
                    f"🎯 TP1: `{tp1:.4f}`\n"
                    f"🛑 SL: `{sl:.4f}`\n"
                )
                
                send_telegram(msg)
                sent_signals[sig_id] = now
                print(f"✅ Sinyal {symbol} terkirim!")

        else:
            print(f"❌ Error API v2 ({response.status_code})")
            print(f"Detail: {response.text}")

    except Exception as e:
        print(f"⚠️ Error: {e}")

if __name__ == "__main__":
    print("Bot altFINS v2 Aktif di Railway...")
    while True:
        fetch_signals()
        time.sleep(600) # Cek setiap 10 menit
