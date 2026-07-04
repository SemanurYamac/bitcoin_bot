# Resmi ve hafif (slim) Python imajı
FROM python:3.12-slim

# Gerekli sistem paketleri
RUN apt-get update && apt-get install -y \
    gcc \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Çalışma dizini
WORKDIR /app

# Çevresel değişkenler
ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8
ENV PYTHONUTF8=1
ENV TZ=Europe/Istanbul

# Önce requirements (Docker cache verimli kullanımı)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# State ve log klasörlerini hazırla
RUN mkdir -p /app/data/live_state /app/logs

# Kodu kopyala
COPY . .

# Sağlık kontrolü: Her 60s bir log dosyasının güncellenip güncellenmediğini kontrol et
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import os,time; f='/app/logs/bot.log'; \
        assert os.path.exists(f) and (time.time()-os.path.getmtime(f)) < 600, 'Bot yanıt vermiyor'" \
    || exit 1

# LIVE modda başlat (sunucuda çalışacak)
CMD ["python", "main.py", "--mode", "live"]
