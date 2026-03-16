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
VOL_MIN_USDT = 5000000 # Ditingkatkan agar dapat koin yang benar-benar liquid
COOLDOWN_SECONDS = 14400 
RISK_REWARD_RATIO = 2.0 # Target minimal 1:2

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
    # Jika candle terakhir tutup di atas candle sebelumnya, trend Bullish
    c4 = [float(x[4]) for x in data]
    return "BULLISH" if c4[-1] > c4[-2] else "BEARISH"

# --- ANALISA ICT UPGRADED ---
def get_ict_analysis(symbol):
    """Mendeteksi FVG, Displacement (Volume), dan Dynamic SL/TP"""
    data = call_binance(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=30")
    if not data or len(data) < 10: return None
    
    try:
        # Format: [high, low, close, volume]
        c = [{"h": float(x[2]), "l": float(x[3]), "c": float(x[4]), "v": float(x[5])} for x in data]
        
        # Fitur 3: Volume Filter (Displacement)
        avg_vol = sum([x['v'] for x in c[-10:]]) / 10
        current_vol = c[-2]['v']
        has_displacement = current_vol > (avg_vol * 1.5) # Volume 1.5x rata-rata

        # Fitur 1: HTF Trend
        htf = get_htf_trend(symbol)

        # Fitur 2: Struktur Dinamis (Swing High/Low)
        swing_low = min([x['l'] for x in c[-10:-1]])
        swing_high = max([x['h'] for x in c[-10:-1]])
        price = c[-1]['c']

        # LOGIKA LONG: HTF Bullish + FVG Bullish + Volume Tinggi
        if htf == "BULLISH" and c[-2]['l'] > c[-4]['h'] and has_displacement:
            sl = swing_low * 0.998 # SL di bawah swing low
            tp = price + (abs(price - sl) * RISK_REWARD_RATIO)
            return {"side": "LONG", "reason": "BULLISH FVG + HTF CONFLUENCE", "tp": tp, "sl": sl}
            
        # LOGIKA SHORT: HTF Bearish + FVG Bearish + Volume Tinggi
        if htf == "BEARISH" and c[-2]['h'] < c[-4]['l'] and has_displacement:
            sl = swing_high * 1.002 # SL di atas swing high
            tp = price - (abs(sl - price) * RISK_REWARD_RATIO)
            return {"side": "SHORT", "reason": "BEARISH FVG + HTF CONFLUENCE", "tp": tp, "sl": sl}
            
        return None
    except: return None

# --- VISUAL CHART PREMIUM ---
def generate_visual_chart(side, price, tp, sl, reason):
    p_f, tp_f, sl_f = format_price(price), format_price(tp), format_price(sl)
    arrow = "▲" if side == "LONG" else "▼"
    
    chart = (
        f"```\n"
        f"🎯 TARGET (TP) : {tp_f}\n"
        f"{arrow}───────────────{arrow}\n"
        f"💎 ENTRY PRICE  : {p_f}\n"
        f"{arrow}───────────────{arrow}\n"
        f"🛑 STOP LOSS    : {sl_f}\n"
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

def format_signal_message(side, symbol, price, tp, sl, reason, mode="SIGNAL"):
    emoji = "🔵" if side == "LONG" else "🟠"
    chart = generate_visual_chart(side, price, tp, sl, reason)
    # Fitur 6: Dynamic ROI Info
    est_roi = (abs(tp-price)/price) * LEVERAGE * 100
    
    msg = (
        f"{emoji} *ICT {mode}: {side}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🪙 *Asset:* #{symbol}\n"
        f"🛡️ *Concept:* `Smart Money (SMC)`\n"
        f"⚙️ *Margin:* `Cross {LEVERAGE}x`\n\n"
        f"{chart}\n\n"
        f"💰 *Est. Profit:* `+{est_roi:.2f}% ROI`\n"
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
                m += "\n".join([f"• *{s}* | {p['side']} | `{format_price(p['entry'])}`" for s,p in active_positions.items()]) if active_positions else "📭 *No Positions*"
                send_telegram(m, sender_id)
            elif "Analisa" in text:
                coin = text.split()[-1].upper()
                sym = coin if coin.endswith("USDT") else coin + "USDT"
                ict = get_ict_analysis(sym)
                ticker = call_binance(f"/api/v3/ticker/price?symbol={sym}")
                if ict and ticker:
                    p = float(ticker['price'])
                    send_telegram(format_signal_message(ict['side'], sym, p, ict['tp'], ict['sl'], ict['reason'], "ANALYZE"), sender_id)
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
        
        # Fitur 5: Break-Even Logika
        # Jika profit sudah mencapai 50% dari target TP, geser SL ke Entry
        if not pos.get('be'):
            progress = abs(curr - pos['entry']) / abs(pos['tp'] - pos['entry'])
            if progress >= 0.5:
                pos['sl'] = pos['entry']
                pos['be'] = True
                send_telegram(f"🛡️ *BREAK-EVEN:* SL for #{symbol} moved to Entry.")

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
            f"✅ TP Hit: `{daily_stats['tp']}`\n"
            f"❌ SL Hit: `{daily_stats['sl']}`\n"
            f"📈 Win Rate: `{wr:.1f}%`\n"
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
                side = ict['side']
                
                # Menggunakan TP & SL dinamis dari analisa ICT
                active_positions[symbol] = {
                    "side": side, 
                    "entry": price, 
                    "tp": ict['tp'], 
                    "sl": ict['sl'],
                    "be": False # Flag break-even
                }
                send_telegram(format_signal_message(side, symbol, price, ict['tp'], ict['sl'], ict['reason']))
        except: continue

if __name__ == "__main__":
    print("Bot ICT SMC v4.5 Active...")
    # Thread perintah telegram
    threading.Thread(target=lambda: [handle_commands() or time.sleep(1) for _ in iter(int, 1)], daemon=True).start()
    while True:
        analyze()
        time.sleep(60)
