import requests
import time
import os

# --- KONFIGURASI ---
# Pastikan nama variabel ini SAMA PERSIS dengan yang ada di Dashboard Railway
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("ALTFINS_API_KEY")

# Link API altFINS (Pastikan paket langganan Anda mendukung endpoint ini)
ENDPOINTS = {
    "VOLUME": "https://api.altfins.com/v1/signals/unusual-volume",
    "BREAKOUT": "https://api.altfins.com/v1/signals/resistance-breakout"
}

# Risk Management
TP1_PCT = 0.02  # 2%
TP2_PCT = 0.05  # 5%
SL_PCT = 0.015  # 1.5%

# Cache untuk mencegah spam (1 jam)
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
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"Gagal kirim Telegram: {e}")
        return False

def fetch_signals():
    # Perbaikan Header: Pastikan API_KEY tidak mengandung kata 'Bearer' di env Railway
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json"
    }
    now = time.time()

    for signal_name, url in ENDPOINTS.items():
        print(f"Mengecek sinyal {signal_name}...")
        try:
            response = requests.get(url, headers=headers, timeout=20)
            
            if response.status_code == 200:
                data = response.json()
                
                # altFINS kadang mengirim list langsung, atau dibungkus dalam {'data': []}
                signals = data.get('data', data) if isinstance(data, dict) else data
                
                if not signals:
                    print(f"Tidak ada sinyal baru untuk {signal_name}")
                    continue

                for coin in signals[:5]: # Ambil 5 koin terbaru
                    symbol = coin.get("symbol", "UNKNOWN")
                    # Mengambil harga (mencoba beberapa key yang umum di API)
                    price_val = coin.get("lastPrice") or coin.get("price") or coin.get("close")
                    
                    if not price_val:
                        continue
                        
                    price = float(price_val)
                    side = "LONG" # Sinyal breakout/volume biasanya bullish
                    
                    # Unik ID agar tidak dobel kirim
                    signal_key = f"{symbol}_{side}_{signal_name}"
                    if signal_key in sent_signals and (now - sent_signals[signal_key] < 3600):
                        continue

                    tp1, tp2, sl = calculate_levels(price, side)

                    pesan = (
                        f"🎯 *ALTFINS {signal_name}*\n\n"
                        f"Koin: *{symbol}*\n"
                        f"Side: `{side}`\n"
                        f"Entry: `{price:.4f}`\n\n"
                        f"🚀 TP1: `{tp1:.4f}`\n"
                        f"🚀 TP2: `{tp2:.4f}`\n"
                        f"🛑 SL: `{sl:.4f}`\n\n"
                        f"_[Sent from Railway Bot]_"
                    )
                    
                    if send_telegram(pesan):
                        sent_signals[signal_key] = now
                        print(f"Sinyal {symbol} berhasil dikirim.")

            else:
                print(f"Kesalahan {signal_name} API: {response.status_code}")
                print(f"Respon Server: {response.text}") # Untuk debug di log Railway

        except Exception as e:
            print(f"Error pada loop {signal_name}: {e}")

# --- EKSEKUSI ---
if __name__ == "__main__":
    print("Bot Sinyal altFINS Berjalan...")
    while True:
        fetch_signals()
        
        # Bersihkan cache lama (lebih dari 24 jam)
        current_time = time.time()
        sent_signals = {k: v for k, v in sent_signals.items() if current_time - v < 86400}
        
        # Tunggu 10 menit sebelum scan lagi
        time.sleep(600)
