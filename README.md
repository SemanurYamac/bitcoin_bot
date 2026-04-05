# 🪙 Bitcoin Trading Bot

Son 3-4 yıllık Bitcoin verilerini analiz eden, teknik göstergelerle sinyal üreten ve otomatik alım-satım yapan bot.

## 🚀 Hızlı Başlangıç

### 1. Gerekli Paketleri Kur
```bash
cd "Bitcoin Bot"
pip install -r requirements.txt
```

### 2. .env Dosyasını Oluştur
```bash
cp .env.example .env
# .env dosyasını düzenleyip API anahtarlarını girin
```

### 3. Backtesting (Geçmiş Verilerle Test)
```bash
python main.py --mode backtest --verbose
```

### 4. Anlık Sinyal Kontrolü
```bash
python main.py --mode signal
```

### 5. Paper Trading (Sanal Para ile Test)
```bash
python main.py --mode paper
```

### 6. Dashboard'u Aç
```bash
streamlit run dashboard/app.py
```

---

## 📁 Proje Yapısı

```
Bitcoin Bot/
├── config/settings.py      → Tüm ayarlar
├── data/
│   ├── collector.py         → Binance'den veri çekme (CCXT)
│   └── storage.py           → SQLite veritabanı
├── analysis/indicators.py   → Teknik göstergeler (RSI, MACD, Bollinger, EMA)
├── strategy/signals.py      → Sinyal üretici (çoklu gösterge)
├── trading/
│   ├── risk_manager.py      → Risk yönetimi (SL, TP, trailing stop)
│   └── executor.py          → Emir yürütme
├── backtest/engine.py       → Backtesting motoru
├── notifications/notifier.py → Telegram bildirimleri
├── dashboard/app.py         → Streamlit web arayüzü
└── main.py                  → Ana çalıştırma
```

## 📊 Strateji: Çoklu Gösterge Sistemi

| Gösterge | Ağırlık | AL Koşulu | SAT Koşulu |
|----------|---------|-----------|------------|
| RSI (14) | 2.0 | < 35 (aşırı satım) | > 65 (aşırı alım) |
| MACD (12,26,9) | 2.5 | Bullish crossover | Bearish crossover |
| Bollinger (20,2) | 1.5 | Alt banda yakın | Üst banda yakın |
| EMA (50/200) | 2.0 | Golden Cross / Uptrend | Death Cross / Downtrend |
| Hacim | 1.0 | Yüksek hacim onayı | Yüksek hacim onayı |

**AL sinyali:** Toplam skor ≥ 5.0  
**SAT sinyali:** Toplam skor ≤ -5.0

## 🛡️ Risk Yönetimi

- **Pozisyon:** Bakiyenin max %15'i
- **Stop-Loss:** %4
- **Take-Profit:** %8
- **Trailing Stop:** %2
- **Max Drawdown:** %15
- **Günlük max işlem:** 5

---

## 🔑 Binance API Anahtarı Oluşturma

1. [binance.com](https://www.binance.com) adresine giriş yapın
2. **Profil** → **API Yönetimi** → **API Oluştur**
3. **Sadece** "Read" ve "Spot Trading" izinlerini açın
4. ⚠️ **Withdrawal (Çekim) iznini ASLA açmayın!**
5. API Key ve Secret Key'i `.env` dosyasına kaydedin

### Paper Trading için (Testnet):
1. [testnet.binance.vision](https://testnet.binance.vision) adresine gidin
2. GitHub ile giriş yapın
3. API anahtarlarını `BINANCE_TESTNET_*` alanlarına kaydedin

---

## ⚠️ Yasal Uyarı

Bu yazılım eğitim amaçlıdır ve yatırım tavsiyesi değildir. Kripto para alım-satımı yüksek risk içerir. Sadece kaybetmeyi göze alabileceğiniz miktarlarla işlem yapın.
