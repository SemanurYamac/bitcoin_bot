"""
Bitcoin Trading Bot - Genel Ayarlar
"""
import os
from dotenv import load_dotenv
from pathlib import Path

# .env dosyasını yükle
load_dotenv(Path(__file__).parent.parent / '.env')


# ─── Borsa Ayarları ────────────────────────────────────────────────
EXCHANGE = 'binance'
SYMBOL = 'BTC/USDT'
TIMEFRAME = '1h'  # 1 saatlik mum

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
# USDT karşılığı dinamik olarak hesaplanır

# ─── Teknik Analiz Parametreleri ────────────────────────────────────
RSI_PERIOD = 14
RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 65

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

BOLLINGER_PERIOD = 20
BOLLINGER_STD = 2

EMA_SHORT = 50
EMA_LONG = 200

VOLUME_MA_PERIOD = 20  # Hacim ortalaması periyodu

# ─── Risk Yönetimi ─────────────────────────────────────────────────
MAX_POSITION_PERCENT = 0.15  # Bakiyenin max %15'i bir pozisyonda
STOP_LOSS_PERCENT = 0.04     # %4 zarar durdurma
TAKE_PROFIT_PERCENT = 0.08   # %8 kâr alma
MAX_DRAWDOWN_PERCENT = 0.15  # %15 max portföy düşüşü
TRAILING_STOP_PERCENT = 0.02 # %2 takip eden stop
MAX_DAILY_TRADES = 5         # Günlük max işlem sayısı

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
