import requests
import time
import os
import threading
from datetime import datetime
from tradingview_ta import TA_Handler, Interval # Library tambahan

# --- KONFIGURASI RAILWAY ---
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
# Format di Railway: ID1,ID2 (Tanpa spasi, pisahkan dengan koma)
WHITELIST_IDS = os.getenv("WHITELIST_IDS", "").split(",")

# Konfigurasi Trading
LEVERAGE = 20          
LONG_THRESHOLD = 5.0   
SHORT_THRESHOLD = -5.0 
VOL_MIN_USDT = 5000000 
COOLDOWN_SECONDS = 28800 

BINANCE_URLS = ["https://api1.binance.com", "https://api2.binance.com", "https://api3.binance.com", "https://data-api.binance.vision"]

# Database RAM
active_positions = {} 
sent_signals = {}
daily_stats = {"tp": 0, "sl": 0, "total_roe": 0.0}
last_report_date = datetime.now().date()
last_update_id = 0

def send_telegram(text, target_id=None, reply_markup=None):
    if not TOKEN: return
    dest = target_id if target_id else CHAT_ID
    if not dest: return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": dest, 
        "text": text, 
        "parse_mode": "Markdown",
        "disable_web_page_preview": False 
    }
    if reply_markup: payload["reply_markup"] = reply_markup
    try:
        requests.post(url, json=payload, timeout=10)
    except: pass

def get_main_menu():
    return {
        "keyboard": [
            [{"text": "📊 Cek Status"}, {"text": "🔍 Analisa BTC"}],
            [{"text": "📈 Analisa ETH"}, {"text": "🚀 Analisa SOL"}]
        ],
        "resize_keyboard": True, "one_time_keyboard": False
    }

def call_binance(endpoint):
    for base_url in BINANCE_URLS:
        try:
            url = f"{base_url}{endpoint}"
            res = requests.get(url, timeout=10)
            if res.status_code == 200: return res.json()
        except: continue
    return None

def get_tv_analysis(symbol):
    """Mengambil rangkuman indikator dari TradingView"""
    try:
        handler = TA_Handler(
            symbol=symbol,
            exchange="BINANCE",
            screener="crypto",
            interval=Interval.INTERVAL_1_HOUR,
            timeout=10
        )
        analysis = handler.get_analysis()
        return {
            "summary": analysis.summary['RECOMMENDATION'],
            "rsi": analysis.indicators['RSI'],
            "price": analysis.indicators['close']
        }
    except:
        return None

def format_signal_message(side, symbol, price, tp, sl, rsi_val, mode="SIGNAL"):
    emoji_side = "🟢" if side == "LONG" else "🔴"
    msg = (
        f"{emoji_side} *NEW {mode}: {side}*\n"
        f"__________________________________\n\n"
        f"💎 *Asset:* #{symbol} | Cross `{LEVERAGE}x`\n"
        f"💵 *Entry:* `{price:.4f}`\n\n"
        f"🎯 *Target (ROE 60%):* `{tp:.4f}`\n"
        f"🛑 *Stop Loss:* `{sl:.4f}`\n"
        f"📊 *RSI (1h):* `{rsi_val:.2f}`\n"
        f"__________________________________\n\n"
        f"📈 [Chart TradingView](https://www.tradingview.com/symbols/BINANCE-{symbol}/)"
    )
    return msg

def handle_commands():
    global last_update_id
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    while True:
        try:
            response = requests.get(url, params={"offset": last_update_id + 1, "timeout": 5}, timeout=10).json()
            if not response.get("result"): continue
            for update in response["result"]:
                last_update_id = update["update_id"]
                message = update.get("message", {})
                text = message.get("text", "")
                sender_id = str(message.get("from", {}).get("id"))
                
                if not text or not sender_id: continue

                if sender_id not in WHITELIST_IDS:
                    if text == "/start":
                        send_telegram(f"❌ *AKSES DITOLAK*", sender_id)
                    continue 

                if text == "/start":
                    send_telegram("👋 *Akses Premium Aktif!*", sender_id, get_main_menu())

                elif text == "📊 Cek Status" or text == "/status":
                    msg = "📋 *Posisi Aktif:*\n" + "\n".join([f"• {s}" for s in active_positions.keys()]) if active_positions else "📭 *Kosong.*"
                    send_telegram(msg, sender_id, get_main_menu())

                elif "Analisa" in text or text.startswith("/analisa"):
                    coin = text.replace("🔍 Analisa ", "").replace("📈 Analisa ", "").replace("🚀 Analisa ", "").replace("/analisa ", "").upper().strip()
                    sym = coin + ("USDT" if not coin.endswith("USDT") else "")
                    
                    data = get_tv_analysis(sym)
                    if not data:
                        send_telegram(f"❌ Koin {sym} tidak ditemukan.", sender_id)
                        continue
                    
                    p = data['price']; rsi = data['rsi']
                    side = "LONG" if "BUY" in data['summary'] else "SHORT"
                    tp = p * (1.03 if side == "LONG" else 0.97); sl = p * (0.985 if side == "LONG" else 1.015)
                    msg = format_signal_message(side, sym, p, tp, sl, rsi, mode="ANALYZE")
                    send_telegram(msg, sender_id, get_main_menu())
        except: time.sleep(2)

def track_prices(current_data):
    global active_positions, daily_stats, sent_signals
    to_remove = []
    for symbol, pos in active_positions.items():
        coin = next((c for c in current_data if c['symbol'] == symbol), None)
        if not coin: continue
        curr = float(coin['lastPrice'])
        status = None
        if pos['side'] == "LONG":
            if curr >= pos['tp']: status = "✅ TAKE PROFIT HIT"
            elif curr <= pos['sl']: status = "❌ STOP LOSS HIT"
        else:
            if curr <= pos['tp']: status = "✅ TAKE PROFIT HIT"
            elif curr >= pos['sl']: status = "❌ STOP LOSS HIT"
        if status:
            raw_pnl = ((curr - pos['entry']) / pos['entry']) * (1 if pos['side'] == "LONG" else -1)
            roe = raw_pnl * LEVERAGE * 100
            daily_stats['tp' if "PROFIT" in status else 'sl'] += 1
            daily_stats['total_roe'] += roe
            
            icon = "💰" if "PROFIT" in status else "💸"
            msg = (f"{icon} *{status}*\n\nAsset: *{symbol}*\nROE: `{roe:+.2f}%` 🚀")
            send_telegram(msg)
            sent_signals[symbol] = time.time()
            to_remove.append(symbol)
    for sym in to_remove:
        if sym in active_positions: del active_positions[sym]

def analyze():
    global last_report_date
    if datetime.now().date() > last_report_date:
        total = daily_stats['tp'] + daily_stats['sl']
        winrate = (daily_stats['tp'] / total * 100) if total > 0 else 0
        report = (f"📊 *DAILY REPORT*\nWin Rate: `{winrate:.1f}%`\nROE: `{daily_stats['total_roe']:+.2f}%`")
        send_telegram(report)
        daily_stats.update({"tp": 0, "sl": 0, "total_roe": 0.0})
        last_report_date = datetime.now().date()

    # Get Binance Prices
    data = call_binance("/fapi/v1/ticker/24hr") 
    if not data: return
    track_prices(data)
    now = time.time()
    
    for coin in data:
        symbol = coin['symbol']
        if not symbol.endswith("USDT") or symbol in active_positions: continue
        try:
            change = float(coin['priceChangePercent']); vol = float(coin['quoteVolume'])
            if vol < VOL_MIN_USDT: continue
            
            if change >= LONG_THRESHOLD or change <= SHORT_THRESHOLD:
                if (symbol in sent_signals and now - sent_signals[symbol] < COOLDOWN_SECONDS): continue
                
                tv = get_tv_analysis(symbol)
                if not tv: continue
                
                side = None
                if change >= LONG_THRESHOLD and "BUY" in tv['summary']: side = "LONG"
                elif change <= SHORT_THRESHOLD and "SELL" in tv['summary']: side = "SHORT"
                
                if side:
                    price = tv['price']; rsi_val = tv['rsi']
                    tp = price * (1.03 if side == "LONG" else 0.97)
                    sl = price * (0.985 if side == "LONG" else 1.015)
                    active_positions[symbol] = {"side": side, "entry": price, "tp": tp, "sl": sl}
                    send_telegram(format_signal_message(side, symbol, price, tp, sl, rsi_val))
        except: continue

    # Log Pengecekan (Diletakkan di luar loop 'for' agar rapi)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Memindai {len(data)} koin... Status: Standby mencari sinyal.")

if __name__ == "__main__":
    print("Bot Premium v4 + TradingView Aktif...")
    threading.Thread(target=handle_commands, daemon=True).start()
    while True:
        analyze()
        time.sleep(60)
