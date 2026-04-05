"""
Bitcoin Trading Bot - Backtesting Motoru
Geçmiş veriler üzerinde strateji simülasyonu yapar.
"""
import pandas as pd
import numpy as np
import logging
from datetime import datetime
from analysis.indicators import TechnicalIndicators
from strategy.signals import SignalGenerator
from trading.risk_manager import RiskManager
from config.settings import BACKTEST_INITIAL_BALANCE, EMA_LONG

logger = logging.getLogger(__name__)


class BacktestEngine:
    """Geçmiş veriler üzerinde strateji simülasyonu yapar."""

    def __init__(self, initial_balance=None):
        self.initial_balance = initial_balance or BACKTEST_INITIAL_BALANCE
        self.signal_generator = SignalGenerator()

    def run(self, df, verbose=False):
        """
        Backtesting çalıştırır.

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
        logger.info("=" * 60)

        # Göstergeleri hesapla
        df = TechnicalIndicators.calculate_all(df)

        # Risk yöneticisi
        risk_manager = RiskManager(self.initial_balance)
        balance = self.initial_balance
        btc_holding = 0.0

        # Sonuç izleme
        trades = []
        portfolio_history = []
        signals_log = []

        # EMA_LONG periyodu kadar bekle (göstergelerin oluşması için)
        start_idx = max(EMA_LONG + 10, 201)

        for i in range(start_idx, len(df)):
            current_price = df['close'].iloc[i]
            current_time = df.index[i]

            # Portföy değerini hesapla
            total_value = balance + (btc_holding * current_price)
            risk_manager.update_peak_balance(total_value)

            portfolio_history.append({
                'timestamp': current_time,
                'balance': balance,
                'btc_holding': btc_holding,
                'btc_price': current_price,
                'total_value': total_value,
            })

            # Aktif pozisyon varsa çıkış kontrol et
            if risk_manager.active_position is not None:
                should_exit, exit_reason = risk_manager.check_exit_conditions(current_price)

                if should_exit:
                    # Pozisyonu kapat
                    result = risk_manager.close_position(current_price)
                    if result:
                        balance += result['exit_price'] * result['amount'] - result['fee']
                        btc_holding -= result['amount']

                        trades.append({
                            'timestamp': current_time,
                            'side': 'sell',
                            'price': result['exit_price'],
                            'amount': result['amount'],
                            'cost': result['exit_price'] * result['amount'],
                            'pnl': result['net_pnl'],
                            'reason': exit_reason,
                        })

                        if verbose:
                            emoji = '✅' if result['net_pnl'] > 0 else '❌'
                            logger.info(
                                f"{emoji} [{current_time}] SATIŞ - {exit_reason} | "
                                f"PnL: ${result['net_pnl']:+,.2f} ({result['pnl_percent']:+.2f}%)"
                            )
                continue  # Bu mumda başka işlem yapma, sonraki muma geç

            # Sinyal üret
            signal_result = self.signal_generator.generate_signal(df, index=i)
            signals_log.append({
                'timestamp': current_time,
                'signal': signal_result['signal'],
                'score': signal_result['score'],
                'price': current_price,
            })

            if signal_result['signal'] == 'BUY':
                # Pozisyon açılabilir mi kontrol et
                can_open, reason = risk_manager.can_open_position(balance, signal_result)

                if can_open:
                    # Pozisyon boyutunu hesapla
                    position = risk_manager.calculate_position_size(balance, current_price)
                    amount = position['btc_amount']
                    cost = position['usdt_amount']
                    fee = cost * 0.001  # %0.1 komisyon

                    # Alım emri simüle et
                    balance -= (cost + fee)
                    btc_holding += amount

                    risk_manager.open_position('buy', current_price, amount,
                                                open_time=current_time)

                    trades.append({
                        'timestamp': current_time,
                        'side': 'buy',
                        'price': current_price,
                        'amount': amount,
                        'cost': cost,
                        'pnl': 0,
                        'reason': '; '.join(signal_result['reasons'][:3]),
                    })

                    if verbose:
                        logger.info(
                            f"🟢 [{current_time}] ALIŞ @ ${current_price:,.2f} | "
                            f"{amount:.6f} BTC | Maliyet: ${cost:,.2f}"
                        )

            elif signal_result['signal'] == 'SELL' and btc_holding > 0:
                # Tüm pozisyonu kapat
                if risk_manager.active_position:
                    result = risk_manager.close_position(current_price)
                    if result:
                        balance += result['exit_price'] * result['amount'] - result['fee']
                        btc_holding -= result['amount']

                        trades.append({
                            'timestamp': current_time,
                            'side': 'sell',
                            'price': current_price,
                            'amount': result['amount'],
                            'cost': result['exit_price'] * result['amount'],
                            'pnl': result['net_pnl'],
                            'reason': '; '.join(signal_result['reasons'][:3]),
                        })

                        if verbose:
                            emoji = '✅' if result['net_pnl'] > 0 else '❌'
                            logger.info(
                                f"{emoji} [{current_time}] SATIŞ (Sinyal) @ ${current_price:,.2f} | "
                                f"PnL: ${result['net_pnl']:+,.2f}"
                            )

        # Son açık pozisyonu kapat
        if btc_holding > 0:
            final_price = df['close'].iloc[-1]
            balance += btc_holding * final_price
            btc_holding = 0

        # ─── Performans Metrikleri ─────────────────────────────
        final_value = balance
        total_return = (final_value - self.initial_balance) / self.initial_balance * 100

        trades_df = pd.DataFrame(trades)
        portfolio_df = pd.DataFrame(portfolio_history)

        # Kazanç/kayıp istatistikleri
        if not trades_df.empty:
            sell_trades = trades_df[trades_df['side'] == 'sell']
            winning_trades = sell_trades[sell_trades['pnl'] > 0]
            losing_trades = sell_trades[sell_trades['pnl'] < 0]
            win_rate = len(winning_trades) / len(sell_trades) * 100 if len(sell_trades) > 0 else 0

            avg_win = winning_trades['pnl'].mean() if len(winning_trades) > 0 else 0
            avg_loss = abs(losing_trades['pnl'].mean()) if len(losing_trades) > 0 else 0
            profit_factor = (winning_trades['pnl'].sum() / abs(losing_trades['pnl'].sum())
                           if len(losing_trades) > 0 and losing_trades['pnl'].sum() != 0
                           else float('inf'))
        else:
            win_rate = 0
            avg_win = 0
            avg_loss = 0
            profit_factor = 0

        # Max drawdown
        if not portfolio_df.empty:
            portfolio_df['peak'] = portfolio_df['total_value'].cummax()
            portfolio_df['drawdown'] = (portfolio_df['peak'] - portfolio_df['total_value']) / portfolio_df['peak']
            max_drawdown = portfolio_df['drawdown'].max() * 100
        else:
            max_drawdown = 0

        # Sharpe Ratio (basitleştirilmiş)
        if not portfolio_df.empty and len(portfolio_df) > 1:
            returns = portfolio_df['total_value'].pct_change().dropna()
            sharpe_ratio = (returns.mean() / returns.std() * np.sqrt(365 * 24)
                          if returns.std() > 0 else 0)
        else:
            sharpe_ratio = 0

        # Buy & Hold karşılaştırması
        bnh_initial_price = df['close'].iloc[start_idx]
        bnh_final_price = df['close'].iloc[-1]
        bnh_return = (bnh_final_price - bnh_initial_price) / bnh_initial_price * 100

        results = {
            'initial_balance': self.initial_balance,
            'final_balance': round(final_value, 2),
            'total_return_percent': round(total_return, 2),
            'total_trades': len(trades),
            'buy_trades': len(trades_df[trades_df['side'] == 'buy']) if not trades_df.empty else 0,
            'sell_trades': len(trades_df[trades_df['side'] == 'sell']) if not trades_df.empty else 0,
            'win_rate': round(win_rate, 2),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'profit_factor': round(profit_factor, 2) if profit_factor != float('inf') else 'Inf',
            'max_drawdown': round(max_drawdown, 2),
            'sharpe_ratio': round(sharpe_ratio, 2),
            'buy_and_hold_return': round(bnh_return, 2),
            'start_date': str(df.index[start_idx]),
            'end_date': str(df.index[-1]),
            'total_candles': len(df),
            'trades': trades_df,
            'portfolio_history': portfolio_df,
            'signals': pd.DataFrame(signals_log),
        }

        # Sonuçları logla
        logger.info("")
        logger.info("=" * 60)
        logger.info("📊 BACKTESTING SONUÇLARI")
        logger.info("=" * 60)
        logger.info(f"  Başlangıç Bakiyesi:   ${self.initial_balance:,.2f}")
        logger.info(f"  Son Bakiye:            ${final_value:,.2f}")
        logger.info(f"  Toplam Getiri:         {total_return:+.2f}%")
        logger.info(f"  Buy & Hold Getiri:     {bnh_return:+.2f}%")
        logger.info(f"  ─────────────────────────────────")
        logger.info(f"  Toplam İşlem:          {len(trades)}")
        logger.info(f"  Kazanma Oranı:         {win_rate:.1f}%")
        logger.info(f"  Ort. Kazanç:           ${avg_win:,.2f}")
        logger.info(f"  Ort. Kayıp:            ${avg_loss:,.2f}")
        logger.info(f"  Profit Factor:         {profit_factor:.2f}" if isinstance(profit_factor, float) else f"  Profit Factor:         {profit_factor}")
        logger.info(f"  Max Drawdown:          {max_drawdown:.2f}%")
        logger.info(f"  Sharpe Ratio:          {sharpe_ratio:.2f}")
        logger.info("=" * 60)

        return results
