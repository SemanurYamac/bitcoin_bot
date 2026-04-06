"""
Bitcoin Trading Bot - Genel Ayarlar
Uzman optimizasyonu: 50 coin, 15dk tarama, $5M hacim filtresi
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

# ─── Çoklu Coin Desteği (50 Coin) ─────────────────────────────────
# Bot bu coinlerin hepsini tarar, sinyal bulduğunda işlem yapar
SYMBOLS = [
    # ─── Tier 1: En Büyük Coinler (Top 10) ─────────────────
    'BTC/USDT',    # Bitcoin
    'ETH/USDT',    # Ethereum
    'BNB/USDT',    # Binance Coin
    'SOL/USDT',    # Solana
    'XRP/USDT',    # Ripple
    'DOGE/USDT',   # Dogecoin
    'ADA/USDT',    # Cardano
    'AVAX/USDT',   # Avalanche
    'TRX/USDT',    # Tron
    'LINK/USDT',   # Chainlink

    # ─── Tier 2: Büyük Altcoinler (11-20) ──────────────────
    'DOT/USDT',    # Polkadot
    'SUI/USDT',    # Sui
    'SHIB/USDT',   # Shiba Inu
    'BCH/USDT',    # Bitcoin Cash
    'LTC/USDT',    # Litecoin
    'HBAR/USDT',   # Hedera
    'UNI/USDT',    # Uniswap
    'NEAR/USDT',   # NEAR Protocol
    'APT/USDT',    # Aptos
    'ICP/USDT',    # Internet Computer

    # ─── Tier 3: Orta Büyüklükte Altcoinler (21-30) ───────
    'ETC/USDT',    # Ethereum Classic
    'FIL/USDT',    # Filecoin
    'ATOM/USDT',   # Cosmos
    'RENDER/USDT', # Render
    'ARB/USDT',    # Arbitrum
    'OP/USDT',     # Optimism
    'FET/USDT',    # Fetch.ai
    'INJ/USDT',    # Injective
    'AAVE/USDT',   # Aave
    'STX/USDT',    # Stacks

    # ─── Tier 4: Yüksek Potansiyelli Altcoinler (31-40) ───
    'PEPE/USDT',   # PEPE
    'POL/USDT',    # Polygon (eski MATIC)
    'SEI/USDT',    # Sei
    'THETA/USDT',  # Theta
    'FTM/USDT',    # Fantom
    'ALGO/USDT',   # Algorand
    'GALA/USDT',   # Gala
    'BONK/USDT',   # Bonk
    'FLOKI/USDT',  # Floki
    'WIF/USDT',    # dogwifhat

    # ─── Tier 5: DeFi, AI & Gaming Tokenları (41-50) ──────
    'IMX/USDT',    # Immutable
    'SAND/USDT',   # The Sandbox
    'JASMY/USDT',  # JasmyCoin
    'PENDLE/USDT', # Pendle
    'ENS/USDT',    # Ethereum Name Service
    'TIA/USDT',    # Celestia
    'JUP/USDT',    # Jupiter
    'ONDO/USDT',   # Ondo Finance
    'WLD/USDT',    # Worldcoin
    'TAO/USDT',    # Bittensor
]

# Çoklu coin modunu aktif etmek için True yap
MULTI_COIN_MODE = True

# Minimum 24s hacim filtresi (USDT cinsinden) - düşük hacimli coinleri atla
# $5M: yeterli likidite + daha fazla fırsat (eskisi $10M idi)
MIN_VOLUME_24H = 5_000_000  # $5M minimum günlük hacim

# Aynı anda max açık pozisyon sayısı (50 coinle 5 daha iyi çeşitlendirme sağlar)
MAX_OPEN_POSITIONS = 5

# ─── Tarama Ayarları ──────────────────────────────────────────────
# Tarama aralığı (dakika) - 1h mum stratejisi için 15dk optimal
SCAN_INTERVAL_MINUTES = 15
# Pozisyon kontrol aralığı (saniye) - aktif pozisyonlar için
POSITION_CHECK_INTERVAL = 300  # 5 dakika

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
RSI_OVERSOLD = 30     # Endüstri standardı (eskisi 35)
RSI_OVERBOUGHT = 70   # Endüstri standardı (eskisi 65)

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

BOLLINGER_PERIOD = 20
BOLLINGER_STD = 2

EMA_SHORT = 50
EMA_LONG = 200

VOLUME_MA_PERIOD = 20  # Hacim ortalaması periyodu

# ─── Risk Yönetimi ─────────────────────────────────────────────────
MAX_POSITION_PERCENT = 0.20  # Bakiyenin max %20'si bir pozisyonda (eskisi %15)
STOP_LOSS_PERCENT = 0.04     # %4 zarar durdurma
TAKE_PROFIT_PERCENT = 0.08   # %8 kâr alma
MAX_DRAWDOWN_PERCENT = 0.15  # %15 max portföy düşüşü
TRAILING_STOP_PERCENT = 0.025 # %2.5 takip eden stop (eskisi %2, kripto için biraz daha geniş)
MAX_DAILY_TRADES = 10        # Günlük max işlem sayısı (eskisi 5, 50 coinle artırıldı)

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
