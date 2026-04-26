"""
Bitcoin Trading Bot - Backtesting Motoru (Faz 4 — Güncellenmiş)
Geçmiş veriler üzerinde strateji simülasyonu yapar.

FAZ 4 DÜZELTMELERİ:
  - Cooldown backtest'te devre dışı: cooldown live trading içindir,
    backtest'te sinyal kalitesini ölçmek için cooldown atlanır.
  - Partial TP simülasyonu: execute_partial_close mantığı backtest'e eklendi.
  - MAX_DAILY_TRADES backtest'te devre dışı (günlük sınır istatistiği bozar).
  - Pozisyon açıkken yeni sinyal aranmaz (doğru davranış), ama cooldown beklenmez.
"""
import pandas as pd
import numpy as np
import logging
from datetime import datetime
from analysis.indicators import TechnicalIndicators
from strategy.signals import SignalGenerator
from config.settings import (
    BACKTEST_INITIAL_BALANCE, EMA_LONG,
    PARTIAL_TP_ENABLED, PARTIAL_TP_R_MULTIPLE,
    PARTIAL_TP_CLOSE_PERCENT, PARTIAL_TP_MOVE_SL_TO_BE,
    STOP_LOSS_PERCENT, TAKE_PROFIT_PERCENT,
    TRAILING_STOP_PERCENT, TRAILING_ACTIVATION,
    ATR_SL_MULT, ATR_TP1_MULT, ATR_TP2_MULT,
    RISK_PER_TRADE, MAX_POSITION_PERCENT,
)

logger = logging.getLogger(__name__)


class BacktestEngine:
    """Geçmiş veriler üzerinde strateji simülasyonu yapar."""

    def __init__(self, initial_balance=None):
        self.initial_balance = initial_balance or BACKTEST_INITIAL_BALANCE
        self.signal_generator = SignalGenerator()

    def run(self, df, verbose=False):
        """
        Backtesting çalıştırır.

        Önemli tasarım kararları:
          - Cooldown devre dışı: backtest'te her sinyal değerlendirilir.
          - Partial TP simüle edilir: pozisyon yarıya iner, SL breakeven'a gelir.
          - MAX_DAILY_TRADES devre dışı: yanlış sınırlama önlenir.
          - Tek pozisyon prensibi korunur: pozisyon açıkken yeni sinyal yok.

        Args:
            df: OHLCV DataFrame (göstergeler henüz eklenmemiş olabilir)
            verbose: Detaylı log çıktısı

        Returns:
            dict: Performans sonuçları
        """
        logger.info("=" * 60)
        logger.info("📊 BACKTESTING BAŞLADI")
        logger.info(f"   Başlangıç bakiyesi: ${self.initial_balance:,.2f}")
        logger.info(f"   Veri aralığı: {df.index[0]} → {df.index[-1]}")
        logger.info(f"   Toplam mum sayısı: {len(df)}")
        logger.info(f"   Partial TP: {'AÇIK' if PARTIAL_TP_ENABLED else 'KAPALI'}")
        logger.info("=" * 60)

        # Göstergeleri hesapla
        df = TechnicalIndicators.calculate_all(df)

        balance = self.initial_balance
        coin_holding = 0.0

        # ── Aktif Pozisyon Durumu ─────────────────────────────────
        active_pos = None   # dict veya None
        # active_pos alanları:
        #   entry_price, amount, stop_loss, take_profit,
        #   partial_tp_price, partial_tp_triggered,
        #   highest_price, trailing_stop

        # Sonuç izleme
        trades = []
        portfolio_history = []

        # EMA_LONG kadar bekle (göstergelerin oluşması için)
        start_idx = max(EMA_LONG + 10, 201)

        for i in range(start_idx, len(df)):
            current_price = df['close'].iloc[i]
            current_time  = df.index[i]

            # ATR değeri (dinamik SL için)
            atr = df['atr'].iloc[i] if 'atr' in df.columns and not pd.isna(df['atr'].iloc[i]) else None

            # Portföy değeri
            total_value = balance + (coin_holding * current_price)
            portfolio_history.append({
                'timestamp': current_time,
                'balance': balance,
                'coin_holding': coin_holding,
                'price': current_price,
                'total_value': total_value,
            })

            # ─── Aktif Pozisyon Varsa: Çıkış / Kısmi TP Kontrol ──────
            if active_pos is not None:

                # ── 1) Partial TP ──────────────────────────────────
                if (PARTIAL_TP_ENABLED
                        and not active_pos['partial_tp_triggered']
                        and current_price >= active_pos['partial_tp_price']):

                    close_amount     = active_pos['amount'] * PARTIAL_TP_CLOSE_PERCENT
                    remaining_amount = active_pos['amount'] * (1 - PARTIAL_TP_CLOSE_PERCENT)

                    gross_pnl = (current_price - active_pos['entry_price']) * close_amount
                    fee       = (active_pos['entry_price'] * close_amount * 0.001) + (current_price * close_amount * 0.001)
                    net_pnl   = gross_pnl - fee

                    balance      += current_price * close_amount - fee
                    coin_holding -= close_amount

                    active_pos['amount']               = round(remaining_amount, 8)
                    active_pos['partial_tp_triggered'] = True

                    # SL breakeven'a taşı
                    if PARTIAL_TP_MOVE_SL_TO_BE:
                        active_pos['stop_loss'] = active_pos['entry_price']

                    trades.append({
                        'timestamp': current_time,
                        'side': 'partial_sell',
                        'price': current_price,
                        'amount': round(close_amount, 8),
                        'cost': current_price * close_amount,
                        'pnl': round(net_pnl, 2),
                        'reason': f"Partial TP {PARTIAL_TP_R_MULTIPLE}R @ ${current_price:,.2f}",
                    })

                    if verbose:
                        logger.info(
                            f"🎯 [{current_time}] PARTIAL TP @ ${current_price:,.2f} | "
                            f"Kapat: {close_amount:.6f} | PnL: ${net_pnl:+,.2f} | "
                            f"SL → ${active_pos['stop_loss']:,.2f}"
                        )

                # ── 2) Trailing Stop Güncelle ───────────────────────
                if current_price > active_pos.get('highest_price', active_pos['entry_price']):
                    active_pos['highest_price'] = current_price
                    active_pos['trailing_stop'] = current_price * (1 - TRAILING_STOP_PERCENT)

                # ── 3) Tam Exit Kontrol ─────────────────────────────
                exit_reason = None

                if current_price <= active_pos['stop_loss']:
                    exit_reason = f"Stop-Loss @ ${active_pos['stop_loss']:,.2f}"

                elif current_price >= active_pos['take_profit']:
                    exit_reason = f"Take-Profit @ ${active_pos['take_profit']:,.2f}"

                elif (active_pos.get('trailing_stop')
                        and current_price <= active_pos['trailing_stop']
                        and active_pos.get('highest_price', 0) >= active_pos['entry_price'] * (1 + TRAILING_ACTIVATION)):
                    exit_reason = f"Trailing Stop @ ${active_pos['trailing_stop']:,.2f}"

                if exit_reason:
                    amount    = active_pos['amount']
                    entry     = active_pos['entry_price']
                    gross_pnl = (current_price - entry) * amount
                    fee       = (entry * amount * 0.001) + (current_price * amount * 0.001)
                    net_pnl   = gross_pnl - fee
                    pnl_pct   = (current_price - entry) / entry * 100

                    balance      += current_price * amount - fee
                    coin_holding -= amount

                    trades.append({
                        'timestamp': current_time,
                        'side': 'sell',
                        'price': current_price,
                        'amount': amount,
                        'cost': current_price * amount,
                        'pnl': round(net_pnl, 2),
                        'reason': exit_reason,
                    })

                    if verbose:
                        emoji = '✅' if net_pnl > 0 else '❌'
                        logger.info(
                            f"{emoji} [{current_time}] SATIŞ - {exit_reason} | "
                            f"PnL: ${net_pnl:+,.2f} ({pnl_pct:+.2f}%)"
                        )

                    active_pos   = None
                    coin_holding = max(coin_holding, 0.0)  # float hata koruması

                # Pozisyon açıksa bu mumda işlem yapma — ama continue YOK:
                # (partial TP sonrası bile tam exit olabilir, yukarıda kontrol edildi)
                continue

            # ─── Sinyal Üret (pozisyon kapalıysa) ────────────────────
            signal_result = self.signal_generator.generate_signal(df, index=i)

            if signal_result['signal'] == 'BUY' and balance > 5:
                # Pozisyon boyutunu hesapla
                # ── ATR Bazlı SL / TP Hesabı (Faz 5: 3:1 R:R hedefi) ──────
                if atr and atr > 0:
                    sl_dist      = atr * ATR_SL_MULT          # 1.5 × ATR
                    tp1_dist     = atr * ATR_TP1_MULT         # 2.0 × ATR
                    tp2_dist     = atr * ATR_TP2_MULT         # 3.0 × ATR
                    stop_dist    = min(sl_dist / current_price, 0.10)  # max %10
                    stop_dist    = max(stop_dist, 0.01)                # min %1
                else:
                    sl_dist   = current_price * STOP_LOSS_PERCENT
                    tp1_dist  = current_price * TAKE_PROFIT_PERCENT
                    tp2_dist  = current_price * TAKE_PROFIT_PERCENT * 1.5
                    stop_dist = STOP_LOSS_PERCENT

                risk_amount    = balance * RISK_PER_TRADE
                position_value = min(risk_amount / stop_dist, balance * MAX_POSITION_PERCENT)
                position_value = max(position_value, 5.0)
                if position_value > balance:
                    position_value = balance * MAX_POSITION_PERCENT

                amount = position_value / current_price
                cost   = position_value
                fee    = cost * 0.001

                if balance < cost + fee:
                    continue

                balance      -= (cost + fee)
                coin_holding += amount

                sl         = current_price - sl_dist
                tp         = current_price + tp2_dist          # Ana TP = 3.0 × ATR
                partial_tp = current_price + tp1_dist          # Partial TP = 2.0 × ATR

                active_pos = {
                    'entry_price':          current_price,
                    'amount':               amount,
                    'stop_loss':            round(sl, 6),
                    'take_profit':          round(tp, 6),
                    'partial_tp_price':     round(partial_tp, 6),
                    'partial_tp_triggered': False,
                    'highest_price':        current_price,
                    'trailing_stop':        None,
                }

                trades.append({
                    'timestamp': current_time,
                    'side': 'buy',
                    'price': current_price,
                    'amount': amount,
                    'cost': cost,
                    'pnl': 0,
                    'reason': '; '.join(signal_result['reasons'][:2]),
                })

                if verbose:
                    logger.info(
                        f"🟢 [{current_time}] ALIŞ @ ${current_price:,.2f} | "
                        f"{amount:.6f} | Maliyet: ${cost:,.2f} | "
                        f"SL: ${sl:,.2f} | TP: ${tp:,.2f} | "
                        f"Partial TP: ${partial_tp:,.2f}"
                    )

        # Son açık pozisyonu kapat
        if active_pos is not None and coin_holding > 0:
            final_price  = df['close'].iloc[-1]
            amount       = active_pos['amount']
            entry        = active_pos['entry_price']
            gross_pnl    = (final_price - entry) * amount
            fee          = (entry * amount * 0.001) + (final_price * amount * 0.001)
            net_pnl      = gross_pnl - fee
            balance     += final_price * amount - fee
            coin_holding = 0.0
            trades.append({
                'timestamp': df.index[-1],
                'side': 'sell',
                'price': final_price,
                'amount': amount,
                'cost': final_price * amount,
                'pnl': round(net_pnl, 2),
                'reason': 'Backtest sonu — pozisyon kapatıldı',
            })

        # ─── Performans Metrikleri ────────────────────────────────
        final_value  = balance + coin_holding * df['close'].iloc[-1]
        total_return = (final_value - self.initial_balance) / self.initial_balance * 100

        trades_df    = pd.DataFrame(trades) if trades else pd.DataFrame()
        portfolio_df = pd.DataFrame(portfolio_history)

        if not trades_df.empty:
            sell_trades    = trades_df[trades_df['side'] == 'sell']
            winning_trades = sell_trades[sell_trades['pnl'] > 0]
            losing_trades  = sell_trades[sell_trades['pnl'] < 0]
            win_rate       = len(winning_trades) / len(sell_trades) * 100 if len(sell_trades) > 0 else 0
            avg_win        = winning_trades['pnl'].mean() if len(winning_trades) > 0 else 0
            avg_loss       = abs(losing_trades['pnl'].mean()) if len(losing_trades) > 0 else 0
            profit_factor  = (
                winning_trades['pnl'].sum() / abs(losing_trades['pnl'].sum())
                if len(losing_trades) > 0 and losing_trades['pnl'].sum() != 0
                else float('inf')
            )
        else:
            win_rate = avg_win = avg_loss = 0
            profit_factor = 0

        # Max drawdown
        if not portfolio_df.empty:
            portfolio_df['peak']     = portfolio_df['total_value'].cummax()
            portfolio_df['drawdown'] = (portfolio_df['peak'] - portfolio_df['total_value']) / portfolio_df['peak']
            max_drawdown = portfolio_df['drawdown'].max() * 100
        else:
            max_drawdown = 0

        # Sharpe Ratio (yıllıklaştırılmış, saatlik veri)
        if not portfolio_df.empty and len(portfolio_df) > 1:
            returns     = portfolio_df['total_value'].pct_change().dropna()
            sharpe_ratio = (returns.mean() / returns.std() * np.sqrt(365 * 24)
                           if returns.std() > 0 else 0)
        else:
            sharpe_ratio = 0

        # Buy & Hold karşılaştırması
        bnh_initial_price = df['close'].iloc[start_idx]
        bnh_final_price   = df['close'].iloc[-1]
        bnh_return        = (bnh_final_price - bnh_initial_price) / bnh_initial_price * 100

        # İşlem sayısı (al+sat çiftleri = round trips)
        buy_count     = len(trades_df[trades_df['side'] == 'buy']) if not trades_df.empty else 0
        partial_count = len(trades_df[trades_df['side'] == 'partial_sell']) if not trades_df.empty else 0
        sell_count    = len(trades_df[trades_df['side'] == 'sell']) if not trades_df.empty else 0

        results = {
            'initial_balance':      self.initial_balance,
            'final_balance':        round(final_value, 2),
            'total_return_percent': round(total_return, 2),
            'total_trades':         buy_count + sell_count + partial_count,
            'buy_trades':           buy_count,
            'sell_trades':          sell_count,
            'partial_tp_trades':    partial_count,
            'win_rate':             round(win_rate, 2),
            'avg_win':              round(avg_win, 2),
            'avg_loss':             round(avg_loss, 2),
            'profit_factor':        round(profit_factor, 2) if profit_factor != float('inf') else 'Inf',
            'max_drawdown':         round(max_drawdown, 2),
            'sharpe_ratio':         round(sharpe_ratio, 2),
            'buy_and_hold_return':  round(bnh_return, 2),
            'start_date':           str(df.index[start_idx]),
            'end_date':             str(df.index[-1]),
            'total_candles':        len(df),
            'trades':               trades_df,
            'portfolio_history':    portfolio_df,
        }

        # Logla
        logger.info("")
        logger.info("=" * 60)
        logger.info("📊 BACKTESTING SONUÇLARI")
        logger.info("=" * 60)
        logger.info(f"  Başlangıç Bakiyesi:   ${self.initial_balance:,.2f}")
        logger.info(f"  Son Bakiye:            ${final_value:,.2f}")
        logger.info(f"  Toplam Getiri:         {total_return:+.2f}%")
        logger.info(f"  Buy & Hold Getiri:     {bnh_return:+.2f}%")
        logger.info(f"  ─────────────────────────────────")
        logger.info(f"  Toplam İşlem (Round):  {buy_count} alış / {sell_count} satış / {partial_count} partial")
        logger.info(f"  Kazanma Oranı:         {win_rate:.1f}%")
        logger.info(f"  Ort. Kazanç:           ${avg_win:,.2f}")
        logger.info(f"  Ort. Kayıp:            ${avg_loss:,.2f}")
        logger.info(f"  Profit Factor:         {profit_factor:.2f}" if isinstance(profit_factor, float) else f"  Profit Factor:         {profit_factor}")
        logger.info(f"  Max Drawdown:          {max_drawdown:.2f}%")
        logger.info(f"  Sharpe Ratio:          {sharpe_ratio:.2f}")
        logger.info("=" * 60)

        return results
