# Sử dụng Python chính thức
FROM python:3.11-slim

WORKDIR /app

# Copy toàn bộ source code
COPY . /app

# Cài dependencies
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Expose port Fly.io yêu cầu
EXPOSE 8080

# Chạy ứng dụng
CMD ["python", "crypto_ema_telegram_bot.py"]
