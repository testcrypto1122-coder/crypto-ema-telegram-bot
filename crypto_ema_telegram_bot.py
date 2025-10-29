import asyncio
import aiohttp
import pandas as pd
from datetime import datetime
import os
from aiohttp import web

# =============================
# ⚙️ CẤU HÌNH
# =============================
SETTINGS = {
    "INTERVAL": "15m",
    "EMA_SHORT": 9,
    "EMA_LONG": 21,
    "RSI_PERIOD": 14,
    "MACD_FAST": 12,
    "MACD_SLOW": 26,
    "MACD_SIGNAL": 9,
    "CONCURRENT_REQUESTS": 10,   # số coin quét đồng thời
    "SLEEP_BETWEEN_ROUNDS": 60,  # giây giữa các vòng quét
    "TELEGRAM_BOT_TOKEN": "8264206004:AAH2zvVURgKLv9hZd-ZKTrB7xcZsaKZCjd0",
    "TELEGRAM_CHAT_ID": "8282016712",
}

# =============================
# 📩 Gửi Telegram
# =============================
async def send_telegram(session, text):
    url = f"https://api.telegram.org/bot{SETTINGS['TELEGRAM_BOT_TOKEN']}/sendMessage"
    payload = {"chat_id": SETTINGS["TELEGRAM_CHAT_ID"], "text": text, "parse_mode": "Markdown"}
    try:
        async with session.post(url, json=payload, timeout=10):
            pass
    except Exception as e:
        print("❌ Lỗi gửi Telegram:", e)

# =============================
# 📊 Lấy danh sách coin USDT
# =============================
async def get_all_symbols(session):
    url = "https://api.binance.com/api/v3/exchangeInfo"
    async with session.get(url) as resp:
        data = await resp.json()
        symbols = [
            s["symbol"] for s in data.get("symbols", [])
            if s["symbol"].endswith("USDT")
            and s["status"]=="TRADING"
            and not any(x in s["symbol"] for x in ["UP","DOWN","BULL","BEAR"])
        ]
        print(f"✅ Lấy được {len(symbols)} coin USDT.")
        return symbols

# =============================
# 🕯️ Lấy dữ liệu nến Binance
# =============================
async def get_klines(session, symbol):
    url = f"https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": SETTINGS["INTERVAL"], "limit": 100}
    async with session.get(url, params=params) as resp:
        data = await resp.json()
        df = pd.DataFrame(data, columns=[
            "time","open","high","low","close","volume",
            "close_time","qav","trades","tbbav","tbqav","ignore"
        ])
        df["close"] = df["close"].astype(float)
        return df

# =============================
# 📈 Tính RSI
# =============================
def calc_rsi(df, period):
    delta = df["close"].diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ma_up = up.ewm(com=period-1, adjust=False).mean()
    ma_down = down.ewm(com=period-1, adjust=False).mean()
    return 100 - 100/(1 + ma_up/ma_down)

# =============================
# 📉 Tính MACD
# =============================
def calc_macd(df, fast, slow, signal):
    ema_fast = df["close"].ewm(span=fast).mean()
    ema_slow = df["close"].ewm(span=slow).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal).mean()
    return macd_line, signal_line, macd_line - signal_line

# =============================
# 🧠 Kiểm tra tín hiệu
# =============================
def check_signal(df):
    if df is None or len(df) < SETTINGS["EMA_LONG"]:
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
# 🔍 Quét từng coin
# =============================
async def scan_coin(session, symbol, semaphore):
    async with semaphore:
        df = await get_klines(session, symbol)
        return symbol, check_signal(df)

# =============================
# 🔁 Vòng quét chính
# =============================
async def main():
    semaphore = asyncio.Semaphore(SETTINGS["CONCURRENT_REQUESTS"])
    last_signals = {}

    async with aiohttp.ClientSession() as session:
        await send_telegram(session, "🚀 Bot EMA+MACD+RSI khởi động!")

        while True:
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🔍 Đang quét tín hiệu...")
            symbols = await get_all_symbols(session)
            tasks = [scan_coin(session, s, semaphore) for s in symbols]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            new_signals = []
            total_buy = total_sell = 0

            for res in results:
                if isinstance(res, tuple):
                    symbol, signal = res
                    if signal:
                        if signal == "BUY": total_buy += 1
                        elif signal == "SELL": total_sell += 1
                        prev_signal = last_signals.get(symbol)
                        if signal != prev_signal:
                            new_signals.append(f"{symbol} → {signal}")
                            last_signals[symbol] = signal

            if new_signals:
                msg = "📊 *Tín hiệu mới phát hiện:*\n" + "\n".join([f"• {s}" for s in new_signals])
                await send_telegram(session, msg)

            summary = f"📈 *Tổng kết vòng quét:*\n🟢 MUA: {total_buy} | 🔴 BÁN: {total_sell}\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            print(summary)
            await send_telegram(session, summary)
            await asyncio.sleep(SETTINGS["SLEEP_BETWEEN_ROUNDS"])

# =============================
# 🌐 Web keep-alive Fly.io
# =============================
async def keep_alive():
    async def handle(request):
        return web.Response(text="✅ Bot đang chạy!")
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    while True:
        await asyncio.sleep(3600)

# =============================
# 🚀 Chạy bot
# =============================
if __name__ == "__main__":
    try:
        asyncio.run(asyncio.gather(main(), keep_alive()))
    except KeyboardInterrupt:
        print("🛑 Bot dừng bằng tay")
