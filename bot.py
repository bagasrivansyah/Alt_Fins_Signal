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

# --- DATABASE RAM (NON-SQLITE) ---
active_positions = {} 
sent_signals = {}
daily_stats = {"tp": 0, "sl": 0, "total_roe": 0.0}
current_day = datetime.now().strftime('%Y-%m-%d')

# --- FORMATTING TOOL ---
def format_price(price):
    if price == 0: return "0"
    if price >= 1000:
        return f"{price:,.2f}"
    elif price >= 1:
        return f"{price:.4f}"
    elif price >= 0.01:
        return f"{price:.6f}"
    else:
        return f"{price:.8f}"

def generate_ascii_chart(side, price, tp, sl):
    p_f, tp_f, sl_f = format_price(price), format_price(tp), format_price(sl)
    if side == "LONG":
        chart = (f"```\n📈 TARGET VISUAL\nTP  ─── {tp_f}\n         ▲\nENT ─── {p_f}\n         ▲\nSL  ─── {sl_f}\n```")
    else:
        chart = (f"```\n📉 TARGET VISUAL\nSL  ─── {sl_f}\n         ▼\nENT ─── {p_f}\n         ▼\nTP  ─── {tp_f}\n```")
    return chart

# --- FUNGSI TELEGRAM ---
def send_telegram(text, target_id=None, reply_markup=None):
    if not TOKEN: return
    dest = target_id if target_id else CHAT_ID
    if not dest: return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": dest, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}
    if reply_markup: payload["reply_markup"] = reply_markup
    try:
        requests.post(url, json=payload, timeout=15)
    except: pass

def get_main_menu():
    return {
        "keyboard": [[{"text": "📊 Cek Status"}, {"text": "📈 Laporan Hari Ini"}],
                     [{"text": "🔍 Analisa BTC"}, {"text": "🚀 Analisa SOL"}]],
        "resize_keyboard": True
    }

# --- FUNGSI BINANCE ---
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

# --- LOGIKA CORE ---
def track_prices(current_data):
    global active_positions, daily_stats
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
            sent_signals[symbol] = time.time()
            to_remove.append(symbol)
            
            icon = "💰" if hit == "TP" else "💸"
            send_telegram(f"{icon} *{hit} HIT*\n\nAsset: *{symbol}*\nROE: `{roe:+.2f}%` 🚀")
            
    for sym in to_remove:
        if sym in active_positions: del active_positions[sym]

def analyze_market():
    data = call_binance("/api/v3/ticker/24hr")
    if not data: return
    track_prices(data)
    now = time.time()
    
    for coin in data:
        symbol = coin['symbol']
        if not symbol.endswith("USDT") or symbol in active_positions: continue
        if symbol in sent_signals and (now - sent_signals[symbol] < COOLDOWN_SECONDS): continue
        
        try:
            change = float(coin['priceChangePercent'])
            vol = float(coin['quoteVolume'])
            if vol < VOL_MIN_USDT: continue
            
            side = "LONG" if change >= LONG_THRESHOLD else "SHORT" if change <= SHORT_THRESHOLD else None
            if side:
                rsi_val = get_rsi(symbol)
                if rsi_val is None or (side == "LONG" and rsi_val > 65) or (side == "SHORT" and rsi_val < 35): continue
                
                price = float(coin['lastPrice'])
                tp = price * (1.03 if side == "LONG" else 0.97)
                sl = price * (0.985 if side == "LONG" else 1.015)
                
                active_positions[symbol] = {"side": side, "entry": price, "tp": tp, "sl": sl}
                
                msg = (f"{'🟢' if side == 'LONG' else '🔴'} *NEW SIGNAL: {side}*\n"
                       f"__________________________________\n\n"
                       f"💎 *Asset:* #{symbol} | `Cross {LEVERAGE}x`\n"
                       f"💵 *Entry:* `{format_price(price)}` | RSI: `{rsi_val:.2f}`\n"
                       f"__________________________________\n"
                       f"{generate_ascii_chart(side, price, tp, sl)}\n"
                       f"📈 [Chart TradingView](https://www.tradingview.com/symbols/BINANCE-{symbol}/)")
                send_telegram(msg)
        except: continue

# --- HANDLER COMMANDS ---
def command_loop():
    last_id = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
            res = requests.get(url, params={"offset": last_id + 1, "timeout": 10}).json()
            if not res.get("result"): continue
            for upd in res["result"]:
                last_id, msg = upd["update_id"], upd.get("message", {})
                txt, uid = msg.get("text", ""), str(msg.get("from", {}).get("id"))
                if uid not in WHITELIST_IDS: continue
                
                if txt == "/start":
                    send_telegram("👋 *Bot RAM v5.4 Aktif!*", uid, get_main_menu())
                elif txt == "📊 Cek Status":
                    res_txt = "📋 *Posisi Aktif:*\n" + "\n".join([f"• {s} ({d['side']})" for s, d in active_positions.items()]) if active_positions else "📭 Kosong"
                    send_telegram(res_txt, uid)
                elif txt == "📈 Laporan Hari Ini":
                    total = daily_stats['tp'] + daily_stats['sl']
                    wr = (daily_stats['tp']/total*100) if total > 0 else 0
                    send_telegram(f"📊 *Progress Hari Ini:*\n✅ TP: {daily_stats['tp']} | ❌ SL: {daily_stats['sl']}\n📈 Winrate: {wr:.1f}%\n💰 Total ROE: {daily_stats['total_roe']:+.2f}%", uid)
        except: pass
        time.sleep(2)

if __name__ == "__main__":
    print("Bot RAM Premium v5.4 Running...")
    threading.Thread(target=command_loop, daemon=True).start()
    while True:
        try:
            now_day = datetime.now().strftime('%Y-%m-%d')
            if now_day != current_day:
                send_telegram(f"📊 *DAILY REPORT*\nTP: {daily_stats['tp']} | SL: {daily_stats['sl']}\nROE: {daily_stats['total_roe']:+.2f}%")
                daily_stats = {"tp": 0, "sl": 0, "total_roe": 0.0}
                current_day = now_day
            analyze_market()
        except: pass
        time.sleep(60)
