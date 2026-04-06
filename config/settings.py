"""
Bitcoin Trading Bot - Genel Ayarlar (Faz 1 — Güvenli Temel)
BTC/ETH/SOL odaklı, risk-based sizing, closed candle sinyal
"""
import os
from dotenv import load_dotenv
from pathlib import Path

# .env dosyasını yükle
load_dotenv(Path(__file__).parent.parent / '.env')


# ─── Borsa Ayarları ────────────────────────────────────────────────
EXCHANGE = 'binance'
SYMBOL = 'BTC/USDT'  # Varsayılan sembol (tek coin modu için)
TIMEFRAME = '1h'  # 1 saatlik mum

# ─── Varlık Evreni (Aşamalı Genişleme) ────────────────────────────
# Faz 1: Sadece en likit 3 coin — strateji validasyonu
# Faz 2+: Config'den yönetilebilir genişleme
SYMBOLS = [
    'BTC/USDT',    # Bitcoin — ana odak
    'ETH/USDT',    # Ethereum — en likit altcoin
    'SOL/USDT',    # Solana — yüksek volatilite + likidite
]

# Çoklu coin modunu aktif etmek için True yap
MULTI_COIN_MODE = True

# Minimum 24s hacim filtresi (USDT cinsinden)
# 3 likit coin ile $5M yeterli
MIN_VOLUME_24H = 5_000_000  # $5M minimum günlük hacim

# Aynı anda max açık pozisyon sayısı
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

# ─── Sinyal Üretim Ayarları ───────────────────────────────────────
# Rejim filtresi: EMA200 altında BUY threshold'u bu çarpanla artırılır
# 2.0 = downtrend'de alım sinyali 2x daha zor
REGIME_FILTER_MULTIPLIER = 2.0

# Cooldown: Exit sonrası bu kadar mum bekle (overtrading engellemesi)
COOLDOWN_CANDLES = 2

# Sinyal ağırlıkları (her göstergenin katkı puanı)
SIGNAL_WEIGHTS = {
    'rsi': 2.0,
    'macd': 2.5,
    'bollinger': 1.5,
    'ema': 2.0,
    'volume': 1.0,
}

# Karar eşikleri
BUY_THRESHOLD = 4.0    # Bu puan üstünde AL sinyali
SELL_THRESHOLD = -4.0   # Bu puan altında SAT sinyali

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

# ─── Teknik Analiz Parametreleri ────────────────────────────────────
RSI_PERIOD = 14
RSI_OVERSOLD = 30     # Endüstri standardı
RSI_OVERBOUGHT = 70   # Endüstri standardı

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

BOLLINGER_PERIOD = 20
BOLLINGER_STD = 2

EMA_SHORT = 50
EMA_LONG = 200

VOLUME_MA_PERIOD = 20  # Hacim ortalaması periyodu

# ─── Risk Yönetimi (Risk-Based Position Sizing) ───────────────────
# Risk-per-trade: Her işlemde bakiyenin max ne kadarını riske at
RISK_PER_TRADE = 0.01  # %1 — endüstri standardı, güvenli başlangıç

# Maksimum pozisyon boyutu (bakiyenin yüzdesi olarak)
MAX_POSITION_PERCENT = 0.15  # %15 — tek pozisyon max bakiyenin %15'i

# Maksimum portföy maruziyeti (tüm açık pozisyonlar toplamı)
MAX_PORTFOLIO_EXPOSURE = 0.40  # %40 — bakiyenin max %40'ı kullanılır

# Stop-loss ve take-profit (ATR-based mode için fallback)
STOP_LOSS_PERCENT = 0.04     # %4 zarar durdurma
TAKE_PROFIT_PERCENT = 0.08   # %8 kâr alma
MAX_DRAWDOWN_PERCENT = 0.15  # %15 max portföy düşüşü
TRAILING_STOP_PERCENT = 0.025 # %2.5 takip eden stop
TRAILING_ACTIVATION = 0.03   # %3 kârdan sonra trailing aktif olsun
MAX_DAILY_TRADES = 6         # Günlük max işlem sayısı

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
