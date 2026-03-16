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

# Parameter Pro ICT/SMC
LEVERAGE = 20          
RISK_PER_TRADE = 0.02 # Risiko 2% dari saldo (untuk perhitungan size)
VOL_MIN_USDT = 10000000 
COOLDOWN_SECONDS = 14400 

BINANCE_URLS = ["https://api1.binance.com", "https://api2.binance.com", "https://api3.binance.com"]

# Database RAM
active_positions = {} 
sent_signals = {}
daily_stats = {"tp": 0, "sl": 0, "total_roe": 0.0}
last_report_date = datetime.now().date()
last_update_id = 0

# --- FORMATTING & UTILITIES ---
def format_price(price):
    if price >= 1000: return f"{price:,.2f}"
    elif price >= 1: return f"{price:.4f}"
    else: return f"{price:.8f}"

def call_binance(endpoint):
    for base_url in BINANCE_URLS:
        try:
            res = requests.get(f"{base_url}{endpoint}", timeout=10)
            if res.status_code == 200: return res.json()
        except: continue
    return None

# --- ADVANCED ICT LOGIC ---
def get_htf_trend(symbol):
    """Filter Multi-Timeframe: Cek Trend di 4H"""
    data = call_binance(f"/api/v3/klines?symbol={symbol}&interval=4h&limit=20")
    if not data: return "NEUTRAL"
    closes = [float(x[4]) for x in data]
    return "BULLISH" if closes[-1] > closes[-5] else "BEARISH"

def get_ict_v2_analysis(symbol):
    """SMC Engine: FVG + Displacement + Dynamic Swing Levels"""
    # Ambil data 1H
    data = call_binance(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=50")
    if not data or len(data) < 10: return None
    
    c = [{"o": float(x[1]), "h": float(x[2]), "l": float(x[3]), "c": float(x[4]), "v": float(x[5])} for x in data]
    avg_vol = np.mean([x['v'] for x in c[-20:]])
    htf = get_htf_trend(symbol)

    # 1. Swing Levels (Dinamis untuk SL)
    swing_low = min([x['l'] for x in c[-10:-1]])
    swing_high = max([x['h'] for x in c[-10:-1]])
    curr_p = c[-1]['c']

    # 2. Bullish Setup (HTF Align + FVG + Displacement)
    if htf == "BULLISH":
        # Cek FVG Bullish (Gap antara Low candle 3 dan High candle 1) + Volume Spike
        if c[-2]['l'] > c[-4]['h'] and c[-2]['v'] > avg_vol * 1.5:
            sl = swing_low * 0.998 # Buffer di bawah swing low
            tp = curr_p + (curr_p - sl) * 2 # RR 1:2
            return {"side": "LONG", "entry": curr_p, "tp": tp, "sl": sl, "reason": "BULLISH FVG + DISPLACEMENT"}

    # 3. Bearish Setup
    if htf == "BEARISH":
        if c[-2]['h'] < c[-4]['l'] and c[-2]['v'] > avg_vol * 1.5:
            sl = swing_high * 1.002 # Buffer di atas swing high
            tp = curr_p - (sl - curr_p) * 2 # RR 1:2
            return {"side": "SHORT", "entry": curr_p, "tp": tp, "sl": sl, "reason": "BEARISH FVG + DISPLACEMENT"}
            
    return None

# --- POSITION MANAGEMENT ---
def track_and_manage():
    global active_positions, daily_stats
    data = call_binance("/api/v3/ticker/price")
    if not data: return
    
    prices = {x['symbol']: float(x['price']) for x in data}
    to_remove = []

    for symbol, pos in active_positions.items():
        if symbol not in prices: continue
        curr = prices[symbol]
        
        # Logika Break-Even (Jika sudah 1:1, pindahkan SL ke Entry)
        if not pos.get('is_breakeven'):
            dist_to_tp = abs(pos['tp'] - pos['entry'])
            if (pos['side'] == "LONG" and curr >= pos['entry'] + (dist_to_tp * 0.5)) or \
               (pos['side'] == "SHORT" and curr <= pos['entry'] - (dist_to_tp * 0.5)):
                pos['sl'] = pos['entry']
                pos['is_breakeven'] = True
                send_telegram(f"🛡️ *SAFE MODE:* SL for #{symbol} moved to ENTRY (Break-Even).")

        # Check Exit (TP/SL)
        hit = None
        if pos['side'] == "LONG":
            if curr >= pos['tp']: hit = "TP ✅"
            elif curr <= pos['sl']: hit = "SL ❌"
        else:
            if curr <= pos['tp']: hit = "TP ✅"
            elif curr >= pos['sl']: hit = "SL ❌"

        if hit:
            roe = ((curr - pos['entry']) / pos['entry']) * (1 if pos['side'] == "LONG" else -1) * LEVERAGE * 100
            daily_stats['total_roe'] += roe
            if "TP" in hit: daily_stats['tp'] += 1
            else: daily_stats['sl'] += 1
            
            msg = f"🏁 *POSITION CLOSED*\nAsset: #{symbol}\nResult: {hit}\nNet ROE: `{roe:+.2f}%`"
            send_telegram(msg)
            to_remove.append(symbol)

    for sym in to_remove: del active_positions[sym]

# --- TELEGRAM UI ---
def format_signal_v2(side, symbol, p, tp, sl, reason):
    emoji = "🔵" if side == "LONG" else "🟠"
    rr = abs(tp-p)/abs(p-sl) if abs(p-sl) != 0 else 0
    msg = (
        f"{emoji} *ICT SMC SIGNAL: {side}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 *Asset:* #{symbol}\n"
        f"💡 *Logic:* `{reason}`\n"
        f"📊 *RR Ratio:* `1:{rr:.1f}`\n\n"
        f"```\n"
        f"ENTRY : {format_price(p)}\n"
        f"TARGET: {format_price(tp)}\n"
        f"STOP  : {format_price(sl)}\n"
        f"```\n"
        f"⚠️ *Note:* SL akan otomatis dipindah ke Entry jika profit 50% dari target."
    )
    return msg

def send_telegram(text, target_id=None):
    if not TOKEN: return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": target_id or CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

# --- MAIN LOOP ---
def main_process():
    while True:
        try:
            # 1. Update Monitor Harga
            track_and_manage()
            
            # 2. Cari Setup Baru
            tickers = call_binance("/api/v3/ticker/24hr")
            if tickers:
                for coin in tickers:
                    symbol = coin['symbol']
                    if not symbol.endswith("USDT") or symbol in active_positions: continue
                    if float(coin['quoteVolume']) < VOL_MIN_USDT: continue
                    
                    setup = get_ict_v2_analysis(symbol)
                    if setup:
                        now = time.time()
                        if symbol in sent_signals and now - sent_signals[symbol] < COOLDOWN_SECONDS: continue
                        
                        active_positions[symbol] = {
                            "side": setup['side'], "entry": setup['entry'], 
                            "tp": setup['tp'], "sl": setup['sl'], "is_breakeven": False
                        }
                        sent_signals[symbol] = now
                        send_telegram(format_signal_v2(setup['side'], symbol, setup['entry'], setup['tp'], setup['sl'], setup['reason']))
            
            time.sleep(60) # Scan tiap menit
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    print("SMC Bot v4.5 Pro - Bagas Rivansyah Version")
    main_process()
