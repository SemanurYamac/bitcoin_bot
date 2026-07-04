"""
Çoklu Coin Karşılaştırması — aynı sermayeyi tek coin (BTC) vs çoklu coin'e
yayma karşılaştırması.

Soru: $1000'i sadece BTC'de mi, yoksa BTC+ETH+SOL'e (eşit dağıtarak) mu?

Mantık:
    Her coin için aynı 40/40/20 portföy stratejisi koşar.
    Tek-coin: $1000 hepsi BTC'de
    3-coin:   $333 BTC + $333 ETH + $333 SOL
    5-coin:   $200 her birine

Kullanım:
    python3 tools/multicoin_simulation.py --capital 1000
"""
import sys
import os
import argparse
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from data.collector import DataCollector
from bots.dca_bot import DCABot
from bots.grid_bot import GridBot
from bots.trend_bot import TrendBot


def simulate_one_coin(df: pd.DataFrame, symbol: str, capital: float,
                       weights: dict) -> dict:
    """Tek coin üzerinde 40/40/20 portföy backtest."""
    if df.empty or len(df) < 250:
        return {'symbol': symbol, 'initial': capital, 'final': capital, 'pnl_pct': 0,
                'dca_pnl': 0, 'grid_pnl': 0, 'trend_pnl': 0, 'error': 'data yok'}

    dca_cap = capital * weights['dca']
    grid_cap = capital * weights['grid']
    trend_cap = capital * weights['trend']

    dca_final = dca_cap
    if dca_cap > 0:
        out = DCABot(coins={symbol: 1.0}, interval_hours=168, buy_pct_of_capital=0.05).backtest(df, dca_cap)
        if not out['equity_curve'].empty:
            dca_final = float(out['equity_curve'].iloc[-1])

    grid_final = grid_cap
    if grid_cap > 0:
        out = GridBot(symbol=symbol, n_grids=15, range_lookback=480).backtest(df, grid_cap)
        if not out['equity_curve'].empty:
            grid_final = float(out['equity_curve'].iloc[-1])

    trend_final = trend_cap
    if trend_cap > 0:
        out = TrendBot(symbol=symbol, risk_per_trade=0.05).backtest(df, trend_cap)
        if not out['equity_curve'].empty:
            trend_final = float(out['equity_curve'].iloc[-1])

    final = dca_final + grid_final + trend_final
    return {
        'symbol': symbol,
        'initial': capital,
        'final': final,
        'pnl_pct': (final - capital) / capital * 100 if capital > 0 else 0,
        'dca_pnl': (dca_final - dca_cap) / dca_cap * 100 if dca_cap > 0 else 0,
        'grid_pnl': (grid_final - grid_cap) / grid_cap * 100 if grid_cap > 0 else 0,
        'trend_pnl': (trend_final - trend_cap) / trend_cap * 100 if trend_cap > 0 else 0,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--capital', type=float, default=1000.0)
    parser.add_argument('--start', default='2022-07-01')
    parser.add_argument('--end', default='2026-05-01')
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format='%(message)s')

    weights = {'dca': 0.40, 'grid': 0.40, 'trend': 0.20}
    coin_sets = {
        '1 coin (sadece BTC)':         ['BTC/USDT'],
        '2 coin (BTC + ETH)':           ['BTC/USDT', 'ETH/USDT'],
        '3 coin (BTC + ETH + SOL)':     ['BTC/USDT', 'ETH/USDT', 'SOL/USDT'],
        '5 coin (BTC+ETH+SOL+XRP+BNB)': ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'BNB/USDT'],
    }

    print('═' * 78)
    print(f'  🌐 ÇOKLU COIN ANALİZİ — ${args.capital:.0f} sermaye, 40/40/20 portföy')
    print(f'  Dönem: {args.start} → {args.end} (~46 ay)')
    print('═' * 78)

    # Tüm coinleri tek sefer indir
    collector = DataCollector()
    all_coins = set()
    for c_list in coin_sets.values():
        all_coins.update(c_list)

    print(f'\n📥 {len(all_coins)} coin verisi indiriliyor...')
    dfs = {}
    for c in sorted(all_coins):
        print(f'  {c}...', end=' ', flush=True)
        df = collector.fetch_historical_data(c, '15m', args.start, args.end)
        dfs[c] = df
        print(f'{len(df):,} mum')
    print()

    print(f'{"SETUP":<35} {"BAŞLANGIÇ":>10} {"FINAL":>12} {"P&L%":>9} {"AYLIK%":>8}')
    print('─' * 78)

    results_summary = []

    for setup_name, coins in coin_sets.items():
        per_coin = args.capital / len(coins)
        coin_results = []
        total_final = 0
        for c in coins:
            r = simulate_one_coin(dfs[c], c, per_coin, weights)
            coin_results.append(r)
            total_final += r['final']

        total_pnl_pct = (total_final - args.capital) / args.capital * 100
        monthly_pct = total_pnl_pct / 46
        results_summary.append({
            'setup': setup_name,
            'final': total_final,
            'pnl_pct': total_pnl_pct,
            'monthly_pct': monthly_pct,
            'coins': coin_results,
        })

        print(f'{setup_name:<35} ${args.capital:>8.0f}   ${total_final:>9.2f}   {total_pnl_pct:>+7.2f}%  {monthly_pct:>+6.2f}%')

    # Detaylı per-coin breakdown
    print()
    print('  COIN BAŞINA DETAY (DCA / Grid / Trend P&L%):')
    print()
    for setup in results_summary:
        print(f'  📊 {setup["setup"]}:')
        for cr in setup['coins']:
            if 'error' not in cr:
                print(f'    {cr["symbol"]:<10} ${cr["initial"]:>6.0f} → ${cr["final"]:>7.2f}  '
                      f'({cr["pnl_pct"]:>+6.2f}%)  '
                      f'[DCA {cr["dca_pnl"]:>+6.1f}% | Grid {cr["grid_pnl"]:>+6.1f}% | Trend {cr["trend_pnl"]:>+6.1f}%]')
            else:
                print(f'    {cr["symbol"]:<10} {cr["error"]}')
        print()

    print('═' * 78)


if __name__ == '__main__':
    main()
