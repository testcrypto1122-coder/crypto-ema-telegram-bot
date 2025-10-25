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
BATCH_SIZE = 50  # số coin mỗi batch

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

# === Lấy dữ liệu nến từ Binance ===
async def get_binance_data(session, symbol: str, interval=INTERVAL, limit=100):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
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
        print(f"⚠️ Lỗi lấy dữ liệu {symbol}: {e}")
        return None

# === Kiểm tra giao cắt EMA ===
def check_ema_crossover_df(df, symbol):
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

# === Quét 1 batch coin ===
async def scan_batch(session, batch):
    tasks = []
    results = {}
    for symbol in batch:
        tasks.append(get_binance_data(session, symbol))
    datas = await asyncio.gather(*tasks)

    for symbol, df in zip(batch, datas):
        result = check_ema_crossover_df(df, symbol)
        results[symbol] = result
    return results

# === Hàm chính quét tất cả coin ===
async def main_loop():
    async with aiohttp.ClientSession() as session:
        await send_telegram_message(session, "🚀 Bot EMA 9/21 đã khởi động và bắt đầu quét coin!")

        while True:
            try:
                # Lấy danh sách coin USDT
                async with session.get("https://api.binance.com/api/v3/exchangeInfo") as resp:
                    exchange_info = await resp.json()
                all_coins = [
                    s['symbol'] for s in exchange_info['symbols']
                    if s['quoteAsset'] == 'USDT' and not any(x in s['symbol'] for x in ['UP','DOWN','BULL','BEAR'])
                ]

                print(f"\n🔍 Quét {len(all_coins)} coin ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')})")

                total_buy, total_sell = 0, 0
                for i in range(0, len(all_coins), BATCH_SIZE):
                    batch = all_coins[i:i+BATCH_SIZE]
                    results = await scan_batch(session, batch)

                    buy_count = sum(1 for v in results.values() if v=="BUY")
                    sell_count = sum(1 for v in results.values() if v=="SELL")
                    total_buy += buy_count
                    total_sell += sell_count

                    await send_telegram_message(session, f"✅ Đã quét xong batch {i//BATCH_SIZE+1}: 🟢 MUA {buy_count} | 🔴 BÁN {sell_count}")

                summary = f"📊 **Tổng kết vòng quét**\n🪙 Tổng coin quét: {len(all_coins)}\n🟢 MUA: {total_buy} | 🔴 BÁN: {total_sell}\n⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
                await send_telegram_message(session, summary)
                print(summary)

                print("⏳ Hoàn tất vòng quét, nghỉ 60 giây...\n")
                await asyncio.sleep(60)

            except Exception as e:
                print(f"❌ Lỗi vòng quét: {e}")
                await asyncio.sleep(30)

# === Flask giữ bot chạy trên Render ===
@app.route('/')
def home():
    return "✅ EMA Bot đang hoạt động ổn định!"

if __name__ == '__main__':
    import threading
    threading.Thread(target=lambda: asyncio.run(main_loop()), daemon=True).start()
    app.run(host='0.0.0.0', port=10000)
