# =============================
# Dockerfile cho Fly.io
# =============================
FROM python:3.12-slim

# Cài đặt dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Tạo thư mục app
WORKDIR /app

# Copy code vào container
COPY . /app

# Cài đặt Python packages
RUN pip install --no-cache-dir \
    aiohttp \
    pandas \
    python-multipart \
    pywin32-ctypes==0.2.0

# Môi trường
ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=UTF-8
ENV PORT=8080

# Lệnh chạy bot
CMD ["python", "crypto_ema_telegram_bot.py"]
