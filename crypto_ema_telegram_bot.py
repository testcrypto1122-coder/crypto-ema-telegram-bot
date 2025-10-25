import requests
import pandas as pd
import time
from datetime import datetime, timezone
from flask import Flask
import threading
import os

# === Cấu hình Telegram ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

if not BOT_TOKEN or not CHAT_ID:
    print("⚠️ Vui lòng đặt BOT_TOKEN và CHAT_ID trong biến môi trường Render.")
    exit(1)

# === Cấu hình EMA ===
INTERVAL = "5m"
EMA_SHORT = 9
EMA_LONG = 21
LIMIT_COINS = 100  # Giới hạn số coin để quét

app = Flask(__name__)

# === Gửi tin nhắn Telegram ===
def send_telegram_message(message: str):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": message}
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            print(f"❌ Lỗi gửi Telegram: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Lỗi gửi Telegram: {e}")

# === Lấy dữ liệu nến từ Binance ===
def get_binance_data(symbol: str, interval=INTERVAL, limit=100):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
        data = requests.get(url, timeout=10).json()
        df = pd.DataFrame(data, columns=[
            "time", "open", "high", "low", "close", "volume", "close_time",
            "quote_asset_volume", "num_trades", "tb_base_vol", "tb_quote_vol", "ignore"
        ])
        df["close"] = df["close"].astype(float)
        return df
    except Exception as e:
        print(f"⚠️ Lỗi lấy dữ liệu {symbol}: {e}")
        return None

# === Kiểm tra giao cắt EMA ===
def check_ema_crossover(symbol: str):
    df = get_binance_data(symbol)
    if df is None or len(df) < EMA_LONG:
        return None

    df["ema_short"] = df["close"].ewm(span=EMA_SHORT).mean()
    df["ema_long"] = df["close"].ewm(span=EMA_LONG).mean()

    prev_short, prev_long = df["ema_short"].iloc[-2], df["ema_long"].iloc[-2]
    last_short, last_long = df["ema_short"].iloc[-1], df["ema_long"].iloc[-1]

    if prev_short < prev_long and last_short > last_long:
        msg = f"🟢 {symbol} — EMA9 cắt lên EMA21 → Tín hiệu MUA"
        print(msg)
        send_telegram_message(msg)
        return "BUY"

    elif prev_short > prev_long and last_short < last_long:
        msg = f"🔴 {symbol} — EMA9 cắt xuống EMA21 → Tín hiệu BÁN"
        print(msg)
        send_telegram_message(msg)
        return "SELL"

    return None

# === Hàm chính quét coin ===
def main():
    send_telegram_message("🚀 Bot EMA 9/21 đã khởi động và bắt đầu quét coin!")

    while True:
        try:
            # Lấy danh sách coin USDT, loại bỏ coin rác
            exchange_info = requests.get("https://api.binance.com/api/v3/exchangeInfo").json()
            all_coins = [
                s['symbol'] for s in exchange_info['symbols']
                if s['quoteAsset'] == 'USDT' and not any(x in s['symbol'] for x in ['UP', 'DOWN', 'BULL', 'BEAR'])
            ][:LIMIT_COINS]

            print(f"\n🔍 Quét {len(all_coins)} coin... ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')})")

            buy_signals, sell_signals = 0, 0

            for symbol in all_coins:
                result = check_ema_crossover(symbol)
                if result == "BUY":
                    buy_signals += 1
                elif result == "SELL":
                    sell_signals += 1
                time.sleep(0.5)

            summary = f"📊 Tổng kết vòng quét:\n" \
                      f"🪙 Coin quét: {len(all_coins)}\n" \
                      f"🟢 MUA: {buy_signals} | 🔴 BÁN: {sell_signals}\n" \
                      f"⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
            print(summary)
            send_telegram_message(summary)
            send_telegram_message("✅ Đã quét xong vòng này, bot sẽ nghỉ 60 giây...")

            time.sleep(60)

        except Exception as e:
            print(f"❌ Lỗi vòng quét: {e}")
            time.sleep(30)

# === Flask giữ bot chạy trên Render ===
@app.route('/')
def home():
    return "✅ EMA Bot đang hoạt động ổn định!"

if __name__ == '__main__':
    threading.Thread(target=main, daemon=True).start()
    app.run(host='0.0.0.0', port=10000)
