import asyncio
import aiohttp
import pandas as pd
from datetime import datetime
from aiohttp import web

# =============================
# ⚙️ Cấu hình
# =============================
SETTINGS = {
    "INTERVAL": "5m",  # khoảng thời gian nến
    "EMA_SHORT": 9,
    "EMA_LONG": 21,
    "RSI_PERIOD": 14,
    "MACD_FAST": 12,
    "MACD_SLOW": 26,
    "MACD_SIGNAL": 9,
    "MAX_COINS": 50,  # top coin theo CoinStats
    "SLEEP_BETWEEN_ROUNDS": 120,  # thời gian nghỉ giữa các vòng (giây)
    "CONCURRENT_REQUESTS": 10,
    "TELEGRAM_BOT_TOKEN": "8264206004:AAH2zvVURgKLv9hZd-ZKTrB7xcZsaKZCjd0",
    "TELEGRAM_CHAT_ID": "8282016712",
    "COINSTATS_API": "https://api.coinstats.app/public/v1",
}

# =============================
# 📨 Gửi thông báo Telegram
# =============================
async def send_telegram(session, text):
    url = f"https://api.telegram.org/bot{SETTINGS['TELEGRAM_BOT_TOKEN']}/sendMessage"
    payload = {"chat_id": SETTINGS["TELEGRAM_CHAT_ID"], "text": text}
    try:
        async with session.post(url, data=payload, timeout=10):
            pass
    except Exception as e:
        print("❌ Telegram error:", e)

# =============================
# 🪙 Lấy danh sách top coin
# =============================
async def get_top_coins(session):
    url = f"{SETTINGS['COINSTATS_API']}/coins?limit={SETTINGS['MAX_COINS']}"
    try:
        async with session.get(url, timeout=10) as resp:
            data = await resp.json()
            return [coin["id"] for coin in data.get("coins", []) if "id" in coin]
    except Exception as e:
        print("⚠️ Lỗi lấy top coin:", e)
        return []

# =============================
# 🕐 Lấy dữ liệu giá CoinStats
# =============================
async def get_klines(session, coin_id):
    # period = 5m, 15m, 1h, 4h, 1d
    period_map = {"5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}
    interval = period_map.get(SETTINGS["INTERVAL"], "5m")
    url = f"{SETTINGS['COINSTATS_API']}/charts?period={interval}&coinId={coin_id}"
    try:
        async with session.get(url, timeout=10) as resp:
            data = await resp.json()
            prices = data.get("chart", [])
            if not prices:
                return None
            df = pd.DataFrame(prices, columns=["time", "close"])
            df["close"] = df["close"].astype(float)
            return df
    except Exception as e:
        print(f"⚠️ Lỗi API {coin_id}: {e}")
        return None

# =============================
# 📊 Tính RSI
# =============================
def calc_rsi(df, period):
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# =============================
# 📈 Tính MACD
# =============================
def calc_macd(df, fast, slow, signal):
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

# =============================
# 🔎 Kiểm tra tín hiệu
# =============================
def check_signal(df):
    if df is None or len(df) < SETTINGS["EMA_LONG"]:
        return None, None

    df["ema_short"] = df["close"].ewm(span=SETTINGS["EMA_SHORT"], adjust=False).mean()
    df["ema_long"] = df["close"].ewm(span=SETTINGS["EMA_LONG"], adjust=False).mean()
    df["rsi"] = calc_rsi(df, SETTINGS["RSI_PERIOD"])
    macd_line, signal_line, _ = calc_macd(df, SETTINGS["MACD_FAST"], SETTINGS["MACD_SLOW"], SETTINGS["MACD_SIGNAL"])

    ema_signal = macd_signal = rsi_signal = None

    # EMA
    if df["ema_short"].iloc[-2] < df["ema_long"].iloc[-2] and df["ema_short"].iloc[-1] > df["ema_long"].iloc[-1]:
        ema_signal = "BUY"
    elif df["ema_short"].iloc[-2] > df["ema_long"].iloc[-2] and df["ema_short"].iloc[-1] < df["ema_long"].iloc[-1]:
        ema_signal = "SELL"

    # MACD
    if macd_line.iloc[-2] < signal_line.iloc[-2] and macd_line.iloc[-1] > signal_line.iloc[-1]:
        macd_signal = "BUY"
    elif macd_line.iloc[-2] > signal_line.iloc[-2] and macd_line.iloc[-1] < signal_line.iloc[-1]:
        macd_signal = "SELL"

    # RSI
    last_rsi = df["rsi"].iloc[-1]
    if last_rsi < 30:
        rsi_signal = "BUY"
    elif last_rsi > 70:
        rsi_signal = "SELL"

    signals = [s for s in [ema_signal, macd_signal, rsi_signal] if s]
    count_buy = signals.count("BUY")
    count_sell = signals.count("SELL")

    if count_buy == 3:
        return "BUY", "🔥 mạnh"
    elif count_sell == 3:
        return "SELL", "🔥 mạnh"
    elif count_buy == 2:
        return "BUY", "⚡ yếu"
    elif count_sell == 2:
        return "SELL", "⚡ yếu"
    return None, None

# =============================
# ⚙️ Quét coin
# =============================
async def scan_coin(session, coin_id, semaphore):
    async with semaphore:
        df = await get_klines(session, coin_id)
        signal, strength = check_signal(df)
        return coin_id, signal, strength

# =============================
# 🧠 Main loop
# =============================
async def main():
    semaphore = asyncio.Semaphore(SETTINGS["CONCURRENT_REQUESTS"])
    last_signals = {}

    async with aiohttp.ClientSession() as session:
        await send_telegram(session, f"🚀 Bot EMA+MACD+RSI khởi động — quét top {SETTINGS['MAX_COINS']} coin ({SETTINGS['INTERVAL']})")

        while True:
            coins = await get_top_coins(session)
            if not coins:
                await asyncio.sleep(15)
                continue

            tasks = [scan_coin(session, c, semaphore) for c in coins]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            new_signals = []
            total_buy = total_sell = 0

            for res in results:
                if not isinstance(res, tuple):
                    continue
                coin_id, signal, strength = res
                prev_signal = last_signals.get(coin_id)

                if signal and signal != prev_signal:
                    new_signals.append(f"{coin_id.upper()} → {signal} {strength}")
                    last_signals[coin_id] = signal
                elif not signal:
                    last_signals[coin_id] = None

                if signal == "BUY":
                    total_buy += 1
                elif signal == "SELL":
                    total_sell += 1

            if new_signals:
                msg = "📊 *Tín hiệu mới EMA+MACD+RSI:*\n" + "\n".join(new_signals)
                print(msg)
                await send_telegram(session, msg)

            summary = f"📈 Tổng kết vòng quét: 🟢 MUA {total_buy} | 🔴 BÁN {total_sell} | ⏰ {datetime.now().strftime('%H:%M:%S')}"
            print(summary)
            await send_telegram(session, summary)

            await asyncio.sleep(SETTINGS["SLEEP_BETWEEN_ROUNDS"])

# =============================
# 🌐 Giữ bot sống trên Render
# =============================
async def keep_alive():
    async def handle(request):
        return web.Response(text="✅ Bot EMA+MACD+RSI (CoinStats) đang chạy OK")
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 10000)
    await site.start()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(keep_alive())
    loop.run_until_complete(main())
