import asyncio
import aiohttp
import pandas as pd
from datetime import datetime, timezone
from flask import Flask
import os

# === Cấu hình Telegram ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "8264206004:AAH2zvVURgKLv9hZd-ZKTrB7xcZsaKZCjd0")
CHAT_ID = os.getenv("CHAT_ID", "8282016712")

# === Cấu hình EMA ===
INTERVAL = "5m"
EMA_SHORT = 9
EMA_LONG = 21
CONCURRENT_REQUESTS = 10  # số coin request cùng lúc trên Render
SLEEP_BETWEEN_ROUNDS = 60  # giây nghỉ giữa các vòng quét

app = Flask(__name__)

# === Gửi tin nhắn Telegram ===
async def send_telegram_message(session, message: str):
    if not BOT_TOKEN or not CHAT_ID:
        print("⚠️ Thiếu BOT_TOKEN hoặc CHAT_ID.")
        return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
        async with session.post(url, json=payload, timeout=10) as resp:
            await resp.text()
    except Exception as e:
        print(f"❌ Lỗi gửi Telegram: {e}")

# === Lấy dữ liệu nến từ Binance với retry ===
async def get_binance_data(session, symbol: str, interval=INTERVAL, limit=100):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    for attempt in range(3):
        try:
            async with session.get(url, timeout=10) as resp:
                data = await resp.json()
                df = pd.DataFrame(data, columns=[
                    "time","open","high","low","close","volume","close_time",
                    "quote_asset_volume","num_trades","tb_base_vol","tb_quote_vol","ignore"
                ])
                df["close"] = df["close"].astype(float)
                return df
        except Exception as e:
            print(f"⚠️ Lỗi lấy dữ liệu {symbol} (attempt {attempt+1}): {e}")
            await asyncio.sleep(1)
    return None

# === Kiểm tra EMA crossover ===
def check_ema_crossover_df(df):
    if df is None or len(df) < EMA_LONG:
        return None
    df["ema_short"] = df["close"].ewm(span=EMA_SHORT).mean()
    df["ema_long"] = df["close"].ewm(span=EMA_LONG).mean()
    prev_short, prev_long = df["ema_short"].iloc[-2], df["ema_long"].iloc[-2]
    last_short, last_long = df["ema_short"].iloc[-1], df["ema_long"].iloc[-1]
    if prev_short < prev_long and last_short > last_long:
        return "BUY"
    elif prev_short > prev_long and last_short < last_long:
        return "SELL"
    return None

# === Quét từng coin với semaphore ===
async def scan_coin(session, symbol, semaphore):
    async with semaphore:
        df = await get_binance_data(session, symbol)
        signal = check_ema_crossover_df(df)
        if signal:
            msg = f"🟢 {symbol} → Tín hiệu MUA" if signal=="BUY" else f"🔴 {symbol} → Tín hiệu BÁN"
            print(msg)
            await send_telegram_message(session, msg)
        return signal

# === Hàm chính quét tất cả coin ===
async def main_loop():
    semaphore = asyncio.Semaphore(CONCURRENT_REQUESTS)
    async with aiohttp.ClientSession() as session:
        await send_telegram_message(session, "🚀 Bot EMA 9/21 đã khởi động và bắt đầu quét coin!")

        while True:
            try:
                # Lấy danh sách coin USDT
                async with session.get("https://api.binance.com/api/v3/exchangeInfo") as resp:
                    exchange_info = await resp.json()
                all_coins = [
                    s['symbol'] for s in exchange_info['symbols']
                    if s['quoteAsset']=='USDT' and not any(x in s['symbol'] for x in ['UP','DOWN','BULL','BEAR'])
                ]
                print(f"\n🔍 Quét {len(all_coins)} coin ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')})")

                tasks = [scan_coin(session, symbol, semaphore) for symbol in all_coins]
                results = await asyncio.gather(*tasks)

                total_buy = sum(1 for r in results if r=="BUY")
                total_sell = sum(1 for r in results if r=="SELL")

                summary = f"📊 Tổng kết vòng quét: 🟢 MUA {total_buy} | 🔴 BÁN {total_sell} | ⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
                print(summary)
                await send_telegram_message(session, summary)
                await send_telegram_message(session, "✅ Đã quét xong vòng này.")

                print(f"⏳ Hoàn tất vòng quét, nghỉ {SLEEP_BETWEEN_ROUNDS} giây...\n")
                await asyncio.sleep(SLEEP_BETWEEN_ROUNDS)

            except Exception as e:
                print(f"❌ Lỗi vòng quét: {e}")
                await asyncio.sleep(10)

# === Flask giữ bot chạy trên Render ===
@app.route('/')
def home():
    return "✅ EMA Bot đang hoạt động ổn định!"

if __name__ == '__main__':
    import threading
    threading.Thread(target=lambda: asyncio.run(main_loop()), daemon=True).start()
    app.run(host='0.0.0.0', port=10000)
