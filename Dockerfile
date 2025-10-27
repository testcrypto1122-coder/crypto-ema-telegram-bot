# Base image Python 3.11
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy files
COPY . /app

# Cài dependencies
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Expose port cho Fly.io Web Service
EXPOSE 8080

# Chạy bot
CMD ["python", "crypto_ema_telegram_bot.py"]

