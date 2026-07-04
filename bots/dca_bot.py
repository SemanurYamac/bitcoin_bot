"""
DCA (Dollar Cost Averaging) Bot — periyodik birikim.

Strateji:
    Belirli aralıkta (default haftalık), tahsis edilmiş sermayenin
    sabit bir oranını BTC+ETH'ye böler ve alır. Hiç satmaz.

Mantık:
    - Yön bahsi yapmaz, fiyatı tahmin etmez
    - Uzun vadede zamanın "lehinde" çalışır (bull thesis)
    - Tek başına ayı'da kaybeder, ama Grid + Trend ile bütünleşir
    - Komisyon erozyonu minimum: ayda 4 işlem × 0.1% = 0.4%/ay

Yapılandırma:
    coins:               {'BTC/USDT': 0.5, 'ETH/USDT': 0.5}
    interval_hours:      168 (haftalık)
    buy_pct_of_capital:  0.10 (her seferde tahsis edilenin %10'u alınır)

Backtest:
    Walk-forward framework ile uyumlu. df tek sembol için çalışır;
    çoklu sembol portföy seviyesinde birleştirilir.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd

from core.bot_base import BotBase

logger = logging.getLogger(__name__)


# Komisyon — Binance spot taker fee
COMMISSION = 0.001  # %0.1


class DCABot(BotBase):
    name = 'dca'

    # Binance min notional ~$5; her coin için bunun üstünde kalmamız lazım
    MIN_NOTIONAL_PER_COIN = 6.0  # $6 — buffer ile

    def __init__(
        self,
        coins: dict[str, float] | None = None,
        interval_hours: int = 168,         # haftalık
        buy_pct_of_capital: float = 0.05,  # tahsisin %5'i/buy ($400 → $20/hafta)
        portfolio_manager=None,
    ):
        super().__init__(portfolio_manager=portfolio_manager)
        self.coins = coins or {'BTC/USDT': 0.5, 'ETH/USDT': 0.5}
        # Ağırlıkları normalize et
        total_w = sum(self.coins.values())
        if total_w <= 0:
            raise ValueError("DCA coin ağırlıkları > 0 olmalı")
        self.coins = {k: v / total_w for k, v in self.coins.items()}

        self.interval = timedelta(hours=interval_hours)
        self.buy_pct = buy_pct_of_capital

        # Live state
        self.cash: float = 0.0
        self.holdings: dict[str, float] = {sym: 0.0 for sym in self.coins}
        self.last_buy_at: datetime | None = None
        self.last_prices: dict[str, float] = {sym: 0.0 for sym in self.coins}

    # ───────────── Live API ─────────────

    def initialize_capital(self, allocated_usdt: float) -> None:
        """Portfolio manager'dan ilk tahsisi al, cash'e koy."""
        self.cash = allocated_usdt
        logger.info(f"[{self.name}] Sermaye tahsisi: ${allocated_usdt:.2f}")

    def step(self, now: datetime) -> None:
        """
        Tek döngü. Eğer interval geldiyse, fiyat çek + alım yap.
        """
        if self.is_paused():
            return

        if self.last_buy_at is not None and (now - self.last_buy_at) < self.interval:
            return  # zamanı gelmedi

        # Live alım
        try:
            from core.exchange import get_collector, get_executor
            collector = get_collector()
            executor = get_executor(self.name)

            # Toplam değerin %buy_pct kadarını dağıt
            allocation = self.portfolio_manager.get_allocation(self.name) if self.portfolio_manager else self.cash
            total_buy_usdt = allocation * self.buy_pct

            # Binance min notional koruma: küçük sermayelerde her coin için en az $6
            min_total = self.MIN_NOTIONAL_PER_COIN * len(self.coins)
            if total_buy_usdt < min_total:
                # Düşük sermaye — buy_pct'i adapte et
                if self.cash >= min_total:
                    logger.info(
                        f"[{self.name}] Düşük sermayede minimum alım uygulandı: "
                        f"${total_buy_usdt:.2f} → ${min_total:.2f} (min notional koruma)"
                    )
                    total_buy_usdt = min_total
                else:
                    logger.info(
                        f"[{self.name}] Alım atlandı: minimum ${min_total:.2f} gerekli, "
                        f"nakit sadece ${self.cash:.2f}"
                    )
                    return

            if total_buy_usdt > self.cash:
                logger.info(f"[{self.name}] Alım atlandı: gerekli ${total_buy_usdt:.2f}, nakit ${self.cash:.2f}")
                return

            for symbol, weight in self.coins.items():
                usdt_amount = total_buy_usdt * weight
                ticker = collector.fetch_ticker(symbol)
                price = float(ticker['last'])
                self.last_prices[symbol] = price

                coin_amount = usdt_amount / price
                if coin_amount <= 0:
                    continue

                result = executor.execute_buy(symbol=symbol, amount=coin_amount)
                if result is None:
                    continue

                actual_cost = result.get('cost', usdt_amount)
                actual_amount = result.get('amount', coin_amount)
                fee = result.get('fee', actual_cost * COMMISSION)

                self.cash -= (actual_cost + fee)
                self.holdings[symbol] += actual_amount

                logger.info(
                    f"[{self.name}] DCA alım: {actual_amount:.6f} {symbol} @ ${price:.2f} "
                    f"(${actual_cost:.2f}, kalan nakit ${self.cash:.2f})"
                )

            self.last_buy_at = now
            self.last_step_at = now.isoformat(timespec='seconds')
            self._save()
            self.report_to_portfolio()

        except Exception as e:
            self.last_error = str(e)
            logger.exception(f"[{self.name}] Step hatası: {e}")

    def current_value(self) -> float:
        """Cash + holdings × güncel fiyat."""
        # Son bilinen fiyatları kullan; canlı ise step() güncel fiyatları çekecek
        position_value = sum(
            self.holdings.get(sym, 0.0) * self.last_prices.get(sym, 0.0)
            for sym in self.coins
        )
        return self.cash + position_value

    def _save(self) -> None:
        self.save_state({
            'cash': self.cash,
            'holdings': self.holdings,
            'last_buy_at': self.last_buy_at.isoformat() if self.last_buy_at else None,
            'last_prices': self.last_prices,
            'coins': self.coins,
            'interval_hours': int(self.interval.total_seconds() / 3600),
            'buy_pct': self.buy_pct,
        })

    def restore(self) -> None:
        s = self.load_state()
        if s is None:
            return
        self.cash = s.get('cash', self.cash)
        self.holdings = s.get('holdings', self.holdings)
        self.last_prices = s.get('last_prices', self.last_prices)
        last = s.get('last_buy_at')
        if last:
            try:
                self.last_buy_at = datetime.fromisoformat(last)
            except Exception:
                self.last_buy_at = None
        logger.info(f"[{self.name}] State restore edildi: cash=${self.cash:.2f}, holdings={self.holdings}")

    # ───────────── Backtest ─────────────

    def backtest(self, df: pd.DataFrame, initial_balance: float = 1000.0) -> dict:
        """
        Tek sembol DCA simülasyonu.

        Mantık: df'i tarayarak her interval'da fiyatı al, sabit USDT
        kadar coin satın al. Equity = cash + coin × price.
        """
        if df.empty:
            return {'equity_curve': pd.Series(dtype=float), 'trades': pd.DataFrame()}

        if not isinstance(df.index, pd.DatetimeIndex):
            df = df.copy()
            df.index = pd.to_datetime(df.index)

        cash = initial_balance
        coin_holding = 0.0
        equity_history = []
        trades = []
        last_buy_ts: pd.Timestamp | None = None

        # Tek sembol → bu botun tüm ağırlığı bu sembolde
        # Çoklu coin durumu walkforward'da symbol başına ayrı çalıştırılır
        weight = 1.0  # tek sembol için
        buy_per_event = initial_balance * self.buy_pct * weight

        for ts, row in df.iterrows():
            price = float(row['close'])

            # İlk alım hemen
            need_buy = (
                last_buy_ts is None
                or (ts - last_buy_ts) >= self.interval
            )

            if need_buy and cash >= buy_per_event:
                cost = buy_per_event
                fee = cost * COMMISSION
                amount = (cost - fee) / price  # net coin
                cash -= cost
                coin_holding += amount
                last_buy_ts = ts
                trades.append({
                    'timestamp': ts,
                    'side': 'buy',
                    'price': price,
                    'amount': amount,
                    'cost': cost,
                    'pnl': 0.0,
                    'reason': 'DCA periodic buy',
                })

            equity_history.append({
                'timestamp': ts,
                'equity': cash + coin_holding * price,
            })

        equity_df = pd.DataFrame(equity_history).set_index('timestamp')
        equity = equity_df['equity']

        # DCA hiç satmadığı için "kapatılan" trade yok → metrikler buy-and-hold benzeri
        # Yine de trades return ediyoruz, raporda buy_count görünür
        return {
            'equity_curve': equity,
            'trades': pd.DataFrame(trades),
        }
