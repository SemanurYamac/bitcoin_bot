"""
Bitcoin Trading Bot - Veri Depolama Modülü
SQLite veritabanı ile geçmiş verileri depolar.
"""
import sqlite3
import pandas as pd
import logging
from pathlib import Path
from config.settings import DB_PATH

logger = logging.getLogger(__name__)


class DataStorage:
    """SQLite ile veri depolama ve okuma."""

    def __init__(self, db_path=None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Veritabanı tablolarını oluşturur."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # OHLCV verileri tablosu (çoklu coin uyumlu composite PK)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ohlcv (
                timestamp TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                symbol TEXT DEFAULT 'BTC/USDT',
                timeframe TEXT DEFAULT '1h',
                PRIMARY KEY (timestamp, symbol, timeframe)
            )
        ''')

        # İşlem geçmişi tablosu
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,  -- 'buy' veya 'sell'
                price REAL NOT NULL,
                amount REAL NOT NULL,
                cost REAL NOT NULL,
                fee REAL DEFAULT 0,
                profit_loss REAL DEFAULT 0,
                strategy TEXT,
                signal_reason TEXT,
                mode TEXT DEFAULT 'backtest'  -- backtest, paper, live
            )
        ''')

        # Portföy durumu tablosu
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS portfolio (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                total_value_usdt REAL NOT NULL,
                btc_amount REAL DEFAULT 0,
                usdt_amount REAL DEFAULT 0,
                unrealized_pnl REAL DEFAULT 0,
                realized_pnl REAL DEFAULT 0
            )
        ''')

        conn.commit()
        conn.close()
        logger.info(f"✅ Veritabanı hazır: {self.db_path}")

    def save_ohlcv(self, df, symbol='BTC/USDT', timeframe='1h'):
        """
        OHLCV verilerini veritabanına kaydeder.

        Args:
            df: pandas DataFrame (index=timestamp, columns=open,high,low,close,volume)
            symbol: İşlem çifti
            timeframe: Zaman dilimi
        """
        conn = sqlite3.connect(self.db_path)

        save_df = df.copy()
        save_df['symbol'] = symbol
        save_df['timeframe'] = timeframe
        save_df.index.name = 'timestamp'

        save_df.to_sql('ohlcv', conn, if_exists='replace', index=True)
        conn.close()

        logger.info(f"💾 {len(save_df)} mum verisi kaydedildi ({symbol})")

    def load_ohlcv(self, symbol='BTC/USDT', timeframe='1h',
                   start_date=None, end_date=None):
        """
        Veritabanından OHLCV verilerini yükler.

        Returns:
            pandas DataFrame
        """
        conn = sqlite3.connect(self.db_path)

        query = "SELECT * FROM ohlcv WHERE symbol = ? AND timeframe = ?"
        params = [symbol, timeframe]

        if start_date:
            query += " AND timestamp >= ?"
            params.append(start_date)
        if end_date:
            query += " AND timestamp <= ?"
            params.append(end_date)

        query += " ORDER BY timestamp"

        df = pd.read_sql_query(query, conn, params=params, parse_dates=['timestamp'])
        conn.close()

        if not df.empty:
            df.set_index('timestamp', inplace=True)
            df = df[['open', 'high', 'low', 'close', 'volume']]
            logger.info(f"📂 {len(df)} mum verisi yüklendi ({symbol})")

        return df

    def save_trade(self, trade_data):
        """
        İşlem kaydı ekler.

        Args:
            trade_data: dict with keys: timestamp, symbol, side, price, amount, cost, fee, etc.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO trades (timestamp, symbol, side, price, amount, cost, fee,
                              profit_loss, strategy, signal_reason, mode)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            str(trade_data.get('timestamp', '')),
            trade_data.get('symbol', 'BTC/USDT'),
            trade_data.get('side', ''),
            trade_data.get('price', 0),
            trade_data.get('amount', 0),
            trade_data.get('cost', 0),
            trade_data.get('fee', 0),
            trade_data.get('profit_loss', 0),
            trade_data.get('strategy', ''),
            trade_data.get('signal_reason', ''),
            trade_data.get('mode', 'backtest'),
        ))

        conn.commit()
        conn.close()
        logger.info(f"💾 İşlem kaydedildi: {trade_data['side'].upper()} "
                    f"{trade_data['amount']:.6f} BTC @ ${trade_data['price']:,.2f}")

    def get_trades(self, mode=None, limit=100):
        """İşlem geçmişini getirir."""
        conn = sqlite3.connect(self.db_path)

        if mode:
            query = "SELECT * FROM trades WHERE mode = ? ORDER BY timestamp DESC LIMIT ?"
            df = pd.read_sql_query(query, conn, params=[mode, limit])
        else:
            query = "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?"
            df = pd.read_sql_query(query, conn, params=[limit])

        conn.close()
        return df

    def save_portfolio_snapshot(self, snapshot):
        """Portföy anlık görüntüsünü kaydeder."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO portfolio (timestamp, total_value_usdt, btc_amount, 
                                  usdt_amount, unrealized_pnl, realized_pnl)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            str(snapshot.get('timestamp', '')),
            snapshot.get('total_value_usdt', 0),
            snapshot.get('btc_amount', 0),
            snapshot.get('usdt_amount', 0),
            snapshot.get('unrealized_pnl', 0),
            snapshot.get('realized_pnl', 0),
        ))

        conn.commit()
        conn.close()

    def get_data_info(self):
        """Veritabanı hakkında bilgi verir."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        info = {}
        
        cursor.execute("SELECT COUNT(*) FROM ohlcv")
        info['ohlcv_count'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM ohlcv")
        row = cursor.fetchone()
        info['ohlcv_start'] = row[0]
        info['ohlcv_end'] = row[1]

        cursor.execute("SELECT COUNT(*) FROM trades")
        info['trade_count'] = cursor.fetchone()[0]

        conn.close()
        return info
