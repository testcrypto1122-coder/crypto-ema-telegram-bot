import requests
import pandas as pd
import time
from datetime import datetime

# =============================
# ⚙️ Cấu hình
# =============================
SETTINGS = {
    "INTERVAL": 300,  # 5 phút mỗi vòng quét
    "TELEGRAM_BOT_TOKEN": "8264206004:AAH2zvVURgKLv9hZd-ZKTrB7xcZsaKZCjd0",
    "TELEGRAM_CHAT_ID": "8282016712"
}

# Danh sách coin top (CoinGecko ID)
COINS = [
    "bitcoin", "ethereum", "bnb", "solana", "xrp", "cardano", "dogecoin", "tron", "avalanche-2", "chainlink",
    "polkadot", "polygon", "shiba-inu", "toncoin", "internet-computer", "uniswap", "near", "aptos",
    "litecoin", "stellar", "cosmos", "filecoin", "vechain", "injective", "arweave", "fantom", "maker",
    "immutable-x", "the-graph", "render-token", "aave", "algorand", "thorchain", "tezos", "gala", "flow",
    "chiliz", "mina-protocol", "rocket-pool", "blur", "curve-dao-token", "nexo", "dash", "compound-governance-token"
]

# =============================
# 🧩 Hàm tiện ích
# =============================
def send_telegram(msg):
    """Gửi tin nhắn Telegram"""
    url = f"https://api.telegram.org/bot{SETTINGS['TELEGRAM_BOT_TOKEN']}/sendMessage"
    try:
        requests.post(url, data={"chat_id": SETTINGS["TELEGRAM_CHAT_ID"], "text": msg})
    except Exception as e:
        print("Lỗi gửi Telegram:", e)


def get_price_data(coin):
    """Lấy dữ liệu giá 5 phút từ CoinGecko"""
    url = f"https://api.coingecko.com/api/v3/coins/{coin}/market_chart?vs_currency=usd&days=1&interval=5m"
    r = requests.get(url, timeout=15)
    data = r.json()
    prices = [x[1] for x in data.get("prices", [])]
    if len(prices) < 50:
        raise ValueError("Không đủ dữ liệu nến")
    df = pd.DataFrame(prices, columns=["close"])
    return df


def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def calc_macd(series):
    ema12 = calc_ema(series, 12)
    ema26 = calc_ema(series, 26)
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd, signal


def calc_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def analyze_coin(coin):
    """Phân tích tín hiệu nâng cao"""
    df = get_price_data(coin)
    df["ema9"] = calc_ema(df["close"], 9)
    df["ema21"] = calc_ema(df["close"], 21)
    df["macd"], df["signal"] = calc_macd(df["close"])
    df["rsi"] = calc_rsi(df["close"])

    # Điều kiện MUA
    if (
        df["ema9"].iloc[-1] > df["ema21"].iloc[-1]
        and df["ema9"].iloc[-2] <= df["ema21"].iloc[-2]
        and df["macd"].iloc[-1] > df["signal"].iloc[-1]
        and df["rsi"].iloc[-1] < 70
    ):
        send_telegram(f"📈 {coin.upper()} → Tín hiệu MUA (EMA9↑ EMA21, MACD+, RSI={df['rsi'].iloc[-1]:.1f})")

    # Điều kiện BÁN
    elif (
        df["ema9"].iloc[-1] < df["ema21"].iloc[-1]
        and df["ema9"].iloc[-2] >= df["ema21"].iloc[-2]
        and df["macd"].iloc[-1] < df["signal"].iloc[-1]
        and df["rsi"].iloc[-1] > 30
    ):
        send_telegram(f"📉 {coin.upper()} → Tín hiệu BÁN (EMA9↓ EMA21, MACD−, RSI={df['rsi'].iloc[-1]:.1f})")


def scan_all_coins():
    """Quét toàn bộ danh sách coin"""
    start = datetime.now().strftime("%H:%M:%S")
    send_telegram(f"🔍 Bắt đầu quét ({start})...")
    count = 0
    for coin in COINS:
        try:
            analyze_coin(coin)
            count += 1
            time.sleep(1.5)
        except Exception as e:
            print(f"Lỗi {coin}: {e}")
            continue
    end = datetime.now().strftime("%H:%M:%S")
    send_telegram(f"✅ Hoàn tất quét {count} coin ({end})")


# =============================
# 🚀 Chạy vòng lặp
# =============================
if __name__ == "__main__":
    send_telegram("🤖 Bot EMA+MACD+RSI đã khởi động thành công!")
    while True:
        scan_all_coins()
        time.sleep(SETTINGS["INTERVAL"])
