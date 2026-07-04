"""
Hibrit Portföy Test — DCA + Donchian paralel (20/80, 50/50, 70/30 ve diğerleri)

$1000 sermayeyi DCA ve Donchian'a böl, paralel çalıştır.
Hem 4 yıl hem son 6 ay sonuçları.
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
from bots.dca_bot import DCABot

UNIVERSE_PATH = Path(__file__).parent.parent / 'data' / 'donchian_universe.json'
COMMISSION = 0.001
LARGE_CAP = {'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'XRP/USDT', 'SOL/USDT'}
MID_CAP = {'ADA/USDT', 'DOT/USDT', 'AVAX/USDT', 'LINK/USDT', 'MATIC/USDT'}


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


def donchian_simulation(coin_data: dict, initial_cash: float,
                         position_pct: float = 0.10, max_positions: int = 5) -> float:
    """Donchian sermaye havuzu simülasyonu — final equity döndürür."""
    all_timestamps = set()
    for df in coin_data.values():
        all_timestamps.update(df.index)
    timeline = sorted(all_timestamps)

    cash = initial_cash
    positions = {}

    for ts in timeline:
        # Açık pozisyonları güncelle
        to_close = []
        for sym, pos in list(positions.items()):
            if sym not in coin_data or ts not in coin_data[sym].index:
                continue
            row = coin_data[sym].loc[ts]
            close = float(row['close'])
            low = float(row['low'])
            atr = float(row['atr']) if not pd.isna(row['atr']) else 0
            d_low = float(row['donchian_low']) if not pd.isna(row['donchian_low']) else 0

            slip = get_slippage(sym)
            exit_price = None

            if low <= pos['stop']:
                exit_price = pos['stop'] * (1 - slip)
            elif d_low > 0 and low <= d_low:
                exit_price = d_low * (1 - slip)

            if exit_price:
                revenue = pos['amount'] * exit_price
                fee = revenue * COMMISSION
                cash += (revenue - fee)
                to_close.append(sym)
            else:
                new_stop = close - atr * 4.0
                if new_stop > pos['stop']:
                    pos['stop'] = new_stop

        for sym in to_close:
            del positions[sym]

        # Yeni sinyaller
        for sym, df in coin_data.items():
            if sym in positions or len(positions) >= max_positions:
                continue
            if ts not in df.index:
                continue
            row = df.loc[ts]
            close = float(row['close'])
            high = float(row['high'])
            atr = float(row['atr']) if not pd.isna(row['atr']) else 0
            d_high = float(row['donchian_high']) if not pd.isna(row['donchian_high']) else 0

            if d_high > 0 and atr > 0 and high >= d_high:
                slip = get_slippage(sym)
                entry = d_high * (1 + slip)
                position_value = cash * position_pct
                if position_value < 5 or position_value > cash:
                    continue
                amount = position_value / entry
                fee = position_value * COMMISSION
                cash -= (position_value + fee)
                positions[sym] = {'entry': entry, 'amount': amount,
                                  'stop': entry - atr * 4.0, 'cost': position_value + fee}

    # Son açık pozisyonları kapat
    last_ts = timeline[-1]
    for sym, pos in list(positions.items()):
        if sym in coin_data and last_ts in coin_data[sym].index:
            slip = get_slippage(sym)
            last_close = float(coin_data[sym].loc[last_ts]['close']) * (1 - slip)
            revenue = pos['amount'] * last_close
            fee = revenue * COMMISSION
            cash += (revenue - fee)

    return cash


def dca_simulation(df_btc: pd.DataFrame, initial_cash: float) -> float:
    """DCA BTC backtest — final equity."""
    if df_btc.empty:
        return initial_cash
    bot = DCABot(coins={'BTC/USDT': 1.0}, interval_hours=168, buy_pct_of_capital=0.05)
    out = bot.backtest(df_btc, initial_balance=initial_cash)
    if out['equity_curve'].empty:
        return initial_cash
    return float(out['equity_curve'].iloc[-1])


def run_hybrid_test(donchian_data: dict, btc_data: pd.DataFrame,
                     total_capital: float, dca_pct: float, donchian_pct: float,
                     period_label: str):
    dca_capital = total_capital * dca_pct
    donchian_capital = total_capital * donchian_pct

    final_dca = dca_simulation(btc_data, dca_capital)
    final_donchian = donchian_simulation(donchian_data, donchian_capital)

    final_total = final_dca + final_donchian
    pnl = final_total - total_capital
    pnl_pct = pnl / total_capital * 100

    return {
        'period': period_label,
        'dca_pct': dca_pct,
        'donchian_pct': donchian_pct,
        'dca_initial': dca_capital,
        'dca_final': final_dca,
        'donchian_initial': donchian_capital,
        'donchian_final': final_donchian,
        'total_initial': total_capital,
        'total_final': final_total,
        'pnl': pnl,
        'pnl_pct': pnl_pct,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--capital', type=float, default=1000.0)
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format='%(message)s')

    if not UNIVERSE_PATH.exists():
        print('❌ Universe yok')
        return

    with open(UNIVERSE_PATH) as f:
        universe = json.load(f)
    coins = universe['coins']

    end_date = datetime.now()

    periods = [
        ('Son 6 ay',  end_date - timedelta(days=180)),
        ('Son 12 ay', end_date - timedelta(days=365)),
        ('4 yıl',     datetime(2022, 7, 1)),
    ]

    print('═' * 90)
    print(f'  🎯 HİBRİT PORTFÖY TEST — DCA + Donchian Karışım')
    print(f'  Sermaye: ${args.capital:.0f} | 3 farklı dönem')
    print('═' * 90)

    collector = DataCollector()

    # Tüm coin verisini en uzun dönem için bir kez indir
    print(f'\n📥 Tüm veriler indiriliyor (~10 dk)...')
    longest_start = periods[-1][1]
    fetch_start = longest_start - timedelta(days=60)

    btc_15m = collector.fetch_historical_data('BTC/USDT', '15m',
                                                fetch_start.strftime('%Y-%m-%d'),
                                                end_date.strftime('%Y-%m-%d'))
    print(f'  ✓ BTC 15m: {len(btc_15m):,} mum')

    coin_data_full = {}
    for c in coins:
        try:
            df = collector.fetch_historical_data(c, '1h',
                                                  fetch_start.strftime('%Y-%m-%d'),
                                                  end_date.strftime('%Y-%m-%d'))
            if not df.empty:
                weekly = resample(df, '1W')
                if len(weekly) >= 8:
                    coin_data_full[c] = compute_indicators(weekly, 6, 2)
        except Exception:
            pass
        time.sleep(0.05)
    print(f'  ✓ {len(coin_data_full)} coin (Donchian)\n')

    # 3 dönem × 4 hibrit kombinasyonu
    splits = [
        ('100/0  Pure DCA', 1.0, 0.0),
        ('50/50',           0.5, 0.5),
        ('30/70',           0.3, 0.7),
        ('20/80 (önerin)',  0.2, 0.8),
        ('0/100 Pure Donchian', 0.0, 1.0),
    ]

    for period_label, period_start in periods:
        print(f'  📊 DÖNEM: {period_label} ({period_start.strftime("%Y-%m-%d")} → {end_date.strftime("%Y-%m-%d")})')
        print('  ' + '─' * 80)
        print(f'  {"SPLIT":<25} {"DCA":>10} {"Donchian":>12} {"TOPLAM":>10} {"P&L":>10} {"P&L %":>8}')
        print('  ' + '─' * 78)

        # Dönem'e kırp
        btc_period = btc_15m[period_start:].copy() if not btc_15m.empty else btc_15m
        coin_data_period = {c: df[period_start:].copy() for c, df in coin_data_full.items()}
        coin_data_period = {c: df for c, df in coin_data_period.items() if len(df) >= 5}

        for split_label, dca_pct, donchian_pct in splits:
            r = run_hybrid_test(coin_data_period, btc_period, args.capital, dca_pct, donchian_pct, period_label)
            emoji = '🏆' if r['pnl_pct'] > 50 else ('✅' if r['pnl_pct'] > 0 else ('⚠️' if r['pnl_pct'] > -5 else '❌'))
            print(f'  {emoji} {split_label:<23} ${r["dca_final"]:>8.2f} ${r["donchian_final"]:>10.2f} '
                  f'${r["total_final"]:>8.2f} ${r["pnl"]:>+8.2f} {r["pnl_pct"]:>+6.2f}%')

        print()

    print('═' * 90)


if __name__ == '__main__':
    main()
