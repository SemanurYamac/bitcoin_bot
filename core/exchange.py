"""
Paylaşılan Borsa Bağlantısı — tüm botlar tek ccxt client kullanır.

Mantık:
    Her bot kendi DataCollector + TradeExecutor instance'ı yaratabilir,
    ama altta yatan ccxt bağlantısı paylaşılmalı (rate limit ortak,
    bağlantı maliyeti tek). Bu modül singleton sağlar.

Kullanım:
    from core.exchange import get_collector, get_executor
    collector = get_collector()              # Singleton
    executor = get_executor('dca_bot')       # Bot başına tagged executor

Önemli:
    - DataCollector zaten ccxt'in built-in rate limit'ini kullanıyor
    - Trade'lere 'bot_name' tag'i ekleniyor — storage'da hangi bot
      yaptığı belli olsun
    - Backtest modunda hiçbir gerçek bağlantı kurulmaz (collector init
      içinde TRADING_MODE kontrolü var)
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_collector = None
_storage = None
_executors: dict[str, object] = {}


def get_collector():
    """Tek paylaşılan DataCollector döndürür."""
    global _collector
    if _collector is None:
        with _lock:
            if _collector is None:
                from data.collector import DataCollector
                _collector = DataCollector()
                logger.info("🔌 Paylaşılan DataCollector oluşturuldu")
    return _collector


def get_storage():
    """Tek paylaşılan DataStorage döndürür."""
    global _storage
    if _storage is None:
        with _lock:
            if _storage is None:
                from data.storage import DataStorage
                _storage = DataStorage()
                logger.info("💾 Paylaşılan DataStorage oluşturuldu")
    return _storage


def get_executor(bot_name: str):
    """
    Bot başına TaggedExecutor döndürür.
    Aynı bot tekrar çağırırsa aynı instance gelir.
    """
    if bot_name in _executors:
        return _executors[bot_name]

    with _lock:
        if bot_name in _executors:
            return _executors[bot_name]
        from trading.executor import TradeExecutor
        executor = TradeExecutor(get_collector(), get_storage())
        # Bot ismini executor'a ekle (storage tag'leme için)
        executor.bot_name = bot_name
        _executors[bot_name] = executor
        logger.info(f"⚙️  Executor oluşturuldu: bot={bot_name}")
        return executor


def fetch_balance_usdt() -> float:
    """USDT serbest bakiyesi (canlıda kullanılır, backtest'te 0)."""
    from config.settings import TRADING_MODE
    if TRADING_MODE == 'backtest':
        return 0.0
    try:
        bal = get_collector().fetch_balance()
        if 'USDT' in bal:
            return float(bal['USDT']['free'])
    except Exception as e:
        logger.error(f"❌ USDT bakiyesi çekilemedi: {e}")
    return 0.0


def reset_for_testing():
    """Test izolasyonu için singleton'ları sıfırlar — sadece test'te kullan."""
    global _collector, _storage, _executors
    _collector = None
    _storage = None
    _executors = {}
