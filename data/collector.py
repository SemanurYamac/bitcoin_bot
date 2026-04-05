"""
Bitcoin Trading Bot - Veri Toplama Modülü
CCXT kütüphanesi ile Binance'den veri çeker.
"""
import ccxt
import pandas as pd
import time
import logging
from datetime import datetime, timedelta
from config.settings import (
    BINANCE_API_KEY, BINANCE_API_SECRET,
    BINANCE_TESTNET_API_KEY, BINANCE_TESTNET_API_SECRET,
    SYMBOL, TIMEFRAME, TRADING_MODE
)

logger = logging.getLogger(__name__)


class DataCollector:
    """Binance borsasından geçmiş ve canlı veri toplar."""

    def __init__(self, use_testnet=False):
        """
        Args:
            use_testnet: True ise Binance testnet (paper trading) kullanır
        """
        if use_testnet or TRADING_MODE == 'paper':
            self.exchange = ccxt.binance({
                'apiKey': BINANCE_TESTNET_API_KEY,
                'secret': BINANCE_TESTNET_API_SECRET,
                'enableRateLimit': True,
                'options': {'defaultType': 'spot'},
            })
            self.exchange.set_sandbox_mode(True)
            logger.info("📋 Binance TESTNET bağlantısı kuruldu (Paper Trading)")
        elif TRADING_MODE == 'live':
            self.exchange = ccxt.binance({
                'apiKey': BINANCE_API_KEY,
                'secret': BINANCE_API_SECRET,
                'enableRateLimit': True,
                'options': {'defaultType': 'spot'},
            })
            logger.info("🔴 Binance CANLI bağlantı kuruldu!")
        else:
            # Backtest modu - kimlik doğrulama gerekmez
            self.exchange = ccxt.binance({
                'enableRateLimit': True,
                'options': {'defaultType': 'spot'},
            })
            logger.info("📊 Binance bağlantısı kuruldu (Backtest modu - sadece veri)")

    def fetch_ohlcv(self, symbol=None, timeframe=None, since=None, limit=500):
        """
        OHLCV (mum) verilerini çeker.

        Args:
            symbol: İşlem çifti (varsayılan: BTC/USDT)
            timeframe: Zaman dilimi (varsayılan: 1h)
            since: Başlangıç tarihi (timestamp ms)
            limit: Mum sayısı limiti (max 1000)

        Returns:
            pandas DataFrame: timestamp, open, high, low, close, volume
        """
        symbol = symbol or SYMBOL
        timeframe = timeframe or TIMEFRAME

        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)

            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            df = df.astype(float)

            logger.info(f"✅ {len(df)} mum verisi çekildi: {symbol} ({timeframe})")
            return df

        except ccxt.NetworkError as e:
            logger.error(f"❌ Ağ hatası: {e}")
            raise
        except ccxt.ExchangeError as e:
            logger.error(f"❌ Borsa hatası: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ Beklenmeyen hata: {e}")
            raise

    def fetch_historical_data(self, symbol=None, timeframe=None,
                               start_date='2022-04-01', end_date=None):
        """
        Belirtilen tarih aralığında tüm geçmiş verileri çeker.
        API limitleri nedeniyle parçalar halinde çeker.

        Args:
            symbol: İşlem çifti
            timeframe: Zaman dilimi
            start_date: Başlangıç tarihi (YYYY-MM-DD)
            end_date: Bitiş tarihi (YYYY-MM-DD), None ise şimdiki zaman

        Returns:
            pandas DataFrame: Tüm geçmiş veriler
        """
        symbol = symbol or SYMBOL
        timeframe = timeframe or TIMEFRAME

        # Tarihleri timestamp'e çevir
        since = int(datetime.strptime(start_date, '%Y-%m-%d').timestamp() * 1000)

        if end_date:
            end_ts = int(datetime.strptime(end_date, '%Y-%m-%d').timestamp() * 1000)
        else:
            end_ts = int(datetime.now().timestamp() * 1000)

        all_data = []
        current_since = since

        logger.info(f"📥 Geçmiş veri indiriliyor: {start_date} → {end_date or 'şimdi'}")

        while current_since < end_ts:
            try:
                ohlcv = self.exchange.fetch_ohlcv(
                    symbol, timeframe,
                    since=current_since,
                    limit=1000  # Binance max limit
                )

                if not ohlcv:
                    break

                all_data.extend(ohlcv)

                # Son mumun timestamp'ini al, bir sonraki istekte oradan devam et
                current_since = ohlcv[-1][0] + 1
                
                logger.info(f"  📦 {len(all_data)} mum indirildi... "
                           f"({datetime.fromtimestamp(current_since/1000).strftime('%Y-%m-%d %H:%M')})")

                # Rate limit'e saygı göster
                time.sleep(self.exchange.rateLimit / 1000)

            except ccxt.NetworkError as e:
                logger.warning(f"⚠️ Ağ hatası, 10 saniye bekleniyor: {e}")
                time.sleep(10)
                continue
            except Exception as e:
                logger.error(f"❌ Veri çekme hatası: {e}")
                break

        if not all_data:
            logger.warning("⚠️ Hiç veri çekilemedi!")
            return pd.DataFrame()

        df = pd.DataFrame(all_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        df = df.astype(float)
        df = df[~df.index.duplicated(keep='first')]  # Duplikasyonları temizle
        df.sort_index(inplace=True)

        # Bitiş tarihine göre filtrele
        if end_date:
            df = df[:end_date]

        logger.info(f"✅ Toplam {len(df)} mum verisi indirildi ({start_date} → {end_date or 'şimdi'})")
        return df

    def fetch_ticker(self, symbol=None):
        """Anlık fiyat bilgisi çeker."""
        symbol = symbol or SYMBOL
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            return {
                'symbol': symbol,
                'last': ticker['last'],
                'bid': ticker['bid'],
                'ask': ticker['ask'],
                'volume': ticker['baseVolume'],
                'change_24h': ticker['percentage'],
                'timestamp': datetime.now()
            }
        except Exception as e:
            logger.error(f"❌ Ticker çekme hatası: {e}")
            raise

    def fetch_balance(self):
        """Hesap bakiyesini çeker (sadece live/paper modda)."""
        if TRADING_MODE == 'backtest':
            logger.warning("⚠️ Backtest modunda bakiye çekilemez")
            return {}

        try:
            balance = self.exchange.fetch_balance()
            relevant = {}
            for currency in ['BTC', 'USDT', 'BNB', 'TRY']:
                if currency in balance and balance[currency]['total'] > 0:
                    relevant[currency] = {
                        'free': balance[currency]['free'],
                        'used': balance[currency]['used'],
                        'total': balance[currency]['total']
                    }
            return relevant
        except Exception as e:
            logger.error(f"❌ Bakiye çekme hatası: {e}")
            raise

    def check_connection(self):
        """Borsa bağlantısını kontrol eder."""
        try:
            self.exchange.load_markets()
            ticker = self.exchange.fetch_ticker(SYMBOL)
            logger.info(f"✅ Bağlantı başarılı! {SYMBOL} son fiyat: ${ticker['last']:,.2f}")
            return True
        except Exception as e:
            logger.error(f"❌ Bağlantı hatası: {e}")
            return False
