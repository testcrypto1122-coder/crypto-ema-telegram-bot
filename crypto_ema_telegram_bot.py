import os
import time
import requests
import pandas as pd
from flask import Flask
from datetime import datetime

# ==============================
# ⚙️ Cấu hình cơ bản
# ==============================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

API_URL = "https://api.binance.com/api/v3/klines"
INTERVAL = "5m"  # khung thời gian quét EMA
VOLUME_THRESHOLD = 500_000  # bỏ qua coin rác (volume < 500K USDT)

# Flask server để Render giữ app online
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ EMA Auto Scanner Bot đang hoạt động..."

# ==============================
# 🔹 Gửi tin nhắn Telegram
# ==============================
def send_telegram_message(message: str):
    if not TELEGRAM_BOT_TOKEN or not CHAT_ID:
        print("❌ Thiếu TELEGRAM_BOT_TOKEN hoặc CHAT_ID.")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": message}
        res = requests.post(url, json=payload)
        if res.status_code != 200:
            print("⚠️ Telegram error:", res.text)
    except Exception as e:
        print("❌ Telegram exception:", e)

# ==============================
# 🔹 Lấy dữ liệu coin
# ==============================
def get_binance_data(symbol: str, interval=INTERVAL, limit=100):
    try:
        url = f"{API_URL}?symbol={symbol}&interval={interval}&limit={limit}"
        res = requests.get(url)
        data = res.json()
        if not isinstance(data, list):
            return None
        df = pd.DataFrame(data, columns=[
            "Open time", "Open", "High", "Low", "Close", "Volume",
            "Close time", "Quote asset volume", "Number of trades",
            "Taker buy base asset volume", "Taker buy quote asset volume", "Ignore"
        ])
        df["Close"] = df["Close"].astype(float)
        df["Quote asset volume"] = df["Quote asset volume"].astype(float)
        return df
    except Exception as e:
        print(f"❌ Lỗi lấy dữ liệu {symbol}: {e}")
        return None

# ==============================
# 🔹 Tính EMA
# ==============================
def calculate_ema(df):
    df["EMA9"] = df["Close"].ewm(span=9, adjust=False).mean()
    df["EMA21"] = df["Close"].ewm(span=21, adjust=False).mean()
    return df

# ==============================
# 🔹 Kiểm tra tín hiệu EMA
# ==============================
def check_ema_signal(df):
    if df is None or len(df) < 2:
        return None
    prev = df.iloc[-2]
    last = df.iloc[-1]
    if prev["EMA9"] < prev["EMA21"] and last["EMA9"] > last["EMA21"]:
        return "BUY"
    elif prev["EMA9"] > prev["EMA21"] and last["EMA9"] < last["EMA21"]:
        return "SELL"
    else:
        return None

# ==============================
# 🔹 Lấy danh sách coin có volume cao
# ==============================
def get_top_coins(limit=30):
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr"
        res = requests.get(url).json()
        df = pd.DataFrame(res)
        df["quoteVolume"] = df["quoteVolume"].astype(float)
        df = df[df["symbol"].str.endswith("USDT")]
        df = df[df["quoteVolume"] > VOLUME_THRESHOLD]
        df = df.sort_values("quoteVolume", ascending=False).head(limit)
        coins = df["symbol"].tolist()
        return coins
    except Exception as e:
        print("❌ Lỗi lấy danh sách coin:", e)
        return ["BTCUSDT", "ETHUSDT"]

# ==============================
# 🔹 Vòng quét chính
# ==============================
def scan_coins():
    coins = get_top_coins()
    print(f"\n🔍 Quét {len(coins)} coin có volume cao... ({datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')})")

    for symbol in coins:
        df = get_binance_data(symbol)
        if df is None:
            continue

        total_volume = df["Quote asset volume"].iloc[-1]
        if total_volume < VOLUME_THRESHOLD:
            print(f"💤 Bỏ qua {symbol} (volume thấp)")
            continue

        df = calculate_ema(df)
        signal = check_ema_signal(df)
        price = df["Close"].iloc[-1]

        if signal == "BUY":
            msg = f"🚀 [{symbol}] MUA: EMA9 cắt lên EMA21 tại {price:.2f} USDT"
            send_telegram_message(msg)
            print(msg)
        elif signal == "SELL":
            msg = f"⚠️ [{symbol}] BÁN: EMA9 cắt xuống EMA21 tại {price:.2f} USDT"
            send_telegram_message(msg)
            print(msg)
        else:
            print(f"⏳ {symbol}: Không có tín hiệu mới.")

# ==============================
# 🔹 MAIN LOOP
# ==============================
def main():
    send_telegram_message("🤖 Bot EMA 9/21 Auto Scanner đã khởi động!")
    while True:
        try:
            scan_coins()
            print("⏸ Nghỉ 60 giây...\n")
            time.sleep(60)  # nghỉ 1 phút rồi quét lại
        except Exception as e:
            print("❌ Lỗi vòng lặp chính:", e)
            time.sleep(60)

# ==============================
# 🔹 Flask để giữ Render online
# ==============================
if __name__ == "__main__":
    import threading
    # Chạy bot trong luồng riêng
    threading.Thread(target=main, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
