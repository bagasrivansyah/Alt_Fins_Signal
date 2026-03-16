import requests
import time
import os
import threading
from datetime import datetime

# --- KONFIGURASI RAILWAY ---
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
WHITELIST_IDS = os.getenv("WHITELIST_IDS", "").split(",")

# --- Pengaturan Strategi Pro (Anti-Spam) ---
LEVERAGE = 20          
VOL_MIN_USDT = 5000000  # Dinaikkan agar fokus pada koin likuid
COOLDOWN_SECONDS = 28800 # 8 Jam jeda untuk koin yang sama
GLOBAL_THROTTLE = 900    # Jeda 15 Menit antar sinyal (Mencegah Spam)
MAX_OPEN_POSITIONS = 3   # Maksimal koin yang dipantau sekaligus

BINANCE_URLS = ["https://api1.binance.com", "https://api2.binance.com", "https://api3.binance.com"]

# Database RAM
active_positions = {} 
sent_signals = {}
last_signal_sent_at = 0 
daily_stats = {"tp": 0, "sl": 0, "total_roe": 0.0}
last_report_date = datetime.now().date()
last_update_id = 0

def format_price(price):
    if price == 0: return "0"
    if price >= 1000: return f"{price:,.2f}"
    elif price >= 1: return f"{price:.4f}"
    elif price >= 0.01: return f"{price:.6f}"
    else: return f"{price:.8f}"

def call_binance(endpoint):
    for base_url in BINANCE_URLS:
        try:
            res = requests.get(f"{base_url}{endpoint}", timeout=10)
            if res.status_code == 200: return res.json()
        except: continue
    return None

def get_market_data(symbol):
    """Mengambil RSI dan data Candle untuk filter kualitas"""
    data = call_binance(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=50")
    if not data or len(data) < 20: return None, None
    
    try:
        closes = [float(x[4]) for x in data]
        klines = [{"h": float(x[2]), "l": float(x[3]), "c": float(x[4]), "o": float(x[1])} for x in data]
        
        # Kalkulasi RSI 14
        deltas = [closes[i+1] - closes[i] for i in range(len(closes)-1)]
        up = [d if d > 0 else 0 for d in deltas]
        down = [abs(d) if d < 0 else 0 for d in deltas]
        avg_gain = sum(up[-14:]) / 14
        avg_loss = sum(down[-14:]) / 14
        rsi = 100 - (100 / (1 + (avg_gain / avg_loss))) if avg_loss > 0 else 100
        
        return rsi, klines
    except: return None, None

def get_ict_analysis(symbol):
    rsi, c = get_market_data(symbol)
    if rsi is None: return None
    
    try:
        # 1. BULLISH FVG + RSI OVERSOLD (< 40)
        if c[-1]['l'] > c[-3]['h'] and rsi < 40:
            return {"side": "LONG", "reason": f"BULLISH FVG + RSI({rsi:.0f})"}
            
        # 2. BEARISH FVG + RSI OVERBOUGHT (> 60)
        if c[-1]['h'] < c[-3]['l'] and rsi > 60:
            return {"side": "SHORT", "reason": f"BEARISH FVG + RSI({rsi:.0f})"}
            
        return None
    except: return None

def generate_visual_chart(side, price, tp, sl, reason):
    p_f, tp_f, sl_f = format_price(price), format_price(tp), format_price(sl)
    arrow = "▲" if side == "LONG" else "▼"
    return (
        f"```\n"
        f"🎯 TARGET (TP) : {tp_f}\n"
        f"{arrow}───────────────{arrow}\n"
        f"💎 ENTRY PRICE  : {p_f}\n"
        f"{arrow}───────────────{arrow}\n"
        f"🛑 STOP LOSS    : {sl_f}\n"
        f"```\n"
        f"💡 *Logic:* `{reason}`"
    )

def send_telegram(text, target_id=None, reply_markup=None):
    if not TOKEN: return
    dest = target_id if target_id else CHAT_ID
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": dest, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}
    if reply_markup: payload["reply_markup"] = reply_markup
    try: requests.post(url, json=payload, timeout=10)
    except: pass

def track_prices(current_data):
    global active_positions, daily_stats, sent_signals
    to_remove = []
    for symbol, pos in active_positions.items():
        coin = next((c for c in current_data if c['symbol'] == symbol), None)
        if not coin: continue
        curr = float(coin['lastPrice'])
        hit = None
        if pos['side'] == "LONG":
            if curr >= pos['tp']: hit = "TAKE PROFIT (TARGET HIT)"
            elif curr <= pos['sl']: hit = "STOP LOSS (INVALIDATED)"
        else:
            if curr <= pos['tp']: hit = "TAKE PROFIT (TARGET HIT)"
            elif curr >= pos['sl']: hit = "STOP LOSS (INVALIDATED)"
            
        if hit:
            raw_pnl = ((curr - pos['entry']) / pos['entry']) * (1 if pos['side'] == "LONG" else -1)
            roe = raw_pnl * LEVERAGE * 100
            daily_stats['tp' if "PROFIT" in hit else 'sl'] += 1
            daily_stats['total_roe'] += roe
            icon = "💎" if "PROFIT" in hit else "🌪️"
            msg = (
                f"{icon} *ICT POSITION CLOSED*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🪙 *Asset:* #{symbol}\n"
                f"📊 *Result:* {hit}\n"
                f"📈 *ROI:* `{roe:+.2f}%` \n"
                f"💵 *Exit:* `{format_price(curr)}` \n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )
            send_telegram(msg)
            sent_signals[symbol] = time.time()
            to_remove.append(symbol)
    for sym in to_remove:
        if sym in active_positions: del active_positions[sym]

def analyze():
    global last_report_date, last_signal_sent_at
    
    # Reset Report Harian
    if datetime.now().date() > last_report_date:
        daily_stats.update({"tp": 0, "sl": 0, "total_roe": 0.0})
        last_report_date = datetime.now().date()

    data = call_binance("/api/v3/ticker/24hr")
    if not data: return
    track_prices(data)
    
    now = time.time()
    
    # FILTER 1: Global Throttle (Jangan kirim pesan jika belum lewat 15 menit dari sinyal terakhir)
    if now - last_signal_sent_at < GLOBAL_THROTTLE:
        return

    # FILTER 2: Batas Maksimal Posisi Aktif
    if len(active_positions) >= MAX_OPEN_POSITIONS:
        return

    for coin in data:
        symbol = coin['symbol']
        if not symbol.endswith("USDT") or symbol in active_positions: continue
        
        try:
            # FILTER 3: Volume Tinggi
            if float(coin['quoteVolume']) < VOL_MIN_USDT: continue
            
            ict = get_ict_analysis(symbol)
            if ict:
                # FILTER 4: Jeda per koin
                if (symbol in sent_signals and now - sent_signals[symbol] < COOLDOWN_SECONDS): continue
                
                price = float(coin['lastPrice'])
                side = ict['side']
                tp = price * (1.04 if side == "LONG" else 0.96)
                sl = price * (0.98 if side == "LONG" else 1.02)
                
                active_positions[symbol] = {"side": side, "entry": price, "tp": tp, "sl": sl}
                last_signal_sent_at = now # Set waktu sinyal terakhir
                
                emoji = "🟢" if side == "LONG" else "🔴"
                chart = generate_visual_chart(side, price, tp, sl, ict['reason'])
                msg = (
                    f"{emoji} *ICT PRO SIGNAL: {side}*\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"🪙 *Asset:* #{symbol}\n"
                    f"⚙️ *Margin:* `Cross {LEVERAGE}x`\n\n"
                    f"{chart}\n\n"
                    f"💰 *Est. Profit:* `+{4.0 * LEVERAGE:.2f}% ROI` \n"
                    f"━━━━━━━━━━━━━━━━━━━━"
                )
                send_telegram(msg)
                break # Berhenti setelah menemukan 1 sinyal berkualitas
        except: continue

if __name__ == "__main__":
    print("Bot ICT SMC v4.8 (Anti-Spam Pro) Online...")
    # Thread handle_commands tetap ada untuk merespon manual
    while True:
        analyze()
        time.sleep(30)

