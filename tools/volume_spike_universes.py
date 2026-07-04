"""
Volume Spike Hunter — Coin Evreni Karşılaştırması

Soru: Volume Spike Hunter hangi tür coinde en iyi?
  - Large-cap (BTC, ETH, BNB, XRP, SOL): likit ama daha az volatil
  - Mid-cap (ADA, DOT, AVAX, LINK, MATIC): orta volatilite
  - Small-cap (SUI, TIA, INJ, NEAR, FTM, ARB, OP, APT, ATOM, ALGO): high volatil, daha çok spike

Hipotez: Small-cap'te daha çok ve daha büyük hareket olur, ama riski yüksek.

Ek test: en iyi evrende multiplier sweep (3x, 5x, 7x, 10x).
"""
import sys
import os
import argparse
import logging
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np

from data.collector import DataCollector


COMMISSION = 0.001


UNIVERSES = {
    'large_cap (5)':  ['BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'XRP/USDT', 'SOL/USDT'],
    'mid_cap (5)':    ['ADA/USDT', 'DOT/USDT', 'AVAX/USDT', 'LINK/USDT', 'MATIC/USDT'],
    'small_cap (10)': ['SUI/USDT', 'TIA/USDT', 'INJ/USDT', 'NEAR/USDT', 'FTM/USDT',
                       'ARB/USDT', 'OP/USDT', 'APT/USDT', 'ATOM/USDT', 'ALGO/USDT'],
    'all (20)':       ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'BNB/USDT',
                       'ADA/USDT', 'DOT/USDT', 'AVAX/USDT', 'LINK/USDT', 'MATIC/USDT',
                       'ATOM/USDT', 'NEAR/USDT', 'ARB/USDT', 'OP/USDT', 'APT/USDT',
                       'INJ/USDT', 'SUI/USDT', 'TIA/USDT', 'FTM/USDT', 'ALGO/USDT'],
}


def detect_spikes(df: pd.DataFrame, multiplier: float = 5.0,
                  lookback_hours: int = 168) -> pd.Series:
    df = df.copy()
    df['volume_24h'] = df['volume'].rolling(24).sum()
    df['avg_24h_vol'] = df['volume_24h'].rolling(lookback_hours).mean().shift(24)
    df['vol_ratio'] = df['volume_24h'] / df['avg_24h_vol']
    return df['vol_ratio'] >= multiplier


def simulate(df: pd.DataFrame, multiplier: float, hold_hours: int,
             tp_pct: float, sl_pct: float) -> dict:
    if df.empty or len(df) < 200:
        return {'trades': []}
    spikes = detect_spikes(df, multiplier=multiplier)
    trades = []
    last_idx = -1
    for i in range(168, len(df) - hold_hours):
        if last_idx >= 0 and (i - last_idx) < 24:
            continue
        if not spikes.iloc[i]:
            continue
        entry = float(df.iloc[i]['close'])
        if entry <= 0:
            continue
        tp = entry * (1 + tp_pct / 100)
        sl = entry * (1 - sl_pct / 100)
        exit_p = float(df.iloc[i + hold_hours - 1]['close'])
        exit_reason = 'time'
        for j in range(i + 1, min(i + hold_hours, len(df))):
            bar = df.iloc[j]
            if bar['low'] <= sl:
                exit_p = sl; exit_reason = 'SL'; break
            if bar['high'] >= tp:
                exit_p = tp; exit_reason = 'TP'; break
        pnl_pct = (exit_p - entry) / entry * 100 - 2 * COMMISSION * 100
        trades.append({'pnl_pct': pnl_pct, 'reason': exit_reason})
        last_idx = i
    return {'trades': trades}


def aggregate(coin_data: dict, coins: list, mul: float, hh: int, tp: float, sl: float):
    """Birden fazla coin'in sonuçlarını topla."""
    all_trades = []
    for c in coins:
        if c not in coin_data:
            continue
        r = simulate(coin_data[c], mul, hh, tp, sl)
        all_trades.extend(r['trades'])
    if not all_trades:
        return None
    pnls = [t['pnl_pct'] for t in all_trades]
    return {
        'n': len(pnls),
        'avg': np.mean(pnls),
        'win_rate': sum(1 for p in pnls if p > 0) / len(pnls) * 100,
        'best': max(pnls),
        'worst': min(pnls),
        'total': sum(pnls),
        'tp_count': sum(1 for t in all_trades if t['reason'] == 'TP'),
        'sl_count': sum(1 for t in all_trades if t['reason'] == 'SL'),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', default='2022-07-01')
    parser.add_argument('--end', default='2026-05-01')
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format='%(message)s')

    print('═' * 90)
    print('  🌐 VOLUME SPIKE HUNTER — Coin Evreni Karşılaştırması')
    print('  Strateji: sıkı spike (5x mul, 72h hold, TP +20% / SL -10%)')
    print('═' * 90)

    collector = DataCollector()

    # Tüm coinler
    all_coins = sorted(set(c for clist in UNIVERSES.values() for c in clist))

    print(f'\n📥 {len(all_coins)} coin verisi indiriliyor (1h, 4 yıl)...')
    coin_data = {}
    for c in all_coins:
        df = collector.fetch_historical_data(c, '1h', args.start, args.end)
        if not df.empty:
            coin_data[c] = df
            print(f'  ✓ {c}')
        time.sleep(0.05)

    print(f'\n✅ {len(coin_data)} coin yüklendi\n')

    # ─── Test 1: Coin evrenlerini karşılaştır (sıkı 5x) ───
    print('  📊 TEST 1: Coin Evreni Karşılaştırması (5x spike, 72h, +20/-10)')
    print('  ' + '─' * 86)
    print(f'  {"EVREN":<18} {"İŞL":>5} {"WIN %":>7} {"ORT %":>7} {"BEST":>7} {"WORST":>7} {"TP":>4} {"SL":>4} {"TOPLAM %":>10}')
    print('  ' + '─' * 86)

    universe_results = {}
    for uni_name, coins in UNIVERSES.items():
        r = aggregate(coin_data, coins, mul=5.0, hh=72, tp=20, sl=10)
        if r:
            universe_results[uni_name] = r
            print(f'  {uni_name:<18} {r["n"]:>5} {r["win_rate"]:>6.1f}% '
                  f'{r["avg"]:>+6.2f}% {r["best"]:>+6.1f}% {r["worst"]:>+6.1f}% '
                  f'{r["tp_count"]:>4} {r["sl_count"]:>4} {r["total"]:>+9.1f}%')

    # ─── Test 2: En iyi evrende multiplier sweep ───
    if universe_results:
        # En çok toplam %P&L üreten evren
        best_uni = max(universe_results.items(), key=lambda x: x[1]['total'])
        best_uni_name = best_uni[0]
        print()
        print(f'  🏆 EN İYİ EVREN: {best_uni_name} (toplam %{best_uni[1]["total"]:.1f})')
        print()
        print(f'  📊 TEST 2: Multiplier Sweep — {best_uni_name} (72h, +20/-10)')
        print('  ' + '─' * 80)
        print(f'  {"MUL":>5} {"İŞL":>5} {"WIN %":>7} {"ORT %":>7} {"BEST":>7} {"WORST":>7} {"TOPLAM %":>10}')
        print('  ' + '─' * 60)

        best_uni_coins = UNIVERSES[best_uni_name]
        best_mul = None
        best_avg = -999

        for mul in [3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0]:
            r = aggregate(coin_data, best_uni_coins, mul=mul, hh=72, tp=20, sl=10)
            if r and r['n'] >= 10:
                emoji = ''
                if r['avg'] > best_avg:
                    best_avg = r['avg']
                    best_mul = mul
                    emoji = ' ⭐'
                print(f'  {mul:>5.1f}x {r["n"]:>5} {r["win_rate"]:>6.1f}% '
                      f'{r["avg"]:>+6.2f}% {r["best"]:>+6.1f}% {r["worst"]:>+6.1f}% '
                      f'{r["total"]:>+9.1f}%{emoji}')

        # ─── Test 3: TP/SL sweep en iyi multiplier ile ───
        if best_mul:
            print()
            print(f'  📊 TEST 3: TP/SL Sweep — {best_uni_name} ({best_mul}x mul, 72h)')
            print('  ' + '─' * 80)
            print(f'  {"TP/SL":>10} {"İŞL":>5} {"WIN %":>7} {"ORT %":>7} {"TOPLAM %":>10}')
            print('  ' + '─' * 50)

            tp_sl_combos = [
                (15, 8), (20, 10), (25, 12), (30, 15), (40, 20), (50, 25),
            ]
            for tp, sl in tp_sl_combos:
                r = aggregate(coin_data, best_uni_coins, mul=best_mul, hh=72, tp=tp, sl=sl)
                if r and r['n'] >= 10:
                    print(f'  {f"+{tp}/-{sl}":>10} {r["n"]:>5} {r["win_rate"]:>6.1f}% '
                          f'{r["avg"]:>+6.2f}% {r["total"]:>+9.1f}%')

    print()
    print('═' * 90)


if __name__ == '__main__':
    main()
