import requests
import pandas as pd
import time
import threading
from Flask import Flask

# =============================
# 🔧 CẤU HÌNH
# =============================
TELEGRAM_BOT_TOKEN = "8264206004:AAH2zvVURgKLv9hZd-ZKTrB7xcZsaKZCjd0"
TELEGRAM_CHAT_ID = "8282016712"  # ví dụ: 8282016712
INTERVAL = "15m"  # khung thời gian
EMA_FAST = 9
EMA_SLOW = 21
SLEEP_TIME = 60  # mỗi 1 phút cập nhật 1 lần

# =============================
# 📡 HÀM GỬI TIN NHẮN TELEGRAM
# =============================
def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text})
        r.raise_for_status()
        print(f"✅ Telegram: {text}")
    except Exception as e:
        print(f"❌ Lỗi gửi telegram: {e}")

# =============================
# 📊 LẤY DANH SÁCH COIN CÓ VOLUME > 1M
# =============================
def get_all_usdt_symbols():
    try:
        info = requests.get("https://api.binance.com/api/v3/exchangeInfo", timeout=10).json()
        tickers = requests.get("https://api.binance.com/api/v3/ticker/24hr", timeout=10).json()

        if "symbols" not in info:
            print("⚠️ Không tìm thấy 'symbols' trong exchangeInfo!")
            return ["BTCUSDT", "ETHUSDT"]

        usdt_symbols = [
            s["symbol"]
            for s in info["symbols"]
            if s["symbol"].endswith("USDT")
            and s["status"] == "TRADING"
            and not s["symbol"].endswith("BUSDUSDT")
            and not s["symbol"].endswith("USDCUSDT")
        ]

        filtered = []
        for t in tickers:
            if t["symbol"] in usdt_symbols and float(t["quoteVolume"]) > 1_000_000:
                filtered.append(t["symbol"])

        print(f"✅ Lấy được {len(filtered)} cặp USDT có volume > 1M")
        return filtered or ["BTCUSDT", "ETHUSDT"]

    except Exception as e:
        print(f"❌ Lỗi lấy danh sách coin: {e}")
        return ["BTCUSDT", "ETHUSDT"]

# =============================
# 📈 LẤY DỮ LIỆU GIÁ & TÍNH EMA
# =============================
def get_ema_signal(symbol):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={INTERVAL}&limit=100"
        data = requests.get(url, timeout=10).json()
        closes = [float(x[4]) for x in data]

        df = pd.DataFrame(closes, columns=["close"])
        df["ema_fast"] = df["close"].ewm(span=EMA_FAST, adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=EMA_SLOW, adjust=False).mean()

        if df["ema_fast"].iloc[-2] < df["ema_slow"].iloc[-2] and df["ema_fast"].iloc[-1] > df["ema_slow"].iloc[-1]:
            return "BUY"
        elif df["ema_fast"].iloc[-2] > df["ema_slow"].iloc[-2] and df["ema_fast"].iloc[-1] < df["ema_slow"].iloc[-1]:
            return "SELL"
        else:
            return None
    except Exception:
        return None

# =============================
# 🔁 HÀM CHÍNH
# =============================
def main():
    symbols = get_all_usdt_symbols()
    print(f"📊 Đang theo dõi {len(symbols)} cặp coin...")

    while True:
        for sym in symbols:
            signal = get_ema_signal(sym)
            if signal:
                send_telegram_message(f"{signal} signal on {sym} ({INTERVAL})")
        time.sleep(SLEEP_TIME)

# =============================
# 🌐 FAKE FLASK SERVER (Render yêu cầu cổng)
# =============================
app = Flask(__name__)

@app.route("/")
def home():
    return "🚀 EMA Bot is running on Render Free 24/7!"

def run_Flask():
    app.run(host="0.0.0.0", port=10000)

# =============================
# ▶️ KHỞI CHẠY BOT
# =============================
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    send_telegram_message("✅ Bot EMA 9/21 đã khởi động trên Render!")
    main()


