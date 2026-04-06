"""
Bitcoin Trading Bot - Veri Toplama Modülü
CCXT kütüphanesi ile Binance'den veri çeker.

ÖNEMLİ: Piyasa verisi (fiyat, mum, ticker) her zaman GERÇEK Binance'den çekilir.
Testnet sadece bakiye ve emir işlemleri için kullanılır.
Testnet'in sınırlı geçmiş verisi olduğu için bu ayrım şarttır.
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
        # ─── Piyasa Verisi İçin GERÇEK Binance (API key gerekmez) ───
        self.public_exchange = ccxt.binance({
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'},
        })
        logger.info("📊 Gerçek Binance piyasa verisi bağlantısı kuruldu")

        # ─── Emir ve Bakiye İşlemleri İçin Exchange ─────────────────
        if use_testnet or TRADING_MODE == 'paper':
            self.exchange = ccxt.binance({
                'apiKey': BINANCE_TESTNET_API_KEY,
                'secret': BINANCE_TESTNET_API_SECRET,
                'enableRateLimit': True,
                'options': {'defaultType': 'spot'},
            })
            self.exchange.set_sandbox_mode(True)
            logger.info("📋 Binance TESTNET bağlantısı kuruldu (Paper Trading - emir/bakiye)")
        elif TRADING_MODE == 'live':
            self.exchange = ccxt.binance({
                'apiKey': BINANCE_API_KEY,
                'secret': BINANCE_API_SECRET,
                'enableRateLimit': True,
                'options': {'defaultType': 'spot'},
            })
            logger.info("🔴 Binance CANLI bağlantı kuruldu!")
        else:
            # Backtest modu
            self.exchange = self.public_exchange
            logger.info("📊 Binance bağlantısı kuruldu (Backtest modu - sadece veri)")

    def fetch_ohlcv(self, symbol=None, timeframe=None, since=None, limit=500):
        """
        OHLCV (mum) verilerini GERÇEK Binance'den çeker.
        Testnet sınırlı veri döndüğü için her zaman gerçek API kullanılır.

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
            # Gerçek Binance'den veri çek (testnet değil!)
            ohlcv = self.public_exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)

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
        """
        symbol = symbol or SYMBOL
        timeframe = timeframe or TIMEFRAME

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
                ohlcv = self.public_exchange.fetch_ohlcv(
                    symbol, timeframe,
                    since=current_since,
                    limit=1000
                )

                if not ohlcv:
                    break

                all_data.extend(ohlcv)
                current_since = ohlcv[-1][0] + 1

                logger.info(f"  📦 {len(all_data)} mum indirildi... "
                           f"({datetime.fromtimestamp(current_since/1000).strftime('%Y-%m-%d %H:%M')})")

                time.sleep(self.public_exchange.rateLimit / 1000)

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
        df = df[~df.index.duplicated(keep='first')]
        df.sort_index(inplace=True)

        if end_date:
            df = df[:end_date]

        logger.info(f"✅ Toplam {len(df)} mum verisi indirildi ({start_date} → {end_date or 'şimdi'})")
        return df

    def fetch_ticker(self, symbol=None):
        """Anlık fiyat bilgisi çeker (gerçek Binance'den)."""
        symbol = symbol or SYMBOL
        try:
            ticker = self.public_exchange.fetch_ticker(symbol)
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
        """Hesap bakiyesini çeker (testnet/live exchange üzerinden)."""
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
        """Borsa bağlantısını kontrol eder (hem gerçek hem testnet)."""
        try:
            # Gerçek Binance piyasa verisi testi
            self.public_exchange.load_markets()
            ticker = self.public_exchange.fetch_ticker(SYMBOL)
            logger.info(f"✅ Bağlantı başarılı! {SYMBOL} son fiyat: ${ticker['last']:,.2f}")

            # Testnet/live emir bağlantısı testi
            if TRADING_MODE in ('paper', 'live'):
                self.exchange.load_markets()
                logger.info("✅ Emir bağlantısı başarılı!")

            return True
        except Exception as e:
            logger.error(f"❌ Bağlantı hatası: {e}")
            return False
