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
LONG_THRESHOLD = 1.2    # Sinyal muncul jika naik 1.2%
SHORT_THRESHOLD = -1.2 
VOL_MIN_USDT = 1000000  # 1 Juta USDT agar koin potensial terbaca
COOLDOWN_SECONDS = 3600 # 1 jam cooldown per koin

BINANCE_URLS = ["https://fapi.binance.com", "https://api.binance.com/fapi"]

# Database RAM
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

def format_signal_message(side, symbol, price, tp, sl, rsi_val, mode="SIGNAL"):
    emoji = "🟢" if side == "LONG" else "🔴"
    return (f"{emoji} *NEW {mode}: {side}*\n__________________________________\n\n"
            f"💎 *Asset:* #{symbol} | `{LEVERAGE}x`\n💵 *Entry:* `{price:.4f}`\n"
            f"🎯 *Target:* `{tp:.4f}`\n🛑 *SL:* `{sl:.4f}`\n📊 *RSI:* `{rsi_val:.2f}`\n"
            f"__________________________________\n\n📈 [TradingView](https://www.tradingview.com/symbols/BINANCE-{symbol}/)")

def handle_commands():
    global last_update_id
    while True:
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
            res = requests.get(url, params={"offset": last_update_id + 1, "timeout": 10}).json()
            for update in res.get("result", []):
                last_update_id = update["update_id"]
                msg = update.get("message", {})
                text = msg.get("text", "")
                sid = str(msg.get("from", {}).get("id"))
                if sid in WHITELIST_IDS:
                    if text == "/start":
                        send_telegram("👋 Bot Aktif & Siaga!", sid, get_main_menu())
                    elif "Analisa" in text:
                        coin = text.split()[-1].upper()
                        sym = coin + "USDT" if "USDT" not in coin else coin
                        data = get_tv_analysis(sym)
                        if data:
                            side = "LONG" if "BUY" in data['summary'] else "SHORT"
                            p = data['price']
                            tp = p * (1.03 if side == "LONG" else 0.97)
                            sl = p * (0.985 if side == "LONG" else 1.015)
                            send_telegram(format_signal_message(side, sym, p, tp, sl, data['rsi'], "ANALYZE"), sid)
        except: pass
        time.sleep(1)

def analyze():
    global last_report_date
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Memulai pemindaian market...")
    
    try:
        # Ambil harga Futures 24h
        res = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=10).json()
        now = time.time()
        
        for coin in res:
            symbol = coin['symbol']
            if not symbol.endswith("USDT") or symbol in active_positions: continue
            
            chg = float(coin['priceChangePercent'])
            vol = float(coin['quoteVolume'])
            
            if vol > VOL_MIN_USDT and (chg >= LONG_THRESHOLD or chg <= SHORT_THRESHOLD):
                if symbol in sent_signals and now - sent_signals[symbol] < COOLDOWN_SECONDS: continue
                
                tv = get_tv_analysis(symbol)
                if not tv: continue
                
                side = "LONG" if (chg >= LONG_THRESHOLD and "BUY" in tv['summary']) else "SHORT" if (chg <= SHORT_THRESHOLD and "SELL" in tv['summary']) else None
                if side:
                    p = tv['price']
                    tp = p * (1.03 if side == "LONG" else 0.97)
                    sl = p * (0.985 if side == "LONG" else 1.015)
                    active_positions[symbol] = {"side": side, "tp": tp, "sl": sl}
                    send_telegram(format_signal_message(side, symbol, p, tp, sl, tv['rsi']))
                    sent_signals[symbol] = now
                    
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Scan selesai. Memantau {len(res)} koin.")
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Error: {e}")

if __name__ == "__main__":
    print("Bot Premium v4 (Optimized) Aktif...")
    # Jalankan Telegram handle di jalur berbeda agar tidak macet
    threading.Thread(target=handle_commands, daemon=True).start()
    
    while True:
        analyze()
        time.sleep(60) # Scan ulang setiap 60 detik
