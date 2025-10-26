# =============================================
# CRYPTO EMA+MACD+RSI BOT — Render Free (Batch Mode)
# =============================================
import os
import requests
import pandas as pd
import time
import threading
from datetime import datetime
import http.server
import socketserver

# =============================
# Cấu hình bot
# =============================
SETTINGS = {
    "INTERVAL": "5m",
    "PAIR_LIST": [
        "BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","LINKUSDT","ADAUSDT","AVAXUSDT",
        "XRPUSDT","DOTUSDT","MATICUSDT","DOGEUSDT","ATOMUSDT","OPUSDT","ARBUSDT",
        "NEARUSDT","APTUSDT","SUIUSDT","TIAUSDT","FILUSDT","SEIUSDT",
        "FTMUSDT","AAVEUSDT","INJUSDT","RNDRUSDT","GRTUSDT","RUNEUSDT","KAVAUSDT",
        "CAKEUSDT","TRXUSDT","UNIUSDT","LTCUSDT","ETCUSDT","PEPEUSDT","WLDUSDT",
        "JUPUSDT","PYTHUSDT","STRKUSDT","SKLUSDT","CHZUSDT","XLMUSDT"
    ],
    "BATCH_SIZE": 10,   # mỗi nhóm quét 10 coin để không quá tải
    "TELEGRAM_BOT_TOKEN": "8264206004:AAH2zvVURgKLv9hZd-ZKTrB7xcZsaKZCjd0",
    "TELEGRAM_CHAT_ID": "8282016712",
    "EMA_FAST": 9,
    "EMA_SLOW": 21,
    "RSI_PERIOD": 14,
    "SLEEP_TIME": 300  # nghỉ 5 phút giữa các vòng quét
}

# =============================
# Giữ Render không timeout (web service)
# =============================
def keep_alive():
    PORT = int(os.environ.get("PORT", 10000))
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", PORT), handler) as httpd:
        print(f"✅ Keep-alive server chạy tại port {PORT}")
        httpd.serve_forever()

threading.Thread(target=keep_alive, daemon=True).start()

# =============================
# Gửi tin Telegram
# =============================
def send_telegram(msg: str):
    try:
        url = f"https://api.telegram.org/bot{SETTINGS['TELEGRAM_BOT_TOKEN']}/sendMessage"
        data = {"chat_id": SETTINGS["TELEGRAM_CHAT_ID"], "text": msg, "parse_mode": "HTML"}
        requests.post(url, data=data, timeout=10)
    except Exception as e:
        print(f"Lỗi gửi Telegram: {e}")

# =============================
# Lấy dữ liệu nến Binance
# =============================
def get_klines(symbol, interval="5m", limit=100):
    url = f"https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        res = requests.get(url, params=params, timeout=10)
        data = res.json()
        if isinstance(data, list):
            df = pd.DataFrame(data, columns=[
                "time","open","high","low","close","volume",
                "_1","_2","_3","_4","_5","_6"
            ])
            df["close"] = df["close"].astype(float)
            return df
        else:
            print(f"Lỗi API {symbol}: {data}")
            return pd.DataFrame()
    except Exception as e:
        print(f"Lỗi lấy dữ liệu {symbol}: {e}")
        return pd.DataFrame()

# =============================
# Tính toán chỉ báo
# =============================
def calc_rsi(df, period=14):
    delta = df["close"].diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ma_up = up.ewm(com=period-1, adjust=False).mean()
    ma_down = down.ewm(com=period-1, adjust=False).mean()
    rsi = 100 - (100 / (1 + ma_up / ma_down))
    return rsi

def calc_macd(df, fast=12, slow=26, signal=9):
    ema_fast = df["close"].ewm(span=fast).mean()
    ema_slow = df["close"].ewm(span=slow).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

# =============================
# Kiểm tra tín hiệu đồng thuận
# =============================
def check_signal(df):
    if len(df) < 30:
        return None

    # EMA
    df["ema_fast"] = df["close"].ewm(span=SETTINGS["EMA_FAST"]).mean()
    df["ema_slow"] = df["close"].ewm(span=SETTINGS["EMA_SLOW"]).mean()
    prev_short, prev_long = df["ema_fast"].iloc[-2], df["ema_slow"].iloc[-2]
    last_short, last_long = df["ema_fast"].iloc[-1], df["ema_slow"].iloc[-1]
    ema_signal = "BUY" if prev_short < prev_long and last_short > last_long else "SELL" if prev_short > prev_long and last_short < last_long else None

    # MACD
    macd_line, signal_line, _ = calc_macd(df)
    prev_macd_diff = macd_line.iloc[-2] - signal_line.iloc[-2]
    last_macd_diff = macd_line.iloc[-1] - signal_line.iloc[-1]
    macd_signal = "BUY" if prev_macd_diff < 0 and last_macd_diff > 0 else "SELL" if prev_macd_diff > 0 and last_macd_diff < 0 else None

    # RSI
    df["rsi"] = calc_rsi(df, SETTINGS["RSI_PERIOD"])
    last_rsi = df["rsi"].iloc[-1]
    rsi_signal = "BUY" if last_rsi < 30 else "SELL" if last_rsi > 70 else None

    # Đồng thuận
    signals = [s for s in [ema_signal, macd_signal, rsi_signal] if s]
    if signals.count("BUY") >= 2:
        return "BUY"
    elif signals.count("SELL") >= 2:
        return "SELL"
    return None

# =============================
# Vòng quét chính
# =============================
def main_loop():
    while True:
        start = datetime.now()
        send_telegram(f"🚀 <b>EMA+MACD+RSI Bot khởi động</b>\n⏰ {start.strftime('%Y-%m-%d %H:%M:%S')}\n🧩 Đang quét {len(SETTINGS['PAIR_LIST'])} coin...")

        total_buy = total_sell = 0
        signals_found = []

        for i in range(0, len(SETTINGS["PAIR_LIST"]), SETTINGS["BATCH_SIZE"]):
            batch = SETTINGS["PAIR_LIST"][i:i + SETTINGS["BATCH_SIZE"]]
            for symbol in batch:
                df = get_klines(symbol, SETTINGS["INTERVAL"])
                if df.empty:
                    continue
                signal = check_signal(df)
                if signal:
                    signals_found.append(f"{symbol} ➜ <b>{signal}</b>")
                    if signal == "BUY":
                        total_buy += 1
                    else:
                        total_sell += 1
                time.sleep(0.5)
            time.sleep(2)  # nghỉ giữa các batch để giảm tải

        if signals_found:
            send_telegram("📊 <b>Tín hiệu mới:</b>\n" + "\n".join(signals_found))
        else:
            print("⏱ Không có tín hiệu mới.")

        summary = f"📈 Tổng kết: 🟢 BUY {total_buy} | 🔴 SELL {total_sell}\n⏰ {datetime.now().strftime('%H:%M:%S')}"
        send_telegram(summary)
        print(summary)
        time.sleep(SETTINGS["SLEEP_TIME"])

# =============================
# Khởi chạy
# =============================
if __name__ == "__main__":
    print("🚀 Bot EMA+MACD+RSI đang chạy trên Render...")
    send_telegram("🤖 Bot EMA+MACD+RSI đã khởi động trên Render Free tier.")
    main_loop()
