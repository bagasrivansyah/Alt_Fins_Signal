import requests
import time
import os

# --- KONFIGURASI ---
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Konfigurasi Trading
LEVERAGE = 20          # Anda bisa mengubah ini (misal: 10, 20, 50)
LONG_THRESHOLD = 5.0   
SHORT_THRESHOLD = -5.0 
VOL_MIN_USDT = 5000000 

BINANCE_URLS = ["https://api1.binance.com", "https://api2.binance.com", "https://data-api.binance.vision"]

active_positions = {} 
sent_signals = {}

def send_telegram(text):
    if not TOKEN or not CHAT_ID: return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False
        }, timeout=10)
    except: pass

def get_rsi(symbol):
    for base in BINANCE_URLS:
        try:
            r = requests.get(f"{base}/api/v3/klines?symbol={symbol}&interval=1h&limit=100", timeout=5).json()
            closes = [float(x[4]) for x in r]
            deltas = [closes[i+1] - closes[i] for i in range(len(closes)-1)]
            up = [x if x > 0 else 0 for x in deltas]; down = [abs(x) if x < 0 else 0 for x in deltas]
            avg_gain = sum(up[-14:]) / 14; avg_loss = sum(down[-14:]) / 14
            if avg_loss == 0: return 100
            return 100 - (100 / (1 + (avg_gain / avg_loss)))
        except: continue
    return None

def track_prices(current_data):
    global active_positions
    to_remove = []

    for symbol, pos in active_positions.items():
        coin_data = next((c for c in current_data if c['symbol'] == symbol), None)
        if not coin_data: continue
        
        current_price = float(coin_data['lastPrice'])
        status = None

        if pos['side'] == "LONG":
            if current_price >= pos['tp']: status = "✅ TAKE PROFIT HIT"
            elif current_price <= pos['sl']: status = "❌ STOP LOSS HIT"
        else:
            if current_price <= pos['tp']: status = "✅ TAKE PROFIT HIT"
            elif current_price >= pos['sl']: status = "❌ STOP LOSS HIT"

        if status:
            # Hitung Profit murni dikali Leverage
            raw_pnl = ((current_price - pos['entry']) / pos['entry'])
            if pos['side'] == "SHORT": raw_pnl = -raw_pnl
            roe = raw_pnl * LEVERAGE * 100
            
            emoji = "💰" if "PROFIT" in status else "💸"
            msg = (
                f"{emoji} *{status}*\n"
                f"━━━━━━━━━━━━━━━\n"
                f"Asset: *{symbol}*\n"
                f"Leverage: `{LEVERAGE}x`\n"
                f"ROE: `{roe:+.2f}%` 🚀\n"
                f"━━━━━━━━━━━━━━━"
            )
            send_telegram(msg)
            to_remove.append(symbol)

    for sym in to_remove:
        del active_positions[sym]

def analyze():
    print("Memindai market...")
    data = None
    for base in BINANCE_URLS:
        try:
            res = requests.get(f"{base}/api/v3/ticker/24hr", timeout=10)
            if res.status_code == 200:
                data = res.json()
                break
        except: continue
    
    if not data: return
    track_prices(data)

    now = time.time()
    for coin in data:
        symbol = coin.get('symbol', '')
        if not symbol.endswith("USDT") or symbol in active_positions: continue
        
        change = float(coin.get('priceChangePercent', 0))
        volume = float(coin.get('quoteVolume', 0))
        if volume < VOL_MIN_USDT: continue

        side = "LONG" if change >= LONG_THRESHOLD else "SHORT" if change <= SHORT_THRESHOLD else None

        if side:
            sig_id = f"{symbol}_{side}"
            if sig_id in sent_signals and (now - sent_signals[sig_id] < 14400): continue

            rsi_val = get_rsi(symbol)
            if rsi_val is None: continue
            if (side == "LONG" and rsi_val > 65) or (side == "SHORT" and rsi_val < 35): continue
            
            price = float(coin['lastPrice'])
            # Target TP 3% (ROE 60% jika leverage 20x)
            # Target SL 1.5% (ROE -30% jika leverage 20x)
            tp = price * (1.03 if side == "LONG" else 0.97)
            sl = price * (0.985 if side == "LONG" else 1.015)
            
            active_positions[symbol] = {
                "side": side, "entry": price, "tp": tp, "sl": sl
            }

            msg = (
                f"{'🟢' if side == 'LONG' else '🔴'} *NEW SIGNAL: {side}*\n"
                f"━━━━━━━━━━━━━━━\n"
                f"💎 *Asset:* #{symbol}\n"
                f"⚙️ *Leverage:* `Cross {LEVERAGE}x`\n"
                f"💵 *Entry:* `{price:.4f}`\n"
                f"━━━━━━━━━━━━━━━\n"
                f"🎯 *Target (ROE 60%):* `{tp:.4f}`\n"
                f"🛑 *Stop Loss:* `{sl:.4f}`\n"
                f"📊 *RSI (1h):* `{rsi_val:.2f}`\n"
                f"━━━━━━━━━━━━━━━\n"
                f"📈 [View Chart](https://www.tradingview.com/symbols/BINANCE-{symbol}/)"
            )
            send_telegram(msg)
            sent_signals[sig_id] = now
            print(f"✅ Sinyal dikirim: {symbol}")

if __name__ == "__main__":
    while True:
        analyze()
        time.sleep(60)
