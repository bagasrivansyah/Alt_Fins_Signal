import requests
import time
import os

# --- KONFIGURASI ---
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("ALTFINS_API_KEY", "")

# PERBAIKAN URL: Menggunakan struktur yang lebih umum untuk sinyal altFINS
ENDPOINTS = {
    "VOLUME": "https://api.altfins.com/api/v1/signals/unusual-volume",
    "BREAKOUT": "https://api.altfins.com/api/v1/signals/resistance-breakout"
}

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

    # Pastikan header menggunakan format yang benar
    headers = {
        "Authorization": f"Bearer {API_KEY.strip()}",
        "Content-Type": "application/json"
    }
    now = time.time()

    for name, url in ENDPOINTS.items():
        print(f"Mengecek {name}...")
        try:
            # Kita coba panggil tanpa parameter tambahan dulu untuk menghindari error 500
            response = requests.get(url, headers=headers, timeout=20)
            
            if response.status_code == 200:
                data = response.json()
                # altFINS biasanya membungkus data dalam key 'data' atau 'results'
                signals = data if isinstance(data, list) else data.get('data', data.get('results', []))
                
                if not signals or not isinstance(signals, list):
                    print(f"Sinyal {name} kosong.")
                    continue

                for coin in signals[:3]:
                    symbol = coin.get("symbol")
                    # Mencoba berbagai kemungkinan nama field harga
                    price_val = coin.get("lastPrice") or coin.get("price") or coin.get("close") or coin.get("last")
                    
                    if not symbol or not price_val: continue
                        
                    price = float(price_val)
                    tp1 = price * (1 + TP1_PCT)
                    sl = price * (1 - SL_PCT)
                    
                    sig_id = f"{symbol}_{name}"
                    if sig_id in sent_signals and (now - sent_signals[sig_id] < 3600):
                        continue

                    msg = (
                        f"🚀 *ALTFINS SIGNAL: {name}*\n\n"
                        f"Pair: #{symbol}\n"
                        f"Entry: `{price:.4f}`\n"
                        f"Target TP: `{tp1:.4f}`\n"
                        f"Stop Loss: `{sl:.4f}`\n"
                    )
                    send_telegram(msg)
                    sent_signals[sig_id] = now
                    print(f"✅ Berhasil kirim {symbol}")

            else:
                print(f"❌ {name} Gagal ({response.status_code})")
                # Jika masih 500, kemungkinan URL butuh penyesuaian dari dokumentasi resmi
                
        except Exception as e:
            print(f"⚠️ Error {name}: {e}")

if __name__ == "__main__":
    print("Bot altFINS Aktif...")
    while True:
        fetch_signals()
        time.sleep(600)
