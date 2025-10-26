import requests
import pandas as pd
import time
from datetime import datetime

# =============================
# Cấu hình
# =============================
SETTINGS = {
    "INTERVAL": "5m",
    "TELEGRAM_BOT_TOKEN": "8264206004:AAH2zvVURgKLv9hZd-ZKTrB7xcZsaKZCjd0",
    "TELEGRAM_CHAT_ID": "8282016712",
    "MAX_COINS": 50,    # chỉ quét top 50 coin
}

# =============================
# Lấy danh sách coin USDT
# =============================
def get_all_usdt_symbols():
    url = "https://api.binance.com/api/v3/exchangeInfo"
    data = requests.get(url, timeout=10).json()
    symbols = [
        s["symbol"]
        for s in data["symbols"]
        if s["symbol"].endswith("USDT")
        and s["status"] == "TRADING"
        and not any(x in s["symbol"] for x in ["UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT"])
    ]
    print(f"Tìm thấy {len(symbols)} cặp USDT đang giao dịch.")
    return symbols[:SETTINGS["MAX_COINS"]]

# =============================
# Lấy dữ liệu nến
# =============================
def get_klines(symbol, interval="5m", limit=100):
    url = f"https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    data = requests.get(url, params=params, timeout=10).json()
    df = pd.DataFrame(data, columns=[
        "time","open","high","low","close","volume",
        "close_time","qav","trades","tbbav","tbqav","ignore"
    ])
    df["close"] = df["close"].astype(float)
    return df

# =============================
# Gửi tin nhắn Telegram
# =============================
def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{SETTINGS['TELEGRAM_BOT_TOKEN']}/sendMessage"
    payload = {"chat_id": SETTINGS["TELEGRAM_CHAT_ID"], "text": text}
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print("Lỗi gửi Telegram:", e)

# =============================
# Kiểm tra EMA crossover
# =============================
def check_ema_cross(symbol):
    try:
        df = get_klines(symbol, SETTINGS["INTERVAL"])
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
    send_telegram_message(f"🚀 Bot EMA khởi động thành công — theo dõi {len(symbols)} coin USDT (khung {SETTINGS['INTERVAL']})")

    while True:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Đang quét tín hiệu...")
        buy_count, sell_count = 0, 0

        for sym in symbols:
            signal = check_ema_cross(sym)
            if signal:
                msg = f"📊 {sym} | EMA9/21 ({SETTINGS['INTERVAL']}) ➜ {signal}"
                print(msg)
                send_telegram_message(msg)
                if signal == "BUY":
                    buy_count += 1
                else:
                    sell_count += 1
            time.sleep(0.5)  # nghỉ 0.5s giữa các request để nhẹ CPU

        summary = f"✅ Đã quét xong vòng: 🟢 MUA {buy_count} | 🔴 BÁN {sell_count} | ⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        print(summary)
        send_telegram_message(summary)
        print("⏳ Nghỉ 60 giây trước vòng quét tiếp theo...\n")
        time.sleep(60)

if __name__ == "__main__":
    main()
