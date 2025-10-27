# crypto_ema_telegram_bot.py
# Phiên bản: debug + retry + persistence để bắt API bị kill / rate-limit trên Render

import asyncio
import aiohttp
import pandas as pd
import json
import os
import time
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
    "MAX_COINS": 50,  # top coin
    "SLEEP_BETWEEN_ROUNDS": 120,
    "CONCURRENT_REQUESTS": 5,  # giảm concurrency để tránh rate-limit
    "TELEGRAM_BOT_TOKEN": "8264206004:AAH2zvVURgKLv9hZd-ZKTrB7xcZsaKZCjd0",
    "TELEGRAM_CHAT_ID": "8282016712",
    "COINSTATS_API": "https://api.coinstats.app/public/v1",
    "MAX_RETRIES": 3,
    "RETRY_BASE_DELAY": 1.5,
    "STATE_FILE": "last_signals.json",
    "ERROR_NOTIFY_THRESHOLD": 5,  # số lỗi liên tiếp để gửi cảnh báo telegram
}

# =============================
# TIỆN ÍCH: lưu / load trạng thái last_signals
# =============================
def load_state():
    try:
        if os.path.exists(SETTINGS["STATE_FILE"]):
            with open(SETTINGS["STATE_FILE"], "r") as f:
                return json.load(f)
    except Exception as e:
        print("⚠️ Không thể load state:", e, flush=True)
    return {}

def save_state(state):
    try:
        with open(SETTINGS["STATE_FILE"], "w") as f:
            json.dump(state, f)
    except Exception as e:
        print("⚠️ Không thể save state:", e, flush=True)

# =============================
# Telegram (async)
# =============================
async def send_telegram(session, text):
    url = f"https://api.telegram.org/bot{SETTINGS['TELEGRAM_BOT_TOKEN']}/sendMessage"
    payload = {"chat_id": SETTINGS["TELEGRAM_CHAT_ID"], "text": text}
    try:
        async with session.post(url, data=payload, timeout=10) as resp:
            await resp.text()
    except Exception as e:
        print("❌ Telegram error:", e, flush=True)

# =============================
# Lấy top coins
# =============================
async def get_top_coins(session):
    url = f"{SETTINGS['COINSTATS_API']}/coins?limit={SETTINGS['MAX_COINS']}"
    try:
        async with session.get(url, timeout=10) as resp:
            if resp.status != 200:
                text = await resp.text()
                print(f"⚠️ get_top_coins status={resp.status} text={text}", flush=True)
                return []
            data = await resp.json()
            return [coin["id"] for coin in data.get("coins", []) if "id" in coin]
    except Exception as e:
        print("⚠️ Lỗi lấy top coin:", e, flush=True)
        return []

# =============================
# Lấy klines với retry + backoff
# =============================
async def _fetch_with_retry(session, url):
    delay = SETTINGS["RETRY_BASE_DELAY"]
    for attempt in range(1, SETTINGS["MAX_RETRIES"] + 1):
        try:
            async with session.get(url, timeout=10) as resp:
                text = await resp.text()
                if resp.status == 200:
                    try:
                        return json.loads(text)
                    except Exception:
                        return None
                # xử lý rate limit / server errors
                if resp.status in (429, 500, 502, 503, 504):
                    print(f"⚠️ HTTP {resp.status} for {url} (attempt {attempt}) - backing off {delay}s", flush=True)
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                else:
                    print(f"⚠️ HTTP {resp.status} for {url}: {text}", flush=True)
                    return None
        except asyncio.TimeoutError:
            print(f"⚠️ Timeout calling {url} (attempt {attempt})", flush=True)
            await asyncio.sleep(delay)
            delay *= 2
        except Exception as e:
            print(f"⚠️ Exception calling {url}: {e} (attempt {attempt})", flush=True)
            await asyncio.sleep(delay)
            delay *= 2
    return None

async def get_klines(session, coin_id):
    # dùng endpoint charts period=24h để có chuỗi dài đủ tính chỉ báo
    url = f"{SETTINGS['COINSTATS_API']}/charts?period=24h&coinId={coin_id}"
    data = await _fetch_with_retry(session, url)
    if not data:
        return None
    prices = data.get("chart") or data.get("data") or []
    if not prices:
        return None
    try:
        df = pd.DataFrame(prices, columns=["time", "close"])
        df["close"] = df["close"].astype(float)
        return df
    except Exception as e:
        print(f"⚠️ Parse klines error for {coin_id}: {e}", flush=True)
        return None

# =============================
# Indicators
# =============================
def calc_rsi(df, period):
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_macd(df, fast, slow, signal):
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def check_signal(df):
    if df is None or len(df) < SETTINGS["EMA_LONG"] + 5:
        return None, None, {}
    df["ema_short"] = df["close"].ewm(span=SETTINGS["EMA_SHORT"], adjust=False).mean()
    df["ema_long"] = df["close"].ewm(span=SETTINGS["EMA_LONG"], adjust=False).mean()
    df["rsi"] = calc_rsi(df, SETTINGS["RSI_PERIOD"])
    macd_line, signal_line, hist = calc_macd(df, SETTINGS["MACD_FAST"], SETTINGS["MACD_SLOW"], SETTINGS["MACD_SIGNAL"])

    # đánh dấu từng thành phần để debug
    ema_signal = macd_signal = rsi_signal = None
    debug = {}

    prev_ema_short = df["ema_short"].iloc[-2]
    prev_ema_long = df["ema_long"].iloc[-2]
    last_ema_short = df["ema_short"].iloc[-1]
    last_ema_long = df["ema_long"].iloc[-1]
    debug["prev_ema_short"] = float(prev_ema_short)
    debug["prev_ema_long"] = float(prev_ema_long)
    debug["last_ema_short"] = float(last_ema_short)
    debug["last_ema_long"] = float(last_ema_long)

    if prev_ema_short < prev_ema_long and last_ema_short > last_ema_long:
        ema_signal = "BUY"
    elif prev_ema_short > prev_ema_long and last_ema_short < last_ema_long:
        ema_signal = "SELL"

    prev_macd = float(macd_line.iloc[-2] - signal_line.iloc[-2])
    last_macd = float(macd_line.iloc[-1] - signal_line.iloc[-1])
    debug["prev_macd_diff"] = prev_macd
    debug["last_macd_diff"] = last_macd
    if prev_macd < 0 and last_macd > 0:
        macd_signal = "BUY"
    elif prev_macd > 0 and last_macd < 0:
        macd_signal = "SELL"

    last_rsi = float(df["rsi"].iloc[-1])
    debug["last_rsi"] = last_rsi
    if last_rsi < 35:
        rsi_signal = "BUY"
    elif last_rsi > 65:
        rsi_signal = "SELL"

    signals = [s for s in [ema_signal, macd_signal, rsi_signal] if s]
    count_buy = signals.count("BUY")
    count_sell = signals.count("SELL")

    if count_buy >= 2:
        return "BUY", f"{count_buy}/3", debug
    elif count_sell >= 2:
        return "SELL", f"{count_sell}/3", debug
    return None, None, debug

# =============================
# Scan 1 coin (kèm logging)
# =============================
async def scan_coin(session, coin_id, semaphore):
    async with semaphore:
        df = await get_klines(session, coin_id)
        signal, strength, debug = check_signal(df)
        # debug print to console (Render logs)
        try:
            if df is not None and "last_rsi" in debug:
                print(f"🔎 {coin_id.upper():12} | price: {df['close'].iloc[-1]:.6f} | RSI:{debug['last_rsi']:.1f} | EMAshort:{debug['last_ema_short']:.6f} | EMA21:{debug['last_ema_long']:.6f} | MACDdiff:{debug['last_macd_diff']:.6f}", flush=True)
            else:
                print(f"🔎 {coin_id.upper():12} | NO DATA", flush=True)
        except Exception as e:
            print(f"⚠️ Print debug error for {coin_id}: {e}", flush=True)
        return coin_id, signal, strength

# =============================
# Main loop
# =============================
async def main():
    semaphore = asyncio.Semaphore(SETTINGS["CONCURRENT_REQUESTS"])
    last_signals = load_state()
    error_counter = 0
    notified_error = False

    async with aiohttp.ClientSession() as session:
        # notify start
        await send_telegram(session, f"🚀 Bot EMA+MACD+RSI (CoinStats) khởi động — quét top {SETTINGS['MAX_COINS']} coin ({SETTINGS['INTERVAL']})")
        while True:
            coins = await get_top_coins(session)
            if not coins:
                error_counter += 1
                print(f"⚠️ Không lấy được danh sách coin (attempts {error_counter})", flush=True)
                if error_counter >= SETTINGS["ERROR_NOTIFY_THRESHOLD"] and not notified_error:
                    await send_telegram(session, "⚠️ Bot gặp lỗi lặp. Không lấy được danh sách coin — có thể API bị rate-limit hoặc bị block.")
                    notified_error = True
                await asyncio.sleep(10)
                continue
            error_counter = 0
            notified_error = False

            print(f"\n=== 🕒 Bắt đầu quét lúc {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | coins={len(coins)} ===", flush=True)
            tasks = [scan_coin(session, c, semaphore) for c in coins]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            new_signals = []
            total_buy = total_sell = 0

            for res in results:
                if not isinstance(res, tuple):
                    print("⚠️ Task exception:", res, flush=True)
                    continue
                coin_id, signal, strength = res
                prev = last_signals.get(coin_id)
                if signal and signal != prev:
                    new_signals.append(f"{coin_id.upper()} → {signal} ({strength})")
                    last_signals[coin_id] = signal
                elif not signal:
                    last_signals[coin_id] = None
                if signal == "BUY":
                    total_buy += 1
                elif signal == "SELL":
                    total_sell += 1

            # persist state each round (cheap)
            try:
                save_state(last_signals)
            except Exception as e:
                print("⚠️ Lỗi save_state:", e, flush=True)

            if new_signals:
                msg = "📊 Tín hiệu mới EMA+MACD+RSI:\n" + "\n".join(new_signals)
                print(msg, flush=True)
                await send_telegram(session, msg)
            else:
                print(f"⏳ Không có tín hiệu mới. Tổng MUA {total_buy} | BÁN {total_sell}", flush=True)

            summary = f"📈 Tổng kết vòng quét: 🟢 MUA {total_buy} | 🔴 BÁN {total_sell} | ⏰ {datetime.now().strftime('%H:%M:%S')}"
            print(summary, flush=True)
            await send_telegram(session, summary)

            # nếu API có dấu hiệu lỗi quá nhiều lần, tăng sleep
            if error_counter > 0:
                sleep_time = SETTINGS["SLEEP_BETWEEN_ROUNDS"] * 2
            else:
                sleep_time = SETTINGS["SLEEP_BETWEEN_ROUNDS"]

            print(f"⏳ Nghỉ {sleep_time}s trước vòng tiếp theo...\n", flush=True)
            await asyncio.sleep(sleep_time)

# =============================
# keep_alive cho Render
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
