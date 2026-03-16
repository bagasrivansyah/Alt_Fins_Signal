import requests
import time
import os
import threading
from datetime import datetime

# --- KONFIGURASI RAILWAY ---
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
WHITELIST_IDS = os.getenv("WHITELIST_IDS", "").split(",")

# Konfigurasi Trading
LEVERAGE = 20          
LONG_THRESHOLD = 5.0   
SHORT_THRESHOLD = -5.0 
VOL_MIN_USDT = 5000000 
COOLDOWN_SECONDS = 28800 

# Endpoint Binance
FUTURES_URL = "https://fapi.binance.com"
SPOT_URL = "https://api.binance.com"

active_positions = {} 
sent_signals = {}
daily_stats = {"tp": 0, "sl": 0, "total_roe": 0.0}
last_report_date = datetime.now().date()
last_update_id = 0

def send_telegram(text, target_id=None, reply_markup=None):
    if not TOKEN: return
    dest = target_id if target_id else CHAT_ID
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": dest, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": False}
    if reply_markup: payload["reply_markup"] = reply_markup
    try: requests.post(url, json=payload, timeout=10)
    except: pass

def get_main_menu():
    return {
        "keyboard": [[{"text": "📊 Cek Status"}, {"text": "🔍 Analisa BTC"}],
                     [{"text": "📈 Analisa ETH"}, {"text": "🚀 Analisa SOL"}]],
        "resize_keyboard": True
    }

def get_binance_data(coin_name):
    """Fungsi sakti mencari koin di semua market Binance"""
    coin = coin_name.upper().strip()
    # Daftar kemungkinan penulisan di API
    search_list = [f"{coin}USDT", f"1000{coin}USDT"]
    
    # 1. Cek di Futures (Prioritas Utama)
    for s in search_list:
        try:
            res = requests.get(f"{FUTURES_URL}/fapi/v1/ticker/price?symbol={s}", timeout=5).json()
            if 'price' in res:
                return s, float(res['price']), "FUTURES"
        except: continue

    # 2. Cek di Spot (Jika di Futures tidak ada)
    try:
        res = requests.get(f"{SPOT_URL}/api/v3/ticker/price?symbol={coin}USDT", timeout=5).json()
        if 'price' in res:
            return f"{coin}USDT", float(res['price']), "SPOT"
    except: pass
    
    return None, None, None

def get_rsi(symbol, market_type):
    base_url = FUTURES_URL if market_type == "FUTURES" else SPOT_URL
    endpoint = "/fapi/v1/klines" if market_type == "FUTURES" else "/api/v3/klines"
    try:
        data = requests.get(f"{base_url}{endpoint}?symbol={symbol}&interval=1h&limit=100", timeout=5).json()
        closes = [float(x[4]) for x in data]
        deltas = [closes[i+1]-closes[i] for i in range(len(closes)-1)]
        up = [x if x > 0 else 0 for x in deltas]; down = [abs(x) if x < 0 else 0 for x in deltas]
        avg_gain = sum(up[-14:])/14; avg_loss = sum(down[-14:])/14
        if avg_loss == 0: return 100
        return 100 - (100 / (1 + (avg_gain/avg_loss)))
    except: return 50

def handle_commands():
    global last_update_id
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    try:
        res = requests.get(url, params={"offset": last_update_id + 1, "timeout": 5}).json()
        for update in res.get("result", []):
            last_update_id = update["update_id"]
            msg = update.get("message", {})
            text = msg.get("text", "")
            sender_id = str(msg.get("from", {}).get("id"))

            if sender_id not in WHITELIST_IDS:
                if text == "/start": send_telegram(f"❌ Akses Ditolak\nID Anda: `{sender_id}`", sender_id)
                continue

            if text == "/start":
                send_telegram("👋 *Akses Premium Aktif!*", sender_id, get_main_menu())
            
            elif "Analisa" in text or text.startswith("/analisa"):
                coin_raw = text.replace("🔍 Analisa ", "").replace("📈 Analisa ", "").replace("🚀 Analisa ", "").replace("/analisa ", "").strip()
                
                sym, price, market = get_binance_data(coin_raw)
                
                if not sym:
                    send_telegram(f"❌ Koin `{coin_raw}` tidak ditemukan di market Spot maupun Futures Binance.", sender_id)
                    continue
                
                rsi_val = get_rsi(sym, market)
                side = "LONG" if rsi_val < 50 else "SHORT"
                tp = price * (1.03 if side == "LONG" else 0.97)
                sl = price * (0.985 if side == "LONG" else 1.015)
                
                # Tampilan Sesuai Gambar yang Anda Mau
                m_info = f"Cross {LEVERAGE}x" if market == "FUTURES" else "SPOT Market"
                resp = (
                    f"{'🟢' if side == 'LONG' else '🔴'} *NEW ANALYZE: {side}*\n"
                    f"__________________________________\n\n"
                    f"💎 *Asset:* #{sym} | `{m_info}`\n"
                    f"💵 *Entry:* `{price:.6f}`\n\n"
                    f"🎯 *Target (ROE 60%):* `{tp:.6f}`\n"
                    f"🛑 *Stop Loss:* `{sl:.6f}`\n"
                    f"📊 *RSI (1h):* `{rsi_val:.2f}`\n"
                    f"__________________________________\n\n"
                    f"📈 [Chart TradingView](https://www.tradingview.com/symbols/BINANCE-{sym}/)"
                )
                send_telegram(resp, sender_id, get_main_menu())
    except: pass

def analyze_market():
    # Scanner otomatis tetap fokus di Futures untuk mencari profit cepat
    try:
        data = requests.get(f"{FUTURES_URL}/fapi/v1/ticker/24hr").json()
        for coin in data:
            symbol = coin['symbol']
            if not symbol.endswith("USDT") or symbol in active_positions: continue
            change = float(coin['priceChangePercent'])
            if abs(change) >= LONG_THRESHOLD:
                price = float(coin['lastPrice'])
                rsi_val = get_rsi(symbol, "FUTURES")
                side = "LONG" if change >= LONG_THRESHOLD and rsi_val < 65 else "SHORT" if change <= SHORT_THRESHOLD and rsi_val > 35 else None
                if side:
                    tp, sl = price * (1.03 if side == "LONG" else 0.97), price * (0.985 if side == "LONG" else 1.015)
                    active_positions[symbol] = {"side": side, "entry": price, "tp": tp, "sl": sl}
                    # Gunakan format visual yang sama untuk sinyal otomatis
                    send_telegram(f"🟢 *AUTO SIGNAL: {side}*\nAsset: #{symbol}\nEntry: `{price}`")
    except: pass

if __name__ == "__main__":
    print("Bot Premium v5 (Multi-Market) Aktif...")
    threading.Thread(target=lambda: [handle_commands() or time.sleep(1) for _ in iter(int, 1)], daemon=True).start()
    while True:
        analyze_market()
        time.sleep(60)
