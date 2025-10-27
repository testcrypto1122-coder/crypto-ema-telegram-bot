FROM python:3.11-slim

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir aiohttp pandas

EXPOSE 8080

CMD ["python", "crypto_ema_telegram_bot.py"]
