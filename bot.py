import requests
import time
import os
import threading
from datetime import datetime

# --- KONFIGURASI RAILWAY ---
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
WHITELIST_IDS = os.getenv("WHITELIST_IDS", "").split(",")

# Konfigurasi Trading Pro
LEVERAGE = 20          
VOL_MIN_USDT = 10000000 
COOLDOWN_SECONDS = 14400 
# Rasio TP 1, 2, dan 3 berdasarkan Risk
TP1_RR = 1.0  # RR 1:1
TP2_RR = 2.0  # RR 1:2
TP3_RR = 3.0  # RR 1:3

BINANCE_URLS = ["https://api1.binance.com", "https://api2.binance.com", "https://api3.binance.com", "https://data-api.binance.vision"]

# Database RAM
active_positions = {} 
sent_signals = {}
daily_stats = {"tp": 0, "sl": 0, "total_roe": 0.0}
last_report_date = datetime.now().date()
last_update_id = 0

# --- FORMAT HARGA DINAMIS ---
def format_price(price):
    if price == 0: return "0"
    if price >= 1000: return f"{price:,.2f}"
    elif price >= 1: return f"{price:.4f}"
    elif price >= 0.01: return f"{price:.6f}"
    else: return f"{price:.8f}"

# --- FITUR 1: HTF FILTER (4 JAM) ---
def get_htf_trend(symbol):
    """Cek trend di timeframe 4H untuk konfirmasi arah besar"""
    data = call_binance(f"/api/v3/klines?symbol={symbol}&interval=4h&limit=5")
    if not data: return None
    c4 = [float(x[4]) for x in data]
    return "BULLISH" if c4[-1] > c4[-2] else "BEARISH"

# --- ANALISA ICT UPGRADED ---
def get_ict_analysis(symbol):
    """Mendeteksi FVG, Displacement (Volume), dan Dynamic SL/TP"""
    data = call_binance(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=30")
    if not data or len(data) < 10: return None
    
    try:
        c = [{"h": float(x[2]), "l": float(x[3]), "c": float(x[4]), "v": float(x[5])} for x in data]
        avg_vol = sum([x['v'] for x in c[-10:]]) / 10
        current_vol = c[-2]['v']
        has_displacement = current_vol > (avg_vol * 1.5)

        htf = get_htf_trend(symbol)
        swing_low = min([x['l'] for x in c[-10:-1]])
        swing_high = max([x['h'] for x in c[-10:-1]])
        price = c[-1]['c']

        if htf == "BULLISH" and c[-2]['l'] > c[-4]['h'] and has_displacement:
            sl = swing_low * 0.998
            risk = abs(price - sl)
            return {
                "side": "LONG", "reason": "BULLISH FVG + HTF", 
                "tp1": price + (risk * TP1_RR), 
                "tp2": price + (risk * TP2_RR), 
                "tp3": price + (risk * TP3_RR), 
                "sl": sl
            }
            
        if htf == "BEARISH" and c[-2]['h'] < c[-4]['l'] and has_displacement:
            sl = swing_high * 1.002
            risk = abs(sl - price)
            return {
                "side": "SHORT", "reason": "BEARISH FVG + HTF", 
                "tp1": price - (risk * TP1_RR), 
                "tp2": price - (risk * TP2_RR), 
                "tp3": price - (risk * TP3_RR), 
                "sl": sl
            }
        return None
    except: return None

# --- VISUAL CHART PREMIUM DENGAN MULTI TP ---
def generate_visual_chart(side, price, tp1, tp2, tp3, sl, reason):
    p_f, t1, t2, t3, sl_f = format_price(price), format_price(tp1), format_price(tp2), format_price(tp3), format_price(sl)
    arrow = "▲" if side == "LONG" else "▼"
    
    chart = (
        f"```\n"
        f"🚀 TP 3 (MAX) : {t3}\n"
        f"🔥 TP 2       : {t2}\n"
        f"🎯 TP 1       : {t1}\n"
        f"{arrow}───────────────{arrow}\n"
        f"💎 ENTRY PRICE : {p_f}\n"
        f"{arrow}───────────────{arrow}\n"
        f"🛑 STOP LOSS   : {sl_f}\n"
        f"```\n"
        f"💡 *Logic:* `{reason}`"
    )
    return chart

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
        "keyboard": [[{"text": "📊 Status Posisi"}, {"text": "🔍 Analisa BTC"}],
                     [{"text": "📈 Analisa ETH"}, {"text": "🚀 Analisa SOL"}]],
        "resize_keyboard": True
    }

def call_binance(endpoint):
    for base_url in BINANCE_URLS:
        try:
            res = requests.get(f"{base_url}{endpoint}", timeout=10)
            if res.status_code == 200: return res.json()
        except: continue
    return None

def format_signal_message(side, symbol, price, tp1, tp2, tp3, sl, reason, mode="SIGNAL"):
    emoji = "🔵" if side == "LONG" else "🟠"
    chart = generate_visual_chart(side, price, tp1, tp2, tp3, sl, reason)
    msg = (
        f"{emoji} *ICT {mode}: {side}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🪙 *Asset:* #{symbol} | `Cross {LEVERAGE}x`\n"
        f"🛡️ *SMC Trailing Active*\n\n"
        f"{chart}\n\n"
        f"⚠️ *Trailing:* TP1 -> BE | TP2 -> Lock TP1\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📈 [View on TradingView](https://www.tradingview.com/symbols/BINANCE-{symbol}/)"
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
            
            if not text or sender_id not in WHITELIST_IDS: continue

            if text == "/start":
                send_telegram("🏛️ *SMC Trading System Active!*", sender_id, get_main_menu())
            elif "Status" in text:
                m = "📋 *ICT ACTIVE POSITIONS*\n━━━━━━━━━━━━━━━━━━━━\n"
                m += "\n".join([f"• *{s}* | {p['side']} | BE Lvl: {p['trail_level']}" for s,p in active_positions.items()]) if active_positions else "📭 *No Positions*"
                send_telegram(m, sender_id)
            elif "Analisa" in text:
                coin = text.split()[-1].upper()
                sym = coin if coin.endswith("USDT") else coin + "USDT"
                ict = get_ict_analysis(sym)
                ticker = call_binance(f"/api/v3/ticker/price?symbol={sym}")
                if ict and ticker:
                    p = float(ticker['price'])
                    send_telegram(format_signal_message(ict['side'], sym, p, ict['tp1'], ict['tp2'], ict['tp3'], ict['sl'], ict['reason'], "ANALYZE"), sender_id)
                else:
                    send_telegram(f"❌ *{sym}* No ICT Setup found.", sender_id)
    except: pass

def track_prices(current_data):
    global active_positions, daily_stats, sent_signals
    to_remove = []
    for symbol, pos in active_positions.items():
        coin = next((c for c in current_data if c['symbol'] == symbol), None)
        if not coin: continue
        curr = float(coin['lastPrice'])
        
        # --- LOGIKA TRAILING STOP (MULTI TP) ---
        if pos['trail_level'] == 0:
            if (pos['side'] == "LONG" and curr >= pos['tp1']) or (pos['side'] == "SHORT" and curr <= pos['tp1']):
                pos['sl'] = pos['entry']
                pos['trail_level'] = 1
                send_telegram(f"🛡️ *TP 1 HIT:* SL moved to Entry (BE) for #{symbol}")

        elif pos['trail_level'] == 1:
            if (pos['side'] == "LONG" and curr >= pos['tp2']) or (pos['side'] == "SHORT" and curr <= pos['tp2']):
                pos['sl'] = pos['tp1']
                pos['trail_level'] = 2
                send_telegram(f"🔒 *TP 2 HIT:* SL moved to TP 1 (Lock Profit) for #{symbol}")

        hit = None
        if pos['side'] == "LONG":
            if curr >= pos['tp3']: hit = "TAKE PROFIT 3 (MAX TARGET)"
            elif curr <= pos['sl']: hit = "TRAILING STOP / SL HIT"
        else:
            if curr <= pos['tp3']: hit = "TAKE PROFIT 3 (MAX TARGET)"
            elif curr >= pos['sl']: hit = "TRAILING STOP / SL HIT"
            
        if hit:
            raw_pnl = ((curr - pos['entry']) / pos['entry']) * (1 if pos['side'] == "LONG" else -1)
            roe = raw_pnl * LEVERAGE * 100
            daily_stats['tp' if "PROFIT 3" in hit else 'sl'] += 1
            daily_stats['total_roe'] += roe
            icon = "💎" if "PROFIT" in hit else "🌪️"
            msg = (
                f"{icon} *ICT POSITION CLOSED*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🪙 *Asset:* #{symbol}\n"
                f"📊 *Result:* {hit}\n"
                f"📈 *ROI:* `{roe:+.2f}%` \n"
                f"💵 *Exit:* `{format_price(curr)}`\n"
                f"━━━━━━━━━━━━━━━━━━━━"
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
        wr = (daily_stats['tp'] / total * 100) if total > 0 else 0
        report = (
            f"🏛️ *SMC PERFORMANCE REPORT*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"✅ TP 3 Hit: `{daily_stats['tp']}`\n"
            f"❌ SL/Trailing Hit: `{daily_stats['sl']}`\n"
            f"💰 Total ROE: `{daily_stats['total_roe']:+.2f}%` \n"
            f"━━━━━━━━━━━━━━━━━━━━"
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
            if float(coin['quoteVolume']) < VOL_MIN_USDT: continue
            ict = get_ict_analysis(symbol)
            if ict:
                if (symbol in sent_signals and now - sent_signals[symbol] < COOLDOWN_SECONDS): continue
                price = float(coin['lastPrice'])
                
                active_positions[symbol] = {
                    "side": ict['side'], 
                    "entry": price, 
                    "tp1": ict['tp1'], 
                    "tp2": ict['tp2'], 
                    "tp3": ict['tp3'], 
                    "sl": ict['sl'],
                    "trail_level": 0 
                }
                send_telegram(format_signal_message(ict['side'], symbol, price, ict['tp1'], ict['tp2'], ict['tp3'], ict['sl'], ict['reason']))
        except: continue

if __name__ == "__main__":
    print("Bot ICT SMC v4.5 Pro Active...")
    threading.Thread(target=lambda: [handle_commands() or time.sleep(1) for _ in iter(int, 1)], daemon=True).start()
    while True:
        analyze()
        time.sleep(60)
