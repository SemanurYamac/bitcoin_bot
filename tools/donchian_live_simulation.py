"""
Donchian Bot — En Gelişmiş Live Simulation

Gerçekçi backtest:
  - Universe (34 coin) → data/donchian_universe.json
  - Son 6 ay haftalık veri
  - Tek sermaye havuzu (cash pool)
  - Max N eşzamanlı pozisyon (sermaye dağıtımı)
  - Position sizing: cash × %X her trade'de
  - Slippage + komisyon dahil
  - Compound düzgün (P&L cash'e geri döner)

$1000 başlangıç → son 6 ayda kaç olurdu?
"""
import sys
import os
import argparse
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
import pandas_ta as ta

from data.collector import DataCollector


COMMISSION = 0.001
LARGE_CAP = {'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'XRP/USDT', 'SOL/USDT'}
MID_CAP = {'ADA/USDT', 'DOT/USDT', 'AVAX/USDT', 'LINK/USDT', 'MATIC/USDT'}

UNIVERSE_PATH = Path(__file__).parent.parent / 'data' / 'donchian_universe.json'


def get_slippage(symbol):
    if symbol in LARGE_CAP: return 0.002
    if symbol in MID_CAP: return 0.004
    return 0.007


def resample(df_1h, freq='1W'):
    return df_1h.resample(freq).agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
    }).dropna()


def compute_indicators(df, entry_p=6, exit_p=2):
    df = df.copy()
    df['donchian_high'] = df['high'].rolling(entry_p).max().shift(1)
    df['donchian_low'] = df['low'].rolling(exit_p).min().shift(1)
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    return df


def run_simulation(coin_data: dict, initial_cash: float = 1000.0,
                    entry_p: int = 6, exit_p: int = 2, atr_stop: float = 4.0,
                    position_pct: float = 0.10, max_positions: int = 5,
                    verbose: bool = True) -> dict:
    """
    Realistic time-series simulation.

    coin_data: {symbol: weekly_df_with_indicators}
    """
    # Tüm timestamp'leri birleştir (union of all coin indices)
    all_timestamps = set()
    for df in coin_data.values():
        all_timestamps.update(df.index)
    timeline = sorted(all_timestamps)

    cash = initial_cash
    positions = {}  # symbol → {'entry', 'amount', 'stop'}
    trades = []
    equity_history = []

    for ts in timeline:
        # 1) Açık pozisyonları güncelle (her coin'de o timestamp'te bar varsa)
        to_close = []
        for sym, pos in list(positions.items()):
            if sym not in coin_data or ts not in coin_data[sym].index:
                continue
            row = coin_data[sym].loc[ts]
            close = float(row['close'])
            high = float(row['high'])
            low = float(row['low'])
            atr = float(row['atr']) if not pd.isna(row['atr']) else 0
            d_low = float(row['donchian_low']) if not pd.isna(row['donchian_low']) else 0

            slip = get_slippage(sym)
            exit_price = None
            exit_reason = None

            # Stop-loss
            if low <= pos['stop']:
                exit_price = pos['stop'] * (1 - slip)
                exit_reason = 'SL'
            # Donchian low exit
            elif d_low > 0 and low <= d_low:
                exit_price = d_low * (1 - slip)
                exit_reason = 'donchian'

            if exit_price:
                revenue = pos['amount'] * exit_price
                fee = revenue * COMMISSION
                cash += (revenue - fee)
                pnl = (revenue - fee) - pos['cost']
                trades.append({
                    'ts': ts, 'symbol': sym, 'side': 'sell',
                    'entry': pos['entry'], 'exit': exit_price,
                    'amount': pos['amount'], 'cost': pos['cost'],
                    'revenue': revenue, 'pnl': pnl, 'reason': exit_reason,
                })
                to_close.append(sym)
                if verbose:
                    print(f'  [{ts.strftime("%Y-%m-%d")}] {sym} {exit_reason}: '
                          f'${pos["entry"]:.4f}→${exit_price:.4f} P&L=${pnl:+.2f} cash=${cash:.2f}')
            else:
                # Trailing stop güncelle
                new_stop = close - atr * atr_stop
                if new_stop > pos['stop']:
                    pos['stop'] = new_stop

        for sym in to_close:
            del positions[sym]

        # 2) Yeni sinyalleri tara
        for sym, df in coin_data.items():
            if sym in positions:
                continue
            if len(positions) >= max_positions:
                break
            if ts not in df.index:
                continue
            row = df.loc[ts]
            close = float(row['close'])
            high = float(row['high'])
            atr = float(row['atr']) if not pd.isna(row['atr']) else 0
            d_high = float(row['donchian_high']) if not pd.isna(row['donchian_high']) else 0

            if d_high > 0 and atr > 0 and high >= d_high:
                # Sinyal: pozisyon aç
                slip = get_slippage(sym)
                entry = d_high * (1 + slip)
                position_value = cash * position_pct
                if position_value < 5:
                    continue
                if position_value > cash:
                    continue
                amount = position_value / entry
                fee = position_value * COMMISSION
                cash -= (position_value + fee)

                positions[sym] = {
                    'entry': entry,
                    'amount': amount,
                    'stop': entry - atr * atr_stop,
                    'cost': position_value + fee,
                }
                trades.append({
                    'ts': ts, 'symbol': sym, 'side': 'buy',
                    'entry': entry, 'amount': amount,
                    'cost': position_value + fee, 'pnl': 0,
                })
                if verbose:
                    print(f'  [{ts.strftime("%Y-%m-%d")}] {sym} BUY @ ${entry:.4f} '
                          f'pozisyon=${position_value:.2f} aktifPos={len(positions)}')

        # 3) Equity hesabı
        position_value = 0
        for sym, pos in positions.items():
            if sym in coin_data and ts in coin_data[sym].index:
                last_close = float(coin_data[sym].loc[ts]['close'])
                position_value += pos['amount'] * last_close
        equity_history.append({
            'ts': ts,
            'cash': cash,
            'position_value': position_value,
            'equity': cash + position_value,
            'open_positions': len(positions),
        })

    # Simulation sonu — açık pozisyonları kapat
    if positions:
        last_ts = timeline[-1]
        for sym, pos in list(positions.items()):
            if sym in coin_data and last_ts in coin_data[sym].index:
                slip = get_slippage(sym)
                last_close = float(coin_data[sym].loc[last_ts]['close']) * (1 - slip)
                revenue = pos['amount'] * last_close
                fee = revenue * COMMISSION
                cash += (revenue - fee)
                pnl = (revenue - fee) - pos['cost']
                trades.append({
                    'ts': last_ts, 'symbol': sym, 'side': 'sell',
                    'entry': pos['entry'], 'exit': last_close,
                    'amount': pos['amount'], 'cost': pos['cost'],
                    'revenue': revenue, 'pnl': pnl, 'reason': 'eof',
                })

    return {
        'final_cash': cash,
        'final_equity': equity_history[-1]['equity'] if equity_history else cash,
        'trades': trades,
        'equity_history': equity_history,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--capital', type=float, default=1000.0)
    parser.add_argument('--months', type=int, default=6, help='Geriye dönük kaç ay')
    parser.add_argument('--position-pct', type=float, default=0.10)
    parser.add_argument('--max-positions', type=int, default=5)
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format='%(message)s')

    if not UNIVERSE_PATH.exists():
        print('❌ Universe dosyası yok! Önce şunu çalıştır:')
        print('   python3 tools/donchian_select_universe.py')
        return

    with open(UNIVERSE_PATH) as f:
        universe = json.load(f)
    coins = universe['coins']

    end_date = datetime.now()
    start_date = end_date - timedelta(days=args.months * 30)
    # Indicator warm-up için 60 gün daha geriye git
    fetch_start = start_date - timedelta(days=60)

    print('═' * 90)
    print(f'  🐢 DONCHIAN LIVE SIMULATION — Son {args.months} Ay Test')
    print(f'  Universe: {len(coins)} coin (data/donchian_universe.json)')
    print(f'  Sermaye: ${args.capital:.0f} | Position: %{args.position_pct*100:.0f}/trade | Max poz: {args.max_positions}')
    print(f'  Dönem: {start_date.strftime("%Y-%m-%d")} → {end_date.strftime("%Y-%m-%d")}')
    print('═' * 90)

    collector = DataCollector()
    print(f'\n📥 {len(coins)} coin verisi indiriliyor (warm-up dahil)...')
    coin_data = {}
    for c in coins:
        try:
            df = collector.fetch_historical_data(c, '1h', fetch_start.strftime('%Y-%m-%d'),
                                                  end_date.strftime('%Y-%m-%d'))
            if not df.empty:
                weekly = resample(df, '1W')
                if len(weekly) >= 8:
                    weekly_with_ind = compute_indicators(weekly, entry_p=6, exit_p=2)
                    # Test dönemine kırp
                    coin_data[c] = weekly_with_ind[start_date:]
        except Exception:
            pass
        time.sleep(0.05)
    print(f'  ✅ {len(coin_data)} coin yüklendi\n')

    # Simulation
    print(f'🎬 SIMULATION BAŞLADI...\n')
    result = run_simulation(
        coin_data, initial_cash=args.capital,
        position_pct=args.position_pct, max_positions=args.max_positions,
        verbose=True,
    )

    final = result['final_equity']
    pnl = final - args.capital
    pnl_pct = pnl / args.capital * 100
    monthly_pct = pnl_pct / args.months
    yearly_pct = ((final / args.capital) ** (12 / args.months) - 1) * 100

    print('\n' + '═' * 90)
    print(f'  📊 SIMULATION SONUCU')
    print('═' * 90)
    print(f'  Başlangıç:          ${args.capital:,.2f}')
    print(f'  Final equity:       ${final:,.2f}')
    print(f'  Cash (bitiş):       ${result["final_cash"]:,.2f}')
    print(f'  Açık pozisyon değeri: ${final - result["final_cash"]:,.2f}')
    print(f'  ────────────────────────────────────')
    print(f'  Net P&L:            ${pnl:+,.2f}')
    print(f'  Yüzde:              {pnl_pct:+.2f}%')
    print(f'  Aylık ortalama:     {monthly_pct:+.2f}%/ay')
    print(f'  Yıllık eşdeğer:     {yearly_pct:+.2f}%/yıl')

    # Trade istatistikleri
    sell_trades = [t for t in result['trades'] if t['side'] == 'sell']
    if sell_trades:
        wins = [t for t in sell_trades if t['pnl'] > 0]
        losses = [t for t in sell_trades if t['pnl'] < 0]
        print(f'\n  Toplam işlem:       {len(sell_trades)}')
        print(f'  Kazanan:            {len(wins)} ({len(wins)/len(sell_trades)*100:.1f}%)')
        print(f'  Kaybeden:           {len(losses)}')
        if wins:
            print(f'  Ort kazanç:         ${np.mean([t["pnl"] for t in wins]):+.2f}')
        if losses:
            print(f'  Ort kayıp:          ${np.mean([t["pnl"] for t in losses]):+.2f}')

        # En iyi / en kötü trade
        best_trade = max(sell_trades, key=lambda t: t['pnl'])
        worst_trade = min(sell_trades, key=lambda t: t['pnl'])
        print(f'\n  🏆 En iyi trade: {best_trade["symbol"]} ${best_trade["pnl"]:+.2f}')
        print(f'  💀 En kötü trade: {worst_trade["symbol"]} ${worst_trade["pnl"]:+.2f}')

    # Equity drawdown
    if result['equity_history']:
        eq_df = pd.DataFrame(result['equity_history'])
        eq_df['peak'] = eq_df['equity'].cummax()
        eq_df['dd'] = (eq_df['equity'] - eq_df['peak']) / eq_df['peak'] * 100
        max_dd = eq_df['dd'].min()
        print(f'\n  Max Drawdown: {max_dd:.2f}%')

    print('═' * 90)


if __name__ == '__main__':
    main()
