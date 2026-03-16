import requests
import time
import os
import threading
from datetime import datetime
from tradingview_ta import TA_Handler, Interval

# --- KONFIGURASI RAILWAY ---
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
WHITELIST_IDS = os.getenv("WHITELIST_IDS", "").split(",")

# Konfigurasi Trading (Optimasi Sensitivitas)
LEVERAGE = 20          
LONG_THRESHOLD = 1.2    # Sinyal muncul jika koin naik 1.2%
SHORT_THRESHOLD = -1.2 
VOL_MIN_USDT = 1000000  # Minimal volume 1 Juta USDT
COOLDOWN_SECONDS = 3600 # 1 jam istirahat per koin agar tidak spam

# Daftar Alamat Binance Cadangan (Solusi untuk "Data Tidak Valid")
BINANCE_ENDPOINTS = [
    "https://fapi.binance.com/fapi/v1/ticker/24hr",
    "https://api.binance.com/fapi/v1/ticker/24hr",
    "https://fapi1.binance.com/fapi/v1/ticker/24hr",
    "https://fapi2.binance.com/fapi/v1/ticker/24hr"
]

# Database RAM
active_positions = {} 
sent_signals = {}
last_update_id = 0

def send_telegram(text, target_id=None):
    if not TOKEN: return
    dest = target_id if target_id else CHAT_ID
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": dest, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

def get_tv_analysis(symbol):
    try:
        handler = TA_Handler(symbol=symbol, exchange="BINANCE", screener="crypto", interval=Interval.INTERVAL_1_HOUR, timeout=10)
        analysis = handler.get_analysis()
        return {
            "summary": analysis.summary['RECOMMENDATION'],
            "rsi": analysis.indicators['RSI'],
            "price": analysis.indicators['close']
        }
    except: return None

def format_signal_message(side, symbol, price, tp, sl, rsi_val):
    emoji = "🟢" if side == "LONG" else "🔴"
    return (f"{emoji} *NEW SIGNAL: {side}*\n__________________________________\n\n"
            f"💎 *Asset:* #{symbol} | `{LEVERAGE}x`\n💵 *Entry:* `{price:.4f}`\n"
            f"🎯 *Target:* `{tp:.4f}`\n🛑 *SL:* `{sl:.4f}`\n📊 *RSI:* `{rsi_val:.2f}`\n"
            f"__________________________________\n\n📈 [TradingView](https://www.tradingview.com/symbols/BINANCE-{symbol}/)")

def handle_commands():
    global last_update_id
    while True:
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
            res = requests.get(url, params={"offset": last_update_id + 1, "timeout": 10}, timeout=15).json()
            if "result" in res:
                for update in res["result"]:
                    last_update_id = update["update_id"]
                    msg = update.get("message", {})
                    text = msg.get("text", "")
                    sid = str(msg.get("from", {}).get("id"))
                    if sid in WHITELIST_IDS and "Analisa" in text:
                        coin = text.split()[-1].upper()
                        sym = coin + "USDT" if "USDT" not in coin else coin
                        data = get_tv_analysis(sym)
                        if data:
                            side = "LONG" if "BUY" in data['summary'] else "SHORT"
                            p = data['price']
                            tp = p * (1.03 if side == "LONG" else 0.97)
                            sl = p * (0.985 if side == "LONG" else 1.015)
                            send_telegram(format_signal_message(side, sym, p, tp, sl, data['rsi']), sid)
        except: pass
        time.sleep(2)

def analyze():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Mencoba memindai market...")
    res = None
    
    # Mencoba alamat cadangan jika alamat utama gagal
    for url in BINANCE_ENDPOINTS:
        try:
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                res = response.json()
                if isinstance(res, list): break
        except: continue

    if not res or not isinstance(res, list):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Gagal: Semua koneksi Binance ditolak.")
        return

    now = time.time()
    count = 0
    
    for coin in res:
        if not isinstance(coin, dict) or 'symbol' not in coin: continue
        symbol = coin['symbol']
        if not symbol.endswith("USDT") or symbol in active_positions: continue
        
        try:
            chg = float(coin.get('priceChangePercent', 0))
            vol = float(coin.get('quoteVolume', 0))
            
            if vol > VOL_MIN_USDT and (chg >= LONG_THRESHOLD or chg <= SHORT_THRESHOLD):
                if symbol in sent_signals and now - sent_signals[symbol] < COOLDOWN_SECONDS: continue
                
                tv = get_tv_analysis(symbol)
                if not tv: continue
                
                side = None
                if chg >= LONG_THRESHOLD and "BUY" in tv['summary']: side = "LONG"
                elif chg <= SHORT_THRESHOLD and "SELL" in tv['summary']: side = "SHORT"
                
                if side:
                    p = tv['price']
                    tp = p * (1.03 if side == "LONG" else 0.97)
                    sl = p * (0.985 if side == "LONG" else 1.015)
                    active_positions[symbol] = {"side": side, "tp": tp, "sl": sl}
                    send_telegram(format_signal_message(side, symbol, p, tp, sl, tv['rsi']))
                    sent_signals[symbol] = now
                    count += 1
        except: continue

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Selesai memindai {len(res)} koin. Ditemukan {count} sinyal.")

if __name__ == "__main__":
    print("Bot Premium v4 (Anti-Blokir) Aktif...")
    threading.Thread(target=handle_commands, daemon=True).start()
    while True:
        analyze()
        time.sleep(60)
