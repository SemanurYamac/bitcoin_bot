# Resmi ve hafif (alpine/slim) Python imajını kullanıyoruz
FROM python:3.11-slim

# Gerekli sistem paketlerini kuruyoruz
RUN apt-get update && apt-get install -y \
    gcc \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Çalışma dizinini ayarla
WORKDIR /app

# Çevresel değişkenler
ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8
ENV PYTHONUTF8=1

# Önce sadece requirements.txt'yi kopyalayıp kuruyoruz (Docker cache'i verimli kullanmak için)
COPY requirements.txt .

# Kütüphaneleri kur
RUN pip install --no-cache-dir -r requirements.txt

# Çökmeleri engellemek ve state bilgisini yazabilmek için data klasörünü önceden hazırla
RUN mkdir -p /app/data/live_state

# Tüm kodu konteyner içine kopyala
COPY . .

# Botu çalıştıran ana komut
CMD ["python", "main.py", "--mode", "paper"]
