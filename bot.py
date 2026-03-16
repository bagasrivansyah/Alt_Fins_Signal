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

BINANCE_URLS = ["https://api1.binance.com", "https://api2.binance.com", "https://api3.binance.com", "https://data-api.binance.vision"]

# Database RAM
active_positions = {} 
sent_signals = {}
daily_stats = {"tp": 0, "sl": 0, "total_roe": 0.0}
last_report_date = datetime.now().date()
last_update_id = 0

def send_telegram(text, target_id=None, image_url=None, reply_markup=None):
    if not TOKEN: return
    dest = target_id if target_id else CHAT_ID
    if not dest: return

    # Jika ada image_url, gunakan metode sendPhoto
    if image_url:
        url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
        payload = {
            "chat_id": dest,
            "photo": image_url,
            "caption": text,
            "parse_mode": "Markdown"
        }
    else:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        payload = {
            "chat_id": dest, 
            "text": text, 
            "parse_mode": "Markdown",
            "disable_web_page_preview": False 
        }
    
    if reply_markup: payload["reply_markup"] = reply_markup
    
    try:
        requests.post(url, json=payload, timeout=15)
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

def get_rsi(symbol):
    data = call_binance(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=100")
    if not data or not isinstance(data, list): return None
    try:
        closes = [float(x[4]) for x in data]
        deltas = [closes[i+1] - closes[i] for i in range(len(closes)-1)]
        up = [x if x > 0 else 0 for x in deltas]; down = [abs(x) if x < 0 else 0 for x in deltas]
        avg_gain = sum(up[-14:]) / 14; avg_loss = sum(down[-14:]) / 14
        if avg_loss == 0: return 100
        return 100 - (100 / (1 + (avg_gain / avg_loss)))
    except: return None

def format_signal_message(side, symbol, price, tp, sl, rsi_val, mode="SIGNAL"):
    emoji_side = "🟢" if side == "LONG" else "🔴"
    msg = (
        f"{emoji_side} *NEW {mode}: {side}*\n"
        f"__________________________________\n\n"
        f"💎 *Asset:* #{symbol} | Cross `{LEVERAGE}x`\n"
        f"💵 *Entry:* `{price:.4f}`\n\n"
        f"🎯 *Target:* `{tp:.4f}`\n"
        f"🛑 *Stop Loss:* `{sl:.4f}`\n"
        f"📊 *RSI (1h):* `{rsi_val:.2f}`\n"
        f"__________________________________\n"
    )
    return msg

def handle_commands():
    global last_update_id
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    try:
        response = requests.get(url, params={"offset": last_update_id + 1, "timeout": 5}, timeout=10).json()
        if not response.get("result"): return
        for update in response["result"]:
            last_update_id = update["update_id"]
            message = update.get("message", {})
            text = message.get("text", "")
            sender_id = str(message.get("from", {}).get("id"))
            
            if not text or not sender_id: continue

            if sender_id not in WHITELIST_IDS:
                if text == "/start":
                    send_telegram(f"❌ *AKSES DITOLAK*\n\nID: `{sender_id}`", sender_id)
                continue 

            if text == "/start":
                send_telegram("👋 *Akses Premium Aktif!*", sender_id, reply_markup=get_main_menu())

            elif text == "📊 Cek Status" or text == "/status":
                msg = "📋 *Posisi Aktif:*\n" + "\n".join([f"• {s}" for s in active_positions.keys()]) if active_positions else "📭 *Kosong.*"
                send_telegram(msg, sender_id, reply_markup=get_main_menu())

            elif "Analisa" in text or text.startswith("/analisa"):
                coin = text.replace("🔍 Analisa ", "").replace("📈 Analisa ", "").replace("🚀 Analisa ", "").replace("/analisa ", "").upper()
                sym = coin + ("USDT" if not coin.endswith("USDT") else "")
                ticker = call_binance(f"/api/v3/ticker/price?symbol={sym}")
                if not ticker:
                    send_telegram(f"❌ Koin {sym} tidak ditemukan.", sender_id)
                    continue
                p = float(ticker['price']); rsi = get_rsi(sym)
                side = "LONG" if rsi < 50 else "SHORT"
                tp = p * (1.03 if side == "LONG" else 0.97); sl = p * (0.985 if side == "LONG" else 1.015)
                
                chart_url = f"https://s3.tradingview.com/external-embedding/embed-widget-mini-symbol-overview.png?symbol=BINANCE:{sym}&theme=dark"
                msg = format_signal_message(side, sym, p, tp, sl, rsi, mode="ANALYZE")
                send_telegram(msg, sender_id, image_url=chart_url, reply_markup=get_main_menu())
    except: pass

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
            msg = (
                f"{icon} *{status}*\n\n"
                f"Asset: *{symbol}*\n"
                f"Side: *{pos['side']}* | ROE: `{roe:+.2f}%` 🚀"
            )
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
        report = (
            f"📊 *DAILY REPORT*\n"
            f"__________________________________\n\n"
            f"✅ TP: `{daily_stats['tp']}` | ❌ SL: `{daily_stats['sl']}`\n"
            f"📈 Win Rate: `{winrate:.1f}%` | ROE: `{daily_stats['total_roe']:+.2f}%`"
        )
        send_telegram(report)
        daily_stats.update({"tp": 0, "sl": 0, "total_roe": 0.0})
        last_report_date = datetime.now().date()

    data = call_binance("/api/v3/ticker/24hr")
    if not data: return
    track_prices(data)
    now = time.time()
    for coin in data:
        symbol = coin['symbol']
        if not symbol.endswith("USDT") or symbol in active_positions: continue
        try:
            change = float(coin['priceChangePercent']); vol = float(coin['quoteVolume'])
            if vol < VOL_MIN_USDT: continue
            side = "LONG" if change >= LONG_THRESHOLD else "SHORT" if change <= SHORT_THRESHOLD else None
            if side:
                if (symbol in sent_signals and now - sent_signals[symbol] < COOLDOWN_SECONDS): continue
                rsi_val = get_rsi(symbol)
                if rsi_val is None or (side == "LONG" and rsi_val > 65) or (side == "SHORT" and rsi_val < 35): continue
                
                price = float(coin['lastPrice'])
                tp = price * (1.03 if side == "LONG" else 0.97)
                sl = price * (0.985 if side == "LONG" else 1.015)
                active_positions[symbol] = {"side": side, "entry": price, "tp": tp, "sl": sl}
                
                chart_url = f"https://s3.tradingview.com/external-embedding/embed-widget-mini-symbol-overview.png?symbol=BINANCE:{symbol}&theme=dark"
                send_telegram(format_signal_message(side, symbol, price, tp, sl, rsi_val), image_url=chart_url)
        except: continue

if __name__ == "__main__":
    print("Bot Final Premium v4 (Image Mode) Aktif...")
    threading.Thread(target=lambda: [handle_commands() or time.sleep(1) for _ in iter(int, 1)], daemon=True).start()
    while True:
        analyze()
        time.sleep(60)