import requests
import pandas as pd
import time
from datetime import datetime
from flask import Flask

# ============ TELEGRAM CONFIG ============
TELEGRAM_BOT_TOKEN = "8264206004:AAH2zvVURgKLv9hZd-ZKTrB7xcZsaKZCjd0"
TELEGRAM_CHAT_ID = "8282016712"  # ví dụ: 8282016712

# ============ FLASK KEEPALIVE ============
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ EMA Bot đang chạy trên Render!", 200

# ============ HÀM GỬI TELEGRAM ============
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print("Lỗi gửi Telegram:", e)

# ============ LẤY DANH SÁCH CẶP USDT ============
def get_all_usdt_symbols():
    url = "https://api.binance.com/api/v3/exchangeInfo"
    try:
        data = requests.get(url, timeout=10).json()
        symbols = [s["symbol"] for s in data.get("symbols", []) if s["symbol"].endswith("USDT")]
        return symbols
    except Exception as e:
        print("Lỗi khi lấy danh sách coin:", e)
        return ["BTCUSDT", "ETHUSDT"]

# ============ LẤY DỮ LIỆU GIÁ & EMA ============
def get_ema_signal(symbol):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=5m&limit=100"
    try:
        data = requests.get(url, timeout=10).json()
        closes = [float(x[4]) for x in data]
        df = pd.DataFrame(closes, columns=["close"])
        df["ema9"] = df["close"].ewm(span=9, adjust=False).mean()
        df["ema21"] = df["close"].ewm(span=21, adjust=False).mean()

        if df["ema9"].iloc[-2] < df["ema21"].iloc[-2] and df["ema9"].iloc[-1] > df["ema21"].iloc[-1]:
            return f"🔼 {symbol} tín hiệu MUA (EMA9 cắt lên EMA21)"
        elif df["ema9"].iloc[-2] > df["ema21"].iloc[-2] and df["ema9"].iloc[-1] < df["ema21"].iloc[-1]:
            return f"🔽 {symbol} tín hiệu BÁN (EMA9 cắt xuống EMA21)"
        return None
    except Exception:
        return None

# ============ CHẠY BOT ============
def main():
    send_telegram_message("🚀 Bot EMA 9/21 đã khởi động!")
    symbols = get_all_usdt_symbols()
    send_telegram_message(f"📊 Đang theo dõi {len(symbols)} cặp coin USDT.")

    while True:
        for sym in symbols[:50]:  # Giới hạn 50 coin/lượt để tránh rate limit
            signal = get_ema_signal(sym)
            if signal:
                send_telegram_message(signal)
            time.sleep(1)
        print("🕒", datetime.now(), "Đã quét xong 1 vòng.")
        time.sleep(60)

if __name__ == "__main__":
    import threading
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()
    main()


