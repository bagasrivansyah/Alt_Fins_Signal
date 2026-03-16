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

BINANCE_URLS = ["https://api1.binance.com", "https://api2.binance.com", "https://api3.binance.com"]

# Database RAM
active_positions = {} 
sent_signals = {}
daily_stats = {"tp": 0, "sl": 0, "total_roe": 0.0}
last_report_date = datetime.now().date()
last_update_id = 0

# --- HELPER FUNCTIONS ---
def format_price(price):
    """Format desimal dinamis untuk koin micin vs koin besar"""
    if price >= 1000: return f"{price:,.2f}"
    if price >= 1: return f"{price:.4f}"
    if price >= 0.01: return f"{price:.6f}"
    return f"{price:.8f}"

def generate_visual_chart(side, price, tp, sl):
    p_f, tp_f, sl_f = format_price(price), format_price(tp), format_price(sl)
    if side == "LONG":
        return f"```\n📈 TARGET VISUAL\nTP  ─── {tp_f}\n         ▲\nENT ─── {p_f}\n         ▲\nSL  ─── {sl_f}\n```"
    return f"```\n📉 TARGET VISUAL\nSL  ─── {sl_f}\n         ▼\nENT ─── {p_f}\n         ▼\nTP  ─── {tp_f}\n```"

def send_telegram(text, target_id=None, reply_markup=None):
    if not TOKEN: return
    dest = target_id if target_id else CHAT_ID
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": dest, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}
    if reply_markup: payload["reply_markup"] = reply_markup
    try: requests.post(url, json=payload, timeout=10)
    except: pass

def get_main_menu():
    return {
        "keyboard": [[{"text": "📊 Cek Status"}, {"text": "🔍 Analisa BTC"}],
                     [{"text": "📈 Analisa ETH"}, {"text": "🚀 Analisa SOL"}]],
        "resize_keyboard": True
    }

# --- BINANCE DATA ---
def call_binance(endpoint):
    for base_url in BINANCE_URLS:
        try:
            res = requests.get(f"{base_url}{endpoint}", timeout=10)
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

# --- CORE LOGIC ---
def format_signal_message(side, symbol, price, tp, sl, rsi_val, mode="SIGNAL"):
    emoji = "🟢" if side == "LONG" else "🔴"
    chart = generate_visual_chart(side, price, tp, sl)
    msg = (
        f"{emoji} *NEW {mode}: {side}*\n"
        f"__________________________________\n\n"
        f"💎 *Asset:* #{symbol} | `Cross {LEVERAGE}x`\n"
        f"💵 *Entry:* `{format_price(price)}` | RSI: `{rsi_val:.2f}`\n"
        f"__________________________________\n"
        f"{chart}\n"
        f"__________________________________\n\n"
        f"📈 [Chart TradingView](https://www.tradingview.com/symbols/BINANCE-{symbol}/)"
    )
    return msg

def handle_commands():
    global last_update_id
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    try:
        res = requests.get(url, params={"offset": last_update_id + 1, "timeout": 5}, timeout=10).json()
        for upd in res.get("result", []):
            last_update_id = upd["update_id"]
            msg = upd.get("message", {})
            txt = msg.get("text", "")
            sid = str(msg.get("from", {}).get("id"))
            
            if sid not in WHITELIST_IDS: continue

            if txt == "/start":
                send_telegram("👋 *Akses Premium Aktif!*", sid, get_main_menu())

            elif "Cek Status" in txt:
                m = "📋 *Posisi Aktif:*\n" + "\n".join([f"• {s}" for s in active_positions.keys()]) if active_positions else "📭 *Kosong.*"
                send_telegram(m, sid)

            elif "Analisa" in txt:
                # Perbaikan Logika Pembersihan Nama Koin
                coin = txt.replace("🔍", "").replace("📈", "").replace("🚀", "").replace("Analisa", "").strip().upper()
                if not coin: continue
                
                sym = coin if coin.endswith("USDT") else coin + "USDT"
                ticker = call_binance(f"/api/v3/ticker/price?symbol={sym}")
                
                if not ticker:
                    send_telegram(f"❌ Koin *{sym}* tidak ditemukan.", sid)
                    continue
                
                p = float(ticker['price']); rsi = get_rsi(sym)
                side = "LONG" if rsi < 50 else "SHORT"
                tp = p * (1.03 if side == "LONG" else 0.97); sl = p * (0.985 if side == "LONG" else 1.015)
                send_telegram(format_signal_message(side, sym, p, tp, sl, rsi, mode="ANALYZE"), sid)
    except: pass

def track_prices(current_data):
    global active_positions
    to_remove = []
    for symbol, pos in active_positions.items():
        coin = next((c for c in current_data if c['symbol'] == symbol), None)
        if not coin: continue
        curr = float(coin['lastPrice'])
        hit = None
        if pos['side'] == "LONG":
            if curr >= pos['tp']: hit = "TP"
            elif curr <= pos['sl']: hit = "SL"
        else:
            if curr <= pos['tp']: hit = "TP"
            elif curr >= pos['sl']: hit = "SL"
        
        if hit:
            roe = ((curr - pos['entry']) / pos['entry']) * (1 if pos['side'] == "LONG" else -1) * LEVERAGE * 100
            daily_stats['tp' if hit == "TP" else 'sl'] += 1
            daily_stats['total_roe'] += roe
            send_telegram(f"{'💰' if hit == 'TP' else '💸'} *{hit} HIT*\n\nAsset: *{symbol}*\nROE: `{roe:+.2f}%` 🚀")
            sent_signals[symbol] = time.time()
            to_remove.append(symbol)
    for s in to_remove: del active_positions[s]

def analyze_loop():
    global last_report_date
    if datetime.now().date() > last_report_date:
        total = daily_stats['tp'] + daily_stats['sl']
        wr = (daily_stats['tp'] / total * 100) if total > 0 else 0
        send_telegram(f"📊 *DAILY REPORT*\n---\n✅ TP: `{daily_stats['tp']}` | ❌ SL: `{daily_stats['sl']}`\nWin Rate: `{wr:.1f}%` | ROE: `{daily_stats['total_roe']:+.2f}%`")
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
                rsi = get_rsi(symbol)
                if rsi is None or (side == "LONG" and rsi > 65) or (side == "SHORT" and rsi < 35): continue
                p = float(coin['lastPrice'])
                active_positions[symbol] = {"side": side, "entry": p, "tp": p * (1.03 if side == "LONG" else 0.97), "sl": p * (0.985 if side == "LONG" else 1.015)}
                send_telegram(format_signal_message(side, symbol, p, active_positions[symbol]['tp'], active_positions[symbol]['sl'], rsi))
        except: continue

if __name__ == "__main__":
    print("Bot RAM Premium v5 Aktif...")
    threading.Thread(target=lambda: [handle_commands() or time.sleep(1) for _ in iter(int, 1)], daemon=True).start()
    while True:
        analyze_loop()
        time.sleep(60)
