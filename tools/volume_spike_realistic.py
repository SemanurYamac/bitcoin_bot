"""
Volume Spike Hunter — GERÇEKÇİ Slippage'lı Backtest

Coin tipine göre farklı slippage:
    Large-cap (BTC, ETH, BNB, XRP, SOL): %0.2 (likit)
    Mid-cap   (ADA, DOT, AVAX, LINK, MATIC): %0.4
    Small-cap (geri kalan): %0.7

Slippage modeli:
    Entry:    market buy → fiyatın %X üstünden alır
    TP exit:  limit sell + kuyruk → TP fiyatının %X altından alır
    SL exit:  market sell → SL fiyatının %X altından satar
    Komisyon: %0.1 × 2 = %0.2 (zaten dahil)

Toplam haircut per trade: ~%0.6-1.6 (coin tipine göre)

3 senaryo karşılaştırması:
    🟢 No-slip (eski) — referans
    🟡 Realistic    — yukarıdaki tier'lar
    🔴 Pessimistic  — 2x slippage (yüksek volatilite peak)
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


# Coin tipine göre slippage tier (her bir leg için, % cinsinden)
SLIPPAGE_TIERS = {
    'large': 0.002,  # %0.2
    'mid':   0.004,  # %0.4
    'small': 0.007,  # %0.7
}

LARGE_CAP = {'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'XRP/USDT', 'SOL/USDT'}
MID_CAP = {'ADA/USDT', 'DOT/USDT', 'AVAX/USDT', 'LINK/USDT', 'MATIC/USDT'}


def get_slippage(symbol: str, multiplier: float = 1.0) -> float:
    """Coin tipine göre slippage döndürür (× multiplier ile pessimist senaryosu için)."""
    if symbol in LARGE_CAP:
        return SLIPPAGE_TIERS['large'] * multiplier
    if symbol in MID_CAP:
        return SLIPPAGE_TIERS['mid'] * multiplier
    return SLIPPAGE_TIERS['small'] * multiplier


def detect_spikes(df: pd.DataFrame, multiplier: float = 5.0,
                  lookback_hours: int = 168) -> pd.Series:
    df = df.copy()
    df['volume_24h'] = df['volume'].rolling(24).sum()
    df['avg_24h_vol'] = df['volume_24h'].rolling(lookback_hours).mean().shift(24)
    df['vol_ratio'] = df['volume_24h'] / df['avg_24h_vol']
    return df['vol_ratio'] >= multiplier


def simulate_with_slippage(df: pd.DataFrame, symbol: str,
                            multiplier: float, hold_hours: int,
                            tp_pct: float, sl_pct: float,
                            slippage_mode: str = 'realistic') -> dict:
    """
    slippage_mode: 'none', 'realistic', 'pessimistic'
    """
    if df.empty or len(df) < 200:
        return {'trades': []}

    if slippage_mode == 'none':
        slip = 0.0
    elif slippage_mode == 'realistic':
        slip = get_slippage(symbol, 1.0)
    else:  # pessimistic
        slip = get_slippage(symbol, 2.0)

    spikes = detect_spikes(df, multiplier=multiplier)
    trades = []
    last_idx = -1

    for i in range(168, len(df) - hold_hours):
        if last_idx >= 0 and (i - last_idx) < 24:
            continue
        if not spikes.iloc[i]:
            continue

        # Entry — market buy, fiyatın %slip üstünden alır
        raw_entry = float(df.iloc[i]['close'])
        if raw_entry <= 0:
            continue
        entry = raw_entry * (1 + slip)

        tp = entry * (1 + tp_pct / 100)
        sl = entry * (1 - sl_pct / 100)

        exit_p = float(df.iloc[i + hold_hours - 1]['close']) * (1 - slip)
        exit_reason = 'time'
        for j in range(i + 1, min(i + hold_hours, len(df))):
            bar = df.iloc[j]
            if bar['low'] <= sl:
                # SL hit — market sell, fiyatın %slip altından
                exit_p = sl * (1 - slip)
                exit_reason = 'SL'
                break
            if bar['high'] >= tp:
                # TP hit — limit sell + kuyruk → TP'nin %slip altından
                exit_p = tp * (1 - slip)
                exit_reason = 'TP'
                break

        # Komisyon
        pnl_pct = (exit_p - entry) / entry * 100 - 2 * COMMISSION * 100
        trades.append({'pnl_pct': pnl_pct, 'reason': exit_reason})
        last_idx = i

    return {'trades': trades}


def aggregate(coin_data: dict, coins: list, mul: float, hh: int,
              tp: float, sl: float, slip_mode: str):
    all_trades = []
    for c in coins:
        if c not in coin_data:
            continue
        r = simulate_with_slippage(coin_data[c], c, mul, hh, tp, sl, slip_mode)
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
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', default='2022-07-01')
    parser.add_argument('--end', default='2026-05-01')
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format='%(message)s')

    print('═' * 90)
    print('  🌐 VOLUME SPIKE HUNTER — Gerçekçi Slippage Modeli')
    print('  Slippage tiers: Large %0.2 | Mid %0.4 | Small %0.7 (her leg için)')
    print('═' * 90)

    coins_all = [
        'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'BNB/USDT',
        'ADA/USDT', 'DOT/USDT', 'AVAX/USDT', 'LINK/USDT', 'MATIC/USDT',
        'ATOM/USDT', 'NEAR/USDT', 'ARB/USDT', 'OP/USDT', 'APT/USDT',
        'INJ/USDT', 'SUI/USDT', 'TIA/USDT', 'FTM/USDT', 'ALGO/USDT',
    ]

    collector = DataCollector()
    print(f'\n📥 {len(coins_all)} coin verisi indiriliyor...')
    coin_data = {}
    for c in coins_all:
        df = collector.fetch_historical_data(c, '1h', args.start, args.end)
        if not df.empty:
            coin_data[c] = df
            print(f'  ✓ {c}')
        time.sleep(0.05)
    print(f'\n✅ {len(coin_data)} coin yüklendi\n')

    # 2 ana strateji × 3 slippage senaryosu
    strategies = [
        ('Sürekli Aktif (4x)',  4.0, 72, 20, 10),
        ('Yüksek Kalite (6x)',  6.0, 72, 20, 10),
    ]

    print('  📊 KARŞILAŞTIRMA — Slippage Etkisi')
    print('  ' + '─' * 86)
    print(f'  {"STRATEJİ":<20} {"SLIP":<13} {"İŞL":>5} {"WIN %":>7} {"ORT %":>7} {"WORST":>7} {"TOPLAM %":>10}')
    print('  ' + '─' * 86)

    results_table = {}

    for label, mul, hh, tp, sl in strategies:
        for slip_mode, slip_label in [('none', '🟢 None'), ('realistic', '🟡 Realistic'), ('pessimistic', '🔴 Pessimist')]:
            r = aggregate(coin_data, coins_all, mul, hh, tp, sl, slip_mode)
            if not r:
                continue
            print(f'  {label:<20} {slip_label:<13} {r["n"]:>5} {r["win_rate"]:>6.1f}% '
                  f'{r["avg"]:>+6.2f}% {r["worst"]:>+6.1f}% {r["total"]:>+9.1f}%')
            results_table.setdefault(label, {})[slip_mode] = r
        print('  ' + '─' * 86)

    # Compound hesabı
    print()
    print('  💰 COMPOUND GETİRİ — \\$100 başlangıç, 4 yıl, kâr reinvest')
    print('  ' + '─' * 70)
    print(f'  {"STRATEJİ":<20} {"NONE":>10} {"REALISTIC":>11} {"PESSIMIST":>11} {"YILLIK":>9}')
    print('  ' + '─' * 70)

    for label, _, _, _, _ in strategies:
        if label not in results_table:
            continue
        row = results_table[label]
        line = f'  {label:<20} '
        yearly_realistic = None
        for mode in ['none', 'realistic', 'pessimistic']:
            if mode not in row:
                line += f' {"-":>10}'
                continue
            r = row[mode]
            # Compound: her işlem ortalama getiriyle çarpılır
            avg_per = 1 + r['avg'] / 100
            n = r['n']
            final = 100 * (avg_per ** n)
            if mode == 'realistic':
                yearly_realistic = (final / 100) ** (1/4) - 1
            line += f' ${final:>8.0f}  '
        if yearly_realistic is not None:
            line += f' {yearly_realistic*100:>+7.1f}%'
        print(line)

    print()
    print('═' * 90)
    print('  💡 Yorum:')
    print('  • Slippage etkisi: ortalama %0.6-1.4 P&L kaybı per işlem')
    print('  • Realistic senaryo gerçek hayatta beklenen rakam')
    print('  • Compound = sermaye reinvest edildiğinde 4 yılda toplam getiri')
    print('═' * 90)


if __name__ == '__main__':
    main()
