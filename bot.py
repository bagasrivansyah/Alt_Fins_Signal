import requests
import time
import os
import threading
import sqlite3
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

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS active_positions 
                 (symbol TEXT PRIMARY KEY, side TEXT, entry REAL, tp REAL, sl REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS sent_signals 
                 (symbol TEXT PRIMARY KEY, timestamp REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS daily_stats 
                 (date TEXT PRIMARY KEY, tp INTEGER, sl INTEGER, total_roe REAL)''')
    conn.commit()
    conn.close()

def get_db_connection():
    return sqlite3.connect('bot_data.db', check_same_thread=False)

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

# --- FUNGSI TELEGRAM ---
def send_telegram(text, target_id=None, reply_markup=None):
    if not TOKEN: return
    dest = target_id if target_id else CHAT_ID
    if not dest: return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": dest, 
        "text": text, 
        "parse_mode": "Markdown",
        "disable_web_page_preview": True 
    }
    if reply_markup: payload["reply_markup"] = reply_markup
    try:
        requests.post(url, json=payload, timeout=15)
    except: pass

def get_main_menu():
    return {
        "keyboard": [
            [{"text": "📊 Cek Status"}, {"text": "📈 Laporan Hari Ini"}],
            [{"text": "🔍 Analisa BTC"}, {"text": "🚀 Analisa SOL"}]
        ],
        "resize_keyboard": True
    }

# --- FUNGSI LAPORAN ---
def send_daily_report(date_str):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT tp, sl, total_roe FROM daily_stats WHERE date = ?", (date_str,))
    row = c.fetchone()
    conn.close()

    if row:
        tp, sl, roe = row
        total = tp + sl
        winrate = (tp / total * 100) if total > 0 else 0
        msg = (
            f"📊 *DAILY PERFORMANCE REPORT*\n"
            f"📅 Tanggal: `{date_str}`\n"
            f"__________________________________\n\n"
            f"✅ Take Profit: `{tp}`\n"
            f"❌ Stop Loss: `{sl}`\n"
            f"📈 Win Rate: `{winrate:.1f}%`\n"
            f"💰 Total ROE: `{roe:+.2f}%`\n"
            f"__________________________________\n\n"
            f"🔥 *Tetap Disiplin & Happy Trading!*"
        )
        send_telegram(msg)

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
        up = [x if x > 0 else 0 for x in deltas]
        down = [abs(x) if x < 0 else 0 for x in deltas]
        avg_gain = sum(up[-14:]) / 14
        avg_loss = sum(down[-14:]) / 14
        if avg_loss == 0: return 100
        return 100 - (100 / (1 + (avg_gain / avg_loss)))
    except: return None

# --- LOGIKA CORE ---
def track_prices(current_data):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM active_positions")
    positions = c.fetchall()
    today = datetime.now().strftime('%Y-%m-%d')
    
    for symbol, side, entry, tp, sl in positions:
        coin = next((c for c in current_data if c['symbol'] == symbol), None)
        if not coin: continue
        
        curr = float(coin['lastPrice'])
        hit = None
        if side == "LONG":
            if curr >= tp: hit = "TP"
            elif curr <= sl: hit = "SL"
        else:
            if curr <= tp: hit = "TP"
            elif curr >= sl: hit = "SL"
            
        if hit:
            raw_pnl = ((curr - entry) / entry) * (1 if side == "LONG" else -1)
            roe = raw_pnl * LEVERAGE * 100
            
            c.execute("INSERT OR IGNORE INTO daily_stats VALUES (?, 0, 0, 0.0)", (today,))
            if hit == "TP":
                c.execute("UPDATE daily_stats SET tp = tp + 1, total_roe = total_roe + ? WHERE date = ?", (roe, today))
            else:
                c.execute("UPDATE daily_stats SET sl = sl + 1, total_roe = total_roe + ? WHERE date = ?", (roe, today))
            
            c.execute("DELETE FROM active_positions WHERE symbol = ?", (symbol,))
            c.execute("INSERT OR REPLACE INTO sent_signals VALUES (?, ?)", (symbol, time.time()))
            
            status_txt = "✅ TAKE PROFIT HIT" if hit == "TP" else "❌ STOP LOSS HIT"
            icon = "💰" if hit == "TP" else "💸"
            send_telegram(f"{icon} *{status_txt}*\n\nAsset: *{symbol}*\nSide: *{side}*\nROE: `{roe:+.2f}%` 🚀")
            
    conn.commit()
    conn.close()

def analyze_market():
    conn = get_db_connection()
    c = conn.cursor()
    data = call_binance("/api/v3/ticker/24hr")
    if not data: return
    
    track_prices(data)
    now = time.time()
    
    for coin in data:
        symbol = coin['symbol']
        if not symbol.endswith("USDT"): continue
        
        c.execute("SELECT 1 FROM active_positions WHERE symbol = ?", (symbol,))
        if c.fetchone(): continue
        
        c.execute("SELECT timestamp FROM sent_signals WHERE symbol = ?", (symbol,))
        last_sent = c.fetchone()
        if last_sent and (now - last_sent[0] < COOLDOWN_SECONDS): continue
        
        try:
            change = float(coin['priceChangePercent'])
            vol = float(coin['quoteVolume'])
            if vol < VOL_MIN_USDT: continue
            
            side = "LONG" if change >= LONG_THRESHOLD else "SHORT" if change <= SHORT_THRESHOLD else None
            if side:
                rsi_val = get_rsi(symbol)
                if rsi_val is None: continue
                if (side == "LONG" and rsi_val > 65) or (side == "SHORT" and rsi_val < 35): continue
                
                price = float(coin['lastPrice'])
                tp = price * (1.03 if side == "LONG" else 0.97)
                sl = price * (0.985 if side == "LONG" else 1.015)
                
                c.execute("INSERT INTO active_positions VALUES (?, ?, ?, ?, ?)", (symbol, side, price, tp, sl))
                conn.commit()
                
                p_f, tp_f, sl_f = format_price(price), format_price(tp), format_price(sl)
                emoji = "🟢" if side == "LONG" else "🔴"
                msg = (
                    f"{emoji} *NEW SIGNAL: {side}*\n"
                    f"__________________________________\n\n"
                    f"💎 *Asset:* #{symbol} | `Cross {LEVERAGE}x`\n"
                    f"💵 *Entry:* `{p_f}`\n"
                    f"🎯 *TP:* `{tp_f}`\n"
                    f"🛑 *SL:* `{sl_f}`\n"
                    f"📊 *RSI:* `{rsi_val:.2f}`\n"
                    f"__________________________________\n\n"
                    f"📈 [Chart TradingView](https://www.tradingview.com/symbols/BINANCE-{symbol}/)"
                )
                send_telegram(msg)
        except: continue
    conn.close()

# --- COMMAND HANDLER ---
def command_loop():
    last_id = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
            res = requests.get(url, params={"offset": last_id + 1, "timeout": 10}).json()
            if not res.get("result"): continue
            
            for upd in res["result"]:
                last_id = upd["update_id"]
                msg = upd.get("message", {})
                txt = msg.get("text", "")
                uid = str(msg.get("from", {}).get("id"))
                
                if uid not in WHITELIST_IDS: continue
                
                if txt == "/start":
                    send_telegram("👋 *Akses Premium Aktif!*", uid, get_main_menu())
                elif txt == "📊 Cek Status":
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute("SELECT symbol, side, entry FROM active_positions")
                    pos = c.fetchall()
                    conn.close()
                    res_txt = "📋 *Posisi Aktif:*\n" + "\n".join([f"• {s} ({sd}) @{format_price(e)}" for s, sd, e in pos]) if pos else "📭 Kosong"
                    send_telegram(res_txt, uid)
                elif txt == "📈 Laporan Hari Ini":
                    today = datetime.now().strftime('%Y-%m-%d')
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute("SELECT tp, sl, total_roe FROM daily_stats WHERE date = ?", (today,))
                    row = c.fetchone()
                    conn.close()
                    if row:
                        send_telegram(f"📊 *Progress Hari Ini:*\n✅ TP: {row[0]} | ❌ SL: {row[1]}\n💰 Total ROE: {row[2]:+.2f}%", uid)
                    else:
                        send_telegram("Belum ada aktivitas trading hari ini.", uid)
                elif "Analisa" in txt:
                    coin = txt.split()[-1].upper()
                    sym = coin if coin.endswith("USDT") else coin + "USDT"
                    ticker = call_binance(f"/api/v3/ticker/price?symbol={sym}")
                    if ticker:
                        p = float(ticker['price'])
                        rsi = get_rsi(sym)
                        side = "LONG" if rsi < 50 else "SHORT"
                        msg = f"🔍 *Analisa {sym}*\nPrice: `{format_price(p)}` | RSI: `{rsi:.2f}`\nSaran: *{side}*"
                        send_telegram(msg, uid)
        except: pass
        time.sleep(2)

if __name__ == "__main__":
    init_db()
    print("Bot Premium v5.2 Active...")
    current_day = datetime.now().strftime('%Y-%m-%d')
    threading.Thread(target=command_loop, daemon=True).start()
    
    while True:
        try:
            now_day = datetime.now().strftime('%Y-%m-%d')
            if now_day != current_day:
                send_daily_report(current_day)
                current_day = now_day
                
            analyze_market()
        except: pass
        time.sleep(60)
