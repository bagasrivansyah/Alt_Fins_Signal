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
VOL_MIN_USDT = 1000000 
COOLDOWN_SECONDS = 3600 

# BYPASS URLS (Untuk menghindari blokir IP Railway)
BINANCE_FUTURES_BYPASS = ["https://fapi.binance.com", "https://api.binance.com/fapi", "https://fapi1.binance.com", "https://fapi2.binance.com"]
BINANCE_SPOT_BYPASS = ["https://api1.binance.com", "https://api2.binance.com", "https://api3.binance.com", "https://data-api.binance.vision"]

active_positions = {} 
sent_signals = {}
last_update_id = 0

def call_binance_bypass(endpoints, path):
    """Fungsi untuk mencoba berbagai API bypass jika satu gagal"""
    for base in endpoints:
        try:
            url = f"{base}{path}"
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                return res.json()
        except:
            continue
    return None

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

def format_premium_message(side, symbol, price, tp, sl, rsi_val, mode="SIGNAL"):
    emoji_side = "🟢" if side == "LONG" else "🔴"
    msg = (
        f"{emoji_side} *NEW {mode}: {side}*\n"
        f"__________________________________\n\n"
        f"💎 *Asset:* #{symbol} | Cross `{LEVERAGE}x`\n"
        f"💵 *Entry:* `{price:.6f}`\n\n"
        f"🎯 *Target (ROE 60%):* `{tp:.6f}`\n"
        f"🛑 *Stop Loss:* `{sl:.6f}`\n"
        f"📊 *RSI (1h):* `{rsi_val:.2f}`\n"
        f"__________________________________\n\n"
        f"📈 [Chart TradingView](https://www.tradingview.com/symbols/BINANCE-{symbol}/)"
    )
    return msg

def get_binance_data_bypass(coin_name):
    coin = coin_name.upper().strip().replace("USDT", "")
    search_list = [f"{coin}USDT", f"1000{coin}USDT"]
    
    # 1. Cek Futures via Bypass
    for s in search_list:
        data = call_binance_bypass(BINANCE_FUTURES_BYPASS, f"/fapi/v1/ticker/price?symbol={s}")
        if data and 'price' in data:
            return s, float(data['price']), "FUTURES"

    # 2. Cek Spot via Bypass
    data = call_binance_bypass(BINANCE_SPOT_BYPASS, f"/api/v3/ticker/price?symbol={coin}USDT")
    if data and 'price' in data:
        return f"{coin}USDT", float(data['price']), "SPOT"
    
    return None, None, None

def get_rsi_bypass(symbol, market_type="FUTURES"):
    endpoints = BINANCE_FUTURES_BYPASS if market_type == "FUTURES" else BINANCE_SPOT_BYPASS
    path = f"/fapi/v1/klines?symbol={symbol}&interval=1h&limit=50" if market_type == "FUTURES" else f"/api/v3/klines?symbol={symbol}&interval=1h&limit=50"
    
    data = call_binance_bypass(endpoints, path)
    if not data: return 50
    try:
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
            if sender_id not in WHITELIST_IDS: continue

            if text == "/start":
                send_telegram("👋 *Bot Premium Aktif!*", sender_id, get_main_menu())
            elif "Analisa" in text or text.startswith("/analisa"):
                coin_raw = text.replace("🔍 Analisa ", "").replace("📈 Analisa ", "").replace("🚀 Analisa ", "").replace("/analisa ", "").strip()
                sym, price, market = get_binance_data_bypass(coin_raw)
                if sym:
                    rsi_v = get_rsi_bypass(sym, market)
                    side = "LONG" if rsi_v < 50 else "SHORT"
                    tp = price * (1.03 if side == "LONG" else 0.97)
                    sl = price * (0.985 if side == "LONG" else 1.015)
                    send_telegram(format_premium_message(side, sym, price, tp, sl, rsi_v, "ANALYZE"), sender_id)
                else:
                    send_telegram(f"❌ Koin `{coin_raw}` tidak ditemukan.", sender_id)
    except: pass

def scan_market_bypass():
    global sent_signals
    # Gunakan bypass untuk mengambil data 24 jam
    data = call_binance_bypass(BINANCE_FUTURES_BYPASS, "/fapi/v1/ticker/24hr")
    if not data: return
    
    now = time.time()
    for coin in data:
        try:
            symbol = coin['symbol']
            if not symbol.endswith("USDT"): continue
            change = float(coin['priceChangePercent'])
            vol = float(coin['quoteVolume'])
            
            if vol > VOL_MIN_USDT and (change >= LONG_THRESHOLD or change <= SHORT_THRESHOLD):
                if symbol in sent_signals and (now - sent_signals[symbol] < COOLDOWN_SECONDS):
                    continue
                
                price = float(coin['lastPrice'])
                rsi_v = get_rsi_bypass(symbol, "FUTURES")
                
                side = None
                if change >= LONG_THRESHOLD and rsi_v < 70: side = "LONG"
                elif change <= SHORT_THRESHOLD and rsi_v > 30: side = "SHORT"
                
                if side:
                    tp = price * (1.03 if side == "LONG" else 0.97)
                    sl = price * (0.985 if side == "LONG" else 1.015)
                    send_telegram(format_premium_message(side, symbol, price, tp, sl, rsi_v, "SIGNAL"))
                    sent_signals[symbol] = now
        except: continue

if __name__ == "__main__":
    print("Bot Premium Bypass v7 Aktif...")
    threading.Thread(target=lambda: [handle_commands() or time.sleep(1) for _ in iter(int, 1)], daemon=True).start()
    while True:
        scan_market_bypass()
        time.sleep(30)
