"""
Grid Trading Bot — sideways piyasada volatiliteyi paraya çevirir.

Strateji:
    Belirli fiyat range'inde N grid seviyesi oluşturur.
    Fiyat her grid'i aşağı geçtiğinde küçük alım, yukarı geçtiğinde
    küçük satım yapar. Yön bahsi yok, her dalga küçük kâr.

Yapılandırma:
    range_method:    'rolling_bbands' | 'manual'
    range_lookback:  Range hesabı için kaç bar bakar (default 480 = 5gün/15m)
    n_grids:         Range'i kaç eşit parçaya böler (default 15)
    range_escape_pct: Fiyat range dışına %X çıkarsa stop-out (default 0.05)

Yapay zeka değil, geometrik bir oyun. En iyi yatay piyasada çalışır.

Backtest:
    Tek sembol df → equity curve + trades. Her grid hit bir buy veya sell.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from core.bot_base import BotBase

logger = logging.getLogger(__name__)


COMMISSION = 0.001  # %0.1


class GridBot(BotBase):
    name = 'grid'

    def __init__(
        self,
        symbol: str = 'BTC/USDT',
        n_grids: int = 15,
        range_lookback: int = 480,           # 5 gün × 96 mum/gün (15m)
        range_method: str = 'rolling_bbands',
        range_escape_pct: float = 0.05,
        capital_per_grid_pct: float = 0.05,  # her grid'in tetiklenmesi tahsisin %5'ini kullanır
        portfolio_manager=None,
    ):
        super().__init__(portfolio_manager=portfolio_manager)
        self.symbol = symbol
        self.n_grids = n_grids
        self.range_lookback = range_lookback
        self.range_method = range_method
        self.range_escape_pct = range_escape_pct
        self.capital_per_grid_pct = capital_per_grid_pct

        # Live state
        self.cash: float = 0.0
        self.coin_holding: float = 0.0
        self.range_low: float | None = None
        self.range_high: float | None = None
        self.grid_levels: list[float] = []
        self.grid_states: dict[float, bool] = {}  # grid → True if "we own from this level"
        self.last_price: float = 0.0

    # ───────────── Range Calculation ─────────────

    @staticmethod
    def _rolling_range_at(df: pd.DataFrame, idx: int, lookback: int) -> tuple[float, float]:
        """idx'den geriye lookback bar high/low bulur."""
        start = max(0, idx - lookback)
        window = df.iloc[start:idx + 1]
        if window.empty:
            row = df.iloc[idx]
            return float(row['low']), float(row['high'])
        return float(window['low'].min()), float(window['high'].max())

    def _build_grid(self, low: float, high: float) -> list[float]:
        """Range'i n_grids+1 eşit aralıklı seviyeye böler."""
        if high <= low or self.n_grids < 2:
            return []
        return list(np.linspace(low, high, self.n_grids + 1))

    # ───────────── Live API ─────────────

    def initialize_capital(self, allocated_usdt: float) -> None:
        self.cash = allocated_usdt

    def step(self, now) -> None:
        """Live grid execution — implementation Faz 2'de live'a alındığında detaylanır."""
        if self.is_paused():
            return
        # NOTE: Live entegrasyonu için canlıya alma fazında genişletilecek.
        # Şu anda backtest odaklı.
        return

    def current_value(self) -> float:
        return self.cash + self.coin_holding * self.last_price

    # ───────────── Backtest ─────────────

    def backtest(self, df: pd.DataFrame, initial_balance: float = 1000.0) -> dict:
        """
        Single-symbol grid simülasyonu.

        Mantık (her bar):
          1. Lookback yetiyse range'i hesapla (start aşamasında bir kez set,
             range_escape sonrası yeniden set)
          2. Fiyat range dışına çıktıysa: tüm pozisyonu kapat, range'i yeniden hesapla
          3. Aksi halde: bar'ın low/high'ı içinden geçen grid seviyelerinde işlem
        """
        if df.empty or len(df) < self.range_lookback + 10:
            return {'equity_curve': pd.Series(dtype=float), 'trades': pd.DataFrame()}

        if not isinstance(df.index, pd.DatetimeIndex):
            df = df.copy()
            df.index = pd.to_datetime(df.index)

        cash = initial_balance
        coin = 0.0
        equity_history = []
        trades = []
        grid_levels: list[float] = []
        bought_at: dict[int, float] = {}  # grid_idx → cost_basis (cash spent buying at this level)

        # USDT per grid trigger
        per_grid_usdt = initial_balance * self.capital_per_grid_pct

        # İlk range
        range_low, range_high = self._rolling_range_at(df, self.range_lookback, self.range_lookback)
        grid_levels = self._build_grid(range_low, range_high)
        bought_at = {}

        for i in range(self.range_lookback, len(df)):
            row = df.iloc[i]
            ts = df.index[i]
            close = float(row['close'])
            high = float(row['high'])
            low = float(row['low'])

            # Range escape kontrolü — close fiyatına bak (intra-bar wick'leri görmezden gel)
            if range_high > 0 and close > range_high * (1 + self.range_escape_pct):
                # Yukarı kaçtı — pozisyonu sat, range'i yenile
                if coin > 0:
                    revenue = coin * close
                    fee = revenue * COMMISSION
                    cash += (revenue - fee)
                    trades.append({
                        'timestamp': ts, 'side': 'sell', 'price': close,
                        'amount': coin, 'cost': revenue,
                        'pnl': revenue - sum(bought_at.values()) - fee,
                        'reason': 'Range yukarı kaçış — full exit',
                    })
                    coin = 0.0
                    bought_at = {}
                # Yeni range
                range_low, range_high = self._rolling_range_at(df, i, self.range_lookback)
                grid_levels = self._build_grid(range_low, range_high)
            elif range_low > 0 and close < range_low * (1 - self.range_escape_pct):
                # Aşağı kaçtı — daha sert: pozisyonu zararına kapat ve bekle
                if coin > 0:
                    revenue = coin * close
                    fee = revenue * COMMISSION
                    cash += (revenue - fee)
                    trades.append({
                        'timestamp': ts, 'side': 'sell', 'price': close,
                        'amount': coin, 'cost': revenue,
                        'pnl': revenue - sum(bought_at.values()) - fee,
                        'reason': 'Range aşağı kaçış — stop-out',
                    })
                    coin = 0.0
                    bought_at = {}
                range_low, range_high = self._rolling_range_at(df, i, self.range_lookback)
                grid_levels = self._build_grid(range_low, range_high)

            if not grid_levels:
                equity_history.append({'timestamp': ts, 'equity': cash + coin * close})
                continue

            # Grid hit detection — bar'ın low/high'ı içinden geçen seviyeler
            # Aşağı geçenler → buy, yukarı geçenler → sell
            for idx, level in enumerate(grid_levels):
                # BUY: low ≤ level < bir önceki close (fiyat aşağı kırdı)
                # ve bu seviyede pozisyonumuz yok
                if idx not in bought_at:
                    if low <= level < (df.iloc[i - 1]['close'] if i > 0 else level + 1):
                        # Bu seviye fiyatı kırdı, alım yap
                        if cash >= per_grid_usdt:
                            amount = (per_grid_usdt - per_grid_usdt * COMMISSION) / level
                            cash -= per_grid_usdt
                            coin += amount
                            bought_at[idx] = per_grid_usdt
                            trades.append({
                                'timestamp': ts, 'side': 'buy', 'price': level,
                                'amount': amount, 'cost': per_grid_usdt, 'pnl': 0.0,
                                'reason': f'Grid #{idx} buy @ ${level:.2f}',
                            })

                # SELL: high ≥ next_level > bir önceki close (fiyat yukarı kırdı)
                # ve bir alt grid'de pozisyonumuz var
                if idx > 0 and (idx - 1) in bought_at:
                    upper_level = level
                    if (df.iloc[i - 1]['close'] if i > 0 else upper_level - 1) < upper_level <= high:
                        # Bir alt grid'de aldığımızı sat
                        cost_basis = bought_at[idx - 1]
                        # Coin amount = ne aldıysak
                        coin_to_sell = (cost_basis * (1 - COMMISSION)) / grid_levels[idx - 1]
                        coin_to_sell = min(coin_to_sell, coin)
                        if coin_to_sell > 0:
                            revenue = coin_to_sell * upper_level
                            fee = revenue * COMMISSION
                            cash += (revenue - fee)
                            coin -= coin_to_sell
                            net_pnl = (revenue - fee) - cost_basis
                            del bought_at[idx - 1]
                            trades.append({
                                'timestamp': ts, 'side': 'sell', 'price': upper_level,
                                'amount': coin_to_sell, 'cost': revenue, 'pnl': net_pnl,
                                'reason': f'Grid #{idx} sell @ ${upper_level:.2f}',
                            })

            equity_history.append({'timestamp': ts, 'equity': cash + coin * close})

        # Son bar'da kalan pozisyonu kapat
        if coin > 0:
            final_price = float(df.iloc[-1]['close'])
            revenue = coin * final_price
            fee = revenue * COMMISSION
            cash += (revenue - fee)
            trades.append({
                'timestamp': df.index[-1], 'side': 'sell', 'price': final_price,
                'amount': coin, 'cost': revenue,
                'pnl': revenue - sum(bought_at.values()) - fee,
                'reason': 'Backtest sonu — pozisyon kapandı',
            })
            coin = 0.0

        equity_df = pd.DataFrame(equity_history).set_index('timestamp')
        return {
            'equity_curve': equity_df['equity'],
            'trades': pd.DataFrame(trades),
        }
