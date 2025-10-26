import asyncio
import aiohttp
import pandas as pd
from datetime import datetime

# =============================
# Cấu hình
# =============================
SETTINGS = {
    "INTERVAL": "5m",
    "EMA_SHORT": 9,
    "EMA_LONG": 21,
    "RSI_PERIOD": 14,
    "MACD_FAST": 12,
    "MACD_SLOW": 26,
    "MACD_SIGNAL": 9,
    "MAX_COINS": 20,  # top coin để giảm request
    "SLEEP_BETWEEN_ROUNDS": 60,
    "CONCURRENT_REQUESTS": 10,
    "TELEGRAM_BOT_TOKEN": "8264206004:AAH2zvVURgKLv9hZd-ZKTrB7xcZsaKZCjd0",
    "TELEGRAM_CHAT_ID": "8282016712",
    "BINANCE_API_TIMEOUT": 10,
}

# =============================
# Telegram
# =============================
async def send_telegram(session, text):
    url = f"https://api.telegram.org/bot{SETTINGS['TELEGRAM_BOT_TOKEN']}/sendMessage"
    payload = {"chat_id": SETTINGS["TELEGRAM_CHAT_ID"], "text": text}
    try:
        async with session.post(url, data=payload, timeout=10) as resp:
            await resp.text()
    except Exception as e:
        print("❌ Lỗi gửi Telegram:", e)

# =============================
# Lấy danh sách coin USDT
# =============================
async def get_all_usdt_symbols(session):
    try:
        async with session.get("https://api.binance.com/api/v3/exchangeInfo", timeout=SETTINGS["BINANCE_API_TIMEOUT"]) as resp:
            data = await resp.json()
        symbols = [
            s["symbol"] for s in data["symbols"]
            if s["symbol"].endswith("USDT") and s["status"]=="TRADING"
            and not any(x in s["symbol"] for x in ["UP","DOWN","BULL","BEAR"])
        ]
        return symbols[:SETTINGS["MAX_COINS"]]
    except Exception as e:
        print("❌ Lỗi lấy danh sách coin:", e)
        return []

# =============================
# Lấy dữ liệu nến
# =============================
async def get_klines(session, symbol):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={SETTINGS['INTERVAL']}&limit=100"
    for attempt in range(3):
        try:
            async with session.get(url, timeout=SETTINGS["BINANCE_API_TIMEOUT"]) as resp:
                data = await resp.json()
                df = pd.DataFrame(data, columns=[
                    "time","open","high","low","close","volume",
                    "close_time","qav","trades","tbbav","tbqav","ignore"
                ])
                df["close"] = df["close"].astype(float)
                return df
        except Exception as e:
            print(f"⚠️ Lỗi lấy {symbol}, attempt {attempt+1}: {e}")
            await asyncio.sleep(1)
    return None

# =============================
# Tính RSI
# =============================
def calc_rsi(df, period):
    delta = df["close"].diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ma_up = up.ewm(com=period-1, adjust=False).mean()
    ma_down = down.ewm(com=period-1, adjust=False).mean()
    rsi = 100 - (100 / (1 + ma_up / ma_down))
    return rsi

# =============================
# Tính MACD
# =============================
def calc_macd(df, fast, slow, signal):
    ema_fast = df["close"].ewm(span=fast).mean()
    ema_slow = df["close"].ewm(span=slow).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

# =============================
# Kiểm tra tín hiệu EMA + MACD + RSI
# =============================
def check_signal(df):
    if df is None or len(df) < max(SETTINGS["EMA_LONG"], SETTINGS["RSI_PERIOD"], SETTINGS["MACD_SLOW"]):
        return None

    # EMA
    df["ema_short"] = df["close"].ewm(span=SETTINGS["EMA_SHORT"]).mean()
    df["ema_long"] = df["close"].ewm(span=SETTINGS["EMA_LONG"]).mean()
    prev_short, prev_long = df["ema_short"].iloc[-2], df["ema_long"].iloc[-2]
    last_short, last_long = df["ema_short"].iloc[-1], df["ema_long"].iloc[-1]
    ema_signal = None
    if prev_short < prev_long and last_short > last_long:
        ema_signal = "BUY"
    elif prev_short > prev_long and last_short < last_long:
        ema_signal = "SELL"

    # MACD
    macd_line, signal_line, _ = calc_macd(df, SETTINGS["MACD_FAST"], SETTINGS["MACD_SLOW"], SETTINGS["MACD_SIGNAL"])
    prev_macd_diff = macd_line.iloc[-2] - signal_line.iloc[-2]
    last_macd_diff = macd_line.iloc[-1] - signal_line.iloc[-1]
    macd_signal = None
    if prev_macd_diff < 0 and last_macd_diff > 0:
        macd_signal = "BUY"
    elif prev_macd_diff > 0 and last_macd_diff < 0:
        macd_signal = "SELL"

    # RSI
    df["rsi"] = calc_rsi(df, SETTINGS["RSI_PERIOD"])
    last_rsi = df["rsi"].iloc[-1]
    rsi_signal = None
    if last_rsi < 30:
        rsi_signal = "BUY"
    elif last_rsi > 70:
        rsi_signal = "SELL"

    # Đồng thuận
    signals = [s for s in [ema_signal, macd_signal, rsi_signal] if s]
    if signals.count("BUY") >= 2:
        return "BUY"
    elif signals.count("SELL") >= 2:
        return "SELL"
    return None

# =============================
# Quét 1 coin
# =============================
async def scan_coin(session, symbol, semaphore):
    async with semaphore:
        df = await get_klines(session, symbol)
        signal = check_signal(df)
        return symbol, signal

# =============================
# Main loop
# =============================
async def main():
    semaphore = asyncio.Semaphore(SETTINGS["CONCURRENT_REQUESTS"])
    last_signals = {}

    async with aiohttp.ClientSession() as session:
        await send_telegram(session, f"🚀 Bot EMA+MACD+RSI khởi động — quét top {SETTINGS['MAX_COINS']} coin ({SETTINGS['INTERVAL']})")

        while True:
            symbols = await get_all_usdt_symbols(session)
            if not symbols:
                await asyncio.sleep(10)
                continue

            tasks = [scan_coin(session, s, semaphore) for s in symbols]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            new_signals = []
            total_buy = total_sell = 0

            for res in results:
                if isinstance(res, tuple):
                    symbol, signal = res
                    prev_signal = last_signals.get(symbol)
                    if signal and signal != prev_signal:
                        new_signals.append(f"{symbol} ➜ {signal}")
                        last_signals[symbol] = signal
                    elif not signal:
                        last_signals[symbol] = None

                    if signal == "BUY":
                        total_buy += 1
                    elif signal == "SELL":
                        total_sell += 1
                else:
                    print("⚠️ Lỗi quét coin:", res)

            # Gửi tín hiệu mới
            if new_signals:
                msg = "📊 Tín hiệu EMA+MACD+RSI mới:\n" + "\n".join(new_signals)
                print(msg)
                await send_telegram(session, msg)

            # Gửi tổng kết vòng quét
            summary = f"📈 Tổng kết vòng quét: 🟢 MUA {total_buy} | 🔴 BÁN {total_sell} | ⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            print(summary)
            await send_telegram(session, summary)

            print(f"⏳ Nghỉ {SETTINGS['SLEEP_BETWEEN_ROUNDS']} giây trước vòng quét tiếp theo...\n")
            await asyncio.sleep(SETTINGS["SLEEP_BETWEEN_ROUNDS"])

# =============================
# Chạy
# =============================
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Bot dừng bằng tay")
