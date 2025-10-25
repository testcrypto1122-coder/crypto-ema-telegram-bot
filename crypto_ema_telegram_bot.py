import requests
import pandas as pd
import time
from datetime import datetime

# =============================
# Cấu hình
# =============================
SETTINGS = {
    "INTERVAL": "15m",
    "TELEGRAM_BOT_TOKEN": "8264206004:AAH2zvVURgKLv9hZd-ZKTrB7xcZsaKZCjd0",
    "TELEGRAM_CHAT_ID": "8282016712",
}

# =============================
# Hàm lấy danh sách coin USDT
# =============================
def get_all_usdt_symbols():
    """Lấy danh sách các cặp USDT có khối lượng giao dịch > 1 triệu USDT (tránh coin rác)."""
    try:
        # 1️⃣ Lấy thông tin sàn (danh sách cặp)
        url_info = "https://api.binance.com/api/v3/exchangeInfo"
        data_info = requests.get(url_info, timeout=10).json()

        if "symbols" not in data_info:
            print("⚠️ Không tìm thấy trường 'symbols' trong exchangeInfo!")
            return ["BTCUSDT", "ETHUSDT"]

        # 2️⃣ Lọc các cặp USDT hợp lệ
        usdt_symbols = [
            s["symbol"]
            for s in data_info["symbols"]
            if s["symbol"].endswith("USDT")
            and s["status"] == "TRADING"
            and not s["symbol"].endswith("BUSDUSDT")
            and not s["symbol"].endswith("USDCUSDT")
        ]

        # 3️⃣ Lấy dữ liệu 24h để lọc volume
        url_ticker = "https://api.binance.com/api/v3/ticker/24hr"
        data_ticker = requests.get(url_ticker, timeout=10).json()

        filtered_symbols = []
        for t in data_ticker:
            if t["symbol"] in usdt_symbols:
                vol = float(t["quoteVolume"])
                if vol >= 1_000_000:  # Chỉ giữ coin có volume > 1 triệu USDT
                    filtered_symbols.append(t["symbol"])

        print(f"✅ Lấy được {len(filtered_symbols)} cặp USDT có volume > 1M từ Binance")
        return filtered_symbols if filtered_symbols else ["BTCUSDT", "ETHUSDT"]

    except Exception as e:
        print(f"❌ Lỗi khi lấy danh sách coin: {e}")
        return ["BTCUSDT", "ETHUSDT"]


# =============================
# Lấy dữ liệu nến
# =============================
def get_klines(symbol, interval="15m", limit=100):
    url = f"https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    data = requests.get(url, params=params, timeout=10).json()
    df = pd.DataFrame(data, columns=[
        "time", "open", "high", "low", "close", "volume",
        "close_time", "qav", "trades", "tbbav", "tbqav", "ignore"
    ])
    df["close"] = df["close"].astype(float)
    return df

# =============================
# Gửi tin nhắn Telegram
# =============================
def send_telegram_message(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print("Lỗi gửi Telegram:", e)

# =============================
# Logic tín hiệu EMA
# =============================
def check_ema_cross(symbol, interval="15m"):
    try:
        df = get_klines(symbol, interval)
        df["ema9"] = df["close"].ewm(span=9).mean()
        df["ema21"] = df["close"].ewm(span=21).mean()

        prev_ema9, prev_ema21 = df["ema9"].iloc[-2], df["ema21"].iloc[-2]
        last_ema9, last_ema21 = df["ema9"].iloc[-1], df["ema21"].iloc[-1]

        if prev_ema9 < prev_ema21 and last_ema9 > last_ema21:
            return "BUY"
        elif prev_ema9 > prev_ema21 and last_ema9 < last_ema21:
            return "SELL"
    except Exception as e:
        print(f"Lỗi {symbol}: {e}")
    return None

# =============================
# Main loop
# =============================
def main():
    symbols = get_all_usdt_symbols()
    send_telegram_message(SETTINGS["TELEGRAM_BOT_TOKEN"], SETTINGS["TELEGRAM_CHAT_ID"],
                          f"🚀 Bot EMA khởi động thành công — theo dõi {len(symbols)} coin USDT (khung {SETTINGS['INTERVAL']})")

    while True:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Đang quét tín hiệu...")
        for sym in symbols:
            signal = check_ema_cross(sym, SETTINGS["INTERVAL"])
            if signal:
                msg = f"📊 {sym} | EMA9/21 ({SETTINGS['INTERVAL']}) ➜ {signal}"
                print(msg)
                send_telegram_message(SETTINGS["TELEGRAM_BOT_TOKEN"], SETTINGS["TELEGRAM_CHAT_ID"], msg)
            time.sleep(0.3)
        print("Hoàn tất chu kỳ. Nghỉ 1 phút...\n")
        time.sleep(60)

# =============================
# Chạy thử
# =============================
if __name__ == "__main__":
    print("Testing Telegram connection...")
    send_telegram_message(
        SETTINGS["TELEGRAM_BOT_TOKEN"],
        SETTINGS["TELEGRAM_CHAT_ID"],
        "✅ Test message: Bot kết nối thành công với Telegram!"
    )
    print("✅ Đã gửi tin nhắn test, kiểm tra Telegram nhé!")
    time.sleep(3)
    print("Starting EMA crossover bot...")
    main()

