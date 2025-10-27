# Dockerfile
FROM python:3.11-slim

# Thư mục làm việc
WORKDIR /app

# Copy file requirements và cài đặt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ code
COPY . .

# Mở port 8080 cho Fly.io
EXPOSE 8080

# Chạy bot
CMD ["python", "crypto_ema_telegram_bot.py"]
