import asyncio
import aiohttp
import pandas as pd
from datetime import datetime

# =============================
# CẤU HÌNH
# =============================
SETTINGS = {
    "INTERVAL": "5m",
    "EMA_SHORT": 9,
    "EMA_LONG": 21,
    "RSI_PERIOD": 14,
    "MACD_FAST": 12,
    "MACD_SLOW": 26,
    "MACD_SIGNAL": 9,
    "CONCURRENT_REQUESTS": 15,  # số coin quét đồng thời
    "SLEEP_BETWEEN_ROUNDS": 60, # giây giữa các vòng quét
    "TELEGRAM_BOT_TOKEN": "8264206004:AAH2zvVURgKLv9hZd-ZKTrB7xcZsaKZCjd0",
    "TELEGRAM_CHAT_ID": "8282016712",
}

# =============================
# Gửi Telegram
# =============================
async def send_telegram(session, text):
    url = f"https://api.telegram.org/bot{SETTINGS['TELEGRAM_BOT_TOKEN']}/sendMessage"
    payload = {"chat_id": SETTINGS["TELEGRAM_CHAT_ID"], "text": text, "parse_mode":"Markdown"}
    try:
        async with session.post(url, json=payload, timeout=10):
            pass
    except Exception as e:
        print("❌ Lỗi Telegram:", e)

# =============================
# Lấy danh sách coin USDT
# =============================
async def get_all_symbols(session):
    url = "https://api.binance.com/api/v3/exchangeInfo"
    for attempt in range(3):
        try:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    print(f"⚠️ Binance API trả code {resp.status}, thử lại...")
                    await asyncio.sleep(2)
                    continue
                data = await resp.json()
                if "symbols" not in data:
                    print("⚠️ Binance API trả dữ liệu không đúng format")
                    await asyncio.sleep(2)
                    continue
                symbols = [
                    s["symbol"] for s in data["symbols"]
                    if s["symbol"].endswith("USDT") and s["status"]=="TRADING"
                    and not any(x in s["symbol"] for x in ["UP","DOWN","BULL","BEAR"])
                ]
                print(f"✅ Tìm thấy {len(symbols)} coin USDT.")
                return symbols
        except Exception as e:
            print(f"⚠️ Lỗi lấy danh sách coin (attempt {attempt+1}): {e}")
            await asyncio.sleep(2)
    print("❌ Không lấy được danh sách coin sau 3 lần thử")
    return []

# =============================
# Lấy dữ liệu nến Binance
# =============================
async def get_klines(session, symbol):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={SETTINGS['INTERVAL']}&limit=100"
    for attempt in range(3):
        try:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    await asyncio.sleep(1)
                    continue
                data = await resp.json()
                df = pd.DataFrame(data, columns=[
                    "time","open","high","low","close","volume",
                    "close_time","qav","trades","tbbav","tbqav","ignore"
                ])
                df["close"] = df["close"].astype(float)
                return df
        except Exception as e:
            print(f"⚠️ Lỗi {symbol} attempt {attempt+1}: {e}")
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
    return 100 - 100/(1 + ma_up/ma_down)

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
# Kiểm tra tín hiệu
# =============================
def check_signal(df):
    if df is None or len(df) < max(SETTINGS["EMA_LONG"], SETTINGS["RSI_PERIOD"], SETTINGS["MACD_SLOW"]):
        return None

    df["ema_short"] = df["close"].ewm(span=SETTINGS["EMA_SHORT"]).mean()
    df["ema_long"] = df["close"].ewm(span=SETTINGS["EMA_LONG"]).mean()
    ema_signal = None
    if df["ema_short"].iloc[-2] < df["ema_long"].iloc[-2] and df["ema_short"].iloc[-1] > df["ema_long"].iloc[-1]:
        ema_signal = "BUY"
    elif df["ema_short"].iloc[-2] > df["ema_long"].iloc[-2] and df["ema_short"].iloc[-1] < df["ema_long"].iloc[-1]:
        ema_signal = "SELL"

    macd_line, signal_line, _ = calc_macd(df, SETTINGS["MACD_FAST"], SETTINGS["MACD_SLOW"], SETTINGS["MACD_SIGNAL"])
    macd_signal = None
    if macd_line.iloc[-2] < signal_line.iloc[-2] and macd_line.iloc[-1] > signal_line.iloc[-1]:
        macd_signal = "BUY"
    elif macd_line.iloc[-2] > signal_line.iloc[-2] and macd_line.iloc[-1] < signal_line.iloc[-1]:
        macd_signal = "SELL"

    df["rsi"] = calc_rsi(df, SETTINGS["RSI_PERIOD"])
    rsi_signal = None
    if df["rsi"].iloc[-1] < 30:
        rsi_signal = "BUY"
    elif df["rsi"].iloc[-1] > 70:
        rsi_signal = "SELL"

    signals = [s for s in [ema_signal, macd_signal, rsi_signal] if s]
    if signals.count("BUY") >= 2:
        return "BUY"
    elif signals.count("SELL") >= 2:
        return "SELL"
    return None

# =============================
# Quét coin
# =============================
async def scan_coin(session, symbol, semaphore):
    async with semaphore:
        df = await get_klines(session, symbol)
        signal = check_signal(df)
        return symbol, signal

# =============================
# Vòng quét chính
# =============================
async def main():
    semaphore = asyncio.Semaphore(SETTINGS["CONCURRENT_REQUESTS"])
    last_signals = {}

    async with aiohttp.ClientSession() as session:
        await send_telegram(session, "🚀 Bot EMA+MACD+RSI khởi động!")

        while True:
            symbols = await get_all_symbols(session)
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
                        new_signals.append(f"{symbol} → {signal}")
                        last_signals[symbol] = signal
                    if signal == "BUY":
                        total_buy += 1
                    elif signal == "SELL":
                        total_sell += 1
                else:
                    print("⚠️ Lỗi scan coin:", res)

            if new_signals:
                await send_telegram(f"📊 Tín hiệu mới:\n" + "\n".join(new_signals))

            summary = f"📈 Tổng kết: 🟢 MUA {total_buy} | 🔴 BÁN {total_sell} | ⏰ {datetime.now().strftime('%H:%M:%S')}"
            print(summary)
            await send_telegram(summary)

            await asyncio.sleep(SETTINGS["SLEEP_BETWEEN_ROUNDS"])

# =============================
# Keep-alive web server Fly.io
# =============================
async def keep_alive():
    from aiohttp import web
    async def handle(request):
        return web.Response(text="✅ Bot đang chạy")
    app = web.Application()
    app.add_routes([web.get("/", handle)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    while True:
        await asyncio.sleep(3600)

# =============================
# Chạy bot
# =============================
if __name__ == "__main__":
    try:
        asyncio.run(asyncio.gather(main(), keep_alive()))
    except KeyboardInterrupt:
        print("🛑 Bot dừng bằng tay")
