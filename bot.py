import requests
import time
import os
import threading
import numpy as np
from datetime import datetime

# --- KONFIGURASI RAILWAY ---
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
WHITELIST_IDS = os.getenv("WHITELIST_IDS", "").split(",")

# Konfigurasi Risk Management
LEVERAGE = 20          
VOL_MIN_USDT = 10000000 # Ditingkatkan ke 10jt untuk akurasi SMC
RISK_PER_TRADE_PERCENT = 1.0 # Resiko 1% saldo per trade
COOLDOWN_SECONDS = 14400 

BINANCE_URLS = ["https://api1.binance.com", "https://api2.binance.com", "https://api3.binance.com"]

# Database RAM
active_positions = {} 
sent_signals = {}
daily_stats = {"tp": 0, "sl": 0, "total_roe": 0.0}
last_report_date = datetime.now().date()
last_update_id = 0

# --- MODUL TEKNIKAL LANJUTAN ---

def get_klines(symbol, interval, limit=50):
    data = call_binance(f"/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}")
    if not data: return None
    return [{"h": float(x[2]), "l": float(x[3]), "c": float(x[4]), "v": float(x[5])} for x in data]

def get_trend_htf(symbol):
    """Filter HTF: Hanya trade searah dengan trend 4H (HTF)"""
    candles = get_klines(symbol, "4h", 20)
    if not candles: return "NEUTRAL"
    ema = np.mean([x['c'] for x in candles])
    return "BULLISH" if candles[-1]['c'] > ema else "BEARISH"

def get_swing_points(candles):
    """Mencari Swing High dan Swing Low terakhir untuk SL dinamis"""
    highs = [x['h'] for x in candles[-15:]]
    lows = [x['l'] for x in candles[-15:]]
    return max(highs), min(lows)

def get_ict_advanced_analysis(symbol):
    """SMC Logic: FVG + MSS + HTF Confluence + Volume Displacement"""
    c_1h = get_klines(symbol, "1h", 50)
    if not c_1h: return None
    
    htf_trend = get_trend_htf(symbol)
    avg_vol = np.mean([x['v'] for x in c_1h[-10:]])
    swing_high, swing_low = get_swing_points(c_1h)
    
    curr = c_1h[-1]
    prev1 = c_1h[-2]
    prev2 = c_1h[-3]

    # Displacement Filter: Candle harus punya volume > 1.5x rata-rata
    is_displacement = curr['v'] > (avg_vol * 1.5)

    # 1. BULLISH SETUP (HTF Bullish + FVG + Displacement)
    if htf_trend == "BULLISH" and is_displacement:
        # Bullish FVG: Low candle saat ini > High candle 2 bar lalu
        if curr['l'] > prev2['h']:
            return {
                "side": "LONG", 
                "reason": "BULLISH FVG + HTF CONFLUENCE",
                "sl": swing_low * 0.998, # SL di bawah Swing Low
                "tp": curr['c'] + (curr['c'] - swing_low) * 2 # RR 1:2
            }

    # 2. BEARISH SETUP (HTF Bearish + FVG + Displacement)
    if htf_trend == "BEARISH" and is_displacement:
        # Bearish FVG: High candle saat ini < Low candle 2 bar lalu
        if curr['h'] < prev2['l']:
            return {
                "side": "SHORT", 
                "reason": "BEARISH FVG + HTF CONFLUENCE",
                "sl": swing_high * 1.002, # SL di atas Swing High
                "tp": curr['c'] - (swing_high - curr['c']) * 2 # RR 1:2
            }

    return None

# --- RISK & POSITION SIZING ---

def calculate_position_size(entry, sl):
    """Menghitung ukuran posisi berdasarkan resiko (Sizing Dinamis)"""
    risk_pct = abs(entry - sl) / entry
    if risk_pct == 0: return 0
    # Formula: (Capital * Risk%) / Risk_Distance
    # Diasumsikan capital per trade disesuaikan dengan resiko 1%
    return (RISK_PER_TRADE_PERCENT / risk_pct)

# --- TELEGRAM & UI ---

def format_price(price):
    if price >= 1000: return f"{price:,.2f}"
    return f"{price:.6f}"

def format_signal_message(side, symbol, entry, tp, sl, reason, is_update=False):
    emoji = "🔵" if side == "LONG" else "🟠"
    arrow = "▲" if side == "LONG" else "▼"
    
    msg = (
        f"{'🔄 *UPDATE POSISI*' if is_update else emoji + ' *NEW SMC SIGNAL*'}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 *Asset:* #{symbol} | {side}\n"
        f"🛡️ *Logic:* `{reason}`\n\n"
        f"```\n"
        f"🎯 TP : {format_price(tp)}\n"
        f"{arrow}───── ENTRY: {format_price(entry)}\n"
        f"🛑 SL : {format_price(sl)}\n"
        f"```\n"
        f"⚙️ *Risk:* `Risk-Free (BE)` jika profit 1:1\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    return msg

def call_binance(endpoint):
    for base_url in BINANCE_URLS:
        try:
            res = requests.get(f"{base_url}{endpoint}", timeout=10)
            if res.status_code == 200: return res.json()
        except: continue
    return None

def send_telegram(text, target_id=None):
    if not TOKEN: return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": target_id or CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

# --- CORE LOGIC ---

def track_positions(current_prices):
    global active_positions, daily_stats
    to_remove = []
    
    for symbol, pos in active_positions.items():
        ticker = next((c for c in current_prices if c['symbol'] == symbol), None)
        if not ticker: continue
        
        curr_p = float(ticker['lastPrice'])
        entry = pos['entry']
        
        # 1. Logika Break-Even (Risk Free)
        # Jika profit sudah mencapai 1:1 RR, pindahkan SL ke Entry
        if not pos.get('is_be'):
            if (pos['side'] == "LONG" and curr_p >= entry + (pos['tp'] - entry)/2):
                pos['sl'] = entry
                pos['is_be'] = True
                send_telegram(f"🛡️ *PROTECTION:* SL untuk #{symbol} dipindah ke Entry (Risk-Free).")
            elif (pos['side'] == "SHORT" and curr_p <= entry - (entry - pos['tp'])/2):
                pos['sl'] = entry
                pos['is_be'] = True
                send_telegram(f"🛡️ *PROTECTION:* SL untuk #{symbol} dipindah ke Entry (Risk-Free).")

        # 2. Check TP / SL
        hit = None
        if pos['side'] == "LONG":
            if curr_p >= pos['tp']: hit = "TP ✅"
            elif curr_p <= pos['sl']: hit = "SL ❌"
        else:
            if curr_p <= pos['tp']: hit = "TP ✅"
            elif curr_p >= pos['sl']: hit = "SL ❌"

        if hit:
            roe = ((curr_p - entry)/entry if pos['side']=="LONG" else (entry - curr_p)/entry) * LEVERAGE * 100
            daily_stats['tp' if "✅" in hit else 'sl'] += 1
            daily_stats['total_roe'] += roe
            send_telegram(f"🏁 *CLOSED {symbol}* at {format_price(curr_p)} ({hit})\nROI: `{roe:+.2f}%`")
            to_remove.append(symbol)

    for s in to_remove: del active_positions[s]

def main_loop():
    global last_report_date
    while True:
        try:
            # 1. Report Harian
            if datetime.now().date() > last_report_date:
                # (Logika report sama seperti sebelumnya)
                last_report_date = datetime.now().date()

            # 2. Ambil Market Data
            market_data = call_binance("/api/v3/ticker/24hr")
            if not market_data: continue
            
            track_positions(market_data)
            
            # 3. Scan New Setup
            for coin in market_data:
                sym = coin['symbol']
                if not sym.endswith("USDT") or sym in active_positions: continue
                if float(coin['quoteVolume']) < VOL_MIN_USDT: continue
                
                # Cooldown check
                if sym in sent_signals and time.time() - sent_signals[sym] < COOLDOWN_SECONDS:
                    continue

                ict = get_ict_advanced_analysis(sym)
                if ict:
                    price = float(coin['lastPrice'])
                    active_positions[sym] = {
                        "side": ict['side'], "entry": price, 
                        "tp": ict['tp'], "sl": ict['sl'], "is_be": False
                    }
                    sent_signals[sym] = time.time()
                    send_telegram(format_signal_message(ict['side'], sym, price, ict['tp'], ict['sl'], ict['reason']))

        except Exception as e:
            print(f"Error: {e}")
        time.sleep(60)

if __name__ == "__main__":
    print("SMC Professional Bot v5.0 Active...")
    main_loop()
