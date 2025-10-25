import aiohttp
import asyncio
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
LIMIT_COINS = 100  # Giới hạn số coin để quét

app = Flask(__name__)

# === Gửi tin nhắn Telegram async ===
async def send_telegram_message(session, message: str):
    if not BOT_TOKEN or not CHAT_ID:
        print("⚠️ Thiếu BOT_TOKEN hoặc CHAT_ID")
        return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
        async with session.post(url, json=payload, timeout=10) as resp:
            await resp.text()
    except Exception as e:
        print(f"❌ Lỗi gửi Telegram: {e}")

# === Lấy dữ liệu nến từ Binance async ===
async def get_binance_data(session, symbol: str, interval=INTERVAL, limit=100):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
        async with session.get(url, timeout=10) as resp:
            data = await resp.json()
        df = pd.DataFrame(data, columns=[
            "time", "open", "high", "low", "close", "volume", "close_time",
            "quote_asset_volume", "num_trades", "tb_base_vol", "tb_quote_vol", "ignore"
        ])
        df["close"] = df["close"].astype(float)
        return df
    except Exception as e:
        print(f"⚠️ Lỗi lấy dữ liệu {symbol}: {e}")
        return None

# === Kiểm tra giao cắt EMA ===
async def check_ema_crossover(session, symbol: str):
    df = await get_binance_data(session, symbol)
    if df is None or len(df) < EMA_LONG:
        return None

    df["ema_short"] = df["close"].ewm(span=EMA_SHORT).mean()
    df["ema_long"] = df["close"].ewm(span=EMA_LONG).mean()

    prev_short, prev_long = df["ema_short"].iloc[-2], df["ema_long"].iloc[-2]
    last_short, last_long = df["ema_short"].iloc[-1], df["ema_long"].iloc[-1]

    # Tín hiệu MUA
    if prev_short < prev_long and last_short > last_long:
        msg = f"🟢 {symbol} — EMA9 cắt lên EMA21 → **Tín hiệu MUA**"
        print(msg)
        await send_telegram_message(session, msg)
        return "BUY"

    # Tín hiệu BÁN
    elif prev_short > prev_long and last_short < last_long:
        msg = f"🔴 {symbol} — EMA9 cắt xuống EMA21 → **Tín hiệu BÁN**"
        print(msg)
        await send_telegram_message(session, msg)
        return "SELL"

    return None

# === Hàm chính quét coin async ===
async def main_loop():
    async with aiohttp.ClientSession() as session:
        await send_telegram_message(session, "🚀 Bot EMA 9/21 đã khởi động và bắt đầu quét coin!")

        while True:
            try:
                # Lấy danh sách coin
                async with session.get("https://api.binance.com/api/v3/exchangeInfo") as resp:
                    exchange_info = await resp.json()
                all_coins = [
                    s['symbol'] for s in exchange_info['symbols']
                    if s['quoteAsset'] == 'USDT' and not any(x in s['symbol'] for x in ['UP', 'DOWN', 'BULL', 'BEAR'])
                ][:LIMIT_COINS]

                print(f"\n🔍 Quét {len(all_coins)} coin... ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')})")

                tasks = [check_ema_crossover(session, symbol) for symbol in all_coins]
                results = await asyncio.gather(*tasks)

                buy_signals = results.count("BUY")
                sell_signals = results.count("SELL")

                summary = f"📊 **Tổng kết vòng quét**\n" \
                          f"🪙 Tổng coin quét: {len(all_coins)}\n" \
                          f"🟢 MUA: {buy_signals} | 🔴 BÁN: {sell_signals}\n" \
                          f"⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
                print(summary)
                await send_telegram_message(session, summary)

                # Thông báo "quét xong"
                await send_telegram_message(session, "✅ Đã quét xong vòng EMA!")

                print("⏱ Nghỉ 60 giây trước vòng quét tiếp theo...\n")
                await asyncio.sleep(60)

            except Exception as e:
                print(f"❌ Lỗi vòng quét: {e}")
                await asyncio.sleep(30)

# === Flask giữ bot chạy trên Render ===
@app.route('/')
def home():
    return "✅ EMA Bot đang hoạt động ổn định!"

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.create_task(main_loop())
    app.run(host='0.0.0.0', port=10000)
