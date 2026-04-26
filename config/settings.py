"""
Bitcoin Trading Bot - Genel Ayarlar (Faz 5 — Momentum Rider)
Gelir odaklı strateji: ADX trend filtresi, EMA hizalama, 15m timeframe.
15 dakikalık mumlar + %2 risk + 3:1 R:R hedefi = pozitif beklenti
"""
import os
from dotenv import load_dotenv
from pathlib import Path

# .env dosyasını yükle
load_dotenv(Path(__file__).parent.parent / '.env')


# ─── Borsa Ayarları ────────────────────────────────────────────────
EXCHANGE = 'binance'
SYMBOL = 'BTC/USDT'  # Varsayılan sembol (tek coin modu için)
TIMEFRAME = '1h'   # 1h: ADX+EMA sinyali 15m gürültüsünden etkilenmiyor

# ─── Varlık Evreni (Faz 4 — Genişletilmiş) ────────────────────────
#
# Coin seçim kriterleri (uzman perspektifi):
#   1. Yüksek likidite (günlük hacim >$50M) → spread ve slippage düşük
#   2. Düşük korelasyon çeşitliliği → BTC ile tam koreleli coins dışlandı
#      (Layer1 / DeFi / Altyapı / Payment segmentleri temsil ediliyor)
#   3. Binance spot'ta standart kural seti mevcut
#   4. Geçmiş verisi 2022'ye kadar ulaşabilir (backtest için)
#
# Segment dağılımı:
#   Layer1  : BTC, ETH, SOL, ADA, AVAX   (konsensüs/platform katmanı)
#   Exchange: BNB                          (Binance ekosistemi)
#   Payment : XRP                          (ödeme/köprü katmanı)
#   Oracle  : LINK                         (akıllı sözleşme altyapısı)
#
# Korelasyon notu: BTC ile yüksek korelasyon kaçınılmaz, ancak
# LINK ve XRP zaman zaman farklı beta sergiler. Bu çeşitlilik
# tüm pozisyonların aynı anda zarara girmesini azaltır.

# ── Faz 5 Coin Evreni: Momentum + Volatilite ───────────────────────────
#
# Seçim kriterleri:
#   - Yüksek likidite (manipulasyon zorlaşsın)
#   - Yüksek ATR/Fiyat oranı (çünkü bu 3:1 R:R sağlar)
#   - Farklı segmentler (BTC ile düşük korelasyon arayışı)
#   - Backtest'te en tutarlı trendler
#
# BTC, ETH    : Likidite ve güvenilirlik
# SOL, BNB    : Momentum, bakikalı trendler
# DOGE        : Yatırımcı ilgisi yüksek, ATR geniş
# XRP         : Farklı beta, haber dışı ADX filtresi geçince güvenilir

SYMBOLS = [
    # --- 1. Koruyucu Mega Majörler ---
    'BTC/USDT',    # Piyasa pusulası
    'ETH/USDT',    # Şampiyon (+%6.61, sadece %3 MaxDD)
    'SOL/USDT',    # Sağlam yüksek hacim
    'XRP/USDT',    # İstikrarlı koruma
    'LINK/USDT',   # Farklı korelasyon
    
    # --- 2. Momentum Roketleri (Optimizasyonun Yıldızları) ---
    'FET/USDT',    # Mega şampiyon (+%8.10)
    'INJ/USDT',    # En sert çöküşte hayatta kalıp kâr alma ustası
    'AR/USDT',     # Arweave (+%4.27 defansif roket)
]

# Çoklu coin modu
MULTI_COIN_MODE = True

# Minimum 24s hacim filtresi
MIN_VOLUME_24H = 1_000_000  # $1M

# Aynı anda max açık pozisyon
# 6 coin × max 3 eş zamanlı = portföyün max %60'u (%20x3)
MAX_OPEN_POSITIONS = 3

# ─── Tarama Ayarları ──────────────────────────────────────────────
# Closed candle modu: True ise sadece kapanmış mum üzerinde sinyal üretir
# Bu mod repaint riskini sıfırlar
CLOSED_CANDLE_MODE = True

# Tarama aralığı (dakika)
# Closed candle modunda: mum kapanışlarını yakalamak için 5dk optimal
SCAN_INTERVAL_MINUTES = 5

# Pozisyon kontrol aralığı (saniye) - aktif pozisyonlar için
POSITION_CHECK_INTERVAL = 300  # 5 dakika

# ─── Sinyal Üretim Ayarları (Faz 5 — Momentum Rider) ────────────────────

# Rejim filtresi: EMA200 altında BUY eşiği bu çarpanla artar
REGIME_FILTER_MULTIPLIER = 1.5

# Cooldown
COOLDOWN_CANDLES = 3  # 15m × 3 = 45 dakika bekleme

# ADX Trend Güç Filtresi (Faz 5 YENİ — En Kritik)
# Bu eşiğin altında hiçbir işlem yapılmaz
# ADX < 20: Sideways (trend yok, en büyük kayıp kaynağı)
# ADX 20-25: Zayıf trend (dikkatli)
# ADX > 25: Güçlü trend (işlem yap)
ADX_PERIOD = 14
ADX_THRESHOLD = 28  # Optimizasyon bulgusu: Daha zayıf trendlerde hata artıyor

# RSI Zone Filtresi
# Long zone: Alım için ideal RSI aralığı
#   40-65: Momentum başladı ama hala enerji var
#   < 35: Aşırı satım — dikkat, devam edebilir
#   > 70: Aşırı alım — long için risklnli
RSI_LONG_MIN = 45   # Dar zone: gerçek momentum
RSI_LONG_MAX = 62   # Aşırı alım başlamadan önce çık
RSI_SHORT_MIN = 35
RSI_SHORT_MAX = 60

# Sinyal ağırlıkları (backwards compat için tutuldu)
# Faz 5'te signals.py doğrudan sabit skorlar kullanıyor
SIGNAL_WEIGHTS = {
    'rsi':       2.0,
    'macd':      2.0,
    'bollinger': 1.0,
    'ema':       3.0,
    'volume':    1.5,
    'adx':       0.0,   # Hard gate, puana katılmıyor
}

# Karar eşikleri (Makine öğrenmesi optimizasyonuyla belirlendi)
# ADX(28+) + EMA full_bull(3+1=4) + MACD(2) + RSI zone(2) + Vol(1.5) + Regime(1.5) = 12
# Çok daha emin sinyalleri yakalayarak Win Rate'i %48'e çıkardı.
BUY_THRESHOLD = 7.0
SELL_THRESHOLD = -7.0

# ─── Partial Take-Profit (Kısmi Kâr Alma) ────────────────────────
#
# Nasıl çalışır?
#   1) Pozisyon giriş fiyatından PARTIAL_TP_R_MULTIPLE × R kadar gelince tetiklenir
#   2) Pozisyonun PARTIAL_TP_CLOSE_PERCENT'i piyasaya satılır → kâr kilitlenir
#   3) Kalan miktar için SL breakeven'a (giriş fiyatı) taşınır → sıfır risk
#   4) Kalan miktar tam TP hedefine (%8) ulaşmaya devam eder
#
# R (Risk Unit) tanımı:
#   1R = Giriş Fiyatı − Stop-Loss Fiyatı  (risk miktarı)
#   Partial TP fiyatı = Giriş + (1.5 × 1R)
#
# Örnek:
#   Giriş = $2,000  |  SL = $1,920  |  1R = $80
#   Partial TP @ 1.5R = $2,000 + 1.5 × $80 = $2,120
#   Tam TP = $2,000 × 1.08 = $2,160
#   → $2,120'de %50 sat, kalan %50 için SL = $2,000 (breakeven)
#   → Kalan %50 için artık "bedava" ticaret yapılıyor
#
PARTIAL_TP_ENABLED = True          # False yaparak tamamen kapatılabilir
PARTIAL_TP_R_MULTIPLE = 1.5        # Kaç R'de tetiklenir (1.5 = 1.5R)
PARTIAL_TP_CLOSE_PERCENT = 0.50    # Tetiklenince pozisyonun kaçta kaçı kapatılır
PARTIAL_TP_MOVE_SL_TO_BE = True    # Kalan için SL breakeven'a çekilsin mi?

# ─── API Anahtarları ───────────────────────────────────────────────
BINANCE_API_KEY = os.getenv('BINANCE_API_KEY', '')
BINANCE_API_SECRET = os.getenv('BINANCE_API_SECRET', '')
BINANCE_TESTNET_API_KEY = os.getenv('BINANCE_TESTNET_API_KEY', '')
BINANCE_TESTNET_API_SECRET = os.getenv('BINANCE_TESTNET_API_SECRET', '')

# ─── Trading Modu ─────────────────────────────────────────────────
# 'backtest' | 'paper' | 'live'
TRADING_MODE = os.getenv('TRADING_MODE', 'backtest')

# ─── Başlangıç Sermayesi (TL) ──────────────────────────────────────
INITIAL_CAPITAL_TRY = 7000  # ~7000 TL

# ─── Teknik Analiz Parametreleri (Faz 5) ──────────────────────────────
RSI_PERIOD = 14
RSI_OVERSOLD = 35     # Faz 5: 30 → 35 (kripto'da 30 yeterli düz değil)
RSI_OVERBOUGHT = 70   # Aynı

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

BOLLINGER_PERIOD = 20
BOLLINGER_STD = 2

# Faz 5: EMA yapısı 4 katmana çıktı
# EMA_FAST  (9):  Hızlı momentum — giriş zamanlaması
# EMA_MID  (21):  Orta momentum — kısa vade trend
# EMA_SLOW (50):  Orta vade trend — yön filtresi
# EMA_TREND(200): Uzun vade trend — rejim filtresi
EMA_FAST  = 9
EMA_MID   = 21
EMA_SLOW  = 50
EMA_TREND = 200

# Backwards compat
EMA_SHORT = EMA_SLOW   # 50
EMA_LONG  = EMA_TREND  # 200

VOLUME_MA_PERIOD = 20  # Hacim ortalaması periyodu

# ─── Risk Yönetimi (Faz 5 — Gelir Odaklı) ───────────────────────────────
#
# Faz 5 güncellemesi:
#   - RISK_PER_TRADE: %1 → %2 (anlamlı dolar miktarları için)
#   - MAX_POSITION_PERCENT: %12 → %20 (3 pozisyon × %20 = %60 max)
#   - STOP_LOSS → ATR-based (sabit % yerine dinamik)
#   - TAKE_PROFIT: 3× ATR hedefi = 3:1 R:R (matematiksel pozitif beklenti)
#
RISK_PER_TRADE = 0.02         # %2 — gelir odaklı, hesaplanmış risk
MAX_POSITION_PERCENT = 0.20   # %20 tek pozisyon max
MAX_PORTFOLIO_EXPOSURE = 0.60 # %60 toplam

# ATR çarpanları — Optimizasyon Testi Sonuçları
# Botun fiyat gürültüsünden ölmemesi için SL daha esnek (2.0)
# TP hedefleri ise çok daha yukarıda (2.5 ve 4.0)
ATR_SL_MULT    = 2.0   # SL = giriş - 2.0 × ATR (Yeterli nefes alma payı)
ATR_TP1_MULT   = 2.5   # TP1 = giriş + 2.5 × ATR (%40 pozisyon kilit)
ATR_TP2_MULT   = 4.0   # TP2 = giriş + 4.0 × ATR (Trend takibi)
ATR_TRAIL_MULT = 2.0   # Trailing stop = peak - 2.0 × ATR

# Fallback (ATR hesaplanamadığında)
STOP_LOSS_PERCENT    = 0.025  # %2.5 fallback SL
TAKE_PROFIT_PERCENT  = 0.06   # %6 fallback TP (2.4:1 R:R)
MAX_DRAWDOWN_PERCENT = 0.15   # %15 max portföy düşüşü
TRAILING_STOP_PERCENT = 0.02  # %2 trailing stop
TRAILING_ACTIVATION   = 0.03  # %3 kârdan sonra trailing aktif
MAX_DAILY_TRADES = 8          # 6 coin × 1h = günlük makul limit

# ─── Fail-Safe Ayarları ───────────────────────────────────────────
# Ardışık hata sayısı bu eşiği geçerse bot koruma moduna geçer
MAX_CONSECUTIVE_ERRORS = 5
# Fail-safe modunda bekleme süresi (saniye)
FAILSAFE_WAIT_SECONDS = 300  # 5 dakika

# ─── Backtesting Ayarları ──────────────────────────────────────────
BACKTEST_START_DATE = '2022-04-01'
BACKTEST_END_DATE = '2026-04-01'
BACKTEST_INITIAL_BALANCE = 1000  # USDT cinsinden

# ─── Veritabanı ────────────────────────────────────────────────────
DB_PATH = Path(__file__).parent.parent / 'data' / 'historical' / 'bitcoin_bot.db'

# ─── Telegram Bildirimleri ─────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')

# ─── Loglama ───────────────────────────────────────────────────────
LOG_LEVEL = 'INFO'
LOG_FILE = Path(__file__).parent.parent / 'logs' / 'bot.log'
