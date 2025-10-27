import asyncio
import aiohttp
import pandas as pd
from datetime import datetime
from aiohttp import web

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
    "MAX_COINS": 50,
    "SLEEP_BETWEEN_ROUNDS": 120,
    "CONCURRENT_REQUESTS": 10,
    "TELEGRAM_BOT_TOKEN": "8264206004:AAH2zvVURgKLv9hZd-ZKTrB7xcZsaKZCjd0", 
    "TELEGRAM_CHAT_ID": "8282016712",
    "COINGECKO_API": "https://api.coingecko.com/api/v3",
}

# =============================
# TELEGRAM
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
# LẤY DANH SÁCH TOP COIN
# =============================
async def get_top_coins(session):
    url = f"{SETTINGS['COINGECKO_API']}/coins/markets?vs_currency=usd&order=market_cap_desc&per_page={SETTINGS['MAX_COINS']}&page=1"
    for attempt in range(3):
        try:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return [coin["id"] for coin in data if "id" in coin]
        except Exception as e:
            print(f"⚠️ Không lấy được danh sách coin (attempt {attempt+1}):", e)
            await asyncio.sleep(2)
    return []

# =============================
# LẤY DỮ LIỆU NẾN
# =============================
async def get_klines(session, coin_id):
    url = f"{SETTINGS['COINGECKO_API']}/coins/{coin_id}/market_chart?vs_currency=usd&days=1&interval={SETTINGS['INTERVAL']}"
    try:
        async with session.get(url, timeout=10) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            prices = data.get("prices", [])
            if not prices:
                return None
            df = pd.DataFrame(prices, columns=["time", "close"])
            df["close"] = df["close"].astype(float)
            return df
    except Exception as e:
        print(f"⚠️ Lỗi API {coin_id.upper()}: {e}")
        return None

# =============================
# CHỈ BÁO RSI
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
# CHỈ BÁO MACD
# =============================
def calc_macd(df, fast, slow, signal):
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

# =============================
# KIỂM TRA TÍN HIỆU
# =============================
def check_signal(df):
    if df is None or len(df) < SETTINGS["EMA_LONG"]:
        return None, None

    df["ema_short"] = df["close"].ewm(span=SETTINGS["EMA_SHORT"], adjust=False).mean()
    df["ema_long"] = df["close"].ewm(span=SETTINGS["EMA_LONG"], adjust=False).mean()
    df["rsi"] = calc_rsi(df, SETTINGS["RSI_PERIOD"])
    macd_line, signal_line, _ = calc_macd(df, SETTINGS["MACD_FAST"], SETTINGS["MACD_SLOW"], SETTINGS["MACD_SIGNAL"])

    ema_signal = macd_signal = rsi_signal = None

    # EMA crossover
    if df["ema_short"].iloc[-2] < df["ema_long"].iloc[-2] and df["ema_short"].iloc[-1] > df["ema_long"].iloc[-1]:
        ema_signal = "BUY"
    elif df["ema_short"].iloc[-2] > df["ema_long"].iloc[-2] and df["ema_short"].iloc[-1] < df["ema_long"].iloc[-1]:
        ema_signal = "SELL"

    # MACD crossover
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

    if count_buy >= 2:
        return "BUY", "⚡ xác suất cao"
    elif count_sell >= 2:
        return "SELL", "⚡ xác suất cao"
    return None, None

# =============================
# QUÉT COIN
# =============================
async def scan_coin(session, coin_id, semaphore):
    async with semaphore:
        df = await get_klines(session, coin_id)
        signal, strength = check_signal(df)
        return coin_id, signal, strength

# =============================
# MAIN LOOP
# =============================
async def main_loop():
    semaphore = asyncio.Semaphore(SETTINGS["CONCURRENT_REQUESTS"])
    last_signals = {}

    async with aiohttp.ClientSession() as session:
        await send_telegram(session, f"🚀 Bot EMA+MACD+RSI khởi động — quét top {SETTINGS['MAX_COINS']} coin ({SETTINGS['INTERVAL']})")

        while True:
            coins = await get_top_coins(session)
            if not coins:
                print("⚠️ Không lấy được danh sách coin, thử lại sau.")
                await asyncio.sleep(10)
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

                if signal == "BUY":
                    total_buy += 1
                elif signal == "SELL":
                    total_sell += 1

            if new_signals:
                msg = "📊 *Tín hiệu mới EMA+MACD+RSI:*\n" + "\n".join(new_signals)
                print(msg)
                await send_telegram(session, msg)

            summary = f"📈 Tổng kết: 🟢 MUA {total_buy} | 🔴 BÁN {total_sell} | ⏰ {datetime.now().strftime('%H:%M:%S')}"
            print(summary)
            await send_telegram(session, summary)
            await asyncio.sleep(SETTINGS["SLEEP_BETWEEN_ROUNDS"])

# =============================
# KEEP-ALIVE WEB SERVICE
# =============================
async def keep_alive():
    async def handle(request):
        return web.Response(text="✅ Bot EMA+MACD+RSI đang chạy trên Fly.io!")
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()

# =============================
# ENTRY POINT
# =============================
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(keep_alive())
    try:
        loop.run_until_complete(main_loop())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()
