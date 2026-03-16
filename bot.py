import requests
import time
import os
import threading
from datetime import datetime

# ==========================================
# ⚙️ KONFIGURASI BALANCED (LEBIH RESPONSIF)
# ==========================================
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
WHITELIST_IDS = os.getenv("WHITELIST_IDS", "").split(",")

# --- Pengaturan Strategi ---
LEVERAGE = 20          
VOL_MIN_USDT = 5000000  # Standar likuiditas
MAX_OPEN_POSITIONS = 5  # Dinaikkan agar lebih banyak koin terpantau
COOLDOWN_PER_COIN = 14400 # 4 Jam jeda per koin yang sama

# --- Pengaturan Anti-Spam (Disesuaikan) ---
GLOBAL_THROTTLE = 180   # Jeda 3 menit antar sinyal baru (Sebelumnya 15 menit)
RSI_FILTER_LONG = 45    # Syarat RSI untuk Long (Sebelumnya 40)
RSI_FILTER_SHORT = 55   # Syarat RSI untuk Short (Sebelumnya 60)

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
    """Mengambil RSI dan data Candle"""
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
        # Analisa FVG (Fair Value Gap)
        # Bullish: Low Candle 1 > High Candle 3
        if c[-1]['l'] > c[-3]['h'] and rsi < RSI_FILTER_LONG:
            return {"side": "LONG", "reason": f"BULLISH FVG | RSI:{rsi:.0f}"}
            
        # Bearish: High Candle 1 < Low Candle 3
        if c[-1]['h'] < c[-3]['l'] and rsi > RSI_FILTER_SHORT:
            return {"side": "SHORT", "reason": f"BEARISH FVG | RSI:{rsi:.0f}"}
            
        return None
    except: return None

def send_telegram(text, target_id=None, reply_markup=None):
    if not TOKEN: return
    dest = target_id if target_id else CHAT_ID
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": dest, "text": text, "parse_mode": "Markdown"}
    if reply_markup: payload["reply_markup"] = reply_markup
    try: requests.post(url, json=payload, timeout=10)
    except: pass

def track_prices(current_data):
    global active_positions, daily_stats
    to_remove = []
    for symbol, pos in active_positions.items():
        coin = next((c for c in current_data if c['symbol'] == symbol), None)
        if not coin: continue
        curr = float(coin['lastPrice'])
        hit = None
        if pos['side'] == "LONG":
            if curr >= pos['tp']: hit = "TAKE PROFIT ✅"
            elif curr <= pos['sl']: hit = "STOP LOSS ❌"
        else:
            if curr <= pos['tp']: hit = "TAKE PROFIT ✅"
            elif curr >= pos['sl']: hit = "STOP LOSS ❌"
            
        if hit:
            raw_pnl = ((curr - pos['entry']) / pos['entry']) * (1 if pos['side'] == "LONG" else -1)
            roe = raw_pnl * LEVERAGE * 100
            daily_stats['tp' if "PROFIT" in hit else 'sl'] += 1
            daily_stats['total_roe'] += roe
            msg = (
                f"🔔 *POSISI DITUTUP*\n"
                f"━━━━━━━━━━━━━━\n"
                f"🪙 Asset: #{symbol}\n"
                f"📊 Hasil: {hit}\n"
                f"📈 ROE: `{roe:+.2f}%` \n"
                f"━━━━━━━━━━━━━━"
            )
            send_telegram(msg)
            to_remove.append(symbol)
    for sym in to_remove:
        if sym in active_positions: del active_positions[sym]

def analyze():
    global last_signal_sent_at, last_report_date
    
    # Report harian otomatis
    if datetime.now().date() > last_report_date:
        daily_stats.update({"tp": 0, "sl": 0, "total_roe": 0.0})
        last_report_date = datetime.now().date()

    data = call_binance("/api/v3/ticker/24hr")
    if not data: return
    track_prices(data)
    
    now = time.time()
    
    # Jeda Global agar tidak spam (3 menit sekali)
    if now - last_signal_sent_at < GLOBAL_THROTTLE:
        return

    for coin in data:
        symbol = coin['symbol']
        if not symbol.endswith("USDT") or symbol in active_positions: continue
        if len(active_positions) >= MAX_OPEN_POSITIONS: break
        
        try:
            if float(coin['quoteVolume']) < VOL_MIN_USDT: continue
            
            ict = get_ict_analysis(symbol)
            if ict:
                # Jeda per koin agar tidak mengulang sinyal koin yang sama
                if (symbol in sent_signals and now - sent_signals[symbol] < COOLDOWN_PER_COIN): continue
                
                price = float(coin['lastPrice'])
                side = ict['side']
                tp = price * (1.04 if side == "LONG" else 0.96)
                sl = price * (0.98 if side == "LONG" else 1.02)
                
                active_positions[symbol] = {"side": side, "entry": price, "tp": tp, "sl": sl}
                sent_signals[symbol] = now
                last_signal_sent_at = now 
                
                msg = (
                    f"{'🔵' if side == 'LONG' else '🟠'} *ICT SIGNAL: {side}*\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"🪙 Asset: #{symbol}\n"
                    f"💡 Logic: `{ict['reason']}`\n"
                    f"💎 Entry: `{format_price(price)}` \n"
                    f"🎯 Target: `{format_price(tp)}` \n"
                    f"🛑 Stop: `{format_price(sl)}` \n"
                    f"━━━━━━━━━━━━━━"
                )
                send_telegram(msg)
                break 
        except: continue

if __name__ == "__main__":
    print("Bot ICT SMC v4.9 (Balanced) Aktif...")
    while True:
        analyze()
        time.sleep(30)

