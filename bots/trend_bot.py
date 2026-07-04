"""
Trend Bot — Multi-Timeframe ML + ATR-Based Risk Management.

Mevcut strategy/signals.py'ın **tutarlı temele oturtulmuş** yeniden yazımı.

Temel farklar:
  1. **Multi-timeframe trend gate**: 1h EMA200 üstünde değilse HİÇ işlem yok
     (mevcut bot'taki sadece-LONG ayı zafiyetinin çözümü)
  2. **Rejim-bağımlı ML eşiği**:
        Strong bull (close > 1h EMA200 × 1.05): conf > 0.55
        Bull           (close > 1h EMA200):       conf > 0.60
        Bear           (close < 1h EMA200):       BOT PASİF (signal yok)
  3. **ATR SL/TP** mevcut config'le aynı (ml_trainer etiket fonksiyonu da
     bu değerleri kullanıyor → eğitim ve canlı uyumlu)
  4. **Tek sembol, focused** — DCA & Grid çoklu sembol kapsıyor
"""
from __future__ import annotations

import logging
import os

import joblib
import numpy as np
import pandas as pd

from analysis.indicators import TechnicalIndicators
from config.settings import (
    TRAILING_ACTIVATION,
    PARTIAL_TP_ENABLED, PARTIAL_TP_R_MULTIPLE, PARTIAL_TP_CLOSE_PERCENT,
    PARTIAL_TP_MOVE_SL_TO_BE,
)
from core.bot_base import BotBase

logger = logging.getLogger(__name__)


COMMISSION = 0.001
DEFAULT_RISK_PER_TRADE = 0.05

# 15m timeframe için ATR multiplier'lar (config 4h için 2.5 — burada 15m override)
ATR_SL_MULT = 1.0     # SL = giriş - 1.0 × ATR
ATR_TP1_MULT = 1.5    # Partial TP @ 1.5 × ATR (live TP1 ile aynı, ML eğitimi ile aynı)
ATR_TP2_MULT = 5.0    # Tam TP @ 5.0 × ATR (uzun trail)
ATR_TRAIL_MULT = 2.0  # Trailing distance
MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'xgboost_model.joblib')


def add_higher_tf_trend(df: pd.DataFrame, htf: str = '1h', ema_period: int = 200) -> pd.DataFrame:
    """15m df'e 1h EMA200 sütunu ekler (forward-fill)."""
    if df.empty or 'close' not in df.columns:
        return df
    df = df.copy()
    htf_close = df['close'].resample(htf).last().dropna()
    htf_ema = htf_close.ewm(span=ema_period, adjust=False).mean()
    df['ema200_htf'] = htf_ema.reindex(df.index, method='ffill')
    return df


class TrendBot(BotBase):
    name = 'trend'

    def __init__(
        self,
        symbol: str = 'BTC/USDT',
        risk_per_trade: float = DEFAULT_RISK_PER_TRADE,
        ml_threshold_bull: float = 0.55,
        ml_threshold_neutral: float = 0.60,
        portfolio_manager=None,
    ):
        super().__init__(portfolio_manager=portfolio_manager)
        self.symbol = symbol
        self.risk_per_trade = risk_per_trade
        self.ml_threshold_bull = ml_threshold_bull
        self.ml_threshold_neutral = ml_threshold_neutral

        self.model = None
        try:
            if os.path.exists(MODEL_PATH):
                self.model = joblib.load(MODEL_PATH)
                logger.info(f"[{self.name}] XGBoost modeli yüklendi: {MODEL_PATH}")
        except Exception as e:
            logger.error(f"[{self.name}] Model yükleme hatası: {e}")

        # Live state
        self.cash: float = 0.0
        self.coin_holding: float = 0.0
        self.last_price: float = 0.0
        self.active_position: dict | None = None

    def initialize_capital(self, allocated_usdt: float) -> None:
        self.cash = allocated_usdt

    def step(self, now) -> None:
        """Live step — Faz 3 canlıya alma sırasında detaylanır."""
        if self.is_paused():
            return
        # Live entegrasyon Faz 3'te
        return

    def current_value(self) -> float:
        return self.cash + self.coin_holding * self.last_price

    # ───────────── Signal Logic ─────────────

    def _ml_features(self, summary: dict, df: pd.DataFrame, idx: int) -> np.ndarray | None:
        """Mevcut ml_trainer.prepare_ml_features ile aynı sırada feature dizisi."""
        try:
            price = summary['price']
            bb_range = summary.get('bb_upper', 0) - summary.get('bb_lower', 0)
            bb_pos = (price - summary.get('bb_lower', 0)) / bb_range if bb_range > 0 else 0.5

            ema_long = summary.get('ema_long')
            ema_dist = (price - ema_long) / ema_long * 100 if ema_long and not pd.isna(ema_long) and ema_long != 0 else 0.0

            ema_slow = summary.get('ema_slow')
            ema_cross = (ema_slow - ema_long) / ema_long * 100 if ema_long and ema_slow and not pd.isna(ema_slow) and ema_long != 0 else 0.0

            stoch_rsi = summary.get('stoch_rsi_k', 50) or 50

            funding_rate = 0.0
            funding_trend = 0.0
            if 'funding_rate' in df.columns:
                fr = df['funding_rate'].iloc[idx]
                funding_rate = float(fr) * 1000 if not pd.isna(fr) else 0.0
                fr_window = df['funding_rate'].iloc[max(0, idx - 3):idx + 1]
                funding_trend = float(fr_window.mean()) * 1000 if len(fr_window) > 0 else 0.0

            if idx >= 4:
                p4 = df['close'].iloc[idx - 4]
                price_momentum = (price - p4) / p4 * 100 if p4 != 0 else 0.0
            else:
                price_momentum = 0.0

            features = [
                summary.get('rsi', 50),
                summary.get('macd_histogram', 0),
                bb_pos,
                summary.get('volume_ratio', 1.0),
                ema_dist,
                ema_cross,
                summary.get('adx', 0),
                stoch_rsi,
                funding_rate,
                funding_trend,
                price_momentum,
            ]

            if self.model is None:
                return None
            n_features = len(self.model.feature_names_in_) if hasattr(self.model, 'feature_names_in_') else len(features)
            arr = np.array([features[:n_features]])
            return np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
        except Exception as e:
            logger.debug(f"[{self.name}] feature error at {idx}: {e}")
            return None

    def _signal(self, df: pd.DataFrame, idx: int) -> tuple[str, dict]:
        """
        Tek bir bar için sinyal.

        Returns: ('BUY' | 'HOLD', meta_dict)
        """
        summary = TechnicalIndicators.get_summary(df, idx)
        if summary is None:
            return 'HOLD', {'reason': 'yetersiz veri'}

        price = summary['price']

        # ── HARD GATE 1: 1h EMA200 trend filtresi ────────────────────
        ema200_htf = df['ema200_htf'].iloc[idx] if 'ema200_htf' in df.columns else None
        if ema200_htf is None or pd.isna(ema200_htf) or price < ema200_htf:
            return 'HOLD', {'reason': f'1h EMA200 altı (htf bear)', 'ema200_htf': ema200_htf}

        # ── HARD GATE 2: ATR mevcut ──────────────────────────────────
        atr = summary.get('atr')
        if atr is None or pd.isna(atr) or atr <= 0:
            return 'HOLD', {'reason': 'ATR yok'}

        # ── ML tahmini ──────────────────────────────────────────────
        if self.model is None:
            return 'HOLD', {'reason': 'ML model yüklenmedi'}

        features = self._ml_features(summary, df, idx)
        if features is None:
            return 'HOLD', {'reason': 'feature build error'}

        try:
            prob = float(self.model.predict_proba(features)[0][1])
        except Exception as e:
            return 'HOLD', {'reason': f'predict error: {e}'}

        # Rejime göre eşik
        is_strong_bull = ema200_htf and price > ema200_htf * 1.05
        threshold = self.ml_threshold_bull if is_strong_bull else self.ml_threshold_neutral

        if prob >= threshold:
            return 'BUY', {
                'reason': f'ML conf={prob:.2f} ≥ {threshold:.2f} (strong_bull={is_strong_bull})',
                'ml_prob': prob,
                'atr': atr,
                'price': price,
            }
        return 'HOLD', {'reason': f'ML conf={prob:.2f} < {threshold:.2f}', 'ml_prob': prob}

    # ───────────── Backtest ─────────────

    def backtest(self, df: pd.DataFrame, initial_balance: float = 1000.0) -> dict:
        """
        Tek sembol trend bot simülasyonu.

        Akış (her bar):
          - Açık pozisyon varsa: SL / TP1 (partial) / TP2 / trailing kontrolü
          - Açık pozisyon yoksa: sinyal değerlendir, BUY ise pozisyon aç
        """
        if df.empty or len(df) < 250:
            return {'equity_curve': pd.Series(dtype=float), 'trades': pd.DataFrame()}

        if not isinstance(df.index, pd.DatetimeIndex):
            df = df.copy()
            df.index = pd.to_datetime(df.index)

        # Indicator + 1h trend
        df = TechnicalIndicators.calculate_all(df)
        df = add_higher_tf_trend(df, htf='1h', ema_period=200)

        cash = initial_balance
        coin = 0.0
        active: dict | None = None
        trades = []
        equity_history = []

        start_idx = 250  # 1h EMA200 oluşması için

        for i in range(start_idx, len(df)):
            row = df.iloc[i]
            ts = df.index[i]
            close = float(row['close'])
            high = float(row['high'])
            low = float(row['low'])
            atr = float(row['atr']) if 'atr' in df.columns and not pd.isna(row['atr']) else None

            # ─── Açık pozisyon yönetimi ─────────────────────────────
            if active is not None:
                # Highest price güncelle (trailing için)
                if high > active['highest']:
                    active['highest'] = high
                    if active.get('atr_at_entry', 0) > 0:
                        trail_mult = ATR_TRAIL_MULT * (0.75 if active['partial_done'] else 1.0)
                        new_trail = active['highest'] - active['atr_at_entry'] * trail_mult
                        if active['trailing_stop'] is None or new_trail > active['trailing_stop']:
                            active['trailing_stop'] = new_trail
                        # SL'yi yukarı çek (ratchet)
                        if active['trailing_stop'] > active['stop_loss']:
                            active['stop_loss'] = active['trailing_stop']

                # Partial TP
                if (PARTIAL_TP_ENABLED
                        and not active['partial_done']
                        and high >= active['partial_tp']):
                    sell_amount = active['amount'] * PARTIAL_TP_CLOSE_PERCENT
                    revenue = sell_amount * active['partial_tp']
                    fee = revenue * COMMISSION
                    entry_cost_for_partial = sell_amount * active['entry']
                    pnl = (revenue - fee) - entry_cost_for_partial
                    cash += (revenue - fee)
                    coin -= sell_amount
                    active['amount'] -= sell_amount
                    active['partial_done'] = True
                    if PARTIAL_TP_MOVE_SL_TO_BE:
                        active['stop_loss'] = max(active['stop_loss'], active['entry'])
                    trades.append({
                        'timestamp': ts, 'side': 'partial_sell', 'price': active['partial_tp'],
                        'amount': sell_amount, 'cost': revenue, 'pnl': pnl,
                        'reason': f'TP1 ATR×{ATR_TP1_MULT}',
                    })

                # Tam çıkış
                exit_reason = None
                exit_price = close
                if low <= active['stop_loss']:
                    exit_reason = f'SL @ ${active["stop_loss"]:.2f}'
                    exit_price = active['stop_loss']
                elif high >= active['take_profit']:
                    exit_reason = f'TP2 @ ${active["take_profit"]:.2f}'
                    exit_price = active['take_profit']

                if exit_reason:
                    revenue = active['amount'] * exit_price
                    fee = revenue * COMMISSION
                    entry_cost = active['amount'] * active['entry']
                    pnl = (revenue - fee) - entry_cost
                    cash += (revenue - fee)
                    coin -= active['amount']
                    trades.append({
                        'timestamp': ts, 'side': 'sell', 'price': exit_price,
                        'amount': active['amount'], 'cost': revenue, 'pnl': pnl,
                        'reason': exit_reason,
                    })
                    active = None

                equity_history.append({'timestamp': ts, 'equity': cash + coin * close})
                continue

            # ─── Sinyal değerlendir ──────────────────────────────────
            signal, meta = self._signal(df, i)
            if signal == 'BUY' and atr and atr > 0:
                sl_dist = atr * ATR_SL_MULT
                tp1_dist = atr * ATR_TP1_MULT
                tp2_dist = atr * ATR_TP2_MULT

                stop = close - sl_dist
                # Risk-bazlı pozisyon boyutu
                risk_dollar = cash * self.risk_per_trade
                if sl_dist <= 0 or sl_dist > close * 0.10:
                    equity_history.append({'timestamp': ts, 'equity': cash + coin * close})
                    continue
                position_value = min(risk_dollar / (sl_dist / close), cash * 0.99)
                position_value = max(position_value, 5.0)
                if position_value > cash:
                    equity_history.append({'timestamp': ts, 'equity': cash + coin * close})
                    continue

                amount = position_value / close
                fee = position_value * COMMISSION
                cash -= (position_value + fee)
                coin += amount

                active = {
                    'entry': close,
                    'amount': amount,
                    'stop_loss': stop,
                    'take_profit': close + tp2_dist,
                    'partial_tp': close + tp1_dist,
                    'partial_done': False,
                    'highest': close,
                    'trailing_stop': None,
                    'atr_at_entry': atr,
                }
                trades.append({
                    'timestamp': ts, 'side': 'buy', 'price': close,
                    'amount': amount, 'cost': position_value, 'pnl': 0.0,
                    'reason': meta.get('reason', 'BUY signal'),
                })

            equity_history.append({'timestamp': ts, 'equity': cash + coin * close})

        # Son açık pozisyonu kapat
        if active is not None and coin > 0:
            final_price = float(df.iloc[-1]['close'])
            revenue = active['amount'] * final_price
            fee = revenue * COMMISSION
            entry_cost = active['amount'] * active['entry']
            pnl = (revenue - fee) - entry_cost
            cash += (revenue - fee)
            coin -= active['amount']
            trades.append({
                'timestamp': df.index[-1], 'side': 'sell', 'price': final_price,
                'amount': active['amount'], 'cost': revenue, 'pnl': pnl,
                'reason': 'Backtest sonu',
            })

        equity_df = pd.DataFrame(equity_history).set_index('timestamp')
        return {
            'equity_curve': equity_df['equity'],
            'trades': pd.DataFrame(trades),
        }
