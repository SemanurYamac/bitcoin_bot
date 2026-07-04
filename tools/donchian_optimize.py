"""
Donchian Optimize — Timeframe + Parametre Sweep

Test boyutları:
  1. Timeframe: 4h, 1d, 1w
  2. Entry/Exit period grid (timeframe-bağımlı)
  3. ATR stop loss multiplier sweep
  4. Coin evreni karşılaştırması

Mevcut başlangıç: Daily 40/15 → +%85 yıllık
Hedef: optimum konfigürasyonu bul
"""
import sys
import os
import argparse
import logging
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
import pandas_ta as ta

from data.collector import DataCollector


COMMISSION = 0.001
LARGE_CAP = {'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'XRP/USDT', 'SOL/USDT'}
MID_CAP = {'ADA/USDT', 'DOT/USDT', 'AVAX/USDT', 'LINK/USDT', 'MATIC/USDT'}


def get_slippage(symbol):
    if symbol in LARGE_CAP: return 0.002
    if symbol in MID_CAP: return 0.004
    return 0.007


def resample(df_1h, freq):
    """1h → herhangi bir TF'ye resample."""
    return df_1h.resample(freq).agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
    }).dropna()


def simulate(df, symbol, entry_p, exit_p, atr_stop_mult=2.0):
    if df.empty or len(df) < entry_p + 30:
        return []
    df = df.copy()
    df['donchian_high'] = df['high'].rolling(entry_p).max().shift(1)
    df['donchian_low'] = df['low'].rolling(exit_p).min().shift(1)
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    slip = get_slippage(symbol)
    trades = []
    pos = None

    for i in range(entry_p + 15, len(df)):
        row = df.iloc[i]
        close = float(row['close'])
        high = float(row['high'])
        low = float(row['low'])
        atr = float(row['atr']) if not pd.isna(row['atr']) else 0
        d_high = float(row['donchian_high']) if not pd.isna(row['donchian_high']) else 0
        d_low = float(row['donchian_low']) if not pd.isna(row['donchian_low']) else 0

        if pos is not None:
            if low <= pos['stop']:
                exit_p_val = pos['stop'] * (1 - slip)
                pnl = (exit_p_val - pos['entry']) / pos['entry'] * 100 - 0.2
                trades.append(pnl)
                pos = None
                continue
            if low <= d_low and d_low > 0:
                exit_p_val = d_low * (1 - slip)
                pnl = (exit_p_val - pos['entry']) / pos['entry'] * 100 - 0.2
                trades.append(pnl)
                pos = None
                continue
            new_stop = close - atr * atr_stop_mult
            if new_stop > pos['stop']:
                pos['stop'] = new_stop

        if pos is None and high >= d_high and d_high > 0 and atr > 0:
            entry = d_high * (1 + slip)
            pos = {'entry': entry, 'stop': entry - atr * atr_stop_mult}

    if pos is not None:
        last_close = float(df.iloc[-1]['close']) * (1 - slip)
        pnl = (last_close - pos['entry']) / pos['entry'] * 100 - 0.2
        trades.append(pnl)

    return trades


def aggregate(coin_data, coins, entry_p, exit_p, atr_mult=2.0):
    all_trades = []
    for c in coins:
        if c not in coin_data:
            continue
        all_trades.extend(simulate(coin_data[c], c, entry_p, exit_p, atr_mult))
    if not all_trades:
        return None
    return {
        'n': len(all_trades),
        'avg': np.mean(all_trades),
        'win_rate': sum(1 for p in all_trades if p > 0) / len(all_trades) * 100,
        'best': max(all_trades),
        'worst': min(all_trades),
        'total': sum(all_trades),
    }


def compound_yearly(avg_pct, n_trades, years, position_pct=0.30):
    avg_per = 1 + avg_pct / 100
    effective = (1 - position_pct) + position_pct * avg_per
    final = effective ** n_trades
    if final <= 0:
        return -100
    return (final ** (1/years) - 1) * 100


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', default='2022-07-01')
    parser.add_argument('--end', default='2026-05-01')
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format='%(message)s')

    coins = [
        'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'BNB/USDT',
        'ADA/USDT', 'DOT/USDT', 'AVAX/USDT', 'LINK/USDT', 'MATIC/USDT',
        'ATOM/USDT', 'NEAR/USDT', 'ARB/USDT', 'OP/USDT', 'APT/USDT',
        'INJ/USDT', 'SUI/USDT', 'TIA/USDT', 'FTM/USDT', 'ALGO/USDT',
    ]

    print('═' * 90)
    print('  🐢 DONCHIAN OPTİMİZASYON — Timeframe + Parametre Sweep')
    print('═' * 90)

    collector = DataCollector()
    print(f'\n📥 {len(coins)} coin verisi indiriliyor (1h base)...')
    raw_data = {}
    for c in coins:
        df = collector.fetch_historical_data(c, '1h', args.start, args.end)
        if not df.empty:
            raw_data[c] = df
        time.sleep(0.05)
    print(f'✅ {len(raw_data)} coin yüklendi\n')

    years = (pd.to_datetime(args.end) - pd.to_datetime(args.start)).days / 365.25

    # ════════════════════════════════════════════════════════════════
    # TEST 1: Timeframe Sweep (sabit ratio entry:exit ≈ 40:15 ≈ 2.7:1)
    # ════════════════════════════════════════════════════════════════
    print('  📊 TEST 1: TIMEFRAME SWEEP (entry:exit ≈ 40:15 oran)')
    print('  ' + '─' * 80)
    print(f'  {"TF":<5} {"Entry":>5} {"Exit":>5} {"İŞL":>5} {"WIN %":>7} {"ORT %":>8} {"TOPLAM %":>10} {"YILLIK":>9}')
    print('  ' + '─' * 80)

    timeframes = [
        ('1h',  '1h',  960, 360),  # 40 gün × 24 / 15 gün × 24 (1h)
        ('4h',  '4h',  240, 90),   # 40 × 6 / 15 × 6 (4h)
        ('1d',  '1D',  40,  15),   # mevcut
        ('1w',  '1W',  6,   2),    # 6 hafta entry / 2 hafta exit
    ]

    tf_results = {}
    for tf_label, freq, ep, exp in timeframes:
        # Resample
        coin_data = {c: resample(df, freq) for c, df in raw_data.items()}
        r = aggregate(coin_data, coins, ep, exp)
        if not r:
            continue
        yearly = compound_yearly(r['avg'], r['n'], years)
        tf_results[tf_label] = {**r, 'yearly': yearly, 'ep': ep, 'exp': exp, 'freq': freq}
        print(f'  {tf_label:<5} {ep:>5} {exp:>5} {r["n"]:>5} {r["win_rate"]:>6.1f}% '
              f'{r["avg"]:>+7.2f}% {r["total"]:>+9.1f}% {yearly:>+8.1f}%')

    # En iyi timeframe
    best_tf = max(tf_results.items(), key=lambda x: x[1]['yearly'])
    best_tf_label = best_tf[0]
    best_freq = best_tf[1]['freq']
    print(f'\n  🏆 En iyi timeframe: {best_tf_label} (yıllık +%{best_tf[1]["yearly"]:.1f})')

    # ════════════════════════════════════════════════════════════════
    # TEST 2: En iyi TF'de Entry/Exit Period Grid
    # ════════════════════════════════════════════════════════════════
    coin_data = {c: resample(df, best_freq) for c, df in raw_data.items()}

    if best_tf_label == '1d':
        entry_options = [15, 20, 25, 30, 40, 55, 80, 100]
        exit_options = [5, 7, 10, 15, 20]
    elif best_tf_label == '4h':
        entry_options = [60, 90, 120, 180, 240, 360]
        exit_options = [30, 45, 60, 90]
    elif best_tf_label == '1h':
        entry_options = [240, 480, 720, 960, 1440]
        exit_options = [120, 240, 360]
    else:  # 1w
        entry_options = [3, 4, 6, 8, 12]
        exit_options = [1, 2, 3]

    print(f'\n  📊 TEST 2: ENTRY/EXIT GRID — {best_tf_label}')
    print('  ' + '─' * 70)
    print(f'  {"Entry":>5} {"Exit":>5} {"İŞL":>5} {"WIN %":>7} {"ORT %":>8} {"YILLIK":>9}')
    print('  ' + '─' * 70)

    grid_results = []
    for ep in entry_options:
        for exp in exit_options:
            if exp >= ep:
                continue
            r = aggregate(coin_data, coins, ep, exp)
            if not r or r['n'] < 30:
                continue
            yearly = compound_yearly(r['avg'], r['n'], years)
            grid_results.append({**r, 'ep': ep, 'exp': exp, 'yearly': yearly})

    # En iyi 5'i göster
    grid_results.sort(key=lambda x: x['yearly'], reverse=True)
    for r in grid_results[:7]:
        print(f'  {r["ep"]:>5} {r["exp"]:>5} {r["n"]:>5} {r["win_rate"]:>6.1f}% '
              f'{r["avg"]:>+7.2f}% {r["yearly"]:>+8.1f}%')

    if not grid_results:
        print('  Yetersiz işlem')
        return

    best_grid = grid_results[0]
    print(f'\n  🏆 En iyi grid: Entry={best_grid["ep"]} Exit={best_grid["exp"]} (yıllık +%{best_grid["yearly"]:.1f})')

    # ════════════════════════════════════════════════════════════════
    # TEST 3: ATR Stop Multiplier Sweep
    # ════════════════════════════════════════════════════════════════
    print(f'\n  📊 TEST 3: ATR STOP SWEEP — {best_tf_label}, entry={best_grid["ep"]}, exit={best_grid["exp"]}')
    print('  ' + '─' * 70)
    print(f'  {"ATR":>5} {"İŞL":>5} {"WIN %":>7} {"ORT %":>8} {"WORST":>8} {"YILLIK":>9}')
    print('  ' + '─' * 70)

    atr_results = []
    for atr_m in [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]:
        r = aggregate(coin_data, coins, best_grid['ep'], best_grid['exp'], atr_mult=atr_m)
        if not r or r['n'] < 20:
            continue
        yearly = compound_yearly(r['avg'], r['n'], years)
        atr_results.append({**r, 'atr_m': atr_m, 'yearly': yearly})
        print(f'  {atr_m:>5.1f} {r["n"]:>5} {r["win_rate"]:>6.1f}% '
              f'{r["avg"]:>+7.2f}% {r["worst"]:>+7.1f}% {yearly:>+8.1f}%')

    if atr_results:
        best_atr = max(atr_results, key=lambda x: x['yearly'])
        print(f'\n  🏆 En iyi ATR: {best_atr["atr_m"]} (yıllık +%{best_atr["yearly"]:.1f})')

    # ════════════════════════════════════════════════════════════════
    # FINAL: En iyi konfigürasyon × Coin evreni
    # ════════════════════════════════════════════════════════════════
    if atr_results:
        best_atr_m = max(atr_results, key=lambda x: x['yearly'])['atr_m']

        print(f'\n  📊 TEST 4: COIN EVRENİ — TF={best_tf_label}, '
              f'entry={best_grid["ep"]}, exit={best_grid["exp"]}, ATR={best_atr_m}')
        print('  ' + '─' * 70)

        universes = {
            'large_cap (5)':  list(LARGE_CAP),
            'mid_cap (5)':    list(MID_CAP),
            'small_cap (10)': [c for c in coins if c not in LARGE_CAP and c not in MID_CAP],
            'all (20)':       coins,
        }

        for uni_name, uni_coins in universes.items():
            r = aggregate(coin_data, uni_coins, best_grid['ep'], best_grid['exp'], atr_mult=best_atr_m)
            if not r or r['n'] < 5:
                continue
            yearly = compound_yearly(r['avg'], r['n'], years)
            print(f'  {uni_name:<18} {r["n"]:>5} {r["win_rate"]:>6.1f}% '
                  f'{r["avg"]:>+7.2f}% YIL: {yearly:>+7.1f}%')

    print()
    print('═' * 90)


if __name__ == '__main__':
    main()
